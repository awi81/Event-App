"""Persistent geocoding cache backed by the geocode_cache table."""
from typing import Optional, Tuple
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.models.cache import GeocodeCache


# Negative results expire faster so a flaky Nominatim call doesn't get stuck.
POSITIVE_TTL = timedelta(days=180)
NEGATIVE_TTL = timedelta(days=14)


def _normalize(query: str) -> str:
    return " ".join(query.strip().lower().split())[:500]


def get_cached_geocode(db: Session, query: str) -> Optional[Tuple[Optional[float], Optional[float]]]:
    """Return (lat, lon) if cached and fresh. (None, None) for cached miss.
    Returns None if no cache entry exists or it expired."""
    key = _normalize(query)
    if not key:
        return None
    row = db.query(GeocodeCache).filter(GeocodeCache.query == key).first()
    if not row:
        return None
    if not row.fetched_at:
        return None
    fetched_at = row.fetched_at
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - fetched_at
    is_positive = row.lat is not None and row.lon is not None
    ttl = POSITIVE_TTL if is_positive else NEGATIVE_TTL
    if age > ttl:
        return None
    return (row.lat, row.lon)


def store_geocode(db: Session, query: str, lat: Optional[float], lon: Optional[float]) -> None:
    key = _normalize(query)
    if not key:
        return
    row = db.query(GeocodeCache).filter(GeocodeCache.query == key).first()
    now = datetime.now(timezone.utc)
    if row:
        row.lat = lat
        row.lon = lon
        row.fetched_at = now
    else:
        db.add(GeocodeCache(query=key, lat=lat, lon=lon, fetched_at=now))
    db.commit()
