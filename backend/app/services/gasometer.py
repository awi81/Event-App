"""Gasometer Oberhausen event source - HTML scraping."""
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

GASOMETER_URL = "https://www.gasometer.de/de/termine"

# Gasometer coordinates
GASOMETER_LAT = 51.4967
GASOMETER_LON = 6.8625

GERMAN_MONTHS = {
    'januar': 1, 'februar': 2, 'märz': 3, 'april': 4,
    'mai': 5, 'juni': 6, 'juli': 7, 'august': 8,
    'september': 9, 'oktober': 10, 'november': 11, 'dezember': 12,
}


async def fetch_gasometer_events() -> List[Dict]:
    """Fetch events from Gasometer website using Playwright."""
    try:
        events = await fetch_with_playwright()
        if events:
            return events
    except Exception as e:
        logger.warning(f"Playwright failed for Gasometer: {e}")

    # Fallback to HTTP
    return await fetch_with_http()


async def fetch_with_playwright() -> List[Dict]:
    """Fetch events using Playwright browser."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            await page.goto(GASOMETER_URL, wait_until="networkidle", timeout=20000)
            await page.wait_for_timeout(2000)

            text = await page.inner_text('body')
            await browser.close()

            return parse_gasometer_text(text)
        except Exception as e:
            logger.error(f"Gasometer Playwright error: {e}")
            await browser.close()
            raise


async def fetch_with_http() -> List[Dict]:
    """Fallback HTTP fetch."""
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }) as client:
        try:
            response = await client.get(GASOMETER_URL)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')
            return parse_gasometer_text(soup.get_text())
        except Exception as e:
            logger.error(f"Gasometer HTTP error: {e}")
            return []


def parse_gasometer_text(text: str) -> List[Dict]:
    """Parse Gasometer page text to extract events."""
    events = []
    seen = set()

    # Pattern: "DD. Monat" followed by event title in caps
    # Example: "08. Juli\nGROSSE BÄUME, KLEINE HELDEN..."
    lines = text.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Look for date pattern: "DD. Monat" or "DD. Monat YYYY"
        date_match = re.match(r'^(\d{1,2})\.\s+(\w+)(?:\s+(\d{4}))?$', line)

        if date_match:
            day = int(date_match.group(1))
            month_name = date_match.group(2).lower()
            year = int(date_match.group(3)) if date_match.group(3) else datetime.now().year

            month = GERMAN_MONTHS.get(month_name)
            if month:
                start_at = None
                try:
                    start_at = datetime(year, month, day)
                except ValueError:
                    pass

                # Title is usually the next non-empty line (often uppercase)
                title = None
                description_lines = []
                for j in range(i + 1, min(i + 20, len(lines))):
                    next_line = lines[j].strip()
                    if not next_line:
                        continue
                    if not title and len(next_line) > 5:
                        title = next_line
                    elif title:
                        # Collect description until next date or section
                        if re.match(r'^\d{1,2}\.\s+\w+', next_line):
                            break
                        if next_line.startswith('Ticket') or next_line.startswith('Einlass'):
                            # Extract time from "Einlass ab HH:MM"
                            time_match = re.search(r'(\d{1,2}):(\d{2})', next_line)
                            if time_match and start_at:
                                start_at = start_at.replace(
                                    hour=int(time_match.group(1)),
                                    minute=int(time_match.group(2))
                                )
                            break
                        description_lines.append(next_line)

                dedup_key = (title, start_at) if title else None
                if title and dedup_key not in seen:
                    seen.add(dedup_key)
                    canonical_id = hashlib.md5(f"gasometer_{title}_{start_at}".encode()).hexdigest()[:16]

                    # Extract price from description
                    price_text = None
                    for dl in description_lines:
                        price_match = re.search(r'Ticketpreis\s+(.+)', dl)
                        if price_match:
                            price_text = price_match.group(1)

                    description = ' '.join(description_lines[:5])

                    events.append({
                        "canonical_id": canonical_id,
                        "title": title[:200],
                        "short_description": description[:500] if description else None,
                        "start_at": start_at,
                        "venue_name": "Gasometer Oberhausen",
                        "city": "Oberhausen",
                        "lat": GASOMETER_LAT,
                        "lon": GASOMETER_LON,
                        "source_url": GASOMETER_URL,
                        "source_name": "Gasometer",
                        "price_text": price_text,
                        "indoor_outdoor": "indoor",
                    })

        i += 1

    logger.info(f"Found {len(events)} events from Gasometer")
    return events


async def sync_gasometer(db: Session):
    """Sync events from Gasometer to database."""
    events_data = await fetch_gasometer_events()
    return sync_events_to_db(db, events_data, "Gasometer")
