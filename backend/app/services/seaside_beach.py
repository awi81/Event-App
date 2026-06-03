"""Seaside Beach Baldeneysee - summer events and concerts."""
import httpx
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
import hashlib
import re
import logging

from app.services.base_sync import sync_events_to_db

logger = logging.getLogger(__name__)

SEASIDE_URL = "https://www.seaside-beach.de/"
SEASIDE_CONCERTS_URL = "https://www.seaside-beach.de/konzerte/"

SEASIDE_LAT = 51.3977
SEASIDE_LON = 7.0361


async def fetch_seaside_events() -> List[Dict]:
    """Fetch events from Seaside Beach."""
    events = []

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }) as client:
        # Try concerts page
        for url in [SEASIDE_CONCERTS_URL, SEASIDE_URL]:
            try:
                response = await client.get(url)
                response.raise_for_status()
                page_events = parse_seaside_html(response.text, url)
                events.extend(page_events)
            except Exception as e:
                logger.warning(f"Error fetching {url}: {e}")

    # Deduplicate
    seen = set()
    unique = []
    for e in events:
        if e["canonical_id"] not in seen:
            seen.add(e["canonical_id"])
            unique.append(e)

    logger.info(f"Found {len(unique)} events from Seaside Beach")
    return unique


def parse_seaside_html(html: str, source_url: str) -> List[Dict]:
    """Parse Seaside Beach HTML for events."""
    soup = BeautifulSoup(html, 'lxml')
    events = []

    # Look for event containers
    text = soup.get_text()
    lines = text.split('\n')

    seen = set()
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Look for date patterns
        date_match = re.search(
            r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})',
            line
        )

        if date_match:
            day = int(date_match.group(1))
            month = int(date_match.group(2))
            year = int(date_match.group(3))
            if year < 100:
                year += 2000

            # Search for time AFTER the date so the date itself (e.g. "28.06.2026")
            # isn't mis-parsed as a time.
            time_segment = line[date_match.end():]
            time_match = re.search(r'(\d{1,2}):(\d{2})\s*(?:Uhr|h)?', time_segment)
            hour = int(time_match.group(1)) if time_match else 0
            minute = int(time_match.group(2)) if time_match else 0
            if hour > 23 or minute > 59:
                hour, minute = 0, 0

            start_at = None
            try:
                start_at = datetime(year, month, day, hour, minute)
            except ValueError:
                i += 1
                continue

            if start_at < datetime.now():
                i += 1
                continue

            # Find title nearby
            title = None
            for j in range(max(0, i - 3), min(i + 4, len(lines))):
                candidate = lines[j].strip()
                if candidate and len(candidate) > 5 and len(candidate) < 150:
                    if not re.match(r'^\d', candidate):
                        if not any(w in candidate.lower() for w in ['€', 'uhr', 'eintritt', 'ticket', 'karten']):
                            title = candidate
                            break

            dedup_key = (title, start_at) if title else None
            if title and dedup_key not in seen:
                seen.add(dedup_key)
                canonical_id = hashlib.md5(f"seaside_{title}_{start_at}".encode()).hexdigest()[:16]

                events.append({
                    "canonical_id": canonical_id,
                    "title": title[:200],
                    "start_at": start_at,
                    "venue_name": "Seaside Beach Baldeneysee",
                    "city": "Essen",
                    "lat": SEASIDE_LAT,
                    "lon": SEASIDE_LON,
                    "source_url": source_url,
                    "source_name": "Seaside Beach",
                    "indoor_outdoor": "outdoor",
                    "kids_suitable": "likely",
                })

        i += 1

    # Also add as a permanent offer (beach/recreation)
    if not events:
        events.append({
            "canonical_id": hashlib.md5(b"seaside_permanent").hexdigest()[:16],
            "title": "Seaside Beach Baldeneysee - Strand, Klettern, Minigolf",
            "venue_name": "Seaside Beach Baldeneysee",
            "city": "Essen",
            "lat": SEASIDE_LAT,
            "lon": SEASIDE_LON,
            "source_url": SEASIDE_URL,
            "source_name": "Seaside Beach",
            "indoor_outdoor": "outdoor",
            "kids_suitable": "likely",
            "is_permanent_offer": True,
        })

    return events


async def sync_seaside_beach(db: Session):
    """Sync events from Seaside Beach to database."""
    events_data = await fetch_seaside_events()
    return sync_events_to_db(db, events_data, "Seaside Beach")
