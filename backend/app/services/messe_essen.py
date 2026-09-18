"""Messe Essen event source — TYPO3 event calendar with detail-page enrichment.

The requested calendar page ``/messen/messekalender/`` only carries a
``.ce-eventslider`` with the next ten fairs and their *start* date. The full
list lives at ``/event-kalender/``: every fair as ``article.list-item`` with a
date range ("22.09.2026 - 25.09.2026"), category ("Fachmesse" /
"Publikumsmesse"), location ("Essen" / "Ausland"), title, deep link, teaser
and logo. That list is the primary source; the detail page adds the long
description and, if present, a price.

robots.txt only disallows /typo3/.
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

logger = logging.getLogger(__name__)

SOURCE_NAME = "Messe Essen"
BASE_URL = "https://www.messe-essen.de"
LIST_URL = f"{BASE_URL}/event-kalender/"

VENUE_NAME = "Messe Essen"
ADDRESS_TEXT = "Messeplatz 1, 45131 Essen"
# Nominatim: exhibition_centre "Messe Essen" (51.4286847, 6.9943796)
VENUE_LAT = 51.4286847
VENUE_LON = 6.9943796

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

_BERLIN = ZoneInfo("Europe/Berlin")

# Fairs are rare, so the window is longer than for other sources.
_WINDOW_DAYS = 180
# Detail pages fetched per sync (politeness cap).
_MAX_DETAIL_FETCHES = 15
_DETAIL_PAUSE_SECONDS = 0.5

# Fair days: one event per fair, first day 10:00 → last day 18:00.
_START_TIME = time(10, 0)
_END_TIME = time(18, 0)

_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
# "Tageskarte: 18 €" / "Eintritt ab 12,50 €" / bare "15 € pro Person"
_PRICE_RE = re.compile(
    r"((?:eintritt|ticket|tageskarte|preis)[^€\n]{0,60}?\d+(?:[,.]\d{2})?\s*€"
    r"|\d+(?:[,.]\d{2})?\s*€[^\n.]{0,40})",
    re.IGNORECASE,
)

_KIDS_KEYWORDS = [
    "kinder", "familie", "familien", "spiel", "dino", "kids",
    "jugend", "comic", "manga",
]
# Teaser lines on the detail page that carry no content.
_DETAIL_SKIP_RE = re.compile(
    r"weitere informationen finden sie|zur webseite|tickets kaufen", re.IGNORECASE
)


def _now_berlin() -> datetime:
    return datetime.now(_BERLIN).replace(tzinfo=None)


def _make_canonical(title: str, start_at: datetime, url: str) -> str:
    return hashlib.md5(
        f"messeessen_{title}_{start_at.isoformat()}_{url}".encode()
    ).hexdigest()[:16]


def _parse_date_range(text: str) -> Tuple[Optional[date], Optional[date]]:
    """"22.09.2026 - 25.09.2026" → (start, end); "12.11.2026" → (start, start)."""
    matches = _DATE_RE.findall(text or "")
    if not matches:
        return None, None
    try:
        first = date(int(matches[0][2]), int(matches[0][1]), int(matches[0][0]))
        last = date(int(matches[-1][2]), int(matches[-1][1]), int(matches[-1][0]))
    except ValueError:
        return None, None
    if last < first:
        last = first
    return first, last


def _detect_kids(title: str, teaser: str) -> str:
    combined = f"{title} {teaser or ''}".lower()
    if any(kw in combined for kw in _KIDS_KEYWORDS):
        return "likely"
    return "unknown"


def _split_categories(text: str) -> Tuple[Optional[str], Optional[str]]:
    """"Fachmesse | Essen" → ("Fachmesse", "Essen")."""
    parts = [p.strip() for p in re.split(r"\s*\|\s*", text or "") if p.strip()]
    category = parts[0] if parts else None
    location = parts[1] if len(parts) > 1 else None
    return category, location


# ─────────────────────────────── parsing ──────────────────────────────────────


def parse_messe_essen_html(html: str, now: Optional[datetime] = None) -> List[Dict]:
    """Parse the /event-kalender/ list page into event dicts (offline-testable)."""
    now = now or _now_berlin()
    soup = BeautifulSoup(html, "lxml")
    items = soup.select("article.list-item")
    logger.debug(f"Messe Essen: {len(items)} list items found")

    events: List[Dict] = []
    seen_ids: set = set()
    for item in items:
        try:
            event = _parse_list_item(item, now)
            if event and event["canonical_id"] not in seen_ids:
                seen_ids.add(event["canonical_id"])
                events.append(event)
        except Exception as exc:
            logger.debug(f"Messe Essen item parse error: {exc}")

    logger.info(f"Messe Essen: {len(events)} events extracted")
    return events


def _text(block, selector: str) -> str:
    el = block.select_one(selector)
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el else ""


def _parse_list_item(item, now: datetime) -> Optional[Dict]:
    """Extract one fair from an ``article.list-item`` block."""
    title_link = item.select_one(".ce-veranstaltungen__title a[href]") or item.select_one(
        "a.list-item_link[href]"
    )
    if not title_link:
        return None
    title = re.sub(r"\s+", " ", title_link.get_text(" ", strip=True)).strip()
    if not title:
        return None
    source_url = urljoin(BASE_URL, title_link["href"])

    start_date, end_date = _parse_date_range(_text(item, ".event-date"))
    if start_date is None:
        return None

    category, location = _split_categories(_text(item, ".ce-veranstaltungen__categories"))
    # Messe Essen also organises fairs abroad ("Fachmesse | Ausland") — skip.
    if location and location.lower() != "essen":
        return None
    # Trade-only fairs (security essen, EURO DEFENCE EXPO, ...) are closed to
    # the public — not an outing for anyone using this app.
    if category and category.lower() == "fachmesse":
        return None

    today = now.date()
    if start_date < today or start_date > today + timedelta(days=_WINDOW_DAYS):
        return None

    teaser = _text(item, ".ce-veranstaltungen__teaser")
    img_el = item.select_one(".ce-veranstaltungen__list-image img[src]") or item.select_one(
        "img[src]"
    )
    image_url = urljoin(BASE_URL, img_el["src"]) if img_el else None

    start_at = datetime.combine(start_date, _START_TIME)
    end_at = datetime.combine(end_date or start_date, _END_TIME)

    return {
        "canonical_id": _make_canonical(title, start_at, source_url),
        "title": title[:500],
        "short_description": teaser[:500] or None,
        "start_at": start_at,
        "end_at": end_at,
        "is_all_day": True,
        "venue_name": VENUE_NAME,
        "address_text": ADDRESS_TEXT,
        "city": "Essen",
        "lat": VENUE_LAT,
        "lon": VENUE_LON,
        "source_url": source_url[:500],
        "source_name": SOURCE_NAME,
        "indoor_outdoor": "indoor",
        "kids_suitable": _detect_kids(title, teaser),
        "category": category or "Messe",
        "image_url": image_url[:500] if image_url else None,
    }


def parse_messe_essen_detail_html(html: str) -> Dict:
    """Extract description / price / opening hours from a fair's detail page.

    Returns only the keys that could be found (empty dict for an empty page).
    """
    soup = BeautifulSoup(html, "lxml")
    result: Dict = {}

    content = soup.select_one(".ce-veranstaltungen__detail-content")
    if content:
        paragraphs = [
            re.sub(r"\s+", " ", p.get_text(" ", strip=True))
            for p in content.find_all("p")
        ]
        meaningful = [p for p in paragraphs if p and not _DETAIL_SKIP_RE.search(p)]
        if meaningful:
            result["short_description"] = " ".join(meaningful)[:500]

    hours = soup.select_one(".event-opening-hours")
    if hours:
        lines = [
            re.sub(r"\s+", " ", p.get_text(" ", strip=True))
            for p in hours.find_all("p")
        ]
        lines = [line for line in lines if line]
        if lines:
            result["opening_hours"] = "; ".join(lines)[:255]

    page_text = soup.get_text(" ", strip=True)
    price_match = _PRICE_RE.search(page_text)
    if price_match:
        result["price_text"] = re.sub(r"\s+", " ", price_match.group(1)).strip()[:255]

    return result


def _merge_detail(event: Dict, detail: Dict) -> Dict:
    """Prefer the detail description when it is longer; append opening hours."""
    description = detail.get("short_description")
    if description and len(description) > len(event.get("short_description") or ""):
        event["short_description"] = description
    hours = detail.get("opening_hours")
    if hours:
        base = event.get("short_description") or ""
        suffix = f" Öffnungszeiten: {hours}"
        if len(base) + len(suffix) <= 500:
            event["short_description"] = (base + suffix).strip()
    if detail.get("price_text") and not event.get("price_text"):
        event["price_text"] = detail["price_text"]
    return event


# ─────────────────────────────── fetch / sync ─────────────────────────────────


async def fetch_messe_essen_events() -> List[Dict]:
    """Fetch the fair list and enrich each fair from its detail page."""
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        try:
            resp = await client.get(LIST_URL)
            resp.raise_for_status()
        except Exception as exc:
            logger.error(f"Messe Essen list fetch failed: {exc}")
            return []

        events = parse_messe_essen_html(resp.text)

        for event in events[:_MAX_DETAIL_FETCHES]:
            try:
                await asyncio.sleep(_DETAIL_PAUSE_SECONDS)
                detail_resp = await client.get(event["source_url"])
                detail_resp.raise_for_status()
                _merge_detail(event, parse_messe_essen_detail_html(detail_resp.text))
            except Exception as exc:
                logger.debug(f"Messe Essen detail fetch failed for {event['source_url']}: {exc}")

        logger.info(f"Messe Essen: {len(events)} events after enrichment")
        return events


async def sync_messe_essen(db: Session):
    """Sync Messe Essen fairs to database."""
    events_data = await fetch_messe_essen_events()
    return sync_events_to_db(db, events_data, SOURCE_NAME)
