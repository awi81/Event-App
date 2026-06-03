"""Distance and travel time calculation from Essen Werden."""
import math
from sqlalchemy.orm import Session
import logging

from app.models.event import Event

logger = logging.getLogger(__name__)

# Essen Werden center coordinates
ESSEN_WERDEN_LAT = 51.3833
ESSEN_WERDEN_LON = 7.0333


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in km using Haversine formula."""
    R = 6371  # Earth radius in km

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.asin(math.sqrt(a))

    return R * c


def estimate_travel_time(distance_km: float) -> int:
    """
    Estimate car travel time in minutes.
    Uses conservative factor for Ruhrgebiet urban driving.
    """
    if distance_km <= 0:
        return 0
    # Base: 5 min (parking etc.) + distance * factor
    # ~30 km/h average in urban Ruhrgebiet
    minutes = 5 + (distance_km / 30) * 60
    return round(minutes)


def calculate_distances(db: Session) -> int:
    """Calculate distance and travel time for all events with coordinates."""
    events = db.query(Event).filter(
        Event.lat.isnot(None),
        Event.lon.isnot(None),
        Event.archived_at.is_(None),
        (Event.distance_km.is_(None)) | (Event.travel_time_minutes.is_(None)),
    ).all()

    updated = 0
    for event in events:
        dist = haversine_km(ESSEN_WERDEN_LAT, ESSEN_WERDEN_LON, event.lat, event.lon)
        travel = estimate_travel_time(dist)

        event.distance_km = round(dist, 1)
        event.travel_time_minutes = travel
        updated += 1

    if updated:
        db.commit()
        logger.info(f"Calculated distances for {updated} events")

    return updated
