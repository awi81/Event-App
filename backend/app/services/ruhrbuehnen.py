"""Ruhrbühnen event source — regional theatre-aggregator HTML list.

``https://www.ruhrbuehnen.de/de/spielplan/`` lists upcoming performances at
theatres across the Ruhr area (Essen, Mülheim, Bochum, Oberhausen,
Gelsenkirchen, Duisburg, Dortmund, Recklinghausen, ...). The list is plain
server-rendered HTML — no Playwright needed. Each day is grouped under a
``div.schedule-date[data-date=<unix ts>]`` heading, followed by a sibling
``div.row[data-date=<same ts>]`` that holds that day's ``div.grid-item``
cards. The ``data-date`` value is a real UTC unix timestamp (verified
against the visible "Fr, 18. September" heading and against a known event
time); converting it with ``ZoneInfo("Europe/Berlin")`` gives the correct
calendar day without any German month-name parsing.

Per card:
    - ``h3.event-title`` → title
    - ``h4.event-meta``  → "HH:MM | Sparte | Stadt" (Sparte is sometimes
      absent: "HH:MM | Stadt")
    - ``div.event-locations`` → two ``span``s after a first one that just
      repeats the time: the presenting theatre company, then (if the venue
      has sub-stages) the specific stage/room, e.g. "Theater und
      Philharmonie Essen" / "Philharmonie Essen".
    - ``img[data-responsive-src]`` → cover image (relative → absolute)
    - the link (``a[href]``) usually points at the presenting theatre's own
      site, not at ruhrbuehnen.de itself.

robots.txt (checked 2026-09-18) is unusually restrictive for this page::

    Disallow: /de/spielplan/?*
    Disallow: /*?date=  /*?page=  /*?locations=  /*?categories=  ... (every filter)
    Allow:    /de/spielplan/$
    Crawl-delay: 5

The site's own pagination is ``?page=N`` (77 pages deep at the time of
writing) and its date-jump widget also works via a disallowed query
parameter. Every way to reach further days is therefore explicitly
disallowed, and only the bare ``/de/spielplan/`` path (no query string at
all) is allowed. This parser makes exactly **one** request per sync and
only ever sees the first page — in practice "today" + "tomorrow" (~24
events across 2 days, as observed during development on 2026-09-18). This
is a deliberate compliance decision, not an oversight — see the module
report for details.

Geographic scope: only theatres in Ruhr-area cities close enough to Essen
Werden are kept (see ``_ALLOWED_CITIES``); Dortmund, Recklinghausen, Hagen,
Moers etc. are dropped even though they appear in the same list.
"""
import hashlib
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.services.base_sync import sync_events_to_db

logger = logging.getLogger(__name__)

SOURCE_NAME = "Ruhrbühnen"
BASE_URL = "https://www.ruhrbuehnen.de"
LIST_URL = f"{BASE_URL}/de/spielplan/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

_BERLIN = ZoneInfo("Europe/Berlin")
_WINDOW_DAYS = 120

# Only theatres in these cities are within reach of Essen Werden. Everything
# else that ruhrbuehnen.de aggregates (Dortmund, Recklinghausen, Hagen,
# Moers, ...) is out of scope for this app and gets dropped in-parser.
_ALLOWED_CITIES = {
    "Essen",
    "Mülheim an der Ruhr",
    "Bochum",
    "Oberhausen",
    "Gelsenkirchen",
    "Duisburg",
    "Velbert",
    "Hattingen",
    "Witten",
}

_KIDS_KEYWORDS = ["kinder", "jugend", "familie", "kita", "schule"]

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def _now_berlin() -> datetime:
    return datetime.now(_BERLIN).replace(tzinfo=None)


def _make_canonical(title: str, start_at: datetime, url: str) -> str:
    return hashlib.md5(
        f"ruhrbuehnen_{title}_{start_at.isoformat()}_{url}".encode()
    ).hexdigest()[:16]


def _detect_kids(title: str, category: Optional[str]) -> str:
    """Sparte "Kinder & Jugend" is an explicit signal; otherwise keyword-guess."""
    cat_lower = (category or "").lower()
    if "kinder" in cat_lower or "jugend" in cat_lower:
        return "yes"
    combined = f"{title} {cat_lower}".lower()
    if any(kw in combined for kw in _KIDS_KEYWORDS):
        return "likely"
    return "unknown"


