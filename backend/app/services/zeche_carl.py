"""Zeche Carl event source — Squarespace HTML scraping with detail-page enrichment."""
import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.services.base_sync import sync_events_to_db, to_berlin_naive

logger = logging.getLogger(__name__)

BASE_URL = "https://www.zechecarl.de"
OVERVIEW_URL = f"{BASE_URL}/programmuebersicht"

# Venue coordinates (Nominatim verified: 51.4964545, 7.0123887)
VENUE_LAT = 51.4964545
VENUE_LON = 7.0123887

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

_MONTH_MAP = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4,
    "mai": 5, "juni": 6, "juli": 7, "august": 8, "september": 9,
    "oktober": 10, "november": 11, "dezember": 12,
}

_KIDS_KEYWORDS = [
    "kind", "kinder", "familie", "familienfreundlich", "jugend",
    "kita", "schule", "flohmarkt", "zirkus",
]


def _parse_german_month(month_str: str) -> int:
    """Convert German month name to int."""
    return _MONTH_MAP.get(month_str.strip().lower(), 0)


def _make_canonical(title: str, date_str: str) -> str:
    return hashlib.md5(f"zechecarl_{title}_{date_str}".encode()).hexdigest()[:16]


def _detect_kids(title: str, description: str) -> str:
    combined = (title + " " + (description or "")).lower()
    if any(kw in combined for kw in _KIDS_KEYWORDS):
        return "likely"
    return "unknown"


def _parse_overview_html(html: str) -> List[Dict]:
    """Parse Squarespace summary-item blocks from the overview page.

    Each block contains: title, month, day, image, relative href.
    Year is inferred from the URL slug (YYMMDD prefix) or current context.
    """
    soup = BeautifulSoup(html, "lxml")

    # Squarespace event cards: div.summary-item with 'summary-item-record-type-event'
    event_items = [
        d for d in soup.find_all("div", class_=True)
        if "summary-item-record-type-event" in " ".join(d.get("class", []))
    ]
    logger.debug(f"Zeche Carl overview: {len(event_items)} event cards found")

    stubs = []
    for item in event_items:
        try:
            stub = _extract_overview_stub(item)
            if stub:
                stubs.append(stub)
        except Exception as exc:
            logger.debug(f"Zeche Carl overview item parse error: {exc}")

    return stubs


def _extract_overview_stub(item) -> Optional[Dict]:
    """Extract minimal event info from one Squarespace summary-item div."""
    thumb_link = item.find("a", attrs={"data-title": True})
    if not thumb_link:
        return None

    title = thumb_link.get("data-title", "").strip()
    if not title or len(title) < 3:
        return None

    href = thumb_link.get("href", "")
    if not href:
        return None
    url = href if href.startswith("http") else f"{BASE_URL}{href}"

    # Date: month name + day number inside the thumbnail date box
    month_el = item.find(class_="summary-thumbnail-event-date-month")
    day_el = item.find(class_="summary-thumbnail-event-date-day")
    month_str = month_el.get_text(strip=True) if month_el else ""
    day_str = day_el.get_text(strip=True) if day_el else ""

    # Year: derive from URL slug pattern YYMMDD (e.g. /carlsprogramm/260605-…)
    year = None
    slug_match = re.search(r"/carlsprogramm/(\d{2})(\d{2})(\d{2})", href)
    if slug_match:
        year_2digit = int(slug_match.group(1))
        year = 2000 + year_2digit

    # Image
    img_el = item.find("img", attrs={"data-src": True})
    image_url = img_el.get("data-src") if img_el else None

    return {
        "title": title,
        "url": url,
        "month_str": month_str,
        "day_str": day_str,
        "year": year,
        "image_url": image_url,
    }


def _enrich_from_detail_json_ld(html: str, stub: Dict) -> Optional[Dict]:
    """Fetch structured data from the detail page JSON-LD (Event schema)."""
    soup = BeautifulSoup(html, "lxml")

    # Try JSON-LD first — most reliable
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                data = next((d for d in data if d.get("@type") == "Event"), None)
            if not data or data.get("@type") != "Event":
                continue
            return _build_event_from_json_ld(data, stub, soup)
        except Exception:
            continue

    # Fallback: parse <time class="event-date"> + paragraphs
    return _build_event_from_html(soup, stub)


def _build_event_from_json_ld(data: Dict, stub: Dict, soup) -> Optional[Dict]:
    """Build event dict from Squarespace event JSON-LD."""
    title = data.get("name", stub["title"])
    # Strip " — ZECHE CARL" suffix added by Squarespace
    title = re.sub(r"\s*[—–-]\s*ZECHE CARL\s*$", "", title, flags=re.IGNORECASE).strip()

    start_raw = data.get("startDate")
    start_at: Optional[datetime] = None
    if start_raw:
        try:
            # Python 3.10 fromisoformat doesn't handle "+0200" (no colon) —
            # normalise to "+02:00" first.
            fixed = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", start_raw)
            start_at = to_berlin_naive(datetime.fromisoformat(fixed))
        except Exception:
            pass

    # Description from paragraphs
    description = _extract_description(soup)

    # Price from paragraphs
    price_text = _extract_price(soup)

    # kids detection
    kids = _detect_kids(title, description or "")

    canonical = _make_canonical(title, start_raw or stub["url"])

    return {
        "canonical_id": canonical,
        "title": title,
        "short_description": description,
        "start_at": start_at,
        "venue_name": "Zeche Carl",
        "city": "Essen",
        "lat": VENUE_LAT,
        "lon": VENUE_LON,
        "source_url": stub["url"],
        "source_name": "Zeche Carl",
        "indoor_outdoor": "indoor",
        "kids_suitable": kids,
        "price_text": price_text,
        "image_url": stub.get("image_url"),
    }


