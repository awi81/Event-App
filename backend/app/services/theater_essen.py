"""Theater und Philharmonie Essen (TUP) - Playwright scraping."""
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
import hashlib
import re
import logging

from app.services.base_sync import sync_events_to_db

logger = logging.getLogger(__name__)

TUP_URL = "https://www.theater-essen.de/programm/kalender/"

# Aalto-Theater / Grillo-Theater / Philharmonie coordinates (Essen center)
TUP_LAT = 51.4480
TUP_LON = 7.0048


async def fetch_theater_essen_events() -> List[Dict]:
    """Fetch events from Theater Essen using Playwright."""
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                await page.goto(TUP_URL, wait_until="networkidle", timeout=20000)
                await page.wait_for_timeout(3000)

                # Scroll to load more events
                for _ in range(3):
                    await page.keyboard.press("End")
                    await page.wait_for_timeout(800)

                text = await page.inner_text('body')
                await browser.close()
                return parse_tup_text(text)
            except Exception as e:
                logger.error(f"TUP Playwright error: {e}")
                await browser.close()
                return []
    except Exception as e:
        logger.error(f"Error fetching Theater Essen: {e}")
        return []


def parse_tup_text(text: str) -> List[Dict]:
    """Parse Theater Essen calendar text.

    Format on page:
        PHILHARMONIE ESSEN     ← venue (before date block)
        Mittwoch               ← weekday (full German)
        25.03.2026             ← date
        09:30 - 10:15          ← time range
        NATIONAL-BANK Pavillon ← sub-venue
        TITEL                  ← event title (often after "Termin in meinen Kalender")
        Subtitle/Genre
    """
    events = []
    seen = set()
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    # Venues are matched case-insensitively. List substrings - a line counts
    # as a venue if ANY of these appear in its uppercase form.
    venue_markers = [
        'PHILHARMONIE', 'AALTO-MUSIKTHEATER', 'AALTO-THEATER', 'AALTO-FOYER',
        'GRILLO-THEATER', 'GRILLO', 'CASA',
        'NATIONAL-BANK', 'ALFRIED KRUPP', 'RWE PAVILLON', 'STADTRAUM',
        'STUDIO-BÜHNE', 'STUDIO BÜHNE', 'PHILHARMONIE ESSEN',
    ]

    def is_venue_line(s: str) -> bool:
        up = s.upper()
        return any(m in up for m in venue_markers)

    i = 0
    current_venue = "Theater Essen"

    while i < len(lines):
        line = lines[i]

        # Track current venue
        if is_venue_line(line) and len(line) < 50:
            current_venue = line
            i += 1
            continue

        # Look for date: "25.03.2026" as standalone line
        date_match = re.match(r'^(\d{1,2})\.(\d{1,2})\.(\d{4})$', line)

        if date_match:
            day = int(date_match.group(1))
            month = int(date_match.group(2))
            year = int(date_match.group(3))

            # Look for time in next line: "09:30 - 10:15" or "19:30"
            hour, minute = 19, 30
            if i + 1 < len(lines):
                time_match = re.match(r'^(\d{1,2}):(\d{2})', lines[i + 1])
                if time_match:
                    hour = int(time_match.group(1))
                    minute = int(time_match.group(2))

            start_at = None
            try:
                start_at = datetime(year, month, day, hour, minute)
            except ValueError:
                i += 1
                continue

            if start_at < datetime.now():
                i += 1
                continue

            # Find title: skip time, venue, meta lines
            title = None
            skip_patterns = [
                r'^\d{1,2}:', r'NATIONAL-BANK', r'Termin in',
                r'TICKETS', r'WENIGE', r'AUSVERKAUFT', r'^\d+,\d+',
                r'Rabattstufe', r'Veranstaltung ist', r'TUPcard',
                r'^F.r\s', r'^ab\s',
                # Labels Theater Essen puts above the title that aren't titles:
                r'^URAUFFÜHRUNG$', r'^URAUFFUEHRUNG$',
                r'^ZUM LETZTEN MAL', r'^PREMIERE$', r'^WIEDERAUFNAHME$',
                r'^GASTSPIEL$', r'^GENERALPROBE$',
                r'^PHILHARMONISCHES KONZERT$', r'^KAMMERKONZERT$',
            ]

            for j in range(i + 1, min(i + 10, len(lines))):
                candidate = lines[j]

                # Stop at next date
                if re.match(r'^\d{1,2}\.\d{1,2}\.\d{4}$', candidate):
                    break
                if any(w in candidate for w in ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag']):
                    break

                # Skip meta lines
                if any(re.search(p, candidate) for p in skip_patterns):
                    continue

                # Venue lines are not titles - track them and keep looking.
                if is_venue_line(candidate) and len(candidate) < 50:
                    current_venue = candidate
                    continue

                if len(candidate) > 3 and not title:
                    title = candidate
                    break

            # Dedup per (title, start_at) so multiple performances of the same
            # play across different show times are all kept (grouping merges them
            # on the UI side).
            dedup_key = (title, start_at) if title else None
            if title and dedup_key not in seen:
                seen.add(dedup_key)
                canonical_id = hashlib.md5(f"tup_{title}_{start_at}".encode()).hexdigest()[:16]

                events.append({
                    "canonical_id": canonical_id,
                    "title": title[:200],
                    "start_at": start_at,
                    "venue_name": current_venue,
                    "city": "Essen",
                    "lat": TUP_LAT,
                    "lon": TUP_LON,
                    "source_url": TUP_URL,
                    "source_name": "Theater Essen",
                    "indoor_outdoor": "indoor",
                })

        i += 1

    logger.info(f"Found {len(events)} events from Theater Essen")
    return events


async def sync_theater_essen(db: Session):
    """Sync events from Theater Essen to database."""
    events_data = await fetch_theater_essen_events()
    return sync_events_to_db(db, events_data, "Theater Essen")
