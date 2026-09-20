"""Zollverein sync.

Background on the old ``events.zollverein.de/api/v1/`` endpoint
-----------------------------------------------------------------
That endpoint answers every request - regardless of User-Agent, Accept,
Referer or Origin header - with ``403 {"code":403,"message":"Unauthorized."}``
(non-date paths like ``/api/v1/events`` 404 instead, so the route exists, it
just requires a credential). This is an application-level auth gate, not a
bot/WAF block: the calendar page at https://www.zollverein.de/kalender/ (a
Nuxt app) never calls that host from the browser at all. Its JS bundle
(``/kalender/_nuxt/*.js``) shows the real client-side call is
``$fetch(`/api/events/${yyyymmdd}`, {query})`` - a same-origin Nuxt/Nitro
server route. That route (``ZOLLVEREIN_DAY_API`` below) presumably proxies to
events.zollverein.de server-side with a credential that never reaches the
browser, which is exactly why no header combination we send can make the
public API accept us, and why the day route is the correct, intended
integration point (it's what real visitors' browsers use).

The day route returns clean structured JSON per calendar day (title, slug,
url, image, times, terms/tags, location, category, description) with no
auth required and no rate limiting observed. We walk it for every day in
[today, today + SYNC_WINDOW_DAYS] to build the event list; each event
occurrence (one specific open day) becomes one row, consistent with how
other multi-date sources in this codebase work - ``grouping.py`` collapses
repeated (title, source) rows into a single frontend card with an
``occurrences[]`` list.

``fetch_zollverein_fallback`` scrapes the calendar page's SSR'd HTML as a
last resort if the JSON route ever becomes unreachable. That page only ever
server-renders "today" plus the next day that has events (mirroring the
JSON route's own ``next_occurrence`` pairing), so it covers at most 1-2 days
- it exists purely so a sync still produces *something* if the JSON route
breaks, not as a real substitute for the 120-day window.
"""
import asyncio
import hashlib
import logging
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import httpx

from sqlalchemy.orm import Session

from app.services.base_sync import sync_events_to_db

logger = logging.getLogger(__name__)

# Same-origin Nuxt/Nitro server route used by zollverein.de/kalender/ itself.
ZOLLVEREIN_DAY_API = "https://www.zollverein.de/kalender/api/events/{date}"
ZOLLVEREIN_CALENDAR_PAGE = "https://www.zollverein.de/kalender/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# Zollverein-wide fallback coordinates (Gelsenkirchener Str. 181, 45309 Essen).
# All events from this source sit within the same UNESCO World Heritage Site
# grounds, so a single approximate point is accurate enough without relying
# on downstream geocoding to resolve dozens of internal building names.
ZOLLVEREIN_LAT = 51.4864
ZOLLVEREIN_LON = 7.0403

SYNC_WINDOW_DAYS = 120
_DAY_CONCURRENCY = 6

_KIDS_SLUGS = {"kinder", "kinder-und-familien"}
_TEEN_SLUGS = {"jugendliche"}
_ADULT_ONLY_SLUGS = {"erwachsee", "erwachsene"}

_GERMAN_MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11,
    "dezember": 12,
}


async def _fetch_day(client: httpx.AsyncClient, day: date) -> dict:
    """GET one day's JSON payload from the Zollverein calendar day route."""
    response = await client.get(ZOLLVEREIN_DAY_API.format(date=day.strftime("%Y%m%d")))
    response.raise_for_status()
    return response.json()


