import httpx
import feedparser
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
import hashlib
import logging

from app.services.base_sync import sync_events_to_db, to_berlin_naive

logger = logging.getLogger(__name__)

RUHRPOTT_KIDS_RSS = "https://ruhrpottkids.com/api/rss/content.rss"

async def fetch_ruhrpott_kids_events() -> List[Dict]:
    """Fetch events from Ruhrpott-Kids RSS feed."""
    try:
        response = httpx.get(RUHRPOTT_KIDS_RSS, timeout=30.0)
        response.raise_for_status()
        return parse_rss_feed(response.text)
    except Exception as e:
        logger.error(f"Error fetching Ruhrpott-Kids: {e}")
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
                logger.warning(f"Error parsing RSS entry: {e}")
                continue

    except Exception as e:
        logger.error(f"Error parsing RSS feed: {e}")

    logger.info(f"Found {len(events)} events from Ruhrpott-Kids")
    return events

def convert_rss_entry(entry) -> Optional[Dict]:
    """Convert RSS entry to our event format."""
    try:
        title = entry.get('title', '')
        if not title:
            return None

        # Generate canonical ID
        canonical_id = hashlib.md5(f"ruhrpottkids_{title}".encode()).hexdigest()[:16]

        # Ruhrpott-Kids RSS: 'published' is the article date, not the event date.
        # These are tips/recommendations, not dated events → treat as permanent offers.
        start_at = None

        # Get summary/description
        description = entry.get('summary', '')
        if hasattr(entry, 'description'):
            description = entry.get('description', '')

        # Get link
        link = entry.get('link', '')

        # Get location
        venue_name = None
        if hasattr(entry, 'location'):
            venue_name = entry.location
        elif hasattr(entry, 'where'):
            venue_name = str(entry.where)

        # Get categories/tags
        category = None
        if hasattr(entry, 'tags'):
            tags = [tag.term for tag in entry.tags]
            category = tags[0] if tags else None

        return {
            "canonical_id": canonical_id,
            "title": title,
            "short_description": description[:500] if description else None,
            "start_at": start_at,
            "venue_name": venue_name,
            "category": category,
            "source_url": link,
            "source_name": "Ruhrpott-Kids",
            "city": "Essen",
            "kids_suitable": "yes",
            "is_permanent_offer": True
        }
    except Exception as e:
        logger.warning(f"Error converting RSS entry: {e}")
        return None

def parse_rss_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse RSS date format."""
    if not date_str:
        return None

    try:
        # Try common RSS date formats
        from email.utils import parsedate_to_datetime
        return to_berlin_naive(parsedate_to_datetime(date_str))
    except Exception:
        pass

    # Try manual parsing
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%a, %d %b %Y %H:%M:%S %z",
    ]

    for fmt in formats:
        try:
            return to_berlin_naive(datetime.strptime(date_str.strip(), fmt))
        except ValueError:
            continue

    return None

async def sync_ruhrpott_kids(db: Session):
    """Sync events from Ruhrpott-Kids to database."""
    logger.info("Starting Ruhrpott-Kids sync")
    events_data = await fetch_ruhrpott_kids_events()
    logger.info(f"Fetched {len(events_data)} events")
    return sync_events_to_db(db, events_data, "Ruhrpott-Kids")
