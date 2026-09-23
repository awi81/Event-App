"""LWL-Industriemuseum event source — three museum sites, one shared HTML template.

Henrichshütte Hattingen, Zeche Nachtigall Witten and Zeche Hannover Bochum all
run the same LWL CMS. Each site lists its upcoming events on
``/de/veranstaltungen/`` as ``div.event-element`` blocks (date, time, type,
title, subtitle, teaser, detail link, image). One parser handles all three.

robots.txt on every site only disallows /login and /admin.
"""
import asyncio
import hashlib
import logging
import re
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.services.base_sync import sync_events_to_db
from app.services.crawler_ua import CRAWLER_USER_AGENT

logger = logging.getLogger(__name__)

SOURCE_NAME = "LWL-Industriemuseum"

# Coordinates: Nominatim-verified museum nodes (OSM), Sept 2026.
SITES: List[Dict] = [
    {
        "key": "henrichshuette",
        "base_url": "https://henrichshuette.lwl.org",
        "list_url": "https://henrichshuette.lwl.org/de/veranstaltungen/",
        "venue_name": "LWL-Industriemuseum Henrichshütte Hattingen",
        "address": "Werksstraße 31-33, 45527 Hattingen",
        "city": "Hattingen",
        "lat": 51.4060305,
        "lon": 7.1881886,
    },
    {
        "key": "zeche-nachtigall",
        "base_url": "https://zeche-nachtigall.lwl.org",
        "list_url": "https://zeche-nachtigall.lwl.org/de/veranstaltungen/",
        "venue_name": "LWL-Industriemuseum Zeche Nachtigall",
        "address": "Nachtigallstraße 35, 58452 Witten",
        "city": "Witten",
        "lat": 51.4287004,
        "lon": 7.3133235,
    },
    {
        "key": "zeche-hannover",
        "base_url": "https://zeche-hannover.lwl.org",
        "list_url": "https://zeche-hannover.lwl.org/de/veranstaltungen/",
        "venue_name": "LWL-Industriemuseum Zeche Hannover",
        "address": "Günnigfelder Straße 251, 44793 Bochum",
        "city": "Bochum",
        "lat": 51.5044976,
        "lon": 7.1645108,
    },
]

_HEADERS = {
    "User-Agent": CRAWLER_USER_AGENT
}

_BERLIN = ZoneInfo("Europe/Berlin")

# Only events from today up to this horizon are kept.
_WINDOW_DAYS = 120
# Multi-day spans longer than this are treated as a daily series (exhibitions)
# and expanded into single days; shorter spans stay one event with end_at.
_SERIES_MIN_DAYS = 7
# Cap for expanded daily occurrences per listing.
_MAX_SERIES_OCCURRENCES = 60

# Fallback times when the listing has no time text.
_DEFAULT_START = time(10, 0)
_DEFAULT_END = time(18, 0)

# "18.9.2026", "26.9." (year missing on the first half of a span)
_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(?:\s*(\d{4}))?")
# Hour with optional minutes, only when followed by a time-ish token so a
# stray number (e.g. "ab 7 Jahre") is never read as a time.
_TIME_RE = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(?=uhr|-|–|bis|und|,|$)", re.IGNORECASE
)
_RANGE_RE = re.compile(r"\d\s*(?:-|–|bis)\s*\d", re.IGNORECASE)

# "Für Kinder", "Kinderführung", "Familienführung", "Familientag" → explicit.
_KIDS_YES_RE = re.compile(r"\b(?:kinder|familie|familien)", re.IGNORECASE)
_KIDS_LIKELY_KEYWORDS = [
    "ferien", "jugend", "basteln", "maus", "schüler", "schueler", "mitmach",
    "knirps", "kids", "kita", "schule", "junior",
]

# Event types that happen inside (everything else is "both": the museums are
# industrial sites with large outdoor grounds).
_INDOOR_TYPE_KEYWORDS = [
    "film", "theater", "kabarett", "kurs", "vortrag", "lesung", "konzert",
]


def _now_berlin() -> datetime:
    return datetime.now(_BERLIN).replace(tzinfo=None)


def _make_canonical(site_key: str, title: str, start_at: datetime, url: str) -> str:
    return hashlib.md5(
        f"lwl_{site_key}_{title}_{start_at.isoformat()}_{url}".encode()
    ).hexdigest()[:16]


# ─────────────────────────────── date / time ──────────────────────────────────


