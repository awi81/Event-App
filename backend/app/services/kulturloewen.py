"""Kulturlöwen Velbert event source — JSON-LD + neanderticket calendar HTML.

kulturloewen.de/veranstaltungen/ embeds the neanderticket calendar ("klive").
The page ships one ``<script type="application/ld+json">`` with an array of
schema.org Event objects (name, startDate, url, location, offers) and, per
event, a ``div.klive-terminbox`` with richer metadata (Rubrik, Künstler,
Untertitel, Foto). Both are joined via the neanderticket event id.
"""
import hashlib
import html as html_lib
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.services.base_sync import sync_events_to_db, to_berlin_naive

logger = logging.getLogger(__name__)

SOURCE_NAME = "Kulturlöwen Velbert"
BASE_URL = "https://www.kulturloewen.de"
# robots.txt only contains "User-agent: *" — everything is allowed.
EVENTS_URL = f"{BASE_URL}/veranstaltungen/"

MAX_DAYS_AHEAD = 120

# Fixed venue coordinates (Nominatim verified, addresses as in the JSON-LD):
#   Forum Velbert (Forum Niederberg), Oststraße 20, 42551 Velbert
#   Historisches Bürgerhaus Langenberg, Hauptstraße 64, 42555 Velbert
#   Vorburg Schloss Hardenberg, Zum Hardenberger Schloss 1, 42553 Velbert
_VENUE_COORDS = {
    "forum velbert": (51.3415978, 7.0463150),
    "historisches bürgerhaus langenberg": (51.3511495, 7.1193279),
    "vorburg schloss hardenberg": (51.3166270, 7.0855288),
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

_TICKET_ID_RE = re.compile(r"(\d+)\s*/?\s*$")
_LAUNCH_TICKET_RE = re.compile(r"launchTicket\((\d+)")
_BG_IMAGE_RE = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)")
_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_KIDS_RE = re.compile(
    r"kinder|familie|familien|kindermusical|familienkonzert|jugend|kids",
    re.IGNORECASE,
)

# Fallback raw category from title keywords when the HTML has no Rubrik.
_CATEGORY_KEYWORDS = [
    ("kindertheater", "Kindertheater"),
    ("konzert", "Konzert"),
    ("comedy", "Comedy"),
    ("kabarett", "Kabarett"),
    ("theater", "Theater"),
    ("lesung", "Lesung"),
    ("musical", "Musical"),
    ("slam", "Poetry Slam"),
]


def _clean(text: Optional[str]) -> str:
    """Unescape HTML entities (&szlig; …) and collapse whitespace."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", html_lib.unescape(str(text)).replace("\xa0", " ")).strip()


def _ticket_id(url: str) -> Optional[str]:
    m = _TICKET_ID_RE.search(url or "")
    return m.group(1) if m else None


def _format_price(offers) -> Optional[str]:
    """'18.00 ' + EUR → 'ab 18 €'; '37.90' → 'ab 37,90 €'; 0 → 'Eintritt frei'."""
    if isinstance(offers, list):
        offers = next((o for o in offers if isinstance(o, dict)), None)
    if not isinstance(offers, dict):
        return None
    raw = str(offers.get("price", "")).strip().replace(",", ".")
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if value <= 0:
        return "Eintritt frei"
    if value == int(value):
        return f"ab {int(value)} €"
    return f"ab {value:.2f}".replace(".", ",") + " €"


def _venue_coords(venue_name: str) -> Optional[tuple]:
    low = venue_name.lower()
    for key, coords in _VENUE_COORDS.items():
        if key in low or low in key:
            return coords
    return None


def _detect_category(title: str, subtitle: str) -> Optional[str]:
    combined = f"{title} {subtitle}".lower()
    for keyword, cat in _CATEGORY_KEYWORDS:
        if keyword in combined:
            return cat
    return None


def _detect_kids(title: str, subtitle: str, rubrik: str, label: str) -> str:
    """'yes' when the source itself flags the event as children's programme."""
    if _KIDS_RE.search(f"{rubrik} {label}"):
        return "yes"
    if _KIDS_RE.search(f"{title} {subtitle}"):
        return "yes"
    return "unknown"


def _make_canonical(title: str, start_at: datetime, url: str) -> str:
    return hashlib.md5(
        f"kulturloewen_{title}_{start_at.isoformat()}_{url}".encode()
    ).hexdigest()[:16]


