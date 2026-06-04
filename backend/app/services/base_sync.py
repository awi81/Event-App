"""Shared sync logic for all event sources.

Responsibilities:
- Upsert events by canonical_id (parameterized SQL).
- Detect cross-source duplicates with a fuzzy title match on the same day.
- Track multi-source confirmations on the surviving Event row.
- Return structured stats per sync (found/created/updated/merged).
"""
from datetime import datetime, timedelta
import logging
import re
import unicodedata
from zoneinfo import ZoneInfo

from sqlalchemy import String, text, func
from sqlalchemy.orm import Session

from app.models.event import Event

# VARCHAR limits from the Event model. Values are clamped before insert/update
# so a single oversized field (e.g. a long Lichtburg price_text) cannot fail
# the row with StringDataRightTruncation.
_STRING_LIMITS: dict[str, int] = {
    col.name: col.type.length
    for col in Event.__table__.columns
    if type(col.type) is String and col.type.length is not None
}


def _clamp_string_fields(event_data: dict) -> None:
    """Truncate string values that exceed their column's VARCHAR limit."""
    for key, limit in _STRING_LIMITS.items():
        value = event_data.get(key)
        if isinstance(value, str) and len(value) > limit:
            event_data[key] = value[:limit].rstrip()

_BERLIN = ZoneInfo("Europe/Berlin")