async def fetch_zollverein_events() -> List[Dict]:
    """Fetch events for [today, today + SYNC_WINDOW_DAYS] from the Zollverein
    calendar day API. Falls back to HTML scraping (1-2 days only) if the
    JSON route is unreachable for the whole window.
    """
    today = datetime.now().date()
    all_days = [today + timedelta(days=i) for i in range(SYNC_WINDOW_DAYS + 1)]
    sem = asyncio.Semaphore(_DAY_CONCURRENCY)

    async def _one(client: httpx.AsyncClient, day: date):
        async with sem:
            try:
                data = await _fetch_day(client, day)
            except Exception as e:
                logger.debug(f"Zollverein: day fetch failed for {day}: {e}")
                return False, []
        return True, parse_zollverein_api(data, day)

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=_HEADERS) as client:
        try:
            results = await asyncio.gather(*(_one(client, d) for d in all_days))
        except Exception as e:
            # Should not normally happen (per-day errors are caught in _one),
            # but guard against e.g. a client construction failure anyway.
            logger.info(f"Zollverein day API unusable ({e}), falling back to HTML scraping")
            return await fetch_zollverein_fallback()

    successes = sum(1 for ok, _ in results if ok)
    events = [e for ok, evs in results if ok for e in evs]

    if successes == 0:
        logger.info(
            "Zollverein day API unreachable for the whole sync window, "
            "falling back to HTML scraping (covers only 1-2 days)"
        )
        return await fetch_zollverein_fallback()

    failures = len(all_days) - successes
    if failures:
        logger.debug(f"Zollverein: {failures}/{len(all_days)} day requests failed, using partial data")

    events = cap_occurrences(events)
    logger.info(f"Found {len(events)} events from Zollverein day API ({successes}/{len(all_days)} days)")
    return events


# Permanent exhibitions are "open" every day of the window and would produce
# ~120 rows each. Same cap visitessen uses; grouping.py folds them into one
# card anyway and the frontend shows at most 8 upcoming dates.
MAX_OCCURRENCES_PER_EVENT = 60


def cap_occurrences(events: List[Dict], limit: int = MAX_OCCURRENCES_PER_EVENT) -> List[Dict]:
    """Keep only the first `limit` occurrences per (source_url or title), in date order."""
    ordered = sorted(events, key=lambda e: (e.get("start_at") or datetime.max))
    seen: Dict[str, int] = {}
    kept: List[Dict] = []
    for e in ordered:
        key = e.get("source_url") or e.get("title") or ""
        seen[key] = seen.get(key, 0) + 1
        if seen[key] <= limit:
            kept.append(e)
    return kept


async def fetch_zollverein_fallback() -> List[Dict]:
    """Fallback: scrape the SSR'd kalender page (today + next event day only)."""
    logger.info("Zollverein: using HTML fallback (covers only the next 1-2 days)")

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=_HEADERS) as client:
        try:
            response = await client.get(ZOLLVEREIN_CALENDAR_PAGE)
            response.raise_for_status()
            return parse_zollverein_html(response.text)
        except Exception as e:
            logger.warning(f"Error fetching Zollverein HTML fallback: {e}")
            return []


def parse_zollverein_date(date_str: Optional[str], time_str: Optional[str] = None) -> Optional[datetime]:
    """Combine a Zollverein 'YYYY-MM-DD' date with an optional 'HH:MM' local
    time into a naive Europe/Berlin datetime.

    Unlike most other parsers in this codebase, no timezone conversion is
    needed here: the day API already returns plain Berlin wall-clock date and
    time components (no UTC offset), so the value is naive-already.
    """
    if not date_str:
        return None
    try:
        combined = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None
    if not time_str:
        return combined
    m = re.match(r"^(\d{1,2}):(\d{2})$", time_str.strip())
    if not m:
        return combined
    return combined.replace(hour=int(m.group(1)), minute=int(m.group(2)))


def _event_times(day: date, times: List[dict]) -> tuple:
    """Turn a day's 'times' slot list into (start_at, end_at, is_all_day).

    Standing exhibitions open one continuous window a day (one slot); guided
    tours can have many slots (one per departure). Either way we want one row
    per (event, day), so we span from the earliest start to the latest end.
    """
    day_str = day.isoformat()
    starts: List[datetime] = []
    ends: List[datetime] = []
    is_all_day = False

    for slot in times or []:
        if slot.get("all_day"):
            is_all_day = True
        start = parse_zollverein_date(day_str, slot.get("start"))
        end = parse_zollverein_date(day_str, slot.get("end"))
        if start:
            starts.append(start)
        if end:
            ends.append(end)

    if not starts:
        return parse_zollverein_date(day_str), None, True

    start_at = min(starts)
    end_at = max(ends) if ends else None
    if end_at and end_at < start_at:
        end_at += timedelta(days=1)  # open-end slot crossing midnight
    return start_at, end_at, is_all_day