def _build_event_from_html(soup, stub: Dict) -> Optional[Dict]:
    """Fallback: derive date from <time class='event-date'> and paragraphs."""
    title = stub["title"]

    time_el = soup.find("time", class_="event-date")
    start_at: Optional[datetime] = None
    if time_el:
        dt_attr = time_el.get("datetime")
        if dt_attr:
            try:
                start_at = datetime.fromisoformat(dt_attr)
            except Exception:
                pass

    # Try to find time in paragraphs
    if start_at is not None:
        page_text = soup.get_text(" ")
        time_match = re.search(r"(\d{1,2}):(\d{2})\s*Uhr", page_text)
        if time_match:
            try:
                start_at = start_at.replace(
                    hour=int(time_match.group(1)),
                    minute=int(time_match.group(2)),
                )
            except Exception:
                pass

    start_at = to_berlin_naive(start_at)
    description = _extract_description(soup)
    price_text = _extract_price(soup)
    kids = _detect_kids(title, description or "")

    canonical = _make_canonical(title, stub["url"])

    return {
        "canonical_id": canonical,
        "title": title,
        "short_description": description,
        "start_at": start_at,
        "venue_name": "Zeche Carl",
        "city": "Essen",
        "lat": VENUE_LAT,
        "lon": VENUE_LON,
        "source_url": stub["url"],
        "source_name": "Zeche Carl",
        "indoor_outdoor": "indoor",
        "kids_suitable": kids,
        "price_text": price_text,
        "image_url": stub.get("image_url"),
    }


def _extract_description(soup) -> Optional[str]:
    """Extract meaningful description from event detail page paragraphs."""
    paragraphs = [
        p.get_text(" ", strip=True)
        for p in soup.find_all("p")
        if p.get_text(strip=True)
    ]
    skip_patterns = [
        r"impressum", r"datenschutz", r"hausordnung", r"gef[öo]rdert",
        r"zeche\s+carl", r"^\s*$",
    ]
    skip_re = re.compile("|".join(skip_patterns), re.IGNORECASE)

    meaningful = [p for p in paragraphs if not skip_re.search(p) and len(p) > 20]
    if not meaningful:
        return None
    return " ".join(meaningful)[:500]


def _extract_price(soup) -> Optional[str]:
    """Extract price information from event page."""
    text = soup.get_text(" ")
    price_match = re.search(r"(AK|VVK|Eintritt|Preis)[:\s]+([^\n]{3,60})", text, re.IGNORECASE)
    if price_match:
        return price_match.group(0).strip()[:100]
    # Simple price pattern: X€
    price_match2 = re.search(r"\d+\s*[€Eur]\w*", text)
    if price_match2:
        ctx_start = max(0, price_match2.start() - 10)
        return text[ctx_start: price_match2.end() + 5].strip()[:60]
    return None


async def fetch_zeche_carl_events() -> List[Dict]:
    """Fetch events from Zeche Carl: overview + detail enrichment."""
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=_HEADERS,
        verify=False,
    ) as client:
        # Step 1: overview page
        try:
            resp = await client.get(OVERVIEW_URL)
            resp.raise_for_status()
        except Exception as exc:
            logger.error(f"Zeche Carl overview fetch failed: {exc}")
            return []

        stubs = _parse_overview_html(resp.text)
        logger.info(f"Zeche Carl: {len(stubs)} stubs from overview")

        # Step 2: enrich each stub with detail page (cap at 40 to be polite)
        events: List[Dict] = []
        for stub in stubs[:40]:
            try:
                await asyncio.sleep(0.4)
                detail_resp = await client.get(stub["url"])
                detail_resp.raise_for_status()
                event = _enrich_from_detail_json_ld(detail_resp.text, stub)
                if event:
                    events.append(event)
            except Exception as exc:
                logger.debug(f"Zeche Carl detail fetch failed for {stub['url']}: {exc}")
                # Still add a minimal event from the stub
                event = _stub_to_minimal_event(stub)
                if event:
                    events.append(event)

        logger.info(f"Zeche Carl: {len(events)} events after enrichment")
        return events


def _stub_to_minimal_event(stub: Dict) -> Optional[Dict]:
    """Create minimal event from overview stub when detail fetch fails."""
    title = stub["title"]
    start_at: Optional[datetime] = None

    if stub.get("year") and stub.get("month_str") and stub.get("day_str"):
        month = _parse_german_month(stub["month_str"])
        try:
            day = int(stub["day_str"])
            if month and 1 <= day <= 31:
                start_at = datetime(stub["year"], month, day)
        except (ValueError, TypeError):
            pass

    canonical = _make_canonical(title, stub["url"])
    return {
        "canonical_id": canonical,
        "title": title,
        "start_at": start_at,
        "venue_name": "Zeche Carl",
        "city": "Essen",
        "lat": VENUE_LAT,
        "lon": VENUE_LON,
        "source_url": stub["url"],
        "source_name": "Zeche Carl",
        "indoor_outdoor": "indoor",
        "kids_suitable": _detect_kids(title, ""),
        "image_url": stub.get("image_url"),
    }


async def sync_zeche_carl(db: Session):
    """Sync Zeche Carl events to database."""
    events_data = await fetch_zeche_carl_events()
    return sync_events_to_db(db, events_data, "Zeche Carl")
