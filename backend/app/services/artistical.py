"""Artistical Theater Essen – GOP Varieté (ehemals variete.de/essen).

Quelle: https://artistical.de
Technologie: Next.js App Router (React Server Components). Die Eventdaten
werden als statisches JavaScript-Array im Turbopack-Bundle ausgeliefert –
kein Playwright nötig. Der relevante Chunk enthält eine Variable ``c`` mit
allen Shows inkl. Spielplandaten.

Robots.txt: variete.de und artistical.de erlauben allgemeines Crawling
(kein Disallow für den genutzten Pfad).

Koordinaten Villa Varieté / Artistical Theater Essen:
  Rottstraße 30, 45127 Essen
  Lat 51.45230 / Lon 7.01330  (OpenStreetMap, abgerufen 03.06.2026)
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

import httpx
from sqlalchemy.orm import Session

from app.services.base_sync import sync_events_to_db

logger = logging.getLogger(__name__)

BASE_URL = "https://artistical.de"
HOME_URL = BASE_URL
VENUE_NAME = "Artistical Theater Essen (GOP Varieté)"
VENUE_LAT = 51.45230
VENUE_LON = 7.01330

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# The event chunk URL is stable across builds because it is content-addressed
# (Turbopack hash derived from content). We discover it dynamically.
_CHUNK_PATTERN = re.compile(
    r'src="(/_next/static/chunks/[^"]+\.js)"[^>]*>',
)

# Pattern to find the events array inside the JS bundle.
# The array is assigned to a variable (currently `c`) right before
# the EventsSection definition. We grab the raw JSON-ish literal.
_EVENTS_ARRAY_PATTERN = re.compile(
    r"let [a-z]=\[(\{slug:.+?\})\]",
    re.DOTALL,
)

# ISO date inside the dates array: "2026-09-22"
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _find_events_chunk_url(html: str) -> Optional[str]:
    """Return the URL of the JS chunk that contains event data."""
    # The chunk that exports EventsSection is referenced in __next_f scripts
    m = re.search(r'"EventsSection"[^"]*"(/_next/static/chunks/[^"]+\.js)"', html)
    if m:
        return BASE_URL + m.group(1)

    # Fallback: scan all chunk src attributes and return the one that
    # references EventsSection in the inline script data
    chunk_ref = re.search(
        r'"EventsSection".*?"(/_next/static/chunks/[^"]+?\.js)"', html, re.DOTALL
    )
    if chunk_ref:
        return BASE_URL + chunk_ref.group(1)

    # Second fallback: find from __next_f.push payload (the chunk id is numeric)
    # The payload contains entries like:  "EventsSection",0,function(){...}],76558
    # and the chunk with id 76558 will appear in script src
    cid_m = re.search(r'"EventsSection",0,function\(\).*?],(\d{4,6})', html, re.DOTALL)
    if cid_m:
        cid = cid_m.group(1)
        # Find the script src that contains this module id in its path
        for src_m in re.finditer(r'src="(/_next/static/chunks/[^"]+\.js)"', html):
            src = src_m.group(1)
            # Turbopack chunk filenames sometimes embed the module id
            # but we can just try all chunks until we find EventsSection
        # If we can't narrow it down, return None (caller will scan all chunks)
    return None


def _extract_events_from_chunk(js: str) -> List[Dict]:
    """Parse show definitions from the JS bundle and return event dicts."""
    events: List[Dict] = []

    # We look for the array literal that contains the show objects.
    # Each object starts with `{slug:"…"` and contains `dates:[…]` or
    # an event-level ticketUrl without explicit dates (= single show).
    #
    # Strategy: find the array by string search, then bracket-balance it,
    # then split into individual show blocks.

    # Use plain string search to locate the array start: '[{slug:'
    array_marker = '[{slug:'
    array_start_idx = js.find(array_marker)
    if array_start_idx < 0:
        logger.warning("Artistical: Event-Array nicht im Chunk gefunden.")
        return []

    # Walk forward to find the matching ] that closes the array
    start = array_start_idx
    depth = 0
    end = start
    for pos, ch in enumerate(js[start:], start):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                end = pos + 1
                break

    raw_array = js[start:end]

    # Split into individual show objects by looking for top-level commas
    # between `},` and `{slug:`. This is fragile for deeply nested structures
    # so we use a simpler approach: extract all ISO dates and associate them
    # with the nearest slug/title above them.
    show_blocks = re.split(r"[}],\s*[{]slug:", raw_array)

    for i, block in enumerate(show_blocks):
        if i > 0:
            block = "{slug:" + block
        elif block.startswith("["):
            # First block starts with the opening bracket
            block = block.lstrip("[")

        slug_m = re.search(r'slug:"([^"]+)"', block)
        title_m = re.search(r'title:"([^"]+)"', block)
        short_m = re.search(r'shortDescription:"([^"]+)"', block)
        label_m = re.search(r'label:"([^"]+)"', block)
        ticket_m = re.search(r'ticketUrl:"([^"]+)"', block)
        image_m = re.search(r'imageUrl:"([^"]+)"', block)
        age_m = re.search(r'ageRecommendation:"([^"]+)"', block)

        if not slug_m or not title_m:
            continue

        slug = slug_m.group(1)
        title = _unescape_js(title_m.group(1))
        short_desc = _unescape_js(short_m.group(1)) if short_m else None
        label = _unescape_js(label_m.group(1)) if label_m else None
        ticket_url = ticket_m.group(1) if ticket_m else f"{BASE_URL}/#veranstaltungen"
        image_url = BASE_URL + image_m.group(1) if image_m else None
        age_rec = age_m.group(1) if age_m else ""

        # kids_suitable: Kindermusical / Familienfreundlich / "Ab X Jahren"
        kids = _kids_suitable(label or "", age_rec)

        # Extract all ISO dates from the dates:[…] arrays in this block
        iso_dates = _ISO_DATE_RE.findall(block)

        # Ticket URL per date may override the show-level URL
        per_date_tickets: Dict[str, str] = {}
        for dm in re.finditer(
            r'\{iso:"(\d{4}-\d{2}-\d{2})",ticketUrl:"([^"]+)"', block
        ):
            per_date_tickets[dm.group(1)] = dm.group(2)

        if iso_dates:
            for iso in iso_dates:
                try:
                    start_at = datetime.strptime(iso, "%Y-%m-%d")
                except ValueError:
                    continue

                t_url = per_date_tickets.get(iso, ticket_url)
                canonical_id = hashlib.md5(
                    f"artistical_{slug}_{iso}".encode()
                ).hexdigest()[:16]

                desc_parts = []
                if short_desc:
                    desc_parts.append(short_desc)
                if age_rec:
                    desc_parts.append(f"Empfehlung: {age_rec}")
                desc = " ".join(desc_parts)[:500] or None

                events.append(
                    {
                        "canonical_id": canonical_id,
                        "title": title[:200],
                        "short_description": desc,
                        "start_at": start_at,
                        "venue_name": VENUE_NAME,
                        "city": "Essen",
                        "lat": VENUE_LAT,
                        "lon": VENUE_LON,
                        "source_url": t_url,
                        "source_name": "GOP Varieté",
                        "indoor_outdoor": "indoor",
                        "kids_suitable": kids,
                        "category": label,
                        "image_url": image_url,
                        "is_permanent_offer": False,
                    }
                )
        else:
            # Show without explicit dates → emit once as permanent offer
            canonical_id = hashlib.md5(
                f"artistical_{slug}".encode()
            ).hexdigest()[:16]
            desc_parts = []
            if short_desc:
                desc_parts.append(short_desc)
            if age_rec:
                desc_parts.append(f"Empfehlung: {age_rec}")
            desc = " ".join(desc_parts)[:500] or None
            events.append(
                {
                    "canonical_id": canonical_id,
                    "title": title[:200],
                    "short_description": desc,
                    "start_at": None,
                    "venue_name": VENUE_NAME,
                    "city": "Essen",
                    "lat": VENUE_LAT,
                    "lon": VENUE_LON,
                    "source_url": ticket_url,
                    "source_name": "GOP Varieté",
                    "indoor_outdoor": "indoor",
                    "kids_suitable": kids,
                    "category": label,
                    "image_url": image_url,
                    "is_permanent_offer": True,
                }
            )

    logger.info("Artistical: %d Event-Einträge aus Chunk extrahiert", len(events))
    return events


def _unescape_js(s: str) -> str:
    """Minimally unescape common JS escape sequences."""
    return (
        s.replace("\\u002B", "+")
        .replace("\\u0026", "&")
        .replace("\\u003C", "<")
        .replace("\\u003E", ">")
        .replace("\\xf6", "ö")
        .replace("\\xe4", "ä")
        .replace("\\xfc", "ü")
        .replace("\\xdf", "ß")
        .replace("\\xd6", "Ö")
        .replace("\\xc4", "Ä")
        .replace("\\xdc", "Ü")
        .replace("\\n", " ")
        .replace('\\"', '"')
        .replace("\\'", "'")
    )


def _kids_suitable(label: str, age_rec: str) -> str:
    label_l = label.lower()
    age_l = age_rec.lower()
    if any(w in label_l for w in ("kindermusical", "kinder", "familien", "family")):
        return "yes"
    if any(w in age_l for w in ("familie", "familien", "kinder", "ab 4", "ab 5", "ab 6")):
        return "yes"
    if "familienfreundlich" in age_l:
        return "yes"
    return "unknown"


async def fetch_artistical_events() -> List[Dict]:
    """Fetch event data from artistical.de by parsing the JS bundle."""
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        # Step 1: fetch home page to discover the relevant chunk URL
        try:
            resp = await client.get(HOME_URL)
            resp.raise_for_status()
        except Exception as exc:
            logger.error("Artistical: Fehler beim Abrufen der Startseite: %s", exc)
            return []

        html = resp.text
        chunk_url = _find_events_chunk_url(html)

        if not chunk_url:
            # Scan all script chunks for the one that contains EventsSection
            for m in re.finditer(r'src="(/_next/static/chunks/[^"]+\.js)"', html):
                url = BASE_URL + m.group(1)
                try:
                    cr = await client.get(url)
                    if "EventsSection" in cr.text and "slug:" in cr.text:
                        chunk_url = url
                        break
                except Exception:
                    continue

        if not chunk_url:
            logger.error(
                "Artistical: Kein JS-Chunk mit Event-Daten gefunden."
            )
            return []

        # Step 2: fetch the chunk
        try:
            chunk_resp = await client.get(chunk_url)
            chunk_resp.raise_for_status()
        except Exception as exc:
            logger.error("Artistical: Fehler beim Laden des JS-Chunks %s: %s", chunk_url, exc)
            return []

        return _extract_events_from_chunk(chunk_resp.text)


async def sync_artistical(db: Session):
    """Sync Artistical Theater Essen events into the database."""
    events_data = await fetch_artistical_events()
    return sync_events_to_db(db, events_data, "GOP Varieté")
