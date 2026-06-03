"""Lichtburg Essen event source — Bühnenveranstaltungen via filmspiegel-essen.de."""
import asyncio
import hashlib
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.services.base_sync import sync_events_to_db

logger = logging.getLogger(__name__)

# The lichtburg-essen.de domain redirects to filmspiegel-essen.de.
# /buehne/ lists only stage events (concerts, comedy, theatre) — no regular film
# screenings. robots.txt: "Disallow:" (nothing disallowed for all agents).
BUEHNE_URL = "https://filmspiegel-essen.de/buehne/"
BASE_URL = "https://filmspiegel-essen.de"

# Venue coordinates (Nominatim verified: 51.4548676, 7.0135673)
VENUE_LAT = 51.4548676
VENUE_LON = 7.0135673

# Maximum number of detail pages to fetch per run (safety cap)
_MAX_DETAIL_FETCHES = 50

# Delay between detail-page requests in seconds (polite crawling)
_DETAIL_DELAY = 0.8

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

_KIDS_KEYWORDS = ["kind", "kinder", "familie", "jugend", "zirkus", "märchen"]

_CATEGORY_MAP = {
    "comedy": "comedy",
    "kabarett": "comedy",
    "konzert": "musik",
    "musik": "musik",
    "jazz": "musik",
    "rock": "musik",
    "pop": "musik",
    "blues": "musik",
    "theater": "theater",
    "oper": "theater",
    "tanz": "tanz",
    "ballet": "tanz",
    "lesung": "literatur",
    "ruhrtriennale": "theater",
    "varieté": "theater",
    "variete": "theater",
    "zirkus": "kinder",
    "circus": "kinder",
    "slam": "literatur",
    "poetry": "literatur",
}

# Date pattern in event card text: "17.06.2026"
_DATE_RE = re.compile(r"(\d{1,2})\.(\d{2})\.(\d{4})")
# Time pattern: "20:00 Uhr"
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*Uhr")
# Price pattern: matches e.g. "42,90 €" or "63,95 €"
_PRICE_RE = re.compile(r"\d[\d,.]+\s*[€$£]|\d[\d,.]+\s*Euro", re.IGNORECASE)


def _parse_event_date(day_text: str, time_text: str) -> Optional[datetime]:
    """Parse date from '17.06.2026' and optional time '20:00 Uhr'."""
    d_match = _DATE_RE.search(day_text)
    if not d_match:
        return None
    try:
        day, month, year = int(d_match.group(1)), int(d_match.group(2)), int(d_match.group(3))
    except ValueError:
        return None

    hour, minute = 0, 0
    if time_text:
        t_match = _TIME_RE.search(time_text)
        if t_match:
            hour, minute = int(t_match.group(1)), int(t_match.group(2))

    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        return None


def _detect_kids(title: str, description: str = "") -> str:
    combined = (title + " " + description).lower()
    if any(kw in combined for kw in _KIDS_KEYWORDS):
        return "likely"
    return "unknown"


def _detect_category(title: str, description: str = "") -> Optional[str]:
    """Keyword-based category detection using title and description text."""
    combined = (title + " " + description).lower()
    for keyword, cat in _CATEGORY_MAP.items():
        if keyword in combined:
            return cat
    return None


def _make_canonical(title: str, date_str: str) -> str:
    return hashlib.md5(f"lichtburg_{title}_{date_str}".encode()).hexdigest()[:16]


def parse_lichtburg_html(html: str) -> List[Dict]:
    """Parse Lichtburg Bühnenveranstaltungen from filmspiegel-essen.de/buehne/.

    Event boxes have class 'box event auditorium-XX event-category-YY'.
    Only Lichtburg events are listed on this page (auditorium-66).
    """
    soup = BeautifulSoup(html, "lxml")

    # Event boxes: div.box.event with auditorium class
    event_boxes = [
        d for d in soup.find_all("div", class_=True)
        if "event" in d.get("class", []) and "box" in d.get("class", [])
    ]
    logger.debug(f"Lichtburg: {len(event_boxes)} event boxes found")

    events: List[Dict] = []
    seen: set = set()

    for box in event_boxes:
        try:
            event = _parse_event_box(box)
            if event and event["canonical_id"] not in seen:
                seen.add(event["canonical_id"])
                events.append(event)
        except Exception as exc:
            logger.debug(f"Lichtburg box parse error: {exc}")

    logger.info(f"Lichtburg: {len(events)} events extracted from overview")
    return events


def _parse_event_box(box) -> Optional[Dict]:
    """Extract event data from one .box.event div."""
    # Link wraps the entire box content
    link_el = box.find("a", class_="box-link", href=True)
    source_url = link_el.get("href", BUEHNE_URL) if link_el else BUEHNE_URL
    if not source_url.startswith("http"):
        source_url = BASE_URL + source_url

    # Title
    title_el = box.find("h3", class_="event-title")
    if not title_el:
        title_el = box.find(class_=lambda x: isinstance(x, list) and "event-title" in x)
    if not title_el:
        return None
    title = title_el.get_text(strip=True)
    if not title:
        return None

    # Date and time from event-timing paragraph
    timing_el = box.find("p", class_="event-timing")
    day_text = ""
    time_text = ""
    if timing_el:
        day_el = timing_el.find("span", class_="event-day")
        time_el = timing_el.find("span", class_="event-time")
        day_text = day_el.get_text(strip=True) if day_el else ""
        time_text = time_el.get_text(strip=True) if time_el else ""

    start_at = _parse_event_date(day_text, time_text)

    # Image
    img_el = box.find("img", class_="event-featured-image")
    image_url = img_el.get("src") if img_el else None

    kids = _detect_kids(title)
    category = _detect_category(title)
    canonical = _make_canonical(title, day_text)

    return {
        "canonical_id": canonical,
        "title": title,
        "start_at": start_at,
        "venue_name": "Lichtburg",
        "city": "Essen",
        "lat": VENUE_LAT,
        "lon": VENUE_LON,
        "source_url": source_url,
        "source_name": "Lichtburg",
        "indoor_outdoor": "indoor",
        "kids_suitable": kids,
        "category": category,
        "image_url": image_url,
    }


