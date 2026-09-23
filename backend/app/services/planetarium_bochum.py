"""Zeiss Planetarium Bochum event source — culturebase.org calendar JSON API.

``https://www.planetarium-bochum.de/de_DE/repertoire`` itself is just static
copy (a PDF download + a link to the actual calendar) — the show list is
rendered client-side on ``/de_DE/calendar`` via a "culturebase.org" widget
(``/media/scripts/page_calendar.js``, ``CbEventSearch``). That widget calls::

    GET /de_DE/event.json
        ?current_language=
        &date=<DD.MM.YYYY>      # results start at/after this date, ascending
        &category=
        &p=<page>               # 1-based, 20 results per page
        &dynamic_calendar=calendar

found by downloading the page's own ``<script src>`` files and grepping for
``ajax``/``url:`` (see ``page_calendar.js`` line ~167:
``url: ENV.link_root + '/event.json'``, with ``link_root`` = ``/de_DE``).
No auth/referer header is required — verified with a plain ``curl`` GET.

Response shape (verified 2026-09-18)::

    {"Count": {"All": 1089, "Date": 724},
     "Pager": {"NbResults": 724, "FirstIndex": 1, "LastIndex": 20,
               "IsFirstPage": true, "IsLastPage": false},
     "EventOverview": [{
         "Title": "...", "DetailUrl": "/de_DE/calendar/<slug>.<id>?event_date=<id>",
         "CalendarDisplayDateTimeStart": "2026-09-18 20:45",   # naive Berlin wall-clock
         "City": "Bochum", "Location": "Zeiss Planetarium Bochum",
         "Keyword": "KinderShow" | "AstronomieShow" | "MusikShow" | "Konzert" | "Hörspiel",
         "Description": "...", "PictureUri": "https://img.culturebase.org/...",
         "IsSoldOut": false, "IsCanceled": false, ...
     }, ...]}

``Keyword`` is exactly the raw show-type category this app wants. Results
are already sorted ascending by date, so pagination just increments ``p``
until ``Pager.IsLastPage`` is true or an item's date passes the 60-day
horizon (~7 shows/day means that is roughly page 20-25).

robots.txt (checked 2026-09-18, both the redirecting ``www.`` host and the
canonical ``planetarium-bochum.de``) only disallows ``/support/`` — nothing
here is restricted.
"""
import asyncio
import hashlib
import logging
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session

from app.services.base_sync import sync_events_to_db
from app.services.crawler_ua import CRAWLER_USER_AGENT

logger = logging.getLogger(__name__)

SOURCE_NAME = "Planetarium Bochum"
BASE_URL = "https://planetarium-bochum.de"
API_URL = f"{BASE_URL}/de_DE/event.json"

VENUE_NAME = "Zeiss Planetarium Bochum"
ADDRESS_TEXT = "Castroper Straße 67, 44791 Bochum"
CITY = "Bochum"
# Nominatim (checked 2026-09-18): "Castroper Straße 67, 44791 Bochum" -> 51.4854920, 7.2276776
# (matches the venue's own Latitude/Longitude in the API payload, ~51.485/7.229, within ~50m)
VENUE_LAT = 51.4854920
VENUE_LON = 7.2276776

_HEADERS = {
    "User-Agent": CRAWLER_USER_AGENT
}

_BERLIN = ZoneInfo("Europe/Berlin")
_WINDOW_DAYS = 60
_PAGE_SIZE = 20
# Politeness caps: 60 days at ~7 shows/day is ~420 events / 20 per page ~= 21
# pages; the horizon check below stops earlier in practice, this is only a
# runaway guard.
_MAX_PAGES = 30
_PAGE_PAUSE_SECONDS = 0.4

_AGE_RE = re.compile(r"ab\s+\d+\s*jahren", re.IGNORECASE)


def _now_berlin() -> datetime:
    return datetime.now(_BERLIN).replace(tzinfo=None)


def _make_canonical(title: str, start_at: datetime, url: str) -> str:
    return hashlib.md5(
        f"planetariumbochum_{title}_{start_at.isoformat()}_{url}".encode()
    ).hexdigest()[:16]


