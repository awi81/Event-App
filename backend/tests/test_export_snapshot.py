"""Snapshot export: which rows end up in events.json."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.models.event import Event
from app.scripts.export_snapshot import _collect_event_rows

BERLIN = ZoneInfo("Europe/Berlin")


def test_export_keeps_running_and_all_day_rows_of_today(db_session):
    now = datetime.now(BERLIN).replace(tzinfo=None)
    today = datetime.combine(now.date(), datetime.min.time())
    rows = {
        "running": dict(start_at=now - timedelta(hours=2), end_at=now + timedelta(hours=2)),
        "all_day": dict(start_at=today),
        "ended": dict(start_at=now - timedelta(hours=3), end_at=now - timedelta(minutes=1)),
        "started_no_end": dict(start_at=now - timedelta(minutes=30)),
        "future": dict(start_at=now + timedelta(days=1)),
        "yesterday_all_day": dict(start_at=today - timedelta(days=1)),
    }
    for cid, kw in rows.items():
        db_session.add(Event(canonical_id=cid, title=cid, source_name="S", **kw))
    db_session.commit()

    exported = {e.canonical_id for e in _collect_event_rows(db_session, limit=0)}
    assert {"running", "all_day", "future"} <= exported
    assert not exported & {"ended", "yesterday_all_day"}
    started = rows["started_no_end"]["start_at"]
    if (started.hour, started.minute) != (0, 0):  # 00:00 would count as all-day
        assert "started_no_end" not in exported
