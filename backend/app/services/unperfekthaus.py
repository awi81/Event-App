"""Unperfekthaus Essen event source - Playwright scraping (403 on plain HTTP)."""
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
import hashlib
import re
import logging

from app.services.base_sync import sync_events_to_db

logger = logging.getLogger(__name__)

UPH_URL = "http://www.uph.de/veranstaltungskalender"
UPH_EVENTS_URL = "http://www.uph.de/offene-events"

UPH_LAT = 51.4497
UPH_LON = 7.0134


async def fetch_unperfekthaus_events() -> List[Dict]:
    """Fetch events from Unperfekthaus using Playwright."""
    try:
        from playwright.async_api import async_playwright

        events = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                # Try the calendar page
                await page.goto(UPH_URL, wait_until="networkidle", timeout=20000)
                await page.wait_for_timeout(3000)

                html = await page.content()
                text = await page.inner_text('body')
                events = parse_uph_text(text)

                if not events:
                    # Try offene-events page
                    await page.goto(UPH_EVENTS_URL, wait_until="networkidle", timeout=20000)
                    await page.wait_for_timeout(2000)
                    text = await page.inner_text('body')
                    events = parse_uph_text(text)

            except Exception as e:
                logger.error(f"UPH Playwright error: {e}")
            finally:
                await browser.close()

        return events
    except Exception as e:
        logger.error(f"Error fetching Unperfekthaus: {e}")
        return []


def parse_uph_text(text: str) -> List[Dict]:
    """Parse Unperfekthaus page text to extract events."""
    events = []
    seen = set()
    lines = text.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Look for date patterns: "DD.MM.YYYY", "DD.MM.", weekday patterns
        date_match = re.search(
            r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})?',
            line
        )

        if date_match:
            day = int(date_match.group(1))
            month = int(date_match.group(2))
            year_str = date_match.group(3)
            year = int(year_str) if year_str else datetime.now().year
            if year < 100:
                year += 2000

            # Extract time — mask the date first so "24.06." is not read as 24:06
            line_wo_date = line[:date_match.start()] + line[date_match.end():]
            time_match = re.search(r'(\d{1,2})[:\.](\d{2})\s*(?:Uhr|h)?', line_wo_date)
            hour = int(time_match.group(1)) if time_match else 0
            minute = int(time_match.group(2)) if time_match else 0

            start_at = None
            try:
                start_at = datetime(year, month, day, hour, minute)
            except ValueError:
                i += 1
                continue

            # Skip past dates
            if start_at < datetime.now():
                i += 1
                continue

            # Look for title in surrounding lines
            title = None
            for j in range(max(0, i - 3), min(i + 5, len(lines))):
                candidate = lines[j].strip()
                if candidate and len(candidate) > 10 and len(candidate) < 150:
                    if not re.match(r'^\d', candidate) and candidate != line:
                        if not any(w in candidate.lower() for w in ['uhr', 'euro', '€', 'eintritt', 'anmeldung']):
                            title = candidate
                            break

            dedup_key = (title, start_at) if title else None
            if title and dedup_key not in seen:
                seen.add(dedup_key)
                canonical_id = hashlib.md5(f"uph_{title}_{start_at}".encode()).hexdigest()[:16]

                events.append({
                    "canonical_id": canonical_id,
                    "title": title[:200],
                    "start_at": start_at,
                    "venue_name": "Unperfekthaus",
                    "city": "Essen",
                    "lat": UPH_LAT,
                    "lon": UPH_LON,
                    "source_url": UPH_URL,
                    "source_name": "Unperfekthaus",
                    "indoor_outdoor": "indoor",
                })

        i += 1

    logger.info(f"Found {len(events)} events from Unperfekthaus")
    return events


async def sync_unperfekthaus(db: Session):
    """Sync events from Unperfekthaus to database."""
    events_data = await fetch_unperfekthaus_events()
    return sync_events_to_db(db, events_data, "Unperfekthaus")
