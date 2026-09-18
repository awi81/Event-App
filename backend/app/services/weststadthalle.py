"""Weststadthalle Essen event source — TYPO3 (tx_news) HTML scraping.

Liste: https://www.weststadthalle.de/veranstaltungen/ — alle kommenden
Veranstaltungen (~75, bis >1 Jahr voraus) als schema.org/Event-Microdata:

  div.filter-item.<Kategorie>            CSS-Klasse = Rubrik ("Comedy", "Konzert", ...)
    li[itemtype="http://schema.org/Event"]
      a > img.mr-3                       Thumbnail 100x100
      time[itemprop=startDate][datetime=YYYY-MM-DD]  "Sonntag, 20.09.2026 - Beginn: 20:00 Uhr"
      h5 a[href] span[itemprop=name]     Titel + Detail-Link
      h5 span.badge                      "Ausverkauft" / "Verlegt auf ..."
      span.category                      "[Comedy]"
      a.btn-success[target=_blank]       Ticketlink (reservix/eventim)

Die Listen-Links tragen "?cHash=...&L=0". robots.txt verbietet "/*cHash",
deshalb werden die Query-Parameter entfernt — die Detailseiten sind auch
ohne cHash erreichbar (200). Detail-Enrichment (Einlass, VVK-Preis,
Beschreibung, groesseres Bild) nur fuer die naechsten MAX_DETAIL_REQUESTS
Termine mit 1 s Pause, weil die Liste keine Beschreibung/Preise enthaelt.
"""
import asyncio
import hashlib
import logging
import re
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.services.base_sync import sync_events_to_db

logger = logging.getLogger(__name__)

BASE_URL = "https://www.weststadthalle.de"
LIST_URL = f"{BASE_URL}/veranstaltungen/"

SOURCE_NAME = "Weststadthalle"
VENUE_NAME = "Weststadthalle"
ADDRESS_TEXT = "Thea-Leymann-Straße 23, 45127 Essen"

# Venue coordinates (OSM "Weststadthalle", Thea-Leymann-Straße 23, Westviertel —
# Nominatim verified: 51.4581367, 7.0027362)
VENUE_LAT = 51.4581367
VENUE_LON = 7.0027362

MAX_DAYS_AHEAD = 120
MAX_DETAIL_REQUESTS = 20
DETAIL_DELAY_SECONDS = 1.0

_BERLIN = ZoneInfo("Europe/Berlin")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

_KIDS_KEYWORDS = [
    "kinder", "kids", "familie", "familien", "märchen", "maerchen", "jugend",
    "mitmach", "puppen",
]

# "Beginn: 20:00 Uhr" — Datum vorher maskieren, damit "20.09.2026" nie als
# Uhrzeit gelesen wird.
_DATE_TEXT_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
_BEGIN_RE = re.compile(r"Beginn\s*:?\s*(\d{1,2})[:.](\d{2})", re.I)
_TIME_RE = re.compile(r"(\d{1,2})[:.](\d{2})\s*Uhr", re.I)
_EINLASS_RE = re.compile(r"Einlass\s*:?\s*(\d{1,2})[:.](\d{2})", re.I)
# Preiszeile in .extrainfo ("VVK: ab 10,90€", "Tickets: 30,00 € zzgl. Gebühren",
# "Eintritt frei"). Wortgrenzen sind Pflicht: "N-euro-diversität" ist kein Preis,
# und manche Seiten missbrauchen .extrainfo fuer den Teaser (daher Laengenlimit).
_PRICE_LINE_RE = re.compile(
    r"(?:\bVVK\b|\bAK\b|\bEintritt\b|\bPreis\w*|\bTickets?\b|\bKarten\b)"
    r".{0,60}?(?:\d|\bfrei\b)"
    r"|\d{1,3}(?:[.,]\d{2})?\s*(?:€|\bEuro\b)",
    re.I,
)
_PRICE_LINE_MAX_LEN = 100


def _berlin_now() -> datetime:
    return datetime.now(_BERLIN).replace(tzinfo=None)


