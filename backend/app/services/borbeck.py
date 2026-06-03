"""borbeck.de event source - RSS Feed for local Essen-Borbeck events."""
import httpx
import feedparser
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
import hashlib
import logging

from app.services.base_sync import sync_events_to_db

logger = logging.getLogger(__name__)

BORBECK_RSS = "https://www.borbeck.de/share/borbeck-rss.xml"


async def fetch_borbeck_events() -> List[Dict]:
    """Fetch events from borbeck.de RSS feed."""
    try:
        response = httpx.get(BORBECK_RSS, timeout=30.0, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        response.raise_for_status()
        return parse_rss_feed(response.text)
    except Exception as e:
        logger.error(f"Error fetching borbeck.de: {e}")
        return []


def parse_rss_feed(xml: str) -> List[Dict]:
    """Parse RSS feed to extract events."""
    events = []

    try:
        feed = feedparser.parse(xml)

        for entry in feed.entries:
            try:
                event = convert_rss_entry(entry)
                if event:
                    events.append(event)
            except Exception as e:
                logger.warning(f"Error parsing borbeck.de RSS entry: {e}")
                continue

    except Exception as e:
        logger.error(f"Error parsing borbeck.de RSS: {e}")

    logger.info(f"Found {len(events)} events from borbeck.de")
    return events


def convert_rss_entry(entry) -> Optional[Dict]:
    """Convert RSS entry to event format."""
    title = entry.get('title', '').strip()
    if not title or len(title) < 5:
        return None

    # Skip non-event items
    skip_words = ['impressum', 'datenschutz', 'kontakt', 'redaktion', 'werbung']
    if any(w in title.lower() for w in skip_words):
        return None

    canonical_id = hashlib.md5(f"borbeck_{title}".encode()).hexdigest()[:16]

    link = entry.get('link', '')

    # RSS published date is article date, not event date
    # Treat as permanent/ongoing local offers
    description = entry.get('summary', '') or entry.get('description', '')

    return {
        "canonical_id": canonical_id,
        "title": title,
        "short_description": description[:500] if description else None,
        "start_at": None,
        "venue_name": None,
        "source_url": link,
        "source_name": "borbeck.de",
        "city": "Essen",
        "is_permanent_offer": True,
    }


async def sync_borbeck(db: Session):
    """Sync events from borbeck.de to database."""
    events_data = await fetch_borbeck_events()
    return sync_events_to_db(db, events_data, "borbeck.de")
