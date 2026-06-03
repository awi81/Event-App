"""Grugapark event source - HTML scraping."""
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

GRUGAPARK_URL = "https://www.grugapark.de/erleben/veranstaltungskalender_2/veranstaltungskalender.de.html"


async def fetch_grugapark_events() -> List[Dict]:
    """Fetch events from Grugapark website."""
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }) as client:
        try:
            response = await client.get(GRUGAPARK_URL)
            response.raise_for_status()
            return parse_grugapark_html(response.text)
        except Exception as e:
            logger.error(f"Error fetching Grugapark: {e}")
            return []


def parse_grugapark_html(html: str) -> List[Dict]:
    """Parse Grugapark HTML to extract events."""
    soup = BeautifulSoup(html, 'lxml')
    events = []

    # Try multiple selectors for event containers
    containers = soup.select('article, .event, .veranstaltung, [class*="event"], .ce-textpic')
    if not containers:
        containers = soup.select('div.row, div.content-element')

    for container in containers:
        try:
            event = extract_grugapark_event(container)
            if event:
                events.append(event)
        except Exception as e:
            logger.debug(f"Error parsing Grugapark element: {e}")
            continue

    # Fallback: extract from headings + paragraphs
    if not events:
        events = extract_from_headings(soup)

    logger.info(f"Found {len(events)} events from Grugapark")
    return events


def extract_grugapark_event(container) -> Optional[Dict]:
    """Extract event from a container element."""
    title_elem = container.select_one('h2, h3, h4, .headline, [class*="title"]')
    if not title_elem:
        return None

    title = title_elem.get_text(strip=True)
    if not title or len(title) < 5:
        return None

    # Skip navigation/footer items
    skip_words = ['kontakt', 'impressum', 'datenschutz', 'anfahrt', 'öffnungszeiten', 'preise', 'newsletter']
    if any(w in title.lower() for w in skip_words):
        return None

    canonical_id = hashlib.md5(f"grugapark_{title}".encode()).hexdigest()[:16]

    # Extract date
    date_elem = container.select_one('time, [class*="date"], [class*="datum"], .date')
    start_at = None
    if date_elem:
        date_text = date_elem.get('datetime') or date_elem.get_text(strip=True)
        start_at = parse_grugapark_date(date_text)

    # Also check text content for date patterns
    if not start_at:
        text = container.get_text()
        date_match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', text)
        if date_match:
            try:
                start_at = datetime(int(date_match.group(3)), int(date_match.group(2)), int(date_match.group(1)))
            except ValueError:
                pass

    # Description
    desc_elem = container.select_one('p, .text, [class*="description"]')
    description = desc_elem.get_text(strip=True)[:500] if desc_elem else None

    # Link
    link_elem = container.select_one('a[href]')
    source_url = None
    if link_elem:
        href = link_elem.get('href', '')
        if href and not href.startswith('#'):
            source_url = href if href.startswith('http') else f"https://www.grugapark.de/{href.lstrip('/')}"

    return {
        "canonical_id": canonical_id,
        "title": title,
        "short_description": description,
        "start_at": start_at,
        "venue_name": "Grugapark",
        "city": "Essen",
        "lat": 51.4293,
        "lon": 7.0561,
        "source_url": source_url or GRUGAPARK_URL,
        "source_name": "Grugapark",
        "indoor_outdoor": "outdoor",
        "kids_suitable": "likely",
    }


def extract_from_headings(soup) -> List[Dict]:
    """Fallback: extract events from headings."""
    events = []
    headings = soup.select('h2, h3')

    for h in headings:
        title = h.get_text(strip=True)
        if not title or len(title) < 5 or len(title) > 200:
            continue

        skip_words = ['kontakt', 'impressum', 'datenschutz', 'anfahrt', 'öffnungszeiten', 'preise', 'newsletter', 'grugapark', 'willkommen']
        if any(w in title.lower() for w in skip_words):
            continue

        canonical_id = hashlib.md5(f"grugapark_{title}".encode()).hexdigest()[:16]

        # Look for date in next sibling
        start_at = None
        next_elem = h.find_next_sibling()
        if next_elem:
            text = next_elem.get_text()
            date_match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', text)
            if date_match:
                try:
                    start_at = datetime(int(date_match.group(3)), int(date_match.group(2)), int(date_match.group(1)))
                except ValueError:
                    pass

        events.append({
            "canonical_id": canonical_id,
            "title": title,
            "start_at": start_at,
            "venue_name": "Grugapark",
            "city": "Essen",
            "lat": 51.4293,
            "lon": 7.0561,
            "source_url": GRUGAPARK_URL,
            "source_name": "Grugapark",
            "indoor_outdoor": "outdoor",
            "kids_suitable": "likely",
        })

    return events


def parse_grugapark_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse Grugapark date formats."""
    if not date_str:
        return None

    # Try ISO format first
    try:
        return datetime.fromisoformat(date_str)
    except (ValueError, TypeError):
        pass

    # German date formats
    formats = ["%d.%m.%Y", "%d.%m.%Y %H:%M", "%d. %B %Y"]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue

    return None


async def sync_grugapark(db: Session):
    """Sync events from Grugapark to database."""
    events_data = await fetch_grugapark_events()
    return sync_events_to_db(db, events_data, "Grugapark")
