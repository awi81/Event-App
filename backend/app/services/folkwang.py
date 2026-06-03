"""Museum Folkwang event source - HTML/Playwright scraping."""
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

FOLKWANG_URL = "https://www.museum-folkwang.de/de/kalender"

FOLKWANG_LAT = 51.4425
FOLKWANG_LON = 7.0026


async def fetch_folkwang_events() -> List[Dict]:
    """Fetch events from Museum Folkwang."""
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                await page.goto(FOLKWANG_URL, wait_until="networkidle", timeout=20000)
                await page.wait_for_timeout(2000)

                # Click "7 TAGE" to show weekly view with actual events
                try:
                    await page.locator('text=7 TAGE').first.click()
                    await page.wait_for_timeout(3000)
                except Exception:
                    pass

                for _ in range(3):
                    await page.keyboard.press("End")
                    await page.wait_for_timeout(800)

                text = await page.inner_text('body')
                await browser.close()
                return parse_folkwang_text(text)
            except Exception as e:
                logger.error(f"Folkwang Playwright error: {e}")
                await browser.close()
                return []
    except Exception as e:
        logger.error(f"Error fetching Museum Folkwang: {e}")
        return []


GERMAN_MONTHS = {
    'januar': 1, 'februar': 2, 'märz': 3, 'april': 4,
    'mai': 5, 'juni': 6, 'juli': 7, 'august': 8,
    'september': 9, 'oktober': 10, 'november': 11, 'dezember': 12,
    'marz': 3,  # without umlaut
}

WEEKDAYS = ['montag', 'dienstag', 'mittwoch', 'donnerstag', 'freitag', 'samstag', 'sonntag']


def parse_folkwang_text(text: str) -> List[Dict]:
    """Parse Museum Folkwang calendar text.

    Format: "DIENSTAG, 24. MÄRZ 2026" then "10:00 – 18:00" then title, then type.
    """
    events = []
    seen = set()
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    current_date = None  # (year, month, day)
    i = 0

    while i < len(lines):
        line = lines[i]
        line_lower = line.lower().replace('ä', 'a').replace('ö', 'o').replace('ü', 'u')

        # Match: "DIENSTAG, 24. MÄRZ 2026" or "SAMSTAG, 29. MÄRZ 2026"
        date_match = re.match(
            r'^(?:' + '|'.join(WEEKDAYS) + r')[,.]?\s*(\d{1,2})\.\s*(\w+)\s+(\d{4})',
            line_lower
        )

        if date_match:
            day = int(date_match.group(1))
            month_name = date_match.group(2).lower()
            year = int(date_match.group(3))
            month = GERMAN_MONTHS.get(month_name)
            if month:
                current_date = (year, month, day)
            i += 1
            continue

        # Match time + title block: "10:00 – 18:00" or "14:30"
        time_match = re.match(r'^(\d{1,2}):(\d{2})', line)

        if time_match and current_date:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            year, month, day = current_date

            start_at = None
            try:
                start_at = datetime(year, month, day, hour, minute)
            except ValueError:
                i += 1
                continue

            if start_at < datetime.now():
                i += 1
                continue

            # Next line(s) = title, then event type
            title = None
            event_type = None
            for j in range(i + 1, min(i + 4, len(lines))):
                candidate = lines[j].strip()
                if not candidate or len(candidate) < 2:
                    continue
                # Stop at next time or date
                if re.match(r'^\d{1,2}:', candidate):
                    break
                if any(candidate.lower().startswith(wd) for wd in WEEKDAYS):
                    break

                if not title:
                    title = candidate
                elif not event_type and len(candidate) < 40:
                    event_type = candidate
                    break

            display_title = f"{title} ({event_type})" if event_type else title
            dedup_key = (display_title, start_at) if title else None
            if title and dedup_key not in seen:
                seen.add(dedup_key)
                canonical_id = hashlib.md5(f"folkwang_{display_title}_{start_at}".encode()).hexdigest()[:16]

                kids = None
                if any(w in (title + (event_type or '')).lower() for w in ['familien', 'kinder', 'kids']):
                    kids = "yes"

                events.append({
                    "canonical_id": canonical_id,
                    "title": display_title[:200],
                    "start_at": start_at,
                    "venue_name": "Museum Folkwang",
                    "city": "Essen",
                    "lat": FOLKWANG_LAT,
                    "lon": FOLKWANG_LON,
                    "source_url": FOLKWANG_URL,
                    "source_name": "Museum Folkwang",
                    "indoor_outdoor": "indoor",
                    "kids_suitable": kids,
                })

        i += 1

    logger.info(f"Found {len(events)} events from Museum Folkwang")
    return events


async def sync_folkwang(db: Session):
    """Sync events from Museum Folkwang to database."""
    events_data = await fetch_folkwang_events()
    return sync_events_to_db(db, events_data, "Museum Folkwang")
