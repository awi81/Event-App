"""Deutsches Bergbau-Museum Bochum event source — TYPO3 (ig_event) Listenseiten.

Quelle: https://www.bergbaumuseum.de/besuch/veranstaltungskalender

Aufbau der Seite: Die Startseite des Kalenders zeigt den laufenden Monat (inkl.
Randtage der Nachbarmonate) als Liste `ul.cal-list-item-wrapper` mit je einem
`li.cal-list-item#cal-day-DDMMYYYY` pro Tag (der Tag steckt verlaessig in
der li-ID); ein li kann mehrere Veranstaltungen enthalten. Jeder Termin traegt:
  - div[data-cal-item]            Veranstaltungs-ID (gleiche ID = Wiederholung)
  - data-cal-suggest              Titel + HTML-Beschreibung (Kosten, Dauer, Alter)
  - data-cal-categories           Zielgruppen-IDs, z.B. "(148)(93)(87)(78)"
                                  78 = Kinder & Jugendliche, 79 = Familien,
                                  80 = Erwachsene, 82 = Wissenschaft,
                                  83 = alle Generationen
  - span.eventtime                Uhrzeit (fehlt bei ganztaegigen Angeboten)
  - span.custom-eventnote         Hinweis (z.B. "geaenderte Uhrzeit ...")
  - a.cal-list-item-title[href]   Detailseite /veranstaltungen-detailseite/<slug>/<Jahr>/<Monat>/<Tag>

Monatswechsel: Das `select#eventmonthpagination` enthaelt je Monat eine URL mit
`monthpagination=<Unix-Timestamp>&cHash=...` (cHash ist serverseitig signiert
und nicht berechenbar, deshalb werden die URLs aus dem Select gelesen). Es
werden der laufende und die zwei Folgemonate geholt = 3 Requests pro Lauf;
Detailseiten werden nicht abgerufen (Liste + data-cal-suggest reichen).

Mehrtaegige Angebote (z.B. Kulturrucksack 19.-24.10.) stehen bereits als ein
li pro Tag in der Liste. Termine ohne Uhrzeit (Dauerangebote wie "Faszination
ueber und unter Tage", Fuehrung im Anschauungsbergwerk) werden um 00:00
(= ganztaegig) geliefert; nennt die Beschreibung "Start jeweils um 11:00 Uhr,
12:00 Uhr ...", gilt die erste Zeit.

Venue: Deutsches Bergbau-Museum, Am Bergbaumuseum 28, 44791 Bochum
(Nominatim verifiziert: 51.4886284, 7.2164106, OSM tourism=museum).

robots.txt: existiert nicht (404) = keine Sperre. Trotzdem hoeflich: eigener
ehrlicher User-Agent, 1,5 s Pause zwischen den Monatsseiten.
"""
import asyncio
import hashlib
import html as html_lib
import logging
import re
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.services.base_sync import sync_events_to_db
from app.services.crawler_ua import CRAWLER_USER_AGENT

logger = logging.getLogger(__name__)

SITE_URL = "https://www.bergbaumuseum.de"
BASE_URL = SITE_URL + "/besuch/veranstaltungskalender"

SOURCE_NAME = "Bergbau-Museum Bochum"
VENUE_NAME = "Deutsches Bergbau-Museum Bochum"
ADDRESS_TEXT = "Am Bergbaumuseum 28, 44791 Bochum"

# Nominatim verifiziert (OSM relation 12155256, tourism=museum):
VENUE_LAT = 51.4886284
VENUE_LON = 7.2164106

MAX_DAYS_AHEAD = 120
MONTHS_AHEAD = 2  # laufender Monat + 2 Folgemonate
PAGE_DELAY_SECONDS = 1.5

_BERLIN = ZoneInfo("Europe/Berlin")
_HEADERS = {"User-Agent": CRAWLER_USER_AGENT}


# Zielgruppen-IDs (Filter "Zielgruppe" der Seite)
_CAT_KIDS = "78"      # Kinder & Jugendliche
_CAT_FAMILY = "79"    # Familien

_DAY_ID_RE = re.compile(r"cal-day-(\d{2})(\d{2})(\d{4})")
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")
_START_TIMES_RE = re.compile(r"Start\s+jeweils\s+um\s+(\d{1,2})[:.](\d{2})", re.I)
_AGE_RE = re.compile(r"ab\s+(\d{1,2})(?:\s*-\s*\d{1,2})?\s+Jahre", re.I)
_PRICE_RE = re.compile(
    r"Kosten:\s*([^<\n]{1,80})|\b(Kostenlos|Eintritt\s+frei)\b", re.I
)
_KIDS_KEYWORDS = ("kinder", "familie", "mitmach", "grubis", "kids")


