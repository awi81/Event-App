import httpx
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
import hashlib
import logging
import json

from app.services.base_sync import sync_events_to_db, to_berlin_naive

logger = logging.getLogger(__name__)

ZOLLVEREIN_API = "https://events.zollverein.de/api/v1/"

async def fetch_zollverein_events() -> List[Dict]:
    """Fetch events from Zollverein JSON API."""
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }) as client:
        try:
            response = await client.get(ZOLLVEREIN_API)
            response.raise_for_status()
            data = response.json()
            return parse_zollverein_api(data)
        except Exception as e:
            logger.error(f"Error fetching Zollverein API: {e}")
            # Fallback to scraping if API fails
            return await fetch_zollverein_fallback()

async def fetch_zollverein_fallback() -> List[Dict]:
    """Fallback: scrape from website if API fails."""
    from bs4 import BeautifulSoup

    url = "https://www.zollverein.de/kalender/"
    logger.info("Falling back to HTML scraping for Zollverein")

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            return parse_zollverein_html(response.text)
        except Exception as e:
            logger.error(f"Error fetching Zollverein fallback: {e}")
            return []

def parse_zollverein_api(data) -> List[Dict]:
    """Parse Zollverein API response."""
    events = []

    try:
        # Handle different API response formats
        items = data
        if isinstance(data, dict):
            if 'events' in data:
                items = data['events']
            elif 'data' in data:
                items = data['data']
            elif 'results' in data:
                items = data['results']

        for item in items:
            try:
                event = convert_zollverein_event(item)
                if event:
                    events.append(event)
            except Exception as e:
                logger.warning(f"Error parsing Zollverein event: {e}")
                continue

    except Exception as e:
        logger.error(f"Error parsing Zollverein API response: {e}")

    logger.info(f"Found {len(events)} events from Zollverein API")
    return events

def convert_zollverein_event(item: dict) -> Optional[Dict]:
    """Convert Zollverein API event to our format."""
    try:
        # Get title
        title = item.get('title') or item.get('name')
        if not title:
            return None

        # Get URL
        url = item.get('url') or item.get('link')
        if url and not url.startswith('http'):
            url = f"https://www.zollverein.de{url}"

        # Generate canonical ID
        canonical_id = hashlib.md5(f"zollverein_{url or title}".encode()).hexdigest()[:16]

        # Parse date
        start_at = None
        start_date = item.get('startDate') or item.get('start_date') or item.get('start')
        if start_date:
            start_at = parse_zollverein_date(start_date)

        end_date = item.get('endDate') or item.get('end_date') or item.get('end')

        # Get description
        description = item.get('description') or item.get('short_description') or ""
        if isinstance(description, str):
            description = description[:500]

        # Get location
        venue_name = "Zollverein"
        location = item.get('location') or item.get('venue')
        if location:
            if isinstance(location, dict):
                venue_name = location.get('name', 'Zollverein')
            else:
                venue_name = location

        # Get category
        category = item.get('category') or item.get('type')
        if isinstance(category, list) and category:
            category = category[0]

        return {
            "canonical_id": canonical_id,
            "title": title,
            "short_description": description,
            "start_at": start_at,
            "venue_name": venue_name,
            "category": category,
            "source_url": url,
            "source_name": "Zollverein",
            "city": "Essen"
        }
    except Exception as e:
        logger.warning(f"Error converting Zollverein event: {e}")
        return None

def parse_zollverein_date(date_str) -> Optional[datetime]:
    """Parse Zollverein date format."""
    if not date_str:
        return None

    # Try ISO format
    try:
        return to_berlin_naive(datetime.fromisoformat(date_str.replace('Z', '+00:00')))
    except Exception:
        pass

    # Try common formats
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            return to_berlin_naive(datetime.strptime(date_str, fmt))
        except ValueError:
            continue

    return None

def parse_zollverein_html(html: str) -> List[Dict]:
    """Parse Zollverein HTML to extract events (fallback)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, 'lxml')
    events = []

    # Find all event list items
    event_items = soup.select('li.mb-4')
    if not event_items:
        event_items = soup.select('li[class*="mb-"]')
    if not event_items:
        event_items = soup.select('li[role="button"]')

    for item in event_items:
        try:
            event = extract_zollverein_event(item)
            if event:
                events.append(event)
        except Exception as e:
            logger.warning(f"Error parsing event: {e}")
            continue

    logger.info(f"Found {len(events)} events from Zollverein HTML")
    return events

def extract_zollverein_event(item) -> Optional[Dict]:
    """Extract event data from HTML element (fallback)."""
    import re

    try:
        title_elem = item.select_one('h3 a')
        if not title_elem:
            title_elem = item.select_one('h3')
        if not title_elem:
            return None

        title = title_elem.get_text(strip=True)
        if not title or len(title) < 5:
            return None

        href = title_elem.get('href', '')
        source_url = f"https://www.zollverein.de{href}" if href else None

        canonical_id = hashlib.md5(f"zollverein_{href or title}".encode()).hexdigest()[:16]

        category_elem = item.select_one('.text-\\[10px\\], .uppercase, .tracking-widest')
        category = category_elem.get_text(strip=True) if category_elem else None
        if not category or len(category) > 30:
            category = None

        venue_name = "Zollverein"
        location_elem = item.select_one('[class*="Ort"]')
        if location_elem:
            venue_name = location_elem.get_text(strip=True)

        desc_elem = item.select_one('p')
        description = desc_elem.get_text(strip=True)[:500] if desc_elem else None

        # Try to extract date from text content
        start_at = None
        text = item.get_text()
        date_match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', text)
        if date_match:
            try:
                start_at = datetime(int(date_match.group(3)), int(date_match.group(2)), int(date_match.group(1)))
            except ValueError:
                pass

        return {
            "canonical_id": canonical_id,
            "title": title,
            "short_description": description,
            "start_at": start_at,
            "venue_name": venue_name,
            "category": category,
            "source_url": source_url,
            "source_name": "Zollverein",
            "city": "Essen",
            "lat": 51.4864,
            "lon": 7.0403,
            "is_permanent_offer": start_at is None,
        }
    except Exception as e:
        return None

async def sync_zollverein(db: Session):
    """Sync events from Zollverein to database."""
    events_data = await fetch_zollverein_events()
    return sync_events_to_db(db, events_data, "Zollverein")