def _parse_event_meta(meta_text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """"HH:MM | Sparte | Stadt" or "HH:MM | Stadt" -> (time, category, city)."""
    normalized = re.sub(r"\s+", " ", meta_text or "")
    parts = [p.strip() for p in normalized.split("|")]
    parts = [p for p in parts if p]
    if not parts:
        return None, None, None
    time_str = parts[0]
    if len(parts) >= 3:
        return time_str, parts[1], parts[-1]
    if len(parts) == 2:
        return time_str, None, parts[1]
    return time_str, None, None


def _venue_from_locations(loc_el) -> Optional[str]:
    """First span repeats the time; then the theatre company, then the stage."""
    if not loc_el:
        return None
    spans = [s.get_text(strip=True) for s in loc_el.find_all("span")]
    venue_parts = [s for s in spans[1:] if s]
    if not venue_parts:
        return None
    # Prefer the specific stage/room over the umbrella theatre company.
    return venue_parts[1] if len(venue_parts) > 1 else venue_parts[0]


def _parse_grid_item(item, day_date, now: datetime) -> Optional[Dict]:
    """Extract one event from a single ``div.grid-item`` card."""
    title_el = item.find("h3", class_="event-title")
    if not title_el:
        return None
    title = title_el.get_text(strip=True)
    if not title:
        return None

    link_el = item.find("a", href=True)
    if not link_el:
        return None
    href = link_el["href"]
    source_url = href if href.startswith("http") else f"{BASE_URL}{href}"

    meta_el = item.find("h4", class_="event-meta")
    time_str, category, city = _parse_event_meta(meta_el.get_text(" ") if meta_el else "")

    # Geographic filter: drop theatres outside the Ruhr-area cities we serve.
    if not city or city not in _ALLOWED_CITIES:
        return None

    hour, minute = 0, 0
    if time_str:
        m = _TIME_RE.match(time_str)
        if m:
            hour, minute = int(m.group(1)), int(m.group(2))

    try:
        start_at = datetime(day_date.year, day_date.month, day_date.day, hour, minute)
    except ValueError:
        return None

    today = now.date()
    if start_at.date() < today or start_at.date() > today + timedelta(days=_WINDOW_DAYS):
        return None

    venue_name = _venue_from_locations(item.find("div", class_="event-locations")) or SOURCE_NAME

    img_el = item.find("img", attrs={"data-responsive-src": True})
    image_url = None
    if img_el:
        src = img_el.get("data-responsive-src")
        if src:
            image_url = src if src.startswith("http") else f"{BASE_URL}{src}"

    return {
        "canonical_id": _make_canonical(title, start_at, source_url),
        "title": title[:500],
        "start_at": start_at,
        "venue_name": venue_name,
        "city": city,
        "source_url": source_url[:500],
        "source_name": SOURCE_NAME,
        "indoor_outdoor": "indoor",
        "kids_suitable": _detect_kids(title, category),
        "category": category,
        "image_url": image_url[:500] if image_url else None,
    }


def parse_ruhrbuehnen_html(html: str, now: Optional[datetime] = None) -> List[Dict]:
    """Parse the Spielplan list page into event dicts (offline-testable).

    ``now`` lets tests pin "today" instead of depending on wall-clock time.
    """
    now = now or _now_berlin()
    soup = BeautifulSoup(html, "lxml")

    events: List[Dict] = []
    for row in soup.find_all("div", class_="row", attrs={"data-date": True}):
        try:
            day_date = datetime.fromtimestamp(int(row["data-date"]), tz=_BERLIN).date()
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        for item in row.find_all("div", class_="grid-item"):
            try:
                event = _parse_grid_item(item, day_date, now)
                if event:
                    events.append(event)
            except Exception as exc:
                logger.debug(f"Ruhrbühnen item parse error: {exc}")

    logger.info(f"Ruhrbühnen: {len(events)} events extracted (Ruhr-area cities only)")
    return events


async def fetch_ruhrbuehnen_events() -> List[Dict]:
    """Fetch the Spielplan list page.

    robots.txt disallows every query-string variant this site offers for
    pagination or date-jumping on this page (see module docstring), so only
    the plain list URL is fetched — a single request, no crawl loop.
    """
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        try:
            resp = await client.get(LIST_URL)
            resp.raise_for_status()
            return parse_ruhrbuehnen_html(resp.text)
        except Exception as exc:
            logger.error(f"Ruhrbühnen fetch failed: {exc}")
            return []


async def sync_ruhrbuehnen(db: Session):
    """Sync Ruhrbühnen events to database."""
    events_data = await fetch_ruhrbuehnen_events()
    return sync_events_to_db(db, events_data, SOURCE_NAME)
