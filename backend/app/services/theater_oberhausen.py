"""Theater Oberhausen event source — server-gerenderter Spielplan (HTML).

Quelle: https://theater-oberhausen.de/programm/spielplan/ (WordPress, Theme
mit Block "eventprogramm"). Alias /spielplan/ liefert dieselbe Seite.

Format: Eine einzige Seite listet den gesamten veroeffentlichten Spielplan
(Stand Okt. 2026: 20.10.2026 bis Jan. 2027, ~70 Termine) in div.programmlisting:
  - h2                        Monatsname (wird nicht gebraucht)
  - h3[data-date]             Tageskopf "Di. 20.10.26" (zweistelliges Jahr)
  - div.programm-item         ein Termin, darin
      div.zeit                "19:30 Uhr"
      div.location            Spielstaette (Raumbuehne Grosses Haus, Studio,
                              Saal Berlin, Theaterzelt, Container-Bar,
                              Satellit der Guten Hoffnung, Ebertplatz)
      div.kategorie b         Roh-Rubrik ("Schauspiel", "Junges Theater",
                              "Urban Arts", "Open Haus", ...), oft leer
      div.statusurauffuhrung  "Premiere"/"Urauffuehrung" (+ Klasse is-premiere)
      div.karten              Status "Karten"/"Restkarten"/"Ausverkauft"
      div.inhalt              h4[data-href]=Detail-URL, p.untertitel1/2/3,
                              p.hinweis
Weitere Monate gibt es NICHT ueber eigene URLs: Die Seite enthaelt bereits
alle Monate, der Kalender-Container (#KalenderContainer) ist nur eine
JS-Navigation ueber dieselben Daten. Ein Lauf = 1 Request, keine Detailseiten
(WP-REST /wp-json/wp/v2/event liefert keine Termine und wird nicht genutzt).

robots.txt: "User-agent: * / Disallow:" — alles erlaubt.

Koordinaten (Nominatim, 20.10.2026 verifiziert):
  - Theater Oberhausen, Will-Quadflieg-Platz 1: 51.4762667, 6.8607018
  - Ebertplatz (Mitte des Platzes, Open-Air): 51.4764684, 6.8596005
  - "Satellit der Guten Hoffnung" (Projektraum "Das Theater Oberhausen auf der
    Marktstrasse") ist in Nominatim nicht auffindbar; die genaue Adresse steht
    nicht im Spielplan -> lat/lon bleiben None (Geocoder/Known Venues).
"""
import hashlib
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

BASE_URL = "https://theater-oberhausen.de/programm/spielplan/"

SOURCE_NAME = "Theater Oberhausen"
ADDRESS_TEXT = "Will-Quadflieg-Platz 1, 46045 Oberhausen"

# Theater Oberhausen (Nominatim: 51.4762667, 6.8607018)
THEATER_LAT = 51.4762667
THEATER_LON = 6.8607018

MAX_DAYS_AHEAD = 120

_BERLIN = ZoneInfo("Europe/Berlin")
_HEADERS = {"User-Agent": CRAWLER_USER_AGENT}

# Spielstaette (Roh-Name der Seite) -> (Anzeigename, Adresse, lat, lon, indoor_outdoor)
_VENUES: Dict[str, tuple] = {
    "satellit der guten hoffnung": (
        "Satellit der Guten Hoffnung",
        "Marktstraße, 46045 Oberhausen",
        None,
        None,
        "indoor",
    ),
    "ebertplatz": (
        "Ebertplatz",
        "Ebertplatz, 46045 Oberhausen",
        51.4764684,
        6.8596005,
        "outdoor",
    ),
    "theaterzelt": (
        "Theaterzelt",
        ADDRESS_TEXT,
        THEATER_LAT,
        THEATER_LON,
        "both",
    ),
}

# Roh-Rubriken, die eindeutig Kinder/Jugend meinen.
_KIDS_CATEGORIES = {"junges theater"}
_KIDS_STRONG = re.compile(r"familienst[uü]ck|kinderst[uü]ck|f[uü]r kinder|ab \d+ jahren", re.I)
_KIDS_WEAK = re.compile(r"familie(?:n)?konzert|kinder|m[aä]rchen|mitmach", re.I)

_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})")
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


def _berlin_now() -> datetime:
    return datetime.now(_BERLIN).replace(tzinfo=None)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _parse_day(h3) -> Optional[date]:
    """'Di. 20.10.26' -> date(2026, 10, 20). Fallback: data-date (Unix-Zeit)."""
    m = _DATE_RE.search(h3.get_text(" ", strip=True))
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            return None
    raw = h3.get("data-date")
    if raw and raw.isdigit():
        return datetime.fromtimestamp(int(raw), _BERLIN).date()
    return None


def _venue_info(raw: str) -> tuple:
    key = _clean(raw).lower()
    if key in _VENUES:
        return _VENUES[key]
    # Raumbuehne Grosses Haus, Studio, Saal Berlin, Container-Bar: im Haus
    # am Will-Quadflieg-Platz.
    name = _clean(raw) or "Theater Oberhausen"
    if name.lower() == "studio":
        name = "Studio (Theater Oberhausen)"
    elif name.lower() == "saal berlin":
        name = "Saal Berlin (Theater Oberhausen)"
    elif name.lower() == "container-bar":
        name = "Container-Bar (Theater Oberhausen)"
    return (name, ADDRESS_TEXT, THEATER_LAT, THEATER_LON, "indoor")


