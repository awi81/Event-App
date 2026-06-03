"""Cleanup service - archive past events automatically, hard-delete old archives."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import logging
import os
import re

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import base as db_base
from app.models.event import Event

logger = logging.getLogger(__name__)

BERLIN = ZoneInfo("Europe/Berlin")

# Archived events older than this are permanently removed from the DB.
ARCHIVE_RETENTION_DAYS = int(os.getenv("ARCHIVE_RETENTION_DAYS", "2"))


def now_berlin() -> datetime:
    """Current time in Europe/Berlin."""
    return datetime.now(BERLIN)


def archive_past_events(db: Session | None = None) -> int:
    """Archive events whose start_at is in the past (Berlin time).
    Skips permanent offers (is_permanent_offer=True).
    """
    close_after = False
    if db is None:
        if db_base.SessionLocal is None:
            logger.warning("DB not initialized, skipping cleanup")
            return 0
        db = db_base.SessionLocal()
        close_after = True

    try:
        now = now_berlin().replace(tzinfo=None)  # DB stores naive datetimes

        archived = (
            db.query(Event)
            .filter(
                Event.archived_at.is_(None),
                Event.start_at.isnot(None),
                Event.start_at < now,
                (Event.is_permanent_offer == False) | (Event.is_permanent_offer.is_(None)),
            )
            .update(
                {"archived_at": now},
                synchronize_session="fetch",
            )
        )

        db.commit()
        if archived:
            logger.info(f"Archived {archived} past events (Berlin time: {now})")
        return archived
    except Exception as e:
        logger.error(f"Cleanup error: {e}")
        db.rollback()
        return 0
    finally:
        if close_after:
            db.close()


# Titles that contain a date header glued together with venue/price text are
# leftovers from a buggy Rausgegangen parser. Common prefixes seen in the wild:
#   "Sa, 30. Mai | 10:00..."           - plain date prefix
#   "5Di, 12. Mai | 18:00..."          - like-counter glued in front
#   "TAGESTIPP22Mo, 01. Jun | 19:00..." - label + counter glued in front
#   "PRÄSENTIERT8Fr, 26. Jun | 16:00..." - sponsorship label + counter
# We match the date pattern anywhere in the title — that's strong evidence
# the title was assembled from raw page text, not extracted properly.
_BROKEN_TITLE_RE = re.compile(
    r'(?:^|TAGESTIPP|PRÄSENTIERT|VERLOSUNG)\s*\d{0,4}\s*'
    r'(?:Mo|Di|Mi|Do|Fr|Sa|So|Heute|Morgen|Übermorgen)[,\s]\s*\d{1,2}\.\s*'
    r'(?:Jan|Feb|Mär|Apr|Mai|Jun|Jul|Aug|Sep|Okt|Nov|Dez)\w*\s*\|\s*\d{1,2}:\d{2}',
    re.IGNORECASE,
)


def purge_broken_titles(db: Session | None = None) -> int:
    """Delete events whose title still looks like a leftover date header."""
    close_after = False
    if db is None:
        if db_base.SessionLocal is None:
            return 0
        db = db_base.SessionLocal()
        close_after = True

    try:
        # Two SQL prefixes are common: glued or with comma+space. Use LIKE so
        # this works on SQLite (tests) and Postgres alike, then fine-filter in
        # Python using the regex.
        # Pull every active row and let the regex pick the bad ones - the LIKE
        # short-list missed digit-prefixed titles like "5Di, 12. Mai | ...".
        candidates = db.query(Event).all()
        broken_ids = [
            c.id for c in candidates if _BROKEN_TITLE_RE.search(c.title or "")
        ]
        if not broken_ids:
            return 0
        deleted = (
            db.query(Event)
            .filter(Event.id.in_(broken_ids))
            .delete(synchronize_session=False)
        )
        db.commit()
        logger.info(f"Purged {deleted} events with broken titles (date prefix)")
        return deleted
    except Exception as e:
        logger.error(f"Broken-title purge error: {e}")
        db.rollback()
        return 0
    finally:
        if close_after:
            db.close()


def merge_existing_cross_source_duplicates(db: Session | None = None) -> int:
    """One-shot retroactive cross-source dedup.

    The base_sync cross-source merge only fires on INSERT, so events that were
    already in the DB before the dedup logic improved stay duplicated. Iterate
    over active events and merge pairs with similar titles (Jaccard >= 0.6) and
    start_at within a 12h window but DIFFERENT source_name.

    Keeps the event with higher source_count (or lower id as tiebreaker) and
    appends the other source_name to its sources_list.
    """
    from app.services.base_sync import _title_similarity

    close_after = False
    if db is None:
        if db_base.SessionLocal is None:
            return 0
        db = db_base.SessionLocal()
        close_after = True

    try:
        events = (
            db.query(Event)
            .filter(Event.archived_at.is_(None), Event.start_at.isnot(None))
            .order_by(Event.start_at)
            .all()
        )

        merged_count = 0
        to_delete: set[int] = set()

        for i, a in enumerate(events):
            if a.id in to_delete:
                continue
            for b in events[i + 1:]:
                if b.id in to_delete:
                    continue
                if a.source_name == b.source_name:
                    continue
                # start_at must be within 12h
                if abs((a.start_at - b.start_at).total_seconds()) > 12 * 3600:
                    # events are sorted by start_at, so once b is too far in
                    # the future we can stop comparing a to anything later.
                    if b.start_at > a.start_at:
                        break
                    continue
                if _title_similarity(a.title or "", b.title or "") < 0.6:
                    continue

                # Decide which one to keep
                keep, drop = (a, b) if (a.source_count or 1) >= (b.source_count or 1) else (b, a)

                # Append the dropped source to the keeper's sources_list
                current = (keep.sources_list or "").split(",") if keep.sources_list else []
                current = [s.strip() for s in current if s.strip()]
                if keep.source_name and keep.source_name not in current:
                    current.insert(0, keep.source_name)
                if drop.source_name and drop.source_name not in current:
                    current.append(drop.source_name)
                keep.sources_list = ",".join(current)
                keep.source_count = len(current)

                to_delete.add(drop.id)
                merged_count += 1

        if to_delete:
            db.query(Event).filter(Event.id.in_(to_delete)).delete(synchronize_session=False)
        db.commit()
        if merged_count:
            logger.info(f"Retroactive cross-source merge: {merged_count} duplicates collapsed")
        return merged_count
    except Exception as e:
        logger.error(f"Retroactive merge error: {e}")
        db.rollback()
        return 0
    finally:
        if close_after:
            db.close()


def purge_old_archives(db: Session | None = None, retention_days: int | None = None) -> int:
    """Hard-delete events that have been archived for more than `retention_days`.

    Default retention is `ARCHIVE_RETENTION_DAYS` (env-configurable, default 2 days).
    Returns the number of deleted rows.
    """
    if retention_days is None:
        retention_days = ARCHIVE_RETENTION_DAYS

    close_after = False
    if db is None:
        if db_base.SessionLocal is None:
            logger.warning("DB not initialized, skipping purge")
            return 0
        db = db_base.SessionLocal()
        close_after = True

    try:
        cutoff = now_berlin().replace(tzinfo=None) - timedelta(days=retention_days)

        deleted = (
            db.query(Event)
            .filter(Event.archived_at.isnot(None), Event.archived_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
        if deleted:
            logger.info(
                f"Purged {deleted} archived events older than {retention_days} days "
                f"(cutoff: {cutoff})"
            )
        return deleted
    except Exception as e:
        logger.error(f"Purge error: {e}")
        db.rollback()
        return 0
    finally:
        if close_after:
            db.close()
