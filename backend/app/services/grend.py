"""GREND Kulturzentrum event source — WordPress/VSEL HTML scraping."""
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

# GREND homepage contains a [vsel_upcoming_events] shortcode that renders all
# upcoming events directly in the HTML as .vsel-content blocks.
# robots.txt only disallows /calendar/action~*/ paths — the main homepage is free.
GREND_URL = "https://grend.de/"

# Venue coordinates (Nominatim verified: 51.4467198, 7.0737495)
VENUE_LAT = 51.4467198
VENUE_LON = 7.0737495

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

_KIDS_KEYWORDS = [
    "kind", "kinder", "jugend", "familie", "schule", "theater makiba",
    "zirkus", "märchen", "maerchen", "bildung",
]

_CATEGORY_MAP = {
    "konzert": "musik",
    "theater": "theater",
    "lesung": "literatur",
    "poetry": "literatur",
    "comedy": "comedy",
    "tanz": "tanz",
    "kabarett": "comedy",
    "slam": "literatur",
    "film": "film",
    "kinder": "kinder",
    "jugend": "kinder",
    "familie": "kinder",
    "workshop": "workshop",
}

# Month abbreviations used by VSEL in German date display (e.g. "Mi. 3.6.2026")
_MONTH_RE = re.compile(
    r"(?:Mo|Di|Mi|Do|Fr|Sa|So)\.?\s*(\d{1,2})\.(\d{1,2})\.(\d{4})"
)


def _parse_vsel_date(date_text: str, time_text: str) -> Optional[datetime]:
    """Parse VSEL date format: 'Mi. 3.6.2026' + time '19:00'."""
    # Strip invisible chars and normalize whitespace
    date_clean = re.sub(r"[ ​﻿­]+", " ", date_text).strip()
    m = _MONTH_RE.search(date_clean)
    if not m:
        return None
    try:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    except ValueError:
        return None

    hour, minute = 0, 0
    if time_text:
        time_clean = re.sub(r"[ ​﻿]+", "", time_text).strip()
        t_match = re.match(r"(\d{1,2}):(\d{2})", time_clean)
        if t_match:
            hour, minute = int(t_match.group(1)), int(t_match.group(2))

    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        return None


def _detect_kids(title: str, zielgruppe: str) -> str:
    combined = (title + " " + (zielgruppe or "")).lower()
    if any(kw in combined for kw in _KIDS_KEYWORDS):
        return "likely"
    return "unknown"


def _detect_category(title: str, zielgruppe: str) -> Optional[str]:
    combined = (title + " " + (zielgruppe or "")).lower()
    for keyword, cat in _CATEGORY_MAP.items():
        if keyword in combined:
            return cat
    return None


def _make_canonical(title: str, url: str) -> str:
    return hashlib.md5(f"grend_{title}_{url}".encode()).hexdigest()[:16]


def parse_grend_html(html: str) -> List[Dict]:
    """Parse GREND homepage HTML to extract upcoming events from VSEL blocks."""
    soup = BeautifulSoup(html, "lxml")

    # VSEL renders events as: div.vsel-content[id="event-XXXXX"]
    event_blocks = soup.find_all("div", class_="vsel-content")
    logger.debug(f"GREND: {len(event_blocks)} vsel-content blocks found")

    events: List[Dict] = []
    seen_ids: set = set()

    for block in event_blocks:
        try:
            event = _parse_vsel_block(block)
            if event and event["canonical_id"] not in seen_ids:
                seen_ids.add(event["canonical_id"])
                events.append(event)
        except Exception as exc:
            logger.debug(f"GREND block parse error: {exc}")

    logger.info(f"GREND: {len(events)} events extracted")
    return events


def _parse_vsel_block(block) -> Optional[Dict]:
    """Extract event data from a single .vsel-content div."""
    # Title
    title_el = block.find("h3", class_="vsel-meta-title")
    if not title_el:
        return None
    title = title_el.get_text(strip=True)
    if not title:
        return None

    # Link (from title anchor)
    link_el = title_el.find("a", href=True)
    source_url = link_el.get("href", GREND_URL) if link_el else GREND_URL

    # Date and time
    date_el = block.find("div", class_="vsel-meta-date")
    time_el = block.find("div", class_="vsel-meta-time")
    date_text = date_el.get_text(strip=True) if date_el else ""
    time_text = time_el.get_text(strip=True) if time_el else ""
    start_at = _parse_vsel_date(date_text, time_text)

    # Zielgruppe/Ort (ACF field)
    ziel_el = block.find("div", class_="vsel-acf-zielgruppeort")
    zielgruppe = ""
    if ziel_el:
        val_el = ziel_el.find(class_="acf-field-value")
        if val_el:
            zielgruppe = val_el.get_text(strip=True)

    # Price
    price_el = block.find("div", class_="vsel-acf-preis")
    price_text: Optional[str] = None
    if price_el:
        val_el = price_el.find(class_="acf-field-value")
        if val_el:
            price_text = val_el.get_text(" ", strip=True)[:120]

    kids = _detect_kids(title, zielgruppe)
    category = _detect_category(title, zielgruppe)

    canonical = _make_canonical(title, source_url)

    return {
        "canonical_id": canonical,
        "title": title,
        "short_description": zielgruppe[:500] if zielgruppe else None,
        "start_at": start_at,
        "venue_name": "GREND",
        "city": "Essen",
        "lat": VENUE_LAT,
        "lon": VENUE_LON,
        "source_url": source_url,
        "source_name": "GREND",
        "indoor_outdoor": "indoor",
        "kids_suitable": kids,
        "price_text": price_text,
        "category": category,
    }


async def fetch_grend_events() -> List[Dict]:
    """Fetch GREND events from homepage (VSEL shortcode output)."""
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        try:
            resp = await client.get(GREND_URL)
            resp.raise_for_status()
            return parse_grend_html(resp.text)
        except Exception as exc:
            logger.error(f"GREND fetch failed: {exc}")
            return []


async def sync_grend(db: Session):
    """Sync GREND events to database."""
    events_data = await fetch_grend_events()
    return sync_events_to_db(db, events_data, "GREND")