def _detect_kids(category: Optional[str], text: str) -> str:
    if category and category.lower() in _KIDS_CATEGORIES:
        return "yes"
    if _KIDS_STRONG.search(text):
        return "yes"
    if _KIDS_WEAK.search(text):
        return "likely"
    return "unknown"


def _make_canonical(title: str, start_at: datetime, url: str) -> str:
    return hashlib.md5(
        f"theater_oberhausen_{title}_{start_at.isoformat()}_{url}".encode()
    ).hexdigest()[:16]


def _parse_item(item, day: date) -> Optional[Dict]:
    zeit = item.find("div", class_="zeit")
    tm = _TIME_RE.search(zeit.get_text(" ", strip=True)) if zeit else None
    start_time = time(int(tm.group(1)), int(tm.group(2))) if tm else time(0, 0)
    if tm and not (0 <= start_time.hour <= 23):
        return None

    title_el = item.select_one("div.inhalt h4")
    title = _clean(title_el.get_text(" ", strip=True)) if title_el else ""
    if not title:
        return None
    url = (title_el.get("data-href") or "").strip()
    if not url:
        a = title_el.find("a", href=True)
        url = a["href"] if a else BASE_URL

    loc = item.find("div", class_="location")
    venue_name, address, lat, lon, io = _venue_info(loc.get_text(" ", strip=True) if loc else "")

    cat_el = item.select_one("div.kategorie")
    category = _clean(cat_el.get_text(" ", strip=True)) if cat_el else ""
    category = category or None

    sub1 = item.select_one("p.untertitel1")
    sub2 = item.select_one("p.untertitel2")
    sub3 = item.select_one("p.untertitel3")
    hint = item.select_one("p.hinweis")
    sub1_t = _clean(sub1.get_text(" ", strip=True)) if sub1 else ""
    sub2_t = _clean(sub2.get_text(" ", strip=True)) if sub2 else ""
    sub3_t = _clean(sub3.get_text(" ", strip=True)) if sub3 else ""
    hint_t = _clean(hint.get_text(" ", strip=True)) if hint else ""

    price_text = None
    if re.search(r"eintritt\s*frei", sub2_t, re.I):
        price_text = "Eintritt frei"
        sub2_t = ""  # kein Beschreibungstext

    status = item.find("div", class_="statusurauffuhrung")
    status_t = _clean(status.get_text(" ", strip=True)) if status else ""
    if not status_t and "is-premiere" in (item.get("class") or []):
        status_t = "Premiere"

    # Satellit-Boilerplate ("Das Theater Oberhausen auf der Marktstrasse") ist
    # keine Beschreibung.
    if sub1_t.lower().startswith("das theater oberhausen auf der marktstra"):
        sub1_t = ""
    parts = [p for p in (status_t, sub1_t, sub2_t, sub3_t, hint_t) if p]
    description = " – ".join(parts)[:500] or None

    kids = _detect_kids(category, f"{title} {sub1_t} {hint_t}")

    return {
        "canonical_id": _make_canonical(title, datetime.combine(day, start_time), url),
        "title": title[:500],
        "short_description": description,
        "start_at": datetime.combine(day, start_time),
        "venue_name": venue_name,
        "address_text": address,
        "city": "Oberhausen",
        "lat": lat,
        "lon": lon,
        "source_url": url[:500],
        "source_name": SOURCE_NAME,
        "indoor_outdoor": io,
        "kids_suitable": kids,
        "price_text": price_text,
        "category": category,
        "image_url": None,
    }


def parse_theater_oberhausen_html(html: str, now: Optional[datetime] = None) -> List[Dict]:
    """Parse the Spielplan page into one event dict per Termin.

    `now` (naive Berlin time) is injectable for tests; window = today .. +120d.
    Termine, die heute schon begonnen haben, fallen raus.
    """
    now = now or _berlin_now()
    window_end = datetime.combine(now.date(), time(0, 0)) + timedelta(days=MAX_DAYS_AHEAD)

    soup = BeautifulSoup(html, "lxml")
    listing = soup.find("div", class_="programmlisting")
    if not listing:
        logger.warning("Theater Oberhausen: kein div.programmlisting gefunden")
        return []

    events: List[Dict] = []
    seen: set = set()
    current_day: Optional[date] = None
    for el in listing.find_all(["h3", "div"], recursive=False):
        if el.name == "h3":
            current_day = _parse_day(el)
            continue
        if "programm-item" not in (el.get("class") or []) or current_day is None:
            continue
        try:
            ev = _parse_item(el, current_day)
        except Exception as exc:
            logger.debug(f"Theater Oberhausen item parse error: {exc}")
            continue
        if not ev:
            continue
        if not (now <= ev["start_at"] < window_end):
            continue
        if ev["canonical_id"] in seen:
            continue
        seen.add(ev["canonical_id"])
        events.append(ev)

    logger.info(f"Theater Oberhausen: {len(events)} events")
    return events


async def fetch_theater_oberhausen_events() -> List[Dict]:
    """Fetch Theater Oberhausen Spielplan (1 Request, never raises)."""
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        try:
            resp = await client.get(BASE_URL)
            resp.raise_for_status()
            return parse_theater_oberhausen_html(resp.text)
        except Exception as exc:
            logger.error(f"Theater Oberhausen fetch failed: {exc}")
            return []


async def sync_theater_oberhausen(db: Session) -> dict:
    """Sync Theater Oberhausen events to database."""
    events_data = await fetch_theater_oberhausen_events()
    return sync_events_to_db(db, events_data, SOURCE_NAME)