def _clean_url(href: str) -> str:
    """Absolute URL ohne Query (cHash/L) — robots.txt verbietet /*cHash."""
    absolute = urljoin(BASE_URL + "/", href)
    parts = urlsplit(absolute)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _parse_start(time_el) -> Optional[datetime]:
    """<time datetime="2026-09-20">Sonntag, 20.09.2026 - Beginn: 20:00 Uhr</time>."""
    if time_el is None:
        return None
    text = time_el.get_text(" ", strip=True)

    day: Optional[datetime] = None
    iso = (time_el.get("datetime") or "").strip()[:10]
    try:
        day = datetime.strptime(iso, "%Y-%m-%d") if iso else None
    except ValueError:
        day = None
    if day is None:
        m = _DATE_TEXT_RE.search(text)
        if m:
            try:
                day = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                return None
    if day is None:
        return None

    masked = _DATE_TEXT_RE.sub(" ", text)
    tm = _BEGIN_RE.search(masked) or _TIME_RE.search(masked)
    if tm:
        hour, minute = int(tm.group(1)), int(tm.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return day.replace(hour=hour, minute=minute)
    return day


def _detect_kids(text: str) -> str:
    lowered = text.lower()
    if any(kw in lowered for kw in _KIDS_KEYWORDS):
        return "likely"
    return "unknown"


def _extract_category(wrapper, li) -> Optional[str]:
    """Rubrik roh: span.category "[Comedy]" oder Filter-Klasse des Wrappers."""
    span = li.find("span", class_="category")
    if span:
        raw = span.get_text(" ", strip=True).strip("[] ")
        if raw:
            return raw[:100]
    if wrapper is not None:
        extra = [
            c for c in wrapper.get("class", [])
            if c not in ("filter-item",) and not c.startswith("col-")
        ]
        if extra:
            return ", ".join(extra)[:100]
    return None


def _make_canonical(title: str, start_at: datetime, url: str) -> str:
    return hashlib.md5(
        f"weststadthalle_{title}_{start_at.isoformat()}_{url}".encode()
    ).hexdigest()[:16]


def _parse_item(li) -> Optional[Dict]:
    """Ein li[itemtype=schema.org/Event] -> Event-Dict (ohne Zeitfenster-Filter)."""
    name_el = li.find(attrs={"itemprop": "name"})
    title_link = li.find("h5")
    title_link = title_link.find("a", href=True) if title_link else None
    title = ""
    if name_el:
        title = name_el.get_text(" ", strip=True)
    elif title_link:
        title = title_link.get("title") or title_link.get_text(" ", strip=True)
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        return None

    href = title_link["href"] if title_link else None
    if not href:
        first_link = li.find("a", href=True)
        href = first_link["href"] if first_link else LIST_URL
    source_url = _clean_url(href)

    start_at = _parse_start(li.find("time"))
    if start_at is None:
        return None

    badges = [b.get_text(" ", strip=True) for b in li.find_all(class_="badge")]
    badges = [b for b in badges if b]
    # "Verlegt auf 14.05.2027" haengt am ALTEN Termin — der neue steht als
    # eigener Eintrag ("Ersatztermin fuer den ...") in der Liste.
    if any(re.match(r"verlegt\s+auf", b, re.I) for b in badges):
        return None
    sold_out = any(b.lower().startswith("ausverkauft") for b in badges)
    notes = [b for b in badges if not b.lower().startswith("ausverkauft")]

    img = li.find("img", src=True)
    image_url = urljoin(BASE_URL + "/", img["src"]) if img else None

    wrapper = li.find_parent("div", class_="filter-item")
    category = _extract_category(wrapper, li)

    return {
        "canonical_id": _make_canonical(title, start_at, source_url),
        "title": title[:500],
        "short_description": " – ".join(notes)[:500] if notes else None,
        "start_at": start_at,
        "venue_name": VENUE_NAME,
        "address_text": ADDRESS_TEXT,
        "city": "Essen",
        "lat": VENUE_LAT,
        "lon": VENUE_LON,
        "source_url": source_url[:500],
        "source_name": SOURCE_NAME,
        "indoor_outdoor": "indoor",
        "kids_suitable": _detect_kids(f"{title} {category or ''}"),
        "price_text": "Ausverkauft" if sold_out else None,
        "category": category,
        "image_url": image_url[:500] if image_url else None,
    }


def parse_weststadthalle_html(html: str, now: Optional[datetime] = None) -> List[Dict]:
    """Parse the Veranstaltungen list; window = today (Berlin) .. +120 days."""
    now = now or _berlin_now()
    window_start = datetime.combine(now.date(), time(0, 0))
    window_end = window_start + timedelta(days=MAX_DAYS_AHEAD)

    soup = BeautifulSoup(html, "lxml")
    items = soup.find_all("li", attrs={"itemtype": re.compile(r"schema\.org/Event$")})
    if not items:
        wrappers = soup.find_all("div", class_="filter-item")
        items = [li for d in wrappers for li in d.find_all("li")]
    logger.debug(f"Weststadthalle: {len(items)} event items found")

    events: List[Dict] = []
    seen_ids: set = set()
    for li in items:
        try:
            event = _parse_item(li)
        except Exception as exc:
            logger.debug(f"Weststadthalle item parse error: {exc}")
            continue
        if not event:
            continue
        if not (window_start <= event["start_at"] < window_end):
            continue
        if event["canonical_id"] in seen_ids:
            continue
        seen_ids.add(event["canonical_id"])
        events.append(event)

    events.sort(key=lambda e: e["start_at"])
    logger.info(
        f"Weststadthalle: {len(events)} events in window from {len(items)} items"
    )
    return events


def parse_weststadthalle_detail_html(html: str) -> Dict:
    """Detailseite -> {short_description?, price_text?, image_url?, einlass?}.

    Liefert nur die Keys, die gefunden wurden (leeres Dict bei leerer Seite).
    """
    soup = BeautifulSoup(html, "lxml")
    result: Dict = {}

    # Zusatzinfos: <div class="extrainfo"><p>Einlass: 18:30 Uhr</p><p>VVK: ab 10,90€</p>
    extra = soup.find(class_="extrainfo")
    einlass: Optional[str] = None
    if extra:
        for p in extra.find_all("p"):
            line = p.get_text(" ", strip=True)
            if not line:
                continue
            if einlass is None and _EINLASS_RE.search(line):
                m = _EINLASS_RE.search(line)
                einlass = f"Einlass {int(m.group(1)):02d}:{m.group(2)} Uhr"
            elif (
                "price_text" not in result
                and len(line) <= _PRICE_LINE_MAX_LEN
                and _PRICE_LINE_RE.search(line)
            ):
                result["price_text"] = line

    # Haupttext
    body = soup.find(attrs={"itemprop": "articleBody"})
    if body is None:
        body = soup.find(class_="news-text-wrap")
    description = ""
    if body:
        paragraphs = [p.get_text(" ", strip=True) for p in body.find_all("p")]
        description = " ".join(p for p in paragraphs if p)
        if not description:
            description = body.get_text(" ", strip=True)
        description = re.sub(r"\s+", " ", description).strip()
    parts = [p for p in (einlass, description) if p]
    if parts:
        result["short_description"] = " · ".join(parts)[:500]

    # Groesseres Bild aus der Galerie (Liste hat nur 100x100)
    gallery = soup.find(class_="gallery")
    if gallery:
        link = gallery.find("a", href=re.compile(r"\.(jpe?g|png|webp|gif)$", re.I))
        img = gallery.find("img", src=True)
        src = link["href"] if link else (img["src"] if img else None)
        if src:
            result["image_url"] = urljoin(BASE_URL + "/", src)[:500]

    return result


def _merge_detail(event: Dict, detail: Dict) -> None:
    """Detail-Daten in das Listen-Event mergen (Badges wie 'Ausverkauft' bleiben)."""
    if detail.get("short_description"):
        prefix = event.get("short_description")
        merged = detail["short_description"]
        if prefix:
            merged = f"{prefix} – {merged}"
        event["short_description"] = merged[:500]
    if detail.get("price_text"):
        if event.get("price_text") == "Ausverkauft":
            event["price_text"] = f"Ausverkauft ({detail['price_text']})"[:255]
        else:
            event["price_text"] = detail["price_text"]
    if detail.get("image_url"):
        event["image_url"] = detail["image_url"]
    if event.get("short_description"):
        event["kids_suitable"] = _detect_kids(
            f"{event['title']} {event['short_description']}"
        )


async def fetch_weststadthalle_events() -> List[Dict]:
    """Fetch list + enrich the next MAX_DETAIL_REQUESTS events (never raises)."""
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        try:
            resp = await client.get(LIST_URL)
            resp.raise_for_status()
            events = parse_weststadthalle_html(resp.text)
        except Exception as exc:
            logger.error(f"Weststadthalle fetch failed: {exc}")
            return []

        enriched = 0
        for event in events[:MAX_DETAIL_REQUESTS]:
            url = event["source_url"]
            if not url.startswith(BASE_URL) or url == LIST_URL:
                continue
            try:
                await asyncio.sleep(DETAIL_DELAY_SECONDS)
                detail_resp = await client.get(url)
                detail_resp.raise_for_status()
                _merge_detail(event, parse_weststadthalle_detail_html(detail_resp.text))
                enriched += 1
            except Exception as exc:
                logger.debug(f"Weststadthalle detail fetch failed for {url}: {exc}")

        logger.info(f"Weststadthalle: {len(events)} events, {enriched} enriched")
        return events


async def sync_weststadthalle(db: Session) -> dict:
    """Sync Weststadthalle events to database."""
    events_data = await fetch_weststadthalle_events()
    return sync_events_to_db(db, events_data, SOURCE_NAME)