def _berlin_now() -> datetime:
    return datetime.now(_BERLIN).replace(tzinfo=None)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _category_ids(raw: str) -> set:
    return set(re.findall(r"\((\d+)\)", raw or ""))


def _description_parts(suggest: str, title: str):
    """data-cal-suggest -> (Klartext-Beschreibung, price_text, HTML)."""
    raw = html_lib.unescape(suggest or "")
    soup = BeautifulSoup(raw, "lxml")
    price = None
    m = _PRICE_RE.search(soup.get_text("\n"))
    if m:
        price = _clean(m.group(1) or m.group(2))[:100]
        if price.lower() == "eintritt frei":
            price = "Eintritt frei"
    # Klartext: Absaetze und Listenpunkte mit Leerzeichen trennen
    text = _clean(soup.get_text(" "))
    if text.lower().startswith(title.lower()):
        text = text[len(title):].strip()
    return text, price, raw


def _pick_category(title: str, text: str) -> str:
    """Roh-Rubrik der Seite aus dem Titel (die Seite hat keine Rubrik-Namen)."""
    t = title.lower()
    if "lesung" in t:
        return "Lesung"
    if "workshop" in t or "werkstatt" in t:
        return "Workshop"
    if "mitmach" in t:
        return "Mitmachaktion"
    if "führung" in t or "fuehrung" in t or "unter tage" in t or "bergwerk" in t:
        return "Führung"
    if "halloween" in t or "saures" in t or "grubenhorror" in t:
        return "Fest"
    if "bergmann" in t:
        return "Führung"
    return "Museum"


def _detect_kids(cat_ids: set, title: str, text: str) -> str:
    age = _AGE_RE.search(text)
    min_age = int(age.group(1)) if age else None
    if _CAT_KIDS in cat_ids:
        return "yes"
    if _CAT_FAMILY in cat_ids:
        # "Zielgruppe ab 14 Jahren" ist trotz Familien-Tag nichts fuer Kinder
        return "likely" if (min_age is not None and min_age >= 12) else "yes"
    haystack = f"{title} {text}".lower()
    if any(kw in haystack for kw in _KIDS_KEYWORDS):
        return "likely"
    return "unknown"


def _make_canonical(item_id: str, start_at: datetime) -> str:
    return hashlib.md5(
        f"bergbaumuseum_{item_id}_{start_at.isoformat()}".encode()
    ).hexdigest()[:16]


def _parse_item(day: date, block) -> Optional[Dict]:
    """Ein div[data-cal-item] eines Tages -> Event-Dict (ohne Fensterfilter)."""
    item_id = block["data-cal-item"]

    title_cell = block.select_one(".event-title-cell")
    link = block.select_one("a.cal-list-item-title")
    if title_cell is None:
        return None
    note_el = title_cell.select_one(".custom-eventnote")
    note = _clean(note_el.get_text(" ")) if note_el else ""
    if note_el:
        note_el.extract()
    title = _clean(title_cell.get_text(" "))
    if not title:
        return None

    text, price, _raw = _description_parts(block.get("data-cal-suggest", ""), title)

    # Uhrzeit: span.eventtime, sonst "Start jeweils um HH:MM" (erste Zeit), sonst ganztaegig
    start_time: Optional[time] = None
    time_el = block.select_one(".eventtime")
    if time_el:
        tm = _TIME_RE.search(time_el.get_text())
        if tm:
            start_time = time(int(tm.group(1)), int(tm.group(2)))
    if start_time is None:
        sm = _START_TIMES_RE.search(text)
        if sm:
            hh, mm = int(sm.group(1)), int(sm.group(2))
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                start_time = time(hh, mm)
    start_at = datetime.combine(day, start_time or time(0, 0))

    href = link["href"] if link and link.get("href") else BASE_URL
    if href.startswith("/"):
        href = SITE_URL + href

    description = text
    if note:
        description = f"{note}. {description}".strip()
    description = description[:500] or None

    cat_ids = _category_ids(block.get("data-cal-categories", ""))
    return {
        "canonical_id": _make_canonical(item_id, start_at),
        "title": title[:500],
        "short_description": description,
        "start_at": start_at,
        "venue_name": VENUE_NAME,
        "address_text": ADDRESS_TEXT,
        "city": "Bochum",
        "lat": VENUE_LAT,
        "lon": VENUE_LON,
        "source_url": href[:500],
        "source_name": SOURCE_NAME,
        "indoor_outdoor": "indoor",
        "kids_suitable": _detect_kids(cat_ids, title, text),
        "price_text": price,
        "category": _pick_category(title, text),
        "image_url": None,
    }