def _parse_display_date(value: Optional[str]) -> Optional[datetime]:
    """"2026-09-18 20:45" (naive Berlin wall-clock, as shown in the UI)."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _detect_kids(category: Optional[str], description: Optional[str]) -> str:
    """Explicit signal only: KinderShow keyword or an "ab N Jahren" age note."""
    if category and "kinder" in category.lower():
        return "yes"
    if description and _AGE_RE.search(description):
        return "yes"
    return "unknown"


def _parse_event_overview_item(item: Dict, today: date, horizon: date) -> Optional[Dict]:
    """Extract one performance from an ``EventOverview`` entry."""
    if not isinstance(item, dict):
        return None
    if item.get("IsCanceled"):
        return None

    title = (item.get("Title") or "").strip()
    if not title:
        return None

    start_at = _parse_display_date(item.get("CalendarDisplayDateTimeStart"))
    if start_at is None:
        return None
    if start_at.date() < today or start_at.date() > horizon:
        return None

    detail_url = item.get("DetailUrl") or ""
    if not detail_url:
        return None
    source_url = detail_url if detail_url.startswith("http") else f"{BASE_URL}{detail_url}"

    category = (item.get("Keyword") or "").strip() or None
    description = re.sub(r"\s+", " ", (item.get("Description") or "")).strip()

    image_url = item.get("PictureUri") or (item.get("EventPicture") if item.get("HasEventPicture") else None)

    price_text = "Ausverkauft" if item.get("IsSoldOut") else None

    return {
        "canonical_id": _make_canonical(title, start_at, source_url),
        "title": title[:500],
        "short_description": description[:500] if description else None,
        "start_at": start_at,
        "venue_name": VENUE_NAME,
        "address_text": ADDRESS_TEXT,
        "city": CITY,
        "lat": VENUE_LAT,
        "lon": VENUE_LON,
        "source_url": source_url[:500],
        "source_name": SOURCE_NAME,
        "indoor_outdoor": "indoor",
        "kids_suitable": _detect_kids(category, description),
        "price_text": price_text,
        "category": category,
        "image_url": image_url[:500] if image_url else None,
    }


def parse_planetarium_bochum_items(items: List[Dict], now: Optional[datetime] = None) -> List[Dict]:
    """Parse a list of raw ``EventOverview`` items into event dicts.

    Offline-testable: pass a plain list of item dicts (a trimmed copy of the
    real ``EventOverview`` array), no network access required. ``now`` lets
    tests pin "today" for the past/horizon filters.
    """
    now = now or _now_berlin()
    today = now.date()
    horizon = today + timedelta(days=_WINDOW_DAYS)

    events: List[Dict] = []
    seen_ids: set = set()
    for item in items or []:
        try:
            event = _parse_event_overview_item(item, today, horizon)
            if event and event["canonical_id"] not in seen_ids:
                seen_ids.add(event["canonical_id"])
                events.append(event)
        except Exception as exc:
            logger.debug(f"Planetarium Bochum item parse error: {exc}")

    logger.info(f"Planetarium Bochum: {len(events)} events extracted")
    return events


async def fetch_planetarium_bochum_events() -> List[Dict]:
    """Fetch the calendar JSON API, paginating until the 60-day horizon."""
    now = _now_berlin()
    horizon = now.date() + timedelta(days=_WINDOW_DAYS)
    raw_items: List[Dict] = []

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        page = 1
        while page <= _MAX_PAGES:
            try:
                resp = await client.get(
                    API_URL,
                    params={
                        "current_language": "",
                        "date": now.strftime("%d.%m.%Y"),
                        "category": "",
                        "p": page,
                        "dynamic_calendar": "calendar",
                    },
                )
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:
                logger.error(f"Planetarium Bochum event.json fetch failed (page {page}): {exc}")
                break

            page_items = payload.get("EventOverview") or []
            if not page_items:
                break
            raw_items.extend(page_items)

            last_date = _parse_display_date(page_items[-1].get("CalendarDisplayDateTimeStart"))
            pager = payload.get("Pager") or {}
            if pager.get("IsLastPage") or (last_date and last_date.date() > horizon):
                break

            page += 1
            await asyncio.sleep(_PAGE_PAUSE_SECONDS)

    logger.info(f"Planetarium Bochum: fetched {len(raw_items)} raw performances over {page} page(s)")
    return parse_planetarium_bochum_items(raw_items, now=now)


async def sync_planetarium_bochum(db: Session):
    """Sync Planetarium Bochum shows to database."""
    events_data = await fetch_planetarium_bochum_events()
    return sync_events_to_db(db, events_data, SOURCE_NAME)
