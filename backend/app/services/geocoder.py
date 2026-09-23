"""
Geocoding Service - Convert addresses to coordinates using Nominatim (OpenStreetMap)
"""

import asyncio
import logging
import os
import re

import httpx
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Nominatim base URL (free, no API key required)
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Default coordinates for Essen if geocoding fails
ESSEN_CENTER = (51.4556, 7.0116)

# Nominatim Usage Policy requires identifying contact in User-Agent.
# https://operations.osmfoundation.org/policies/nominatim/
_CONTACT = os.getenv("NOMINATIM_CONTACT", "your-email@example.com")
if _CONTACT == "your-email@example.com":
    logger.warning("NOMINATIM_CONTACT ist nicht gesetzt — bitte als Umgebungsvariable oder GitHub-Secret eintragen.")
NOMINATIM_USER_AGENT = f"Event-App-Essen/1.0 (+{_CONTACT})"


# Every source covers the Ruhr area around Essen. A hit outside this box is a
# namesake: venue "Essen" resolved to Essen (Oldenburg), 160 km north.
_REGION = {"south": 51.0, "north": 51.9, "west": 6.3, "east": 7.9}


def in_region(lat: float, lon: float) -> bool:
    return _REGION["south"] <= lat <= _REGION["north"] and _REGION["west"] <= lon <= _REGION["east"]


class GeocodeUnavailable(Exception):
    """Nominatim did not answer properly (429/5xx/timeout). Not a "not found":
    callers must not cache this as a negative result."""


# Nominatim policy: at most one request per second, across the whole process.
_last_call_at = 0.0
_call_lock = asyncio.Lock()


async def _throttle() -> None:
    global _last_call_at
    async with _call_lock:
        loop = asyncio.get_running_loop()
        wait = _last_call_at + 1.0 - loop.time()
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_at = loop.time()


_VENUE_NOISE_RE = re.compile(r"\s*\([^)]*\)|\s+[-–•|]\s+.*$|[\"„“”]")


def clean_venue_name(venue_name: str) -> str:
    """"Anneliese Brost Musikforum Ruhr (Großer Saal)" -> "Anneliese Brost Musikforum Ruhr",
    "Alleato Arena - Heimat der Füchse" -> "Alleato Arena". Nominatim's free-text
    search fails on hall/room suffixes and slogans."""
    return " ".join(_VENUE_NOISE_RE.sub("", venue_name or "").split())


async def geocode_address(address: str, city: str = "Essen") -> Optional[Tuple[float, float]]:
    """
    Geocode an address to lat/lon coordinates.
    Returns (lat, lon) tuple or None if not found.
    """
    if not address:
        return None

    # Build search query
    query = f"{address}, {city}, Germany"

    await _throttle()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                NOMINATIM_URL,
                params={
                    "q": query,
                    "format": "json",
                    "limit": 1,
                    "addressdetails": 0,
                    "viewbox": f"{_REGION['west']},{_REGION['north']},{_REGION['east']},{_REGION['south']}",
                    "bounded": 1,
                },
                headers={
                    "User-Agent": NOMINATIM_USER_AGENT,
                }
            )
    except httpx.HTTPError as exc:
        raise GeocodeUnavailable(f"{type(exc).__name__}: {exc}") from exc

    if response.status_code != 200:
        # 429/403 = we are being throttled, 5xx = their problem; either way
        # this says nothing about the address.
        raise GeocodeUnavailable(f"HTTP {response.status_code}")
    try:
        data = response.json()
        if data:
            lat, lon = float(data[0]["lat"]), float(data[0]["lon"])
            return (lat, lon) if in_region(lat, lon) else None
    except (ValueError, KeyError, TypeError) as exc:
        raise GeocodeUnavailable(f"bad payload: {exc}") from exc
    return None


async def geocode_event_venue(venue_name: Optional[str], address_text: Optional[str], city: str = "Essen") -> Optional[Tuple[float, float]]:
    """
    Try to geocode an event's venue/address.
    Tries multiple combinations to find the best match.
    """
    # Build list of address candidates to try (geocode_address appends
    # ", {city}, Germany" itself). Raises GeocodeUnavailable on service errors.
    candidates: list[str] = []
    cleaned = clean_venue_name(venue_name or "")
    if cleaned.lower() == (city or "").lower():
        # Venue "Essen" in city Essen says nothing about the place.
        venue_name, cleaned = None, ""

    # A street address with a house number beats a bare venue name: "Zentrum
    # 60plus, Essen" resolves to one of several houses of that name across the
    # city, "Heckstraße 27, Essen" to the right one. Vague addresses without a
    # number stay last so they don't win with a city/district centroid.
    precise_address = bool(address_text and re.search(r"\d", address_text))

    if venue_name and address_text:
        candidates.append(f"{venue_name}, {address_text}")
    if precise_address:
        candidates.append(address_text)
    if venue_name:
        candidates.append(venue_name)
    if cleaned and cleaned.lower() != (venue_name or "").lower():
        candidates.append(cleaned)
    if address_text and not precise_address:
        candidates.append(address_text)

    seen: set[str] = set()
    for query in candidates:
        if query.lower() in seen:
            continue
        seen.add(query.lower())
        result = await geocode_address(query, city)
        if result:
            return result

    return None