def parse_lichtburg_detail_html(html: str) -> Dict:
    """Extract enrichment data (description, category hints, price) from a detail page.

    Detail page structure (filmspiegel-essen.de/veranstaltungen/<slug>/):
    - p.movie-description        → short subtitle/tagline
    - div.section--inverse.section--p-large > div.col-md-8
                                 → full long description text
    - div.section > h3 "Preiskategorien" > div.mb-minicard
                                 → price categories
    - p.event-types > a.event-type → venue + event type tags (no genre-specific links)

    Returns a dict with keys: short_description, price_text.
    (category is derived later by _detect_category on combined title+description)
    """
    soup = BeautifulSoup(html, "lxml")
    result: Dict = {}

    # --- Description ---
    # Primary: long description section (section--inverse section--p-large)
    long_desc = ""
    for div in soup.find_all("div", class_=True):
        classes = div.get("class", [])
        if "section--inverse" in classes and "section--p-large" in classes:
            col = div.find("div", class_=lambda c: c and "col-md-8" in c)
            if col:
                text = col.get_text(" ", strip=True)
                if len(text) > 30:
                    long_desc = text
                    break

    # Fallback: movie-description paragraph (short subtitle)
    if not long_desc:
        desc_el = soup.find("p", class_="movie-description")
        if desc_el:
            long_desc = desc_el.get_text(strip=True)

    if long_desc:
        result["short_description"] = long_desc

    # --- Price ---
    price_parts: List[str] = []
    for sec in soup.find_all("div", class_=True):
        classes = sec.get("class", [])
        if "section" not in classes:
            continue
        h3 = sec.find("h3")
        if not h3 or "preis" not in h3.get_text(strip=True).lower():
            continue
        for mini in sec.find_all("div", class_="mb-minicard"):
            parts = [p.get_text(strip=True) for p in mini.find_all("p") if p.get_text(strip=True)]
            if parts:
                price_parts.append(" ".join(parts))
        break

    if price_parts:
        result["price_text"] = " / ".join(price_parts)

    return result


async def _fetch_detail(client: httpx.AsyncClient, url: str) -> Dict:
    """Fetch one detail page and return enrichment dict. Never raises."""
    try:
        resp = await client.get(url, timeout=20.0)
        resp.raise_for_status()
        return parse_lichtburg_detail_html(resp.text)
    except Exception as exc:
        logger.debug(f"Lichtburg detail fetch failed ({url}): {exc}")
        return {}


async def fetch_lichtburg_events() -> List[Dict]:
    """Fetch Lichtburg Bühnenveranstaltungen from filmspiegel-essen.de.

    Fetches the overview page, then enriches each event with data from its
    detail page (description, price). Detail fetches are capped at
    _MAX_DETAIL_FETCHES; if the cap is hit, a warning is logged.
    """
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        # --- Overview ---
        try:
            resp = await client.get(BUEHNE_URL)
            resp.raise_for_status()
        except Exception as exc:
            logger.error(f"Lichtburg overview fetch failed: {exc}")
            return []

        events = parse_lichtburg_html(resp.text)
        if not events:
            return []

        # --- Detail enrichment ---
        to_enrich = events
        if len(events) > _MAX_DETAIL_FETCHES:
            logger.warning(
                f"Lichtburg: {len(events)} events exceed detail-fetch cap "
                f"({_MAX_DETAIL_FETCHES}); enriching first {_MAX_DETAIL_FETCHES} only."
            )
            to_enrich = events[:_MAX_DETAIL_FETCHES]

        for idx, event in enumerate(to_enrich):
            detail_url = event.get("source_url", "")
            if not detail_url or detail_url == BUEHNE_URL:
                continue

            enrichment = await _fetch_detail(client, detail_url)
            if enrichment:
                # Description
                desc = enrichment.get("short_description", "")
                if desc and len(desc) >= 30:
                    event["short_description"] = desc

                # Price
                price = enrichment.get("price_text", "")
                if price:
                    event["price_text"] = price

                # Re-detect category using description for more coverage
                if not event.get("category"):
                    event["category"] = _detect_category(
                        event.get("title", ""), desc
                    )
                elif event.get("category") and desc:
                    # Allow description to override if title-only detection was None
                    pass

            # Polite delay between requests (skip after last item)
            if idx < len(to_enrich) - 1:
                await asyncio.sleep(_DETAIL_DELAY)

        with_desc = sum(
            1 for e in events if e.get("short_description") and len(e.get("short_description", "")) >= 30
        )
        with_cat = sum(1 for e in events if e.get("category"))
        logger.info(
            f"Lichtburg: {len(events)} events total, "
            f"{with_desc} with description, {with_cat} with category"
        )
        return events


async def sync_lichtburg(db: Session):
    """Sync Lichtburg events to database."""
    events_data = await fetch_lichtburg_events()
    return sync_events_to_db(db, events_data, "Lichtburg")
