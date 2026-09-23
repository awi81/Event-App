"""Tests for the cleanup / archive service."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.cleanup import (
    archive_past_events,
    now_berlin,
    purge_old_archives,
    purge_broken_titles,
)
from app.models.event import Event

BERLIN = ZoneInfo("Europe/Berlin")


def _add(db, canonical_id, **kwargs):
    kwargs.setdefault("title", "T")
    kwargs.setdefault("source_name", "S")
    db.add(Event(canonical_id=canonical_id, **kwargs))


def test_archives_past_event(db_session):
    yesterday = datetime.now(BERLIN).replace(tzinfo=None) - timedelta(days=1)
    _add(db_session, "past_001", start_at=yesterday)
    db_session.commit()

    n = archive_past_events(db_session)
    assert n == 1
    row = db_session.query(Event).filter(Event.canonical_id == "past_001").first()
    assert row.archived_at is not None


def test_keeps_future_event(db_session):
    tomorrow = datetime.now(BERLIN).replace(tzinfo=None) + timedelta(days=1)
    _add(db_session, "future_001", start_at=tomorrow)
    db_session.commit()

    n = archive_past_events(db_session)
    assert n == 0
    row = db_session.query(Event).filter(Event.canonical_id == "future_001").first()
    assert row.archived_at is None


def test_keeps_permanent_offer_even_if_past(db_session):
    yesterday = datetime.now(BERLIN).replace(tzinfo=None) - timedelta(days=1)
    _add(db_session, "perm_001", start_at=yesterday, is_permanent_offer=True)
    db_session.commit()

    archive_past_events(db_session)
    row = db_session.query(Event).filter(Event.canonical_id == "perm_001").first()
    assert row.archived_at is None


def test_skips_events_without_start_at(db_session):
    _add(db_session, "no_date_001", start_at=None)
    db_session.commit()

    n = archive_past_events(db_session)
    assert n == 0


def test_keeps_running_event_until_its_end(db_session):
    now = datetime.now(BERLIN).replace(tzinfo=None)
    _add(db_session, "running_001", start_at=now - timedelta(hours=2), end_at=now + timedelta(hours=1))
    _add(db_session, "ended_001", start_at=now - timedelta(hours=3), end_at=now - timedelta(minutes=5))
    db_session.commit()

    assert archive_past_events(db_session) == 1
    running = db_session.query(Event).filter(Event.canonical_id == "running_001").first()
    assert running.archived_at is None


def test_all_day_event_lasts_until_end_of_its_day():
    from app.services.cleanup import effective_end, is_over

    day = datetime(2026, 9, 23)
    assert effective_end(day, None) == datetime(2026, 9, 23, 23, 59, 59, 999999)
    assert effective_end(day.replace(hour=10), None, is_all_day=True).date() == day.date()
    assert effective_end(day.replace(hour=20), None) == day.replace(hour=20)
    # end before start (bad data) falls back to the start
    assert effective_end(day.replace(hour=20), day.replace(hour=18)) == day.replace(hour=20)

    event = Event(canonical_id="x", title="T", source_name="S", start_at=day)
    assert not is_over(event, day.replace(hour=15))
    assert is_over(event, datetime(2026, 9, 24, 0, 1))


def test_doesnt_reprocess_already_archived(db_session):
    yesterday = datetime.now(BERLIN).replace(tzinfo=None) - timedelta(days=1)
    _add(db_session, "again_001", start_at=yesterday)
    db_session.commit()

    archive_past_events(db_session)
    n = archive_past_events(db_session)
    assert n == 0


def test_now_berlin_is_timezone_aware():
    assert now_berlin().tzinfo is not None


def test_purge_deletes_old_archives(db_session):
    now = datetime.now(BERLIN).replace(tzinfo=None)
    _add(
        db_session,
        "old_archive_001",
        start_at=now - timedelta(days=10),
        archived_at=now - timedelta(days=5),
    )
    db_session.commit()

    deleted = purge_old_archives(db_session, retention_days=2)
    assert deleted == 1
    assert db_session.query(Event).filter(Event.canonical_id == "old_archive_001").first() is None


def test_purge_keeps_recent_archives(db_session):
    now = datetime.now(BERLIN).replace(tzinfo=None)
    _add(
        db_session,
        "recent_archive_001",
        start_at=now - timedelta(days=1),
        archived_at=now - timedelta(hours=12),
    )
    db_session.commit()

    deleted = purge_old_archives(db_session, retention_days=2)
    assert deleted == 0
    assert db_session.query(Event).filter(Event.canonical_id == "recent_archive_001").first() is not None


def test_purge_does_not_touch_active_events(db_session):
    """Active (non-archived) events must never be deleted by purge."""
    _add(db_session, "active_001", start_at=datetime(2099, 1, 1))  # future
    db_session.commit()

    purge_old_archives(db_session, retention_days=0)
    assert db_session.query(Event).filter(Event.canonical_id == "active_001").first() is not None


def test_purge_broken_titles_removes_date_prefixed_titles(db_session):
    _add(db_session, "broken_001", title="Sa, 30. Mai | 10:00Alexander Lackmann")
    _add(db_session, "broken_002", title="Do, 19. Mär | 19:00Konzert im Goethebunker")
    _add(db_session, "good_001", title="Alexander Lackmann - Gelb ist Geschichte")
    db_session.commit()

    deleted = purge_broken_titles(db_session)
    assert deleted == 2

    remaining = {e.canonical_id for e in db_session.query(Event).all()}
    assert "good_001" in remaining
    assert "broken_001" not in remaining


def test_purge_broken_titles_leaves_normal_titles(db_session):
    _add(db_session, "ok_001", title="Sommerfest in Werden")
    _add(db_session, "ok_002", title="Konzert: Sa, na klar! Eine Liedermacher-Show")  # date-like but not prefix
    db_session.commit()

    deleted = purge_broken_titles(db_session)
    assert deleted == 0


def test_purge_respects_custom_retention(db_session):
    now = datetime.now(BERLIN).replace(tzinfo=None)
    _add(db_session, "p_keep", start_at=now - timedelta(days=10), archived_at=now - timedelta(days=5))
    _add(db_session, "p_drop", start_at=now - timedelta(days=20), archived_at=now - timedelta(days=15))
    db_session.commit()

    deleted = purge_old_archives(db_session, retention_days=10)
    assert deleted == 1
    remaining = {e.canonical_id for e in db_session.query(Event).all()}
    assert "p_keep" in remaining
    assert "p_drop" not in remaining


def test_purge_broken_titles_removes_venue_and_label_titles(db_session):
    # Rausgegangen text extractor sometimes promotes a venue header or ad label.
    rg = "Rausgegangen"
    _add(db_session, "venue_001", title="UNESCO-WELTERBE ZOLLVEREIN | ESSEN", source_name=rg)
    _add(db_session, "venue_002", title="Sponsored", venue_name="Waste Me", source_name=rg)
    _add(db_session, "venue_003", title="Zeche Carl", venue_name="Zeche Carl", source_name=rg)
    _add(db_session, "venue_004", title="Zollverein, Essen", venue_name=None, source_name=rg)
    _add(db_session, "ok_003", title="Sommerfest UNESCO-Welterbe Zollverein", venue_name="Zollverein", source_name=rg)
    _add(db_session, "ok_004", title="Zeche Carl Open Air", venue_name="Zeche Carl", source_name=rg)
    # Title == venue is legitimate outside Rausgegangen (permanent exhibitions).
    _add(db_session, "ok_005", title="Portal der Industriekultur", venue_name="Portal der Industriekultur", source_name="Zollverein")
    db_session.commit()

    deleted = purge_broken_titles(db_session)
    assert deleted == 4

    remaining = {e.canonical_id for e in db_session.query(Event).all()}
    assert remaining == {"ok_003", "ok_004", "ok_005"}