def _kids_suitable_from_terms(terms: List[dict]) -> Optional[str]:
    slugs = set()
    for term in terms or []:
        attrs = (term or {}).get("attributes") or {}
        slug = attrs.get("slug")
        if slug:
            slugs.add(slug)

    if slugs & _KIDS_SLUGS:
        return "yes"
    if slugs & _TEEN_SLUGS:
        return "likely"
    if slugs & _ADULT_ONLY_SLUGS:
        return "no"
    return None


def parse_zollverein_api(day_data: dict, requested_date: date) -> List[Dict]:
    """Parse one day's response from the Zollverein calendar day API."""
    events: List[Dict] = []
    items = (day_data or {}).get("data") or []

    for item in items:
        try:
            event = convert_zollverein_event(item, requested_date)
            if event:
                events.append(event)
        except Exception as e:
            logger.warning(f"Error parsing Zollverein event: {e}")
            continue

    return events


def convert_zollverein_event(item: dict, requested_date: date) -> Optional[Dict]:
    """Convert one Zollverein day-API event occurrence to our event format."""
    try:
        attributes = item.get("attributes") or {}
        title = attributes.get("title")
        if not title:
            return None

        event_id = item.get("id") or ""
        url = attributes.get("url")

        canonical_id = hashlib.md5(
            f"zollverein_{event_id or url or title}_{requested_date.isoformat()}".encode()
        ).hexdigest()[:16]

        start_at, end_at, is_all_day = _event_times(requested_date, item.get("times") or [])

        location = item.get("location") or {}
        loc_attrs = location.get("attributes") or {}
        venue_name = loc_attrs.get("title") or "Zollverein"

        category_obj = item.get("category") or {}
        category = (category_obj.get("attributes") or {}).get("title")

        content = item.get("content") or {}
        excerpt = (content.get("excerpt") or {}).get("text")
        description = excerpt[:500] if excerpt else None

        image = attributes.get("image") or {}
        image_url = image.get("url")

        kids_suitable = _kids_suitable_from_terms(item.get("terms") or [])

        event: Dict = {
            "canonical_id": canonical_id,
            "title": title,
            "short_description": description,
            "start_at": start_at,
            "end_at": end_at,
            "is_all_day": is_all_day,
            "is_recurring": bool(item.get("recurring")),
            "venue_name": venue_name,
            "category": category,
            "source_url": url,
            "source_name": "Zollverein",
            "city": "Essen",
            "lat": ZOLLVEREIN_LAT,
            "lon": ZOLLVEREIN_LON,
        }
        if image_url:
            event["image_url"] = image_url
        if kids_suitable:
            event["kids_suitable"] = kids_suitable

        return event
    except Exception as e:
        logger.warning(f"Error converting Zollverein event: {e}")
        return None


def _parse_german_day_heading(text: Optional[str]) -> Optional[date]:
    """Parse 'Veranstaltungen am Sonntag, September 20, 2026' into a date."""
    if not text:
        return None
    m = re.search(r"([A-Za-zÀ-ÿ]+)\s+(\d{1,2}),\s+(\d{4})", text)
    if not m:
        return None
    month = _GERMAN_MONTHS.get(m.group(1).lower())
    if not month:
        return None
    try:
        return date(int(m.group(3)), month, int(m.group(2)))
    except ValueError:
        return None


