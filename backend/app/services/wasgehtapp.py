"""wasgehtapp.de event source."""
import httpx
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
import hashlib
import json
import logging
import re

from app.services.base_sync import sync_events_to_db

logger = logging.getLogger(__name__)

WASGEHTAPP_BASE = "https://www.wasgehtapp.de"
# Direct link to Essen
WASGEHTAPP_ESSEN_URL = f"{WASGEHTAPP_BASE}/index.php?geo_id=16348&ort=Essen&x=7.00865&y=51.4625&select_ort=1&radius=20&region=07"

async def fetch_wasgehtapp_events(city: str = "Essen") -> List[Dict]:
    """Fetch events from wasgehtapp.de using Playwright."""
    try:
        # Try Playwright first (for JavaScript-rendered content)
        events = await fetch_with_playwright(city)
        if events:
            logger.info(f"Found {len(events)} events with Playwright")
            return events
    except Exception as e:
        logger.warning(f"Playwright failed: {e}")

    # Fallback to HTTP (won't work well for this site)
    return await fetch_with_http(city)

async def fetch_with_playwright(city: str) -> List[Dict]:
    """Fetch events using Playwright browser."""
    from playwright.async_api import async_playwright

    url = WASGEHTAPP_ESSEN_URL

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)

            # Get text content
            text = await page.inner_text('body')
            await browser.close()

            # Extract events from text
            return extract_events_from_text(text, city, url)
        except Exception as e:
            logger.error(f"Playwright error: {e}")
            await browser.close()
            raise

def extract_events_from_text(text: str, city: str, source_url: str = None) -> List[Dict]:
    """Extract events from page text content."""
    if source_url is None:
        source_url = WASGEHTAPP_ESSEN_URL
    events = []
    seen = set()
    lines = text.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Look for date patterns like "Fr, 20.03, 16:00 Uhr" or "Di, 17.03.26"
        match = re.search(r'(Mo|Di|Mi|Do|Fr|Sa|So),?\s*(\d{1,2})\.(\d{2}),?\s*(\d{1,2}):(\d{2})\s*Uhr?', line)

        if match:
            weekday = match.group(1)
            day = int(match.group(2))
            month = int(match.group(3))
            hour = int(match.group(4))
            minute = int(match.group(5))

            # Handle 2-digit year
            year = datetime.now().year
            if month > 12:  # Bug: month and day might be swapped
                month, day = day, month

            try:
                start_at = datetime(year, month, day, hour, minute)
            except ValueError as e:
                logger.warning(f"wasgehtapp: ungültiges Datum (Tag={day}, Monat={month}, Jahr={year}): {e}")
                i += 1
                continue

            # Look for title in previous lines
            title = None
            venue = None

            # Search backwards for the title
            for j in range(max(0, i-5), i):
                prev_line = lines[j].strip()
                if prev_line and len(prev_line) > 10 and len(prev_line) < 150:
                    # Skip navigation, dates, etc.
                    if any(x in prev_line.lower() for x in ['uhr', 'pin', 'link', 'favorit', 'mehr', 'km', 'eintritt', '€']):
                        continue
                    if prev_line.startswith('tag') or prev_line.startswith('kon') or prev_line.startswith('the') or prev_line.startswith('com'):
                        continue
                    if re.match(r'^\d+,\d+\s*€', prev_line):
                        continue
                    if 'Uhr' in prev_line:
                        continue
                    title = prev_line
                    break

            dedup_key = (title, start_at) if title else None
            if title and dedup_key not in seen:
                seen.add(dedup_key)

                # Look for venue in current line (after pin)
                pin_match = re.search(r'pin\s+([^,]+)', line)
                if pin_match:
                    venue = pin_match.group(1).strip()

                canonical_id = hashlib.md5(f"wasgehtapp_{title}_{start_at}_{city}".encode()).hexdigest()[:16]

                events.append({
                    "canonical_id": canonical_id,
                    "title": title[:200],
                    "start_at": start_at,
                    "venue_name": venue,
                    "city": city,
                    "source_url": source_url,
                    "source_name": "wasgehtapp.de"
                })

        i += 1

    logger.info(f"Extracted {len(events)} events from wasgehtapp.de")
    return events

async def fetch_with_http(city: str) -> List[Dict]:
    """Fallback: Fetch events using HTTP."""
    url = WASGEHTAPP_ESSEN_URL

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            return parse_wasgehtapp_html(response.text, city)
        except Exception as e:
            logger.error(f"Error fetching wasgehtapp.de: {e}")
            return []

def parse_wasgehtapp_html(html: str, city: str) -> List[Dict]:
    """Parse HTML to extract event data."""
    # Not implemented - would need JavaScript
    return []

async def sync_wasgehtapp(db: Session):
    """Sync events from wasgehtapp.de to database."""
    events_data = await fetch_wasgehtapp_events("Essen")
    return sync_events_to_db(db, events_data, "wasgehtapp.de")