def _extract_json_ld_events(soup) -> List[Dict]:
    """Collect all schema.org Event objects from ld+json scripts."""
    items: List[Dict] = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = (script.string or script.get_text() or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.debug(f"Kulturlöwen: invalid JSON-LD block skipped: {exc}")
            continue
        if isinstance(data, dict) and "@graph" in data:
            data = data["@graph"]
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            continue
        for item in data:
            if isinstance(item, dict) and item.get("@type") == "Event":
                items.append(item)
    return items


def _extract_html_meta(soup) -> Dict[str, Dict]:
    """Map neanderticket id → Rubrik/Künstler/Titel/Untertitel/Foto/Ende."""
    meta: Dict[str, Dict] = {}
    for box in soup.find_all("div", class_="klive-terminbox"):
        try:
            tid = None
            more = box.find("a", class_="klive-mehr-infos")
            if more and more.get("id", "").startswith("a"):
                tid = more["id"][1:]
            if not tid:
                m = _LAUNCH_TICKET_RE.search(str(box))
                tid = m.group(1) if m else None
            if not tid:
                continue

            def text_of(cls: str) -> str:
                el = box.find(class_=cls)
                return _clean(el.get_text(" ", strip=True)) if el else ""

            image_url = None
            foto = box.find(class_="klive-foto")
            if foto:
                m = _BG_IMAGE_RE.search(foto.get("style", ""))
                if m:
                    image_url = m.group(1).strip()

            end_time = None
            ende = box.select_one(".klive-zeit .ende")
            if ende:
                m = _TIME_RE.search(_clean(ende.get_text()))
                if m:
                    end_time = (int(m.group(1)), int(m.group(2)))

            meta[tid] = {
                "rubrik": text_of("klive-rubrik"),
                "label": text_of("klive-label"),
                "artist": text_of("klive-titel-artist"),
                "titel": text_of("klive-titel-titel"),
                "subtitle": text_of("klive-titel-subtitel"),
                "image_url": image_url,
                "end_time": end_time,
            }
        except Exception as exc:
            logger.debug(f"Kulturlöwen terminbox parse error: {exc}")
    return meta


def _build_event(item: Dict, meta: Dict) -> Optional[Dict]:
    """Build one event dict from a JSON-LD Event + optional HTML metadata."""
    name = _clean(item.get("name"))
    url = _clean(item.get("url")) or EVENTS_URL
    if not name:
        return None

    start_raw = item.get("startDate")
    if not start_raw:
        return None
    try:
        start_at = to_berlin_naive(datetime.fromisoformat(str(start_raw).strip()))
    except ValueError:
        return None

    # Title: "Künstler: Titel" when the HTML splits them (JSON-LD only has the
    # bare programme title, e.g. "Best Of"), otherwise the JSON-LD name.
    artist = meta.get("artist", "")
    titel = meta.get("titel", "")
    if artist and titel and artist.lower() != titel.lower():
        title = f"{artist}: {titel}"
    else:
        title = name
    title = title[:500]

    subtitle = meta.get("subtitle", "")
    description = subtitle or _clean(item.get("description"))

    # Location
    location = item.get("location") or {}
    if isinstance(location, list):
        location = location[0] if location else {}
    venue_name = _clean(location.get("name")) or "Kulturlöwen Velbert"
    address = location.get("address") or {}
    if not isinstance(address, dict):
        address = {}
    street = _clean(address.get("streetAddress"))
    postal = _clean(address.get("postalCode"))
    locality = _clean(address.get("addressLocality"))
    city = locality or "Velbert"
    address_parts = [p for p in (street, f"{postal} {city}".strip()) if p]
    address_text = ", ".join(address_parts) if street else None

    # End time (only the HTML knows it, rarely filled)
    end_at: Optional[datetime] = None
    end_time = meta.get("end_time")
    if end_time:
        end_at = start_at.replace(hour=end_time[0], minute=end_time[1])
        if end_at <= start_at:
            end_at += timedelta(days=1)
    elif item.get("endDate"):
        try:
            end_at = to_berlin_naive(datetime.fromisoformat(str(item["endDate"]).strip()))
        except ValueError:
            end_at = None

    image = item.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url")
    image_url = _clean(image) or meta.get("image_url")

    rubrik = meta.get("rubrik", "")
    label = meta.get("label", "")
    category = rubrik or label or _detect_category(title, subtitle)

    event = {
        "canonical_id": _make_canonical(title, start_at, url),
        "title": title,
        "short_description": description[:500] if description else None,
        "start_at": start_at,
        "end_at": end_at,
        "venue_name": venue_name[:255],
        "address_text": address_text,
        "city": city,
        "source_url": url[:500],
        "source_name": SOURCE_NAME,
        "indoor_outdoor": "indoor",
        "kids_suitable": _detect_kids(title, subtitle, rubrik, label),
        "price_text": _format_price(item.get("offers")),
        "category": category[:100] if category else None,
        "image_url": image_url[:500] if image_url else None,
    }
    coords = _venue_coords(venue_name)
    if coords:
        event["lat"], event["lon"] = coords
    return event


def filter_time_window(events: List[Dict], now: Optional[datetime] = None) -> List[Dict]:
    """Keep events from today up to MAX_DAYS_AHEAD days (page lists into 2027)."""
    now = now or datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    horizon = today + timedelta(days=MAX_DAYS_AHEAD)
    return [
        e for e in events
        if e.get("start_at") is not None and today <= e["start_at"] <= horizon
    ]


def parse_kulturloewen_html(html: str, now: Optional[datetime] = None) -> List[Dict]:
    """Parse the Veranstaltungen page (JSON-LD + klive boxes) into event dicts."""
    soup = BeautifulSoup(html, "lxml")
    items = _extract_json_ld_events(soup)
    meta = _extract_html_meta(soup)
    logger.debug(f"Kulturlöwen: {len(items)} JSON-LD events, {len(meta)} HTML boxes")

    events: List[Dict] = []
    seen: set = set()
    for item in items:
        try:
            tid = _ticket_id(str(item.get("url", "")))
            event = _build_event(item, meta.get(tid, {}) if tid else {})
        except Exception as exc:
            logger.debug(f"Kulturlöwen event parse error: {exc}")
            continue
        if not event or event["canonical_id"] in seen:
            continue
        seen.add(event["canonical_id"])
        events.append(event)

    events = filter_time_window(events, now)
    logger.info(f"Kulturlöwen: {len(events)} events extracted")
    return events


async def fetch_kulturloewen_events() -> List[Dict]:
    """Fetch the Kulturlöwen Veranstaltungen page and parse it."""
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        try:
            resp = await client.get(EVENTS_URL)
            resp.raise_for_status()
            return parse_kulturloewen_html(resp.text)
        except Exception as exc:
            logger.error(f"Kulturlöwen fetch failed: {exc}")
            return []


async def sync_kulturloewen(db: Session) -> dict:
    """Sync Kulturlöwen Velbert events to database."""
    events_data = await fetch_kulturloewen_events()
    return sync_events_to_db(db, events_data, SOURCE_NAME)