def parse_zollverein_html(html: str) -> List[Dict]:
    """Parse the SSR'd zollverein.de/kalender/ page (fallback only).

    The page server-renders one <li> "day section" per day it shows (today,
    plus the next day that has events - it has no further pagination in
    static HTML), each containing a heading with the German date and a list
    of event <li> items.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    events: List[Dict] = []

    day_sections = soup.select('li[class*="mb-8"]')
    if day_sections:
        for section in day_sections:
            heading = section.select_one("h2 span.sr-only") or section.select_one("h2.sr-only")
            day = _parse_german_day_heading(heading.get_text(strip=True)) if heading else None
            for item in section.select("li.mb-4"):
                try:
                    event = extract_zollverein_event(item, day)
                    if event:
                        events.append(event)
                except Exception as e:
                    logger.warning(f"Error parsing event: {e}")
                    continue
    else:
        # Structure changed beyond recognition of the day sections - fall
        # back to a flat scan so a full markup rewrite doesn't yield zero.
        event_items = soup.select("li.mb-4") or soup.select('li[class*="mb-"]') or soup.select('li[role="button"]')
        for item in event_items:
            try:
                event = extract_zollverein_event(item, None)
                if event:
                    events.append(event)
            except Exception as e:
                logger.warning(f"Error parsing event: {e}")
                continue

    logger.info(f"Found {len(events)} events from Zollverein HTML fallback")
    return events


def extract_zollverein_event(item, day: Optional[date] = None) -> Optional[Dict]:
    """Extract event data from one HTML list item (fallback)."""
    try:
        title_elem = item.select_one("h3 a") or item.select_one("h3")
        if not title_elem:
            return None

        title = title_elem.get_text(strip=True)
        if not title or len(title) < 5:
            return None

        link_elem = item.select_one("h3 a")
        href = link_elem.get("href", "") if link_elem else ""
        source_url = f"https://www.zollverein.de{href}" if href else None

        effective_day = day or datetime.now().date()
        canonical_id = hashlib.md5(
            f"zollverein_{href or title}_{effective_day.isoformat()}".encode()
        ).hexdigest()[:16]

        category = None
        category_elem = item.select_one('[aria-label^="Kategorie"]')
        if category_elem:
            category = category_elem.get("aria-label", "").replace("Kategorie", "").strip() or None

        venue_name = "Zollverein"
        h3_tag = item.select_one("h3")
        venue_div = h3_tag.find_previous_sibling("div") if h3_tag else None
        if venue_div:
            venue_text = venue_div.get_text(strip=True)
            if venue_text:
                venue_name = venue_text

        desc_elem = item.select_one("p.text-gray-700") or item.select_one("p")
        description = desc_elem.get_text(strip=True)[:500] if desc_elem else None

        start_at = datetime(effective_day.year, effective_day.month, effective_day.day)
        end_at = None
        time_elem = item.select_one("span.sr-only")
        if time_elem:
            m = re.search(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", time_elem.get_text())
            if m:
                start_at = start_at.replace(hour=int(m.group(1)), minute=int(m.group(2)))
                end_at = datetime(
                    effective_day.year, effective_day.month, effective_day.day,
                    int(m.group(3)), int(m.group(4)),
                )

        img_elem = item.select_one(".event-list-image img") or item.select_one('img[loading="lazy"]')
        image_url = img_elem.get("src") if img_elem else None

        event: Dict = {
            "canonical_id": canonical_id,
            "title": title,
            "short_description": description,
            "start_at": start_at,
            "venue_name": venue_name,
            "category": category,
            "source_url": source_url,
            "source_name": "Zollverein",
            "city": "Essen",
            "lat": ZOLLVEREIN_LAT,
            "lon": ZOLLVEREIN_LON,
        }
        if end_at:
            event["end_at"] = end_at
        if image_url:
            event["image_url"] = image_url

        return event
    except Exception:
        return None


async def sync_zollverein(db: Session):
    """Sync events from Zollverein to database."""
    events_data = await fetch_zollverein_events()
    return sync_events_to_db(db, events_data, "Zollverein")