def parse_bergbaumuseum_html(html: str, now: Optional[datetime] = None) -> List[Dict]:
    """Parse one monthly list page into event dicts (one per Termin).

    `now` (naive Berlin time) is injectable for tests; window = today .. +120d.
    Vergangene Termine fallen raus; ganztaegige (00:00) Termine gelten bis
    Tagesende.
    """
    now = now or _berlin_now()
    window_start = datetime.combine(now.date(), time(0, 0))
    window_end = window_start + timedelta(days=MAX_DAYS_AHEAD)

    soup = BeautifulSoup(html, "lxml")
    items = soup.select("li.cal-list-item")
    events: List[Dict] = []
    seen: set = set()
    # Ein li (= ein Tag) kann mehrere Veranstaltungen (div[data-cal-item]) tragen.
    parsed: List[Dict] = []
    for li in items:
        m = _DAY_ID_RE.match(li.get("id", ""))
        if not m:
            continue
        try:
            day = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            continue
        for block in li.find_all(attrs={"data-cal-item": True}):
            try:
                ev = _parse_item(day, block)
            except Exception as exc:
                logger.debug(f"Bergbaumuseum item parse error: {exc}")
                continue
            if ev:
                parsed.append(ev)
    for ev in parsed:
        start = ev["start_at"]
        if not (window_start <= start < window_end):
            continue
        if start.time() != time(0, 0) and start < now:
            continue  # heute schon vorbei
        if ev["canonical_id"] in seen:
            continue
        seen.add(ev["canonical_id"])
        events.append(ev)
    logger.info(f"Bergbaumuseum: {len(events)} events from {len(parsed)} items")
    return events


def parse_month_urls(html: str, now: Optional[datetime] = None) -> List[str]:
    """URLs (mit cHash) des laufenden Monats + MONTHS_AHEAD Folgemonate.

    Der laufende Monat ist die Seite selbst und wird nicht erneut geholt, die
    Rueckgabe enthaelt nur die Folgemonate. Ausgangspunkt ist der im Select
    markierte Monat (selected), nicht `now`, damit die Reihenfolge stimmt.
    """
    soup = BeautifulSoup(html, "lxml")
    options = soup.select("select#eventmonthpagination option")
    urls: List[str] = []
    selected_idx = next(
        (i for i, o in enumerate(options) if o.has_attr("selected")), None
    )
    if selected_idx is None:
        return urls
    for opt in options[selected_idx + 1: selected_idx + 1 + MONTHS_AHEAD]:
        value = opt.get("value", "")
        if value.startswith("/"):
            value = SITE_URL + value
        if value:
            urls.append(value)
    return urls


async def _get_with_retry(client: httpx.AsyncClient, url: str) -> Optional[str]:
    """GET mit 2 Wiederholungen bei Timeouts (TLS-Handshake war einmal zaeh).

    Bei 403/429 wird sofort abgebrochen (keine Sperre umgehen).
    """
    for attempt in range(3):
        try:
            resp = await client.get(url)
            if resp.status_code in (403, 429):
                logger.error(f"Bergbaumuseum: HTTP {resp.status_code} — Abbruch")
                return None
            resp.raise_for_status()
            return resp.text
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            logger.warning(f"Bergbaumuseum {url[:80]} attempt {attempt + 1}: {exc}")
            await asyncio.sleep(3)
    return None


async def fetch_bergbaumuseum_events() -> List[Dict]:
    """Fetch events of current + 2 following months (3 requests, never raises)."""
    events: List[Dict] = []
    seen: set = set()
    try:
        async with httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, headers=_HEADERS
        ) as client:
            first = await _get_with_retry(client, BASE_URL)
            if first is None:
                return []
            pages = [first]
            for url in parse_month_urls(first):
                await asyncio.sleep(PAGE_DELAY_SECONDS)
                page = await _get_with_retry(client, url)
                if page:
                    pages.append(page)
            for page in pages:
                for ev in parse_bergbaumuseum_html(page):
                    if ev["canonical_id"] not in seen:
                        seen.add(ev["canonical_id"])
                        events.append(ev)
    except Exception as exc:
        logger.error(f"Bergbaumuseum fetch failed: {exc}")
        return events
    events.sort(key=lambda e: e["start_at"])
    return events


async def sync_bergbaumuseum(db: Session) -> dict:
    """Sync Bergbau-Museum Bochum events to database."""
    events_data = await fetch_bergbaumuseum_events()
    return sync_events_to_db(db, events_data, SOURCE_NAME)
