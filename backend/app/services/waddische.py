"""waddische.de (Werdener Nachrichten) - local Essen-Werden events."""
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

WADDISCHE_URL = "https://waddische.de/termine/"


async def fetch_waddische_events() -> List[Dict]:
    """Fetch events from waddische.de."""
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }) as client:
        try:
            response = await client.get(WADDISCHE_URL)
            response.raise_for_status()
            return parse_waddische_html(response.text)
        except Exception as e:
            logger.error(f"Error fetching waddische.de: {e}")
            return []


GERMAN_MONTHS = {
    'januar': 1, 'februar': 2, 'märz': 3, 'april': 4,
    'mai': 5, 'juni': 6, 'juli': 7, 'august': 8,
    'september': 9, 'oktober': 10, 'november': 11, 'dezember': 12,
}


def parse_waddische_html(html: str) -> List[Dict]:
    """Parse waddische.de HTML for events.

    Structure: h3 = category, h4 = date ("Freitag, 12. Dezember:"),
    then p/text = event entries with times and titles.
    """
    soup = BeautifulSoup(html, 'lxml')
    events = []
    seen = set()

    content = soup.select_one('.entry-content, article, #content')
    if not content:
        content = soup

    current_category = None
    current_date = None  # (day, month)

    for element in content.children:
        if not hasattr(element, 'name') or not element.name:
            continue

        text = element.get_text(strip=True)
        if not text:
            continue

        # h3 = category ("Treffs, Kurse & Workshops", "Kinder und Jugend", etc.)
        if element.name == 'h3':
            if any(w in text.lower() for w in ['kinder', 'jugend', 'bühne', 'musik', 'ausstellung', 'treff', 'kurs']):
                current_category = text
            continue

        # h4 = date ("Freitag, 12. Dezember:" or "Montag, 15. Dezember:")
        if element.name == 'h4':
            date_match = re.search(r'(\d{1,2})\.\s*(\w+)', text)
            if date_match:
                day = int(date_match.group(1))
                month_name = date_match.group(2).lower().rstrip(':')
                month = GERMAN_MONTHS.get(month_name)
                if month:
                    current_date = (day, month)
            continue

        # ul, p or other elements = event entries
        if element.name in ('p', 'div', 'ul') and current_date and current_category:
            # Extract individual events from text (may have multiple)
            for line in text.split('\n'):
                line = line.strip()
                if not line or len(line) < 10:
                    continue

                # Try to find time: "19:00 Uhr" or "10.00 Uhr"
                time_match = re.search(r'(\d{1,2})[:\.](\d{2})\s*(?:Uhr|h)?', line)
                hour = int(time_match.group(1)) if time_match else 0
                minute = int(time_match.group(2)) if time_match else 0

                # Build title: remove the time portion
                title = line
                if time_match:
                    title = line[time_match.end():].strip()
                    title = re.sub(r'^[:\-–,\s]+', '', title)

                if not title or len(title) < 5:
                    title = line  # Use full line if extraction failed

                # Skip nav/meta noise
                if any(w in title.lower() for w in ['impressum', 'datenschutz', 'kontakt', 'e-paper', 'abo', 'links', 'agb']):
                    continue

                if title in seen:
                    continue
                seen.add(title)

                year = datetime.now().year
                day, month = current_date
                # If month is in the past, assume next year
                now = datetime.now()
                if month < now.month or (month == now.month and day < now.day):
                    year += 1

                start_at = None
                try:
                    start_at = datetime(year, month, day, hour, minute)
                except ValueError:
                    continue

                canonical_id = hashlib.md5(f"waddische_{title}".encode()).hexdigest()[:16]

                kids = None
                if current_category and 'kinder' in current_category.lower():
                    kids = "yes"

                events.append({
                    "canonical_id": canonical_id,
                    "title": title[:200],
                    "start_at": start_at,
                    "venue_name": None,
                    "city": "Essen",
                    "source_url": WADDISCHE_URL,
                    "source_name": "Werdener Nachrichten",
                    "kids_suitable": kids,
                })

    logger.info(f"Found {len(events)} events from waddische.de")
    return events


async def sync_waddische(db: Session):
    """Sync events from waddische.de to database."""
    events_data = await fetch_waddische_events()
    return sync_events_to_db(db, events_data, "Werdener Nachrichten")
