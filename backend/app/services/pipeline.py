"""Full sync pipeline used by both the manual API and the scheduled job."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.crawl_run import CrawlRun
from app.services.sources_registry import SOURCES, SourceEntry
from app.services.cleanup import (
    archive_past_events,
    purge_old_archives,
    purge_broken_titles,
    merge_existing_cross_source_duplicates,
)
from app.services.distance import calculate_distances
from app.services.geocoder import geocode_event_venue
from app.services.geocode_cache import get_cached_geocode, store_geocode
from app.services.known_venues import find_known_venue
from app.services.weather import apply_weather_to_events
from app.services.quality import recompute_all_quality_scores

logger = logging.getLogger(__name__)


async def run_source_sync(entry: SourceEntry, db: Session) -> dict:
    """Run one source's sync and persist a CrawlRun row.

    Returns a dict summarising the run.
    """
    run = CrawlRun(
        source_name=entry.name,
        started_at=datetime.now(timezone.utc),
        status="running",
    )
    db.add(run)
    db.commit()

    try:
        result = await entry.sync_fn(db)
        # Sources may return either an int (legacy) or a dict.
        if isinstance(result, dict):
            run.items_found = result.get("found", 0)
            run.items_created = result.get("created", 0)
            run.items_updated = result.get("updated", 0)
            run.items_merged = result.get("merged", 0)
            count = run.items_created + run.items_updated
        else:
            count = int(result or 0)
            run.items_found = count
            run.items_created = count  # legacy: don't differentiate

        run.finished_at = datetime.now(timezone.utc)
        run.status = "success"
        db.commit()
        return {"name": entry.name, "count": count, "ok": True}
    except Exception as e:
        run.finished_at = datetime.now(timezone.utc)
        run.status = "error"
        run.error_log = str(e)[:2000]
        db.commit()
        logger.error(f"Sync error for {entry.name}: {e}")
        return {"name": entry.name, "count": 0, "ok": False, "error": str(e)}


async def geocode_pending_events(db: Session, max_nominatim_calls: int = 100) -> int:
    """Resolve coordinates for events without lat/lon.

    1. Try known venues (no network).
    2. Try persistent geocode cache.
    3. Fall back to Nominatim (rate limited, capped).
    """
    pending = (
        db.query(Event)
        .filter((Event.lat.is_(None)) | (Event.lon.is_(None)))
        .filter(Event.archived_at.is_(None))
        .limit(500)
        .all()
    )

    updated = 0
    nominatim_calls = 0

    for event in pending:
        # 1. Known venue fast-path
        known = find_known_venue(event.venue_name or "", event.title or "")
        if known:
            event.lat = known["lat"]
            event.lon = known["lon"]
            if not event.address_text:
                event.address_text = known["address"]
            updated += 1
            continue

        # 2. Cache
        query = f"{event.venue_name or ''}|{event.address_text or ''}|{event.city or 'Essen'}".strip("|")
        if not query:
            continue
        cached = get_cached_geocode(db, query)
        if cached is not None:
            lat, lon = cached
            if lat is not None and lon is not None:
                event.lat = lat
                event.lon = lon
                updated += 1
            continue

        # 3. Nominatim (rate-limited, capped)
        # nominatim_calls zählt pro Event (= ein geocode_event_venue-Aufruf);
        # intern können daraus bis zu 4 Nominatim-HTTP-Requests werden (ein
        # Kandidat pro Versuch). Das Rate-Limit-Sleep (1 s) sitzt in geocoder.py
        # direkt nach jedem HTTP-Call → hier kein zusätzliches Sleep nötig.
        if nominatim_calls >= max_nominatim_calls:
            continue
        nominatim_calls += 1
        try:
            result = await geocode_event_venue(
                event.venue_name,
                event.address_text,
                event.city or "Essen",
            )
        except Exception as e:
            logger.debug(f"Nominatim error: {e}")
            result = None

        if result:
            event.lat, event.lon = result
            store_geocode(db, query, result[0], result[1])
            updated += 1
        else:
            store_geocode(db, query, None, None)

    if updated:
        db.commit()
        logger.info(f"Geocoded {updated} events (Nominatim calls: {nominatim_calls})")
    return updated


async def run_full_sync(db: Session, only_sources: Optional[list[str]] = None) -> dict:
    """Execute every sync step in order and return a structured summary."""
    summary: dict = {"sources": [], "totals": {}}

    sources = SOURCES if not only_sources else [s for s in SOURCES if s.name in only_sources]

    for entry in sources:
        result = await run_source_sync(entry, db)
        summary["sources"].append(result)

    total_count = sum(s["count"] for s in summary["sources"])
    summary["totals"]["events_synced"] = total_count

    # Classification (keyword based)
    try:
        from app.api.events import _apply_classification_to_all  # local import to avoid cycle
        classified = _apply_classification_to_all(db)
        summary["totals"]["classified"] = classified
    except Exception as e:
        logger.error(f"Classification step failed: {e}")
        summary["totals"]["classified_error"] = str(e)

    # Geocoding (known venues → cache → Nominatim)
    try:
        geocoded = await geocode_pending_events(db)
        summary["totals"]["geocoded"] = geocoded
    except Exception as e:
        logger.error(f"Geocoding step failed: {e}")
        summary["totals"]["geocoded_error"] = str(e)

    # Distances
    try:
        dist = calculate_distances(db)
        summary["totals"]["distances"] = dist
    except Exception as e:
        logger.error(f"Distance step failed: {e}")
        summary["totals"]["distances_error"] = str(e)

    # Weather
    try:
        upcoming = (
            db.query(Event)
            .filter(Event.archived_at.is_(None), Event.start_at.isnot(None))
            .all()
        )
        weather_count = await apply_weather_to_events(upcoming, db)
        summary["totals"]["weather"] = weather_count
    except Exception as e:
        logger.error(f"Weather step failed: {e}")
        summary["totals"]["weather_error"] = str(e)

    # Quality score
    try:
        quality = recompute_all_quality_scores(db)
        summary["totals"]["quality_scored"] = quality
    except Exception as e:
        logger.error(f"Quality step failed: {e}")
        summary["totals"]["quality_error"] = str(e)

    # Archive past events
    try:
        archived = archive_past_events(db)
        summary["totals"]["archived"] = archived
    except Exception as e:
        logger.error(f"Archive step failed: {e}")
        summary["totals"]["archived_error"] = str(e)

    # Purge archives older than retention window (default 2 days)
    try:
        purged = purge_old_archives(db)
        summary["totals"]["purged"] = purged
    except Exception as e:
        logger.error(f"Purge step failed: {e}")
        summary["totals"]["purged_error"] = str(e)

    # Purge leftover broken-title rows from the old Rausgegangen parser bug
    try:
        broken = purge_broken_titles(db)
        if broken:
            summary["totals"]["broken_titles_purged"] = broken
    except Exception as e:
        logger.error(f"Broken-title purge failed: {e}")

    # Retroactively merge any cross-source duplicates the base_sync missed
    try:
        merged = merge_existing_cross_source_duplicates(db)
        if merged:
            summary["totals"]["retro_merged"] = merged
    except Exception as e:
        logger.error(f"Retro cross-source merge failed: {e}")

    return summary
