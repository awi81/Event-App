"""Event API endpoints.

The heavy lifting lives in app.services.pipeline. This file is intentionally
thin: it maps query params to a SQL query and delegates sync to the pipeline.
"""
from datetime import datetime, date, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo
import logging

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.models.base import get_db
from app.models.event import Event, KidsSuitable, IndoorOutdoor
from app.models.crawl_run import CrawlRun
from app.schemas.event import EventResponse
from app.services.classifier import apply_classification
from app.services.grouping import group_events
from app.services.pipeline import run_full_sync
from app.services.sources_registry import seed_sources
from app.services.weather import get_weather_for_date
from app.services.robots_check import check_all_sources

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/events", response_model=List[EventResponse])
def get_events(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    category: Optional[str] = Query(None),
    kids_only: bool = Query(False),
    indoor_outdoor: Optional[str] = Query(None),
    max_travel_time: Optional[int] = Query(None),
    time_of_day: Optional[str] = Query(None),
    favorites: Optional[str] = Query(None, description="Comma-separated canonical_ids to filter by"),
    q: Optional[str] = Query(None, description="Free-text search across title/venue/description"),
    sort: str = Query("smart"),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    # Hide archived events AND any past-dated events that aren't permanent offers,
    # so the scheduled archive job's lag doesn't leak yesterday's events into "today".
    now_naive = datetime.now(ZoneInfo("Europe/Berlin")).replace(tzinfo=None)
    query = db.query(Event).filter(Event.archived_at.is_(None))
    query = query.filter(
        or_(
            Event.start_at.is_(None),
            Event.start_at >= now_naive,
            Event.is_permanent_offer == True,  # noqa: E712 (SQLAlchemy)
        )
    )

    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Event.title.ilike(like),
                Event.venue_name.ilike(like),
                Event.short_description.ilike(like),
            )
        )

    if start_date:
        query = query.filter(Event.start_at >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        query = query.filter(Event.start_at <= datetime.combine(end_date, datetime.max.time()))
    if category:
        query = query.filter(Event.category == category)
    if kids_only:
        query = query.filter(Event.kids_suitable.in_([KidsSuitable.yes, KidsSuitable.likely]))
    if indoor_outdoor == "indoor":
        query = query.filter(Event.indoor_outdoor.in_([IndoorOutdoor.indoor, IndoorOutdoor.both]))
    elif indoor_outdoor == "outdoor":
        query = query.filter(Event.indoor_outdoor.in_([IndoorOutdoor.outdoor, IndoorOutdoor.both]))
    if max_travel_time:
        query = query.filter(
            or_(Event.travel_time_minutes <= max_travel_time, Event.travel_time_minutes.is_(None))
        )

    if time_of_day:
        from sqlalchemy import extract
        if time_of_day == "vormittags":
            query = query.filter(extract("hour", Event.start_at) < 12)
        elif time_of_day == "nachmittags":
            query = query.filter(
                extract("hour", Event.start_at) >= 12,
                extract("hour", Event.start_at) < 18,
            )
        elif time_of_day == "abends":
            query = query.filter(extract("hour", Event.start_at) >= 18)

    if favorites:
        ids = [s for s in (favorites or "").split(",") if s]
        if ids:
            query = query.filter(Event.canonical_id.in_(ids))

    # Order DB-side just for predictability; final ordering happens after grouping.
    query = query.order_by(Event.start_at.asc().nullslast())

    # Pull enough rows that grouping can produce `limit` groups even when each
    # event has many occurrences (Theater = up to ~30 per production).
    rows = query.limit(min(limit * 10, 2000)).all()
    grouped = group_events(rows)

    # Apply requested sort across groups
    if sort == "quality":
        grouped.sort(key=lambda g: (-(g["quality_score"] or 0.0), g["start_at"] or datetime.max))
    elif sort == "travel":
        grouped.sort(key=lambda g: ((g["travel_time_minutes"] is None, g["travel_time_minutes"] or 9999), g["start_at"] or datetime.max))
    elif sort == "start_at":
        grouped.sort(key=lambda g: (g["start_at"] is None, g["start_at"] or datetime.max))
    # else: "smart" - keep grouping's natural order (next occurrence asc, quality desc)

    return grouped[:limit]


@router.get("/events/{event_id}", response_model=EventResponse)
def get_event(event_id: int, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event nicht gefunden")

    # Find sibling performances of the same production (same title + source).
    from app.services.grouping import normalise_title

    key = normalise_title(event.title)
    siblings = []
    if key:
        candidates = (
            db.query(Event)
            .filter(
                Event.archived_at.is_(None),
                Event.source_name == event.source_name,
            )
            .all()
        )
        siblings = [c for c in candidates if normalise_title(c.title) == key]

    if not siblings:
        siblings = [event]

    siblings.sort(key=lambda c: (c.start_at is None, c.start_at or datetime.max))

    response = EventResponse.model_validate(event)
    response.occurrences = [
        {
            "id": s.id,
            "start_at": s.start_at,
            "venue_name": s.venue_name,
            "source_url": s.source_url,
            "is_permanent_offer": s.is_permanent_offer,
        }
        for s in siblings
    ]
    return response


@router.post("/events/sync")
async def sync_events(clear_first: bool = Query(False), db: Session = Depends(get_db)):
    """Trigger a sync from all sources via the full pipeline."""
    if clear_first:
        db.query(Event).delete()
        db.commit()
        logger.info("Cleared all events before sync")

    # Make sure the sources table reflects the configured sources.
    try:
        seed_sources(db)
    except Exception as e:
        logger.warning(f"seed_sources failed: {e}")

    summary = await run_full_sync(db)

    details = [
        f"{s['name']}: {s['count']} events" + ("" if s.get("ok") else f" (error: {s.get('error', '?')})")
        for s in summary["sources"]
    ]
    for key, value in summary.get("totals", {}).items():
        details.append(f"{key}: {value}")

    return {"synced": summary["totals"].get("events_synced", 0), "details": details}


@router.get("/admin/sources-health")
def get_sources_health(db: Session = Depends(get_db)):
    """Per-source view: last run, last success, item counts and a status badge.

    Status:
      - "green":  last run was success AND found > 0
      - "yellow": last run was success but found = 0 (source still works but no items)
      - "red":    last run was an error
      - "stale":  no successful run in the last 48h
      - "unknown": no runs at all yet
    """
    from datetime import timedelta
    from app.services.sources_registry import SOURCES

    now = datetime.now(timezone.utc)
    results = []
    for entry in SOURCES:
        # Look at the last 5 runs of this source
        runs = (
            db.query(CrawlRun)
            .filter(CrawlRun.source_name == entry.name)
            .order_by(CrawlRun.started_at.desc())
            .limit(5)
            .all()
        )
        last = runs[0] if runs else None
        last_success = next((r for r in runs if r.status == "success"), None)

        if not last:
            status = "unknown"
        elif last.status == "error":
            status = "red"
        elif last.status == "success" and (last.items_found or 0) == 0:
            status = "yellow"
        elif last.status == "success" and (last.items_found or 0) > 0:
            status = "green"
        else:
            status = "unknown"

        if status in ("green", "yellow") and last_success and last_success.finished_at:
            finished_aware = last_success.finished_at
            if finished_aware.tzinfo is None:
                finished_aware = finished_aware.replace(tzinfo=timezone.utc)
            if (now - finished_aware) > timedelta(hours=48):
                status = "stale"

        # Active events currently attributed to this source
        active_count = (
            db.query(func.count(Event.id))
            .filter(Event.archived_at.is_(None), Event.source_name == entry.name)
            .scalar()
        )

        results.append({
            "source": entry.name,
            "base_url": entry.base_url,
            "source_type": entry.source_type,
            "status": status,
            "active_events": int(active_count or 0),
            "last_run_at": last.started_at.isoformat() if last and last.started_at else None,
            "last_run_status": last.status if last else None,
            "last_run_found": last.items_found if last else None,
            "last_run_error": last.error_log if last else None,
            "last_success_at": last_success.finished_at.isoformat() if last_success and last_success.finished_at else None,
            "last_success_found": last_success.items_found if last_success else None,
            "trend_found": [r.items_found or 0 for r in runs],
        })

    return {"sources": results}


@router.get("/admin/stats")
def get_admin_stats(db: Session = Depends(get_db)):
    """Admin overview: counts, data quality, sources, categories, crawl history."""
    # Single aggregate over events.
    stats = db.query(
        func.count(Event.id).label("total"),
        func.sum(case((Event.archived_at.is_(None), 1), else_=0)).label("active"),
        func.sum(case(((Event.archived_at.is_(None)) & ((Event.lat.is_(None)) | (Event.lon.is_(None))), 1), else_=0)).label("no_coords"),
        func.sum(case(((Event.archived_at.is_(None)) & ((Event.category.is_(None)) | (Event.category == "")), 1), else_=0)).label("no_category"),
        func.sum(case(((Event.archived_at.is_(None)) & (Event.start_at.is_(None)), 1), else_=0)).label("no_date"),
        func.sum(case(((Event.archived_at.is_(None)) & ((Event.short_description.is_(None)) | (Event.short_description == "")), 1), else_=0)).label("no_desc"),
        func.avg(case((Event.archived_at.is_(None), Event.quality_score), else_=None)).label("avg_quality"),
    ).one()

    total = stats.total or 0
    active = int(stats.active or 0)
    archived = total - active

    source_stats = (
        db.query(Event.source_name, func.count(Event.id))
        .filter(Event.archived_at.is_(None))
        .group_by(Event.source_name)
        .all()
    )
    category_stats = (
        db.query(Event.category, func.count(Event.id))
        .filter(Event.archived_at.is_(None))
        .group_by(Event.category)
        .all()
    )

    recent_runs = (
        db.query(CrawlRun)
        .order_by(CrawlRun.started_at.desc())
        .limit(30)
        .all()
    )
    crawl_history = [
        {
            "source": run.source_name,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "status": run.status,
            "items_found": run.items_found,
            "items_created": run.items_created,
            "items_updated": run.items_updated,
            "items_merged": run.items_merged,
            "error": run.error_log,
        }
        for run in recent_runs
    ]

    return {
        "total_events": total,
        "active_events": active,
        "archived_events": archived,
        "average_quality": round(float(stats.avg_quality), 3) if stats.avg_quality is not None else None,
        "sources": {name or "Unbekannt": count for name, count in source_stats},
        "data_quality": {
            "ohne_koordinaten": int(stats.no_coords or 0),
            "ohne_kategorie": int(stats.no_category or 0),
            "ohne_datum": int(stats.no_date or 0),
            "ohne_beschreibung": int(stats.no_desc or 0),
        },
        "categories": {cat or "Keine": count for cat, count in category_stats},
        "crawl_history": crawl_history,
    }


@router.get("/admin/robots-check")
def admin_robots_check():
    """Live-check robots.txt for every configured source."""
    results = check_all_sources()
    return {
        "results": [
            {
                "source": r.source,
                "base_url": r.base_url,
                "robots_url": r.robots_url,
                "fetched": r.fetched,
                "allowed": r.allowed,
                "crawl_delay": r.crawl_delay,
                "excerpt": r.raw_excerpt,
                "error": r.error,
            }
            for r in results
        ]
    }


@router.get("/weather/today")
async def weather_today(db: Session = Depends(get_db)):
    """Return today's weather forecast for Essen (cached in DB)."""
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Europe/Berlin")).date()
    weather = await get_weather_for_date(today, db)
    if not weather:
        return {"available": False}
    return {"available": True, "date": today.isoformat(), **weather}


@router.get("/admin/events-problems")
def get_events_with_problems(
    kind: str = Query("no_coords", description="no_coords | no_date | no_category | no_desc"),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    """Return raw data of events with a specific data-quality issue."""
    query = db.query(Event).filter(Event.archived_at.is_(None))
    if kind == "no_coords":
        query = query.filter((Event.lat.is_(None)) | (Event.lon.is_(None)))
    elif kind == "no_date":
        query = query.filter(Event.start_at.is_(None))
    elif kind == "no_category":
        query = query.filter((Event.category.is_(None)) | (Event.category == ""))
    elif kind == "no_desc":
        query = query.filter((Event.short_description.is_(None)) | (Event.short_description == ""))
    else:
        raise HTTPException(status_code=400, detail="Unbekannter kind-Filter")

    rows = query.order_by(Event.id.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "canonical_id": r.canonical_id,
            "title": r.title,
            "source_name": r.source_name,
            "source_url": r.source_url,
            "venue_name": r.venue_name,
            "city": r.city,
            "start_at": r.start_at.isoformat() if r.start_at else None,
            "category": r.category,
            "lat": r.lat,
            "lon": r.lon,
            "quality_score": r.quality_score,
        }
        for r in rows
    ]


def _apply_classification_to_all(db: Session) -> int:
    """Apply classification to events missing category, indoor_outdoor, or kids_suitable."""
    events = db.query(Event).filter(Event.archived_at.is_(None)).all()

    updated = 0
    for event in events:
        event_data = {
            "title": event.title or "",
            "short_description": event.short_description or "",
            "venue_name": event.venue_name or "",
            "source_name": event.source_name or "",
            "category": event.category,
            "indoor_outdoor": event.indoor_outdoor.value if event.indoor_outdoor else None,
            "kids_suitable": event.kids_suitable.value if event.kids_suitable else None,
        }

        event_data = apply_classification(event_data)

        changed = False
        if event_data.get("category") and not event.category:
            event.category = event_data["category"]
            changed = True
        if event_data.get("indoor_outdoor") and event.indoor_outdoor in (None, IndoorOutdoor.unknown):
            try:
                event.indoor_outdoor = IndoorOutdoor(event_data["indoor_outdoor"])
                changed = True
            except ValueError:
                pass
        if event_data.get("kids_suitable") and event.kids_suitable in (None, KidsSuitable.unknown):
            try:
                event.kids_suitable = KidsSuitable(event_data["kids_suitable"])
                changed = True
            except ValueError:
                pass

        if changed:
            updated += 1

    db.commit()
    logger.info(f"Classified {updated} events")
    return updated
