"""Export a static snapshot (``events.json`` + ``weather.json``) for the static
GitHub-Pages build of the Event-App.

This reuses the *live* code paths verbatim so the static client receives the
exact same data semantics as the running API:

  * :func:`app.services.pipeline.run_full_sync` -- the same pipeline the manual
    ``POST /events/sync`` endpoint and the 12h scheduler run.
  * :func:`app.services.grouping.group_events` -- the exact grouping that
    ``GET /events`` applies (one card per production with ``occurrences[]``).
  * :class:`app.schemas.event.EventResponse` -- the exact response schema
    ``GET /events`` serialises, including every derived field (quality_score,
    distance_km, travel_time_minutes, source_count, sources_list, image_url,
    kids_suitable, indoor_outdoor, is_permanent_offer, is_all_day, age_note,
    weather_note, occurrences[]). The browser cannot recompute these (no DB,
    no Haversine origin), so they must be baked in.

Time-relative logic is deliberately **not** applied here. The export ships all
upcoming + permanent events (the same base filter ``GET /events`` uses, minus
the today/tomorrow/weekend narrowing) and lets the browser decide
past-vs-future from the visitor's clock at render time. ``start_at`` stays
local-naive (Europe/Berlin) so ``new Date(localISO)`` parses as local time in
the browser -- we never mix in a ``Z`` suffix.

Output is deterministic and minified (sorted keys, events ordered by the
clock-independent ``canonical_id``, ``separators=(",", ":")``,
``ensure_ascii=False``) so unchanged crawls produce no diff and therefore no
commit.

Usage (run from ``backend/``)::

    python -m app.scripts.export_snapshot                 # full sync, then export
    python -m app.scripts.export_snapshot --no-sync       # export current DB as-is
    python -m app.scripts.export_snapshot --sources Grugapark,borbeck.de
    python -m app.scripts.export_snapshot --out ../frontend/public/data
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("export_snapshot")

BERLIN = ZoneInfo("Europe/Berlin")

# .../backend/app/scripts/export_snapshot.py -> parents[3] == repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_OUT = _REPO_ROOT / "frontend" / "public" / "data"


def _collect_event_rows(db, limit: int):
    """Pull all upcoming + permanent (+ undated) active events.

    Mirrors the base filter of ``GET /events`` exactly, but without the
    date-range / category / search narrowing -- the client applies those
    client-side against the visitor's clock. The ``>= now`` bound only keeps
    the dataset from carrying genuinely-past rows; events that pass between
    export and page-load are re-hidden client-side.
    """
    from sqlalchemy import or_

    from app.models.event import Event

    now_naive = datetime.now(BERLIN).replace(tzinfo=None)
    query = (
        db.query(Event)
        .filter(Event.archived_at.is_(None))
        .filter(
            or_(
                Event.start_at.is_(None),
                Event.start_at >= now_naive,
                Event.is_permanent_offer == True,  # noqa: E712 (SQLAlchemy needs ==)
            )
        )
        .order_by(Event.start_at.asc().nullslast())
    )
    if limit:
        query = query.limit(limit)
    return query.all()


def _build_events_payload(rows) -> list[dict]:
    """Group + serialise rows through the exact ``GET /events`` code path.

    ``now=datetime.min`` makes group_events pick the earliest occurrence as the
    group representative instead of the wall-clock-relative "next upcoming" one,
    so the headline fields (and the canonical_id we sort by) don't flip between
    runs as occurrences pass their start time. The client recomputes the real
    next-upcoming from occurrences[] (migration plan, B4), so a stable headline
    is fine here and keeps identical crawls byte-identical (no spurious commit).
    """
    from app.schemas.event import EventResponse
    from app.services.grouping import group_events

    grouped = group_events(rows, now=datetime.min)
    events = []
    for g in grouped:
        e = EventResponse.model_validate(g).model_dump(mode="json")
        # created_at is a per-insert timestamp; on the fresh-DB CI runner it is
        # now() for every row on every run, which would churn the committed diff
        # endlessly. The static client never uses it (generated_at covers "when").
        e.pop("created_at", None)
        events.append(e)
    # Deterministic, clock-independent order so identical crawls produce no diff.
    events.sort(key=lambda e: e["canonical_id"])
    return events


async def _build_weather_today(db) -> dict:
    """Today's Essen forecast, shaped like the ``GET /weather/today`` response
    so the static ``WeatherBanner`` can consume it 1:1."""
    from app.services.weather import get_weather_for_date

    today = datetime.now(BERLIN).date()
    weather = await get_weather_for_date(today, db)
    if not weather:
        return {"available": False}
    return {"available": True, "date": today.isoformat(), **weather}


def _write_json(path: Path, payload: dict) -> int:
    """Write a deterministic, minified JSON file. Returns the byte size.

    ``allow_nan=False`` makes a stray NaN/Infinity float (e.g. a malformed
    geocode) raise here instead of emitting the bare ``NaN``/``Infinity`` tokens,
    which are not valid JSON and would make the browser's JSON.parse reject the
    whole file. The live ``GET /events`` path (Starlette) fails loud on NaN the
    same way, so this keeps parity.
    """
    text = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False
    )
    path.write_text(text + "\n", encoding="utf-8")
    return len(text.encode("utf-8")) + 1


async def export_snapshot(
    out_dir,
    do_sync: bool,
    only_sources: Optional[list[str]],
    limit: int,
) -> dict:
    """Run the (optional) sync, then write events.json + weather.json."""
    from app.models import base as db_base

    db_base.init_db()
    if db_base.SessionLocal is None:
        raise RuntimeError("DB not initialised: init_db() produced no SessionLocal")

    db = db_base.SessionLocal()
    try:
        if do_sync:
            # Imported lazily: pulls in the parser/Playwright chain, which we
            # don't want to require for a plain --no-sync export.
            from app.services.pipeline import run_full_sync
            from app.services.sources_registry import seed_sources

            try:
                seed_sources(db)
            except Exception as e:  # non-fatal: admin names only
                logger.warning("seed_sources failed: %s", e)
            logger.info("Running full sync%s ...", f" ({', '.join(only_sources)})" if only_sources else "")
            summary = await run_full_sync(db, only_sources=only_sources)
            logger.info("Sync totals: %s", summary.get("totals"))

        rows = _collect_event_rows(db, limit)
        if limit and len(rows) == limit:
            logger.warning(
                "Row cap of %d hit -- the dataset may be truncated (far-future + "
                "undated rows dropped first). Re-run with --limit 0 to ship everything.",
                limit,
            )
        events = _build_events_payload(rows)
        weather_today = await _build_weather_today(db)
    finally:
        db.close()

    generated_at = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "generated_at": generated_at,
        "weather_today": weather_today,
        "events": events,
    }

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    events_file = out_path / "events.json"
    weather_file = out_path / "weather.json"
    events_bytes = _write_json(events_file, snapshot)
    # Standalone weather file (referenced by the migration plan's committed-file
    # list); the client reads weather_today from the events.json wrapper.
    weather_bytes = _write_json(
        weather_file, {"generated_at": generated_at, "weather_today": weather_today}
    )

    return {
        "events_path": str(events_file),
        "weather_path": str(weather_file),
        "event_count": len(events),
        "occurrence_count": sum(len(e.get("occurrences") or []) for e in events),
        "events_bytes": events_bytes,
        "weather_bytes": weather_bytes,
        "weather_available": bool(weather_today.get("available")),
        "generated_at": generated_at,
    }


def _parse_args(argv) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export a static events/weather snapshot.")
    p.add_argument(
        "--out",
        default=str(_DEFAULT_OUT),
        help="Output directory (default: <repo>/frontend/public/data)",
    )
    p.add_argument(
        "--no-sync",
        dest="sync",
        action="store_false",
        help="Skip the pipeline and export the current DB as-is",
    )
    p.add_argument(
        "--sources",
        default=None,
        help="Comma-separated source names to sync (default: all). Implies a sync.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max event rows to pull before grouping (0 = no limit, the default; "
        "ships the complete upcoming + permanent set as the spec requires)",
    )
    p.set_defaults(sync=True)
    return p.parse_args(argv)


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    only_sources = (
        [s.strip() for s in args.sources.split(",") if s.strip()] if args.sources else None
    )
    do_sync = args.sync or bool(only_sources)

    result = asyncio.run(export_snapshot(args.out, do_sync, only_sources, args.limit))

    logger.info(
        "Wrote %d events (%d occurrences) -> %s (%.1f KiB); weather available=%s -> %s",
        result["event_count"],
        result["occurrence_count"],
        result["events_path"],
        result["events_bytes"] / 1024,
        result["weather_available"],
        result["weather_path"],
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