def _parse_date_text(
    date_text: str, now: Optional[datetime] = None
) -> Tuple[Optional[date], Optional[date]]:
    """Parse the ``.event-date`` text into (start_date, end_date).

    Formats seen live:
    - "Freitag, 18.9.2026"                        → single day
    - "Samstag, 26.9. bis Sonntag, 27.9.2026"     → span, year only on the end
    - "Mittwoch, 6.5. bis Sonntag, 4.10.2026"     → long span (exhibition)
    A date without any year gets the next occurrence in the future.
    """
    now = now or _now_berlin()
    matches = _DATE_RE.findall(date_text or "")
    if not matches:
        return None, None

    def _build(
        day_s: str, month_s: str, year_s: str, fallback_year: Optional[int]
    ) -> Optional[date]:
        try:
            day, month = int(day_s), int(month_s)
            year = int(year_s) if year_s else fallback_year
            if year is None:
                # No year anywhere: choose the next future occurrence.
                candidate = date(now.year, month, day)
                if candidate < now.date():
                    candidate = date(now.year + 1, month, day)
                return candidate
            return date(year, month, day)
        except ValueError:
            return None

    end_day, end_month, end_year = matches[-1]
    end_date = _build(end_day, end_month, end_year, None)
    if end_date is None:
        return None, None

    if len(matches) == 1:
        return end_date, None

    start_day, start_month, start_year = matches[0]
    fallback_year = end_date.year
    # Year-wrapping span ("20.12. bis 5.1.2027"): start belongs to the year before.
    if not start_year and int(start_month) > end_date.month:
        fallback_year = end_date.year - 1
    start_date = _build(start_day, start_month, start_year, fallback_year)
    if start_date is None:
        return None, None
    if start_date > end_date:
        return end_date, None
    return start_date, end_date


def _parse_time_text(time_text: str) -> Tuple[List[time], Optional[time]]:
    """Parse the ``.event-time`` text into (start_times, end_time).

    Formats seen live:
    - "17:00 Uhr"                              → [17:00], None
    - "15 - 19:30 Uhr" / "12:00 bis 18:00 Uhr" → [15:00], 19:30
    - "Einlass 18:00 Uhr, Beginn 20:00 Uhr"    → [20:00], None
    - "12:00 und 15:00 Uhr"                    → [12:00, 15:00], None
    - "FR 18:00-21:30 Uhr, SA und SO je 10:00-16:00 Uhr" → [18:00], 16:00
    Returns ([], None) when no time can be found (→ all-day).
    """
    text = (time_text or "").strip().lower()
    if not text:
        return [], None
    # Mask anything date-like first ("24.06." must never become 24:06).
    text = re.sub(r"\d{1,2}\.\d{1,2}\.(?:\d{2,4})?", " ", text)

    # "Einlass 18:00 Uhr, Beginn 20:00 Uhr" → the Beginn time is the start.
    beginn = re.search(r"beginn\s*:?\s*(\d{1,2})(?::(\d{2}))?", text)
    if beginn:
        t = _safe_time(beginn.group(1), beginn.group(2))
        return ([t], None) if t else ([], None)

    times: List[time] = []
    for hour_s, minute_s in _TIME_RE.findall(text):
        t = _safe_time(hour_s, minute_s)
        if t:
            times.append(t)
    if not times:
        return [], None
    if len(times) >= 2 and _RANGE_RE.search(text):
        return [times[0]], times[-1]
    if len(times) >= 2 and " und " in text:
        return times, None
    return [times[0]], None


def _safe_time(hour_s: str, minute_s: Optional[str]) -> Optional[time]:
    try:
        hour = int(hour_s)
        minute = int(minute_s) if minute_s else 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return time(hour, minute)
    except (TypeError, ValueError):
        pass
    return None


# ─────────────────────────────── classification ───────────────────────────────


def _detect_kids(event_type: str, title: str, subtitle: str) -> str:
    combined = " ".join([event_type or "", title or "", subtitle or ""])
    if _KIDS_YES_RE.search(combined):
        return "yes"
    lowered = combined.lower()
    if any(kw in lowered for kw in _KIDS_LIKELY_KEYWORDS):
        return "likely"
    return "unknown"


def _detect_indoor_outdoor(event_type: str) -> str:
    lowered = (event_type or "").lower()
    if any(kw in lowered for kw in _INDOOR_TYPE_KEYWORDS):
        return "indoor"
    return "both"


# ─────────────────────────────── parsing ──────────────────────────────────────


def parse_lwl_html(html: str, site: Dict, now: Optional[datetime] = None) -> List[Dict]:
    """Parse one site's listing page into event dicts (offline-testable)."""
    now = now or _now_berlin()
    soup = BeautifulSoup(html, "lxml")
    blocks = soup.select("div.event-element")
    logger.debug(f"LWL {site['key']}: {len(blocks)} event-element blocks found")

    events: List[Dict] = []
    seen_ids: set = set()
    for block in blocks:
        try:
            for event in _parse_event_block(block, site, now):
                if event["canonical_id"] not in seen_ids:
                    seen_ids.add(event["canonical_id"])
                    events.append(event)
        except Exception as exc:
            logger.debug(f"LWL {site['key']} block parse error: {exc}")

    logger.info(f"LWL {site['key']}: {len(events)} events extracted")
    return events


def _text(block, selector: str) -> str:
    el = block.select_one(selector)
    return el.get_text(" ", strip=True) if el else ""


