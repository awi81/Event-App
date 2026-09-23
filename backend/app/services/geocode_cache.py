"""Persistent geocoding cache backed by the geocode_cache table."""
from typing import Optional, Tuple
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.models.cache import GeocodeCache
from app.services.geocoder import in_region


# Negative results expire faster so a flaky Nominatim answer doesn't get stuck
# (an empty result list happens under load, too).
POSITIVE_TTL = timedelta(days=180)
NEGATIVE_TTL = timedelta(days=3)


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
    if is_positive and not in_region(row.lat, row.lon):
        return None  # namesake hit from before the region check: look it up again
    return (row.lat, row.lon)


def export_cache(db: Session) -> list[dict]:
    """All still-fresh cache rows as plain dicts (for the committed snapshot).

    The GitHub-Actions crawler starts with an empty DB every run; without this
    the 100-calls-per-run Nominatim budget would re-geocode the same venues
    forever and most events would never get coordinates.
    """
    now = datetime.now(timezone.utc)
    rows: list[dict] = []
    for row in db.query(GeocodeCache).all():
        if not row.fetched_at:
            continue
        fetched_at = row.fetched_at
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        is_positive = row.lat is not None and row.lon is not None
        if now - fetched_at > (POSITIVE_TTL if is_positive else NEGATIVE_TTL):
            continue
        rows.append(
            {"query": row.query, "lat": row.lat, "lon": row.lon, "fetched_at": fetched_at.isoformat()}
        )
    rows.sort(key=lambda r: r["query"])
    return rows


def import_cache(db: Session, rows: list[dict]) -> int:
    """Seed the cache table from exported rows; existing entries win. Returns inserted count."""
    inserted = 0
    for r in rows:
        key = _normalize(str(r.get("query") or ""))
        if not key:
            continue
        try:
            fetched_at = datetime.fromisoformat(str(r.get("fetched_at")))
        except (TypeError, ValueError):
            continue
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        lat, lon = r.get("lat"), r.get("lon")
        if lat is not None and lon is not None and not in_region(lat, lon):
            continue
        if db.query(GeocodeCache).filter(GeocodeCache.query == key).first():
            continue
        db.add(GeocodeCache(query=key, lat=r.get("lat"), lon=r.get("lon"), fetched_at=fetched_at))
        inserted += 1
    db.commit()
    return inserted


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
