"""
Geocoding Service - Convert addresses to coordinates using Nominatim (OpenStreetMap)
"""

import asyncio
import logging
import os
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


async def geocode_address(address: str, city: str = "Essen") -> Optional[Tuple[float, float]]:
    """
    Geocode an address to lat/lon coordinates.
    Returns (lat, lon) tuple or None if not found.
    """
    if not address:
        return None

    # Build search query
    query = f"{address}, {city}, Germany"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                NOMINATIM_URL,
                params={
                    "q": query,
                    "format": "json",
                    "limit": 1,
                    "addressdetails": 0
                },
                headers={
                    "User-Agent": NOMINATIM_USER_AGENT,
                }
            )

            if response.status_code == 200:
                data = response.json()
                if data and len(data) > 0:
                    lat = float(data[0]["lat"])
                    lon = float(data[0]["lon"])
                    return (lat, lon)
    except Exception:
        pass

    return None


async def geocode_event_venue(venue_name: Optional[str], address_text: Optional[str], city: str = "Essen") -> Optional[Tuple[float, float]]:
    """
    Try to geocode an event's venue/address.
    Tries multiple combinations to find the best match.
    """
    # Build list of address candidates to try
    candidates = []

    if venue_name and address_text:
        candidates.append(f"{venue_name}, {address_text}")
    if venue_name:
        candidates.append(f"{venue_name}, {city}")
    if address_text:
        candidates.append(f"{address_text}, {city}")
    if venue_name:
        candidates.append(f"{venue_name}, Essen, Germany")

    # Try each candidate
    for query in candidates:
        result = await geocode_address(query, city)
        if result:
            return result
        # Rate limit: Nominatim requires 1 second between requests
        await asyncio.sleep(1)

    return None
