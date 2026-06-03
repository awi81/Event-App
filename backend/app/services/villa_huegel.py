"""Villa Hügel / Krupp-Stiftung Essen – Veranstaltungen.

Quelle: https://www.krupp-stiftung.de/veranstaltungen
Technologie: Next.js (getStaticProps). Die gesamte Veranstaltungsliste ist
im __NEXT_DATA__ JSON-Blob auf der Seite eingebettet – kein Playwright nötig.

Das `programs`-Array enthält die einzelnen Programmpunkte mit:
  - title, subtitle, slug, date_as_string, thumbnail.src

`date_as_string` ist Freitext (z. B. "7. Juli 2026", "Ab 6. Februar ...",
"Ganzjährig"). Eindeutige Einzeldaten werden geparst; mehrdeutige /
saisonale Einträge werden als `is_permanent_offer=True` eingetragen.

Koordinaten Villa Hügel, Essen-Bredeney:
  Hügel 1, 45133 Essen (Bredeney)
  Lat 51.40780 / Lon 7.01270  (OpenStreetMap, abgerufen 03.06.2026)
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

BASE_URL = "https://www.krupp-stiftung.de"
EVENTS_URL = f"{BASE_URL}/veranstaltungen"

VENUE_NAME = "Villa Hügel"
VENUE_LAT = 51.40780
VENUE_LON = 7.01270

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
}

_GERMAN_MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "april": 4,
    "mai": 5, "juni": 6, "juli": 7, "august": 8,
    "september": 9, "oktober": 10, "november": 11, "dezember": 12,
}

# Patterns we know mean "no specific date" → permanent / seasonal offer
_PERMANENT_KEYWORDS = (
    "ganzjährig", "ganzj", "ab ", "bis ", "monat", "wöchentlich",
    "jeden", "täglich", "abgeschlossen", "ios", "android", "für ios",
)


def _clean_title(raw: str) -> str:
    """Strip \r\n line breaks that appear in the Krupp JSON titles."""
    return re.sub(r"[\r\n]+", " ", raw).strip()


def _parse_date_as_string(s: str) -> Optional[datetime]:
    """Try to parse a German date string like '7. Juli 2026' into a datetime.

    Returns None for ambiguous / non-parseable strings.
    """
    if not s:
        return None
    s = s.strip()

    # Check for permanent / undateable keywords first
    sl = s.lower()
    if any(kw in sl for kw in _PERMANENT_KEYWORDS):
        return None

    # "7. Juli 2026"  or  "7. Juli 2026, 18:30 Uhr"
    m = re.match(
        r"(\d{1,2})\.\s+(\w+)\s+(\d{4})(?:,?\s+(\d{1,2}):(\d{2}))?",
        s,
    )
    if m:
        day = int(m.group(1))
        month_name = m.group(2).lower()
        year = int(m.group(3))
        hour = int(m.group(4)) if m.group(4) else 0
        minute = int(m.group(5)) if m.group(5) else 0
        month = _GERMAN_MONTHS.get(month_name)
        if month:
            try:
                return datetime(year, month, day, hour, minute)
            except ValueError:
                pass

    # "2. Juni 2026" (no leading zero)
    m2 = re.match(r"(\d{1,2})\.\s*(\w+)\s+(\d{4})", s)
    if m2:
        day = int(m2.group(1))
        month = _GERMAN_MONTHS.get(m2.group(2).lower())
        year = int(m2.group(3))
        if month:
            try:
                return datetime(year, month, day)
            except ValueError:
                pass

    return None


def _kids_suitable(title: str, subtitle: str) -> str:
    """Determine kids suitability from title/subtitle keywords."""
    text = (title + " " + subtitle).lower()
    if any(
        w in text
        for w in (
            "family", "famil", "kinder", "kinderprogramm", "kinderführung",
            "ist family", "hügel ist family",
        )
    ):
        return "yes"
    return "unknown"


def _indoor_outdoor(title: str, subtitle: str) -> str:
    text = (title + " " + subtitle).lower()
    if any(w in text for w in ("park", "außen", "outdoor", "picknick", "garten")):
        return "outdoor"
    if any(w in text for w in ("kino", "vortrag", "ausstellung", "konzert", "führung", "halle")):
        return "indoor"
    return "both"


def parse_villa_huegel_programs(programs: list) -> List[Dict]:
    """Convert the `programs` list from __NEXT_DATA__ to event dicts."""
    events: List[Dict] = []

    for prog in programs:
        try:
            raw_title = prog.get("title", "")
            title = _clean_title(raw_title)
            if not title or len(title) < 3:
                continue

            subtitle = prog.get("subtitle", "") or ""
            slug = prog.get("slug", "")
            date_str = prog.get("date_as_string", "") or ""
            thumbnail = prog.get("thumbnail") or {}
            image_url = thumbnail.get("src") if thumbnail else None

            # "Abgeschlossen" → veraltete Einträge überspringen
            if "abgeschlossen" in date_str.lower():
                continue

            start_at = _parse_date_as_string(date_str)
            is_permanent = start_at is None

            detail_url = f"{BASE_URL}/programm/{slug}" if slug else EVENTS_URL

            kids = _kids_suitable(title, subtitle)
            indoor_outdoor = _indoor_outdoor(title, subtitle)

            # Build description: subtitle + date hint if permanent
            desc_parts = []
            if subtitle:
                desc_parts.append(subtitle)
            if is_permanent and date_str:
                desc_parts.append(f"Termin: {date_str}")
            desc = " | ".join(desc_parts)[:500] or None

            id_src = (
                f"villahuegel_{slug}_{start_at.date().isoformat()}"
                if start_at
                else f"villahuegel_{slug}"
            )
            canonical_id = hashlib.md5(id_src.encode("utf-8")).hexdigest()[:16]

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
                    "source_url": detail_url,
                    "source_name": "Villa Hügel",
                    "indoor_outdoor": indoor_outdoor,
                    "kids_suitable": kids,
                    "is_permanent_offer": is_permanent,
                    "image_url": image_url,
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Villa Hügel: Fehler bei Programm-Eintrag: %s", exc)
            continue

    logger.info("Villa Hügel: %d Events aus programs extrahiert", len(events))
    return events


async def fetch_villa_huegel_events() -> List[Dict]:
    """Fetch Villa Hügel events from krupp-stiftung.de/veranstaltungen."""
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        try:
            resp = await client.get(EVENTS_URL)
            resp.raise_for_status()
        except Exception as exc:
            logger.error("Villa Hügel: Fehler beim Abrufen: %s", exc)
            return []

        html = resp.text

        # Extract __NEXT_DATA__ JSON blob
        m = re.search(
            r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        )
        if not m:
            logger.error("Villa Hügel: __NEXT_DATA__ nicht gefunden.")
            return []

        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError as exc:
            logger.error("Villa Hügel: __NEXT_DATA__ nicht parsebar: %s", exc)
            return []

        programs = (
            data.get("props", {})
            .get("pageProps", {})
            .get("programs", [])
        )
        if not programs:
            logger.warning("Villa Hügel: programs-Array leer oder nicht vorhanden.")
            return []

        return parse_villa_huegel_programs(programs)


async def sync_villa_huegel(db: Session):
    """Sync Villa Hügel events into the database."""
    events_data = await fetch_villa_huegel_events()
    return sync_events_to_db(db, events_data, "Villa Hügel")