def _parse_event_block(block, site: Dict, now: datetime) -> List[Dict]:
    """Turn one ``div.event-element`` into zero, one or several event dicts."""
    title = re.sub(r"\s+", " ", _text(block, ".event-title")).strip()
    if not title:
        return []

    date_text = _text(block, ".event-date")
    start_date, end_date = _parse_date_text(date_text, now)
    if start_date is None:
        return []

    time_text = _text(block, ".event-time")
    start_times, end_time = _parse_time_text(time_text)
    is_all_day = not start_times
    if is_all_day:
        start_times = [_DEFAULT_START]

    event_type = _text(block, ".event-type")
    subtitle = _text(block, ".event-subtitle")
    description = _text(block, ".event-description")

    # Deep link: "/de/veranstaltungen/?id=1101498" → absolute; fallback to
    # the list page plus the title span's anchor.
    link_el = block.select_one("a.btn-link[href]") or block.select_one("a[href]")
    if link_el and link_el.get("href") and not link_el["href"].startswith("#"):
        source_url = urljoin(site["base_url"], link_el["href"])
    else:
        title_span = block.select_one(".event-title [id]")
        fragment = f"#{title_span['id']}" if title_span else ""
        source_url = site["list_url"] + fragment

    img_el = block.select_one(".event-image img[src]") or block.select_one("img[src]")
    image_url = urljoin(site["base_url"], img_el["src"]) if img_el else None

    short_description = " — ".join(p for p in [subtitle, description] if p)[:500] or None

    base = {
        "title": title[:500],
        "short_description": short_description,
        "is_all_day": is_all_day,
        "venue_name": site["venue_name"],
        "address_text": site["address"],
        "city": site["city"],
        "lat": site["lat"],
        "lon": site["lon"],
        "source_url": source_url[:500],
        "source_name": SOURCE_NAME,
        "indoor_outdoor": _detect_indoor_outdoor(event_type),
        "kids_suitable": _detect_kids(event_type, title, subtitle),
        "category": event_type or None,
        "image_url": image_url[:500] if image_url else None,
    }

    today = now.date()
    horizon = today + timedelta(days=_WINDOW_DAYS)
    events: List[Dict] = []

    # Long spans (exhibitions, "6.5. bis 4.10.") are daily series: one row per
    # day from today on, so an already-running exhibition stays visible.
    if end_date and (end_date - start_date).days > _SERIES_MIN_DAYS:
        day = max(start_date, today)
        count = 0
        while day <= end_date and day <= horizon and count < _MAX_SERIES_OCCURRENCES:
            start_at = datetime.combine(day, start_times[0])
            end_at = datetime.combine(day, end_time) if end_time else None
            events.append(_finish_event(base, site, start_at, end_at))
            day += timedelta(days=1)
            count += 1
        return events

    if start_date < today or start_date > horizon:
        return []

    last_day = end_date or start_date
    for start_time in start_times:
        start_at = datetime.combine(start_date, start_time)
        if end_time:
            end_at = datetime.combine(last_day, end_time)
        elif end_date:
            end_at = datetime.combine(last_day, _DEFAULT_END)
        else:
            end_at = None
        events.append(_finish_event(base, site, start_at, end_at))
    return events


def _finish_event(base: Dict, site: Dict, start_at: datetime, end_at: Optional[datetime]) -> Dict:
    if end_at is not None and end_at <= start_at:
        end_at = None
    event = dict(base)
    event["start_at"] = start_at
    event["end_at"] = end_at
    event["canonical_id"] = _make_canonical(
        site["key"], base["title"], start_at, base["source_url"]
    )
    return event


# ─────────────────────────────── fetch / sync ─────────────────────────────────


async def fetch_lwl_industriemuseum_events() -> List[Dict]:
    """Fetch the listing page of all three sites (1 s pause between requests)."""
    events: List[Dict] = []
    # Host publishes AAAA records; GitHub runners have no working IPv6 and
    # time out on connect. Force IPv4.
    async with httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(local_address="0.0.0.0"),
        timeout=30.0,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        for index, site in enumerate(SITES):
            if index > 0:
                await asyncio.sleep(1.0)
            # The LWL host occasionally times out for a whole run (all three
            # sites at once, empty httpx message) — one retry after a pause
            # has been enough so far.
            for attempt in (1, 2):
                try:
                    resp = await client.get(site["list_url"])
                    resp.raise_for_status()
                    events.extend(parse_lwl_html(resp.text, site))
                    break
                except Exception as exc:
                    if attempt == 1:
                        logger.info(f"LWL {site['key']}: {type(exc).__name__}: {exc} — retry")
                        await asyncio.sleep(5.0)
                    else:
                        logger.error(f"LWL {site['key']} fetch failed: {type(exc).__name__}: {exc}")

    logger.info(f"LWL-Industriemuseum: {len(events)} events total")
    return events


async def sync_lwl_industriemuseum(db: Session):
    """Sync LWL-Industriemuseum events (three sites) to database."""
    events_data = await fetch_lwl_industriemuseum_events()
    return sync_events_to_db(db, events_data, SOURCE_NAME)