def to_berlin_naive(dt) -> "datetime | None":
    """Convert a datetime to Europe/Berlin wall-clock time, then strip tzinfo.

    The DB column start_at is tz-naive and stores Berlin local time.
    - tz-aware input  → convert to Berlin, drop tzinfo
    - tz-naive input  → assumed already Berlin local, returned unchanged
    - None            → returned as None
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(_BERLIN).replace(tzinfo=None)
    return dt

logger = logging.getLogger(__name__)

# Invisible / format characters that some upstream pages embed inside titles
# (Theater Essen uses Soft Hyphens for line-break hints). They make titles
# look ugly in the UI and break Jaccard similarity-based dedup.
_INVISIBLE_CHARS = re.compile(
    r"[­​‌‍⁠﻿]"  # soft hyphen, zero-width family, BOM
)


def sanitize_title(title: str | None) -> str | None:
    if not title:
        return title
    cleaned = _INVISIBLE_CHARS.sub("", title)
    # Collapse runs of whitespace that might be left behind.
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None

# Words ignored when comparing titles (German + venue-style noise).
_TITLE_STOPWORDS = {
    "der", "die", "das", "den", "dem", "und", "oder", "mit", "im", "in", "ein",
    "eine", "einen", "einem", "auf", "an", "am", "von", "vom", "zur", "zum",
    "bei", "für", "fuer", "&", "-", "–", "—", "presents",
}


def _normalize_title(title: str) -> str:
    if not title:
        return ""
    # Strip invisible chars first, then NFKC-normalize so 'café' == 'café'.
    s = _INVISIBLE_CHARS.sub("", title)
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"[^\wäöüß ]+", " ", s, flags=re.UNICODE)
    tokens = [t for t in s.split() if t and t not in _TITLE_STOPWORDS]
    return " ".join(tokens)


def _title_similarity(a: str, b: str) -> float:
    """Jaccard similarity over normalised tokens."""
    ta = set(_normalize_title(a).split())
    tb = set(_normalize_title(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _find_cross_source_duplicate(
    db: Session, title: str, start_at, source_name: str
) -> Event | None:
    """Find an event from another source on the same day with a similar title.

    Same-day window is +/- 12h to absorb timezone slips in upstream feeds.
    """
    if not title or not start_at:
        return None

    window_start = start_at - timedelta(hours=12)
    window_end = start_at + timedelta(hours=12)
    candidates = (
        db.query(Event)
        .filter(
            Event.start_at >= window_start,
            Event.start_at <= window_end,
            Event.source_name != source_name,
            Event.archived_at.is_(None),
        )
        .all()
    )
    for cand in candidates:
        if _title_similarity(title, cand.title or "") >= 0.6:
            return cand
    return None


def _record_additional_source(event: Event, source_name: str, source_url: str | None) -> bool:
    """Bump source_count and append the source name. Returns True if changed."""
    current = (event.sources_list or "").split(",") if event.sources_list else []
    current = [s.strip() for s in current if s.strip()]
    if event.source_name and event.source_name not in current:
        current.insert(0, event.source_name)
    if source_name in current:
        return False
    current.append(source_name)
    event.sources_list = ",".join(current)
    event.source_count = len(current)
    return True


def sync_events_to_db(db: Session, events_data: list[dict], source_name: str) -> dict:
    """Upsert events and return stats: {found, created, updated, merged}."""
    # Deduplicate within batch
    seen_ids: set[str] = set()
    unique_events: list[dict] = []
    for event in events_data:
        cid = event.get("canonical_id")
        if cid and cid not in seen_ids:
            seen_ids.add(cid)
            unique_events.append(event)

    found = len(unique_events)
    created = 0
    updated = 0
    merged = 0

    # Commit per event: a failing row only rolls back itself, never the
    # already-persisted rest of the batch (a shared-transaction rollback once
    # wiped almost the whole Lichtburg sync because of one oversized field).
    for event_data in unique_events:
        try:
            canonical_id = event_data["canonical_id"]
            event_data.setdefault("source_name", source_name)
            # Strip soft hyphens / zero-width chars from titles + venue names so
            # the UI is clean and cross-source dedup actually matches.
            if "title" in event_data:
                event_data["title"] = sanitize_title(event_data["title"])
            if "venue_name" in event_data:
                event_data["venue_name"] = sanitize_title(event_data["venue_name"])
            _clamp_string_fields(event_data)

            existing = db.execute(
                text("SELECT id FROM events WHERE canonical_id = :cid"),
                {"cid": canonical_id},
            ).fetchone()

            if existing:
                set_clauses = []
                params = {"canonical_id": canonical_id}
                for key, value in event_data.items():
                    if value is not None and hasattr(Event, key) and key != "canonical_id":
                        set_clauses.append(f"{key} = :{key}")
                        params[key] = value
                if set_clauses:
                    db.execute(
                        text(
                            f"UPDATE events SET {', '.join(set_clauses)} "
                            f"WHERE canonical_id = :canonical_id"
                        ),
                        params,
                    )
                db.commit()
                updated += 1
                continue

            # Look for a cross-source duplicate before inserting.
            cross = _find_cross_source_duplicate(
                db, event_data.get("title", ""), event_data.get("start_at"), source_name
            )
            if cross is not None:
                changed = _record_additional_source(
                    cross, source_name, event_data.get("source_url")
                )
                if changed:
                    db.add(cross)
                    db.commit()
                    merged += 1
                continue

            columns = [k for k in event_data.keys() if hasattr(Event, k)]
            placeholders = [f":{c}" for c in columns]
            params = {c: event_data[c] for c in columns}
            params.setdefault("source_count", 1)
            if "source_count" not in columns:
                columns.append("source_count")
                placeholders.append(":source_count")
            db.execute(
                text(
                    f"INSERT INTO events ({', '.join(columns)}) "
                    f"VALUES ({', '.join(placeholders)})"
                ),
                params,
            )
            db.commit()
            created += 1
        except Exception as e:
            logger.warning(
                f"Error syncing event from {source_name}: "
                f"{event_data.get('title', 'unknown')[:60]}: {e}"
            )
            try:
                db.rollback()
            except Exception:
                pass
            continue

    try:
        db.commit()  # close any open read-only transaction
    except Exception as e:
        logger.error(f"Final commit failed for {source_name}: {e}")
        db.rollback()

    logger.info(
        f"Sync {source_name}: found={found} created={created} updated={updated} merged={merged}"
    )
    return {
        "found": found,
        "created": created,
        "updated": updated,
        "merged": merged,
    }
