"""Tests for the event grouping service."""
from datetime import datetime, timedelta

from app.models.event import Event
from app.services.grouping import normalise_title, group_events


def _evt(canonical_id: str, title: str, start_at=None, source="Theater Essen", **kw) -> Event:
    return Event(
        canonical_id=canonical_id,
        title=title,
        source_name=source,
        start_at=start_at,
        **kw,
    )


def test_normalise_title_strips_articles_and_case():
    assert normalise_title("Die Zauberflöte") == "zauberflöte"
    assert normalise_title("La Traviata, Oper in 3 Akten") == "la traviata oper 3 akten"


def test_normalise_title_handles_none_and_empty():
    assert normalise_title(None) == ""
    assert normalise_title("") == ""


def test_group_collapses_same_title_same_source(db_session):
    now = datetime.now()
    events = [
        _evt("a", "La Traviata", start_at=now + timedelta(days=2)),
        _evt("b", "La Traviata", start_at=now + timedelta(days=5)),
        _evt("c", "La Traviata", start_at=now + timedelta(days=9)),
    ]
    grouped = group_events(events)
    assert len(grouped) == 1
    assert grouped[0]["title"] == "La Traviata"
    assert len(grouped[0]["occurrences"]) == 3


def test_group_keeps_different_titles_separate():
    now = datetime.now()
    events = [
        _evt("a", "La Traviata", start_at=now + timedelta(days=1)),
        _evt("b", "Boris Godunov", start_at=now + timedelta(days=2)),
    ]
    grouped = group_events(events)
    assert len(grouped) == 2


def test_group_keeps_different_sources_separate():
    """Same play name from different sources should not be merged at grouping
    time - the base_sync dedup handles real cross-source duplicates."""
    now = datetime.now()
    events = [
        _evt("a", "Hamlet", start_at=now + timedelta(days=1), source="Theater Essen"),
        _evt("b", "Hamlet", start_at=now + timedelta(days=2), source="Rausgegangen"),
    ]
    grouped = group_events(events)
    assert len(grouped) == 2


def test_group_uses_next_future_start_as_representative():
    now = datetime.now()
    events = [
        _evt("a", "Show", start_at=now - timedelta(days=5)),  # past
        _evt("b", "Show", start_at=now + timedelta(days=3)),  # next future
        _evt("c", "Show", start_at=now + timedelta(days=10)),
    ]
    grouped = group_events(events)
    assert len(grouped) == 1
    # The headline start_at should be the next future occurrence
    headline = grouped[0]["start_at"]
    assert headline == events[1].start_at


def test_group_occurrences_sorted_by_start_at():
    now = datetime.now()
    events = [
        _evt("c", "Show", start_at=now + timedelta(days=10)),
        _evt("a", "Show", start_at=now + timedelta(days=1)),
        _evt("b", "Show", start_at=now + timedelta(days=5)),
    ]
    grouped = group_events(events)
    starts = [o["start_at"] for o in grouped[0]["occurrences"]]
    assert starts == sorted(starts)


def test_group_handles_missing_start_at():
    """Permanent offer without start_at should still produce one group."""
    e = _evt("a", "Dauerausstellung", start_at=None, is_permanent_offer=True)
    grouped = group_events([e])
    assert len(grouped) == 1
    assert grouped[0]["title"] == "Dauerausstellung"
    assert grouped[0]["occurrences"][0]["is_permanent_offer"] is True


def test_group_empty_title_does_not_merge():
    """Events with unparseable titles must not collapse into one bucket."""
    events = [
        _evt("a", "", start_at=datetime.now()),
        _evt("b", "   ", start_at=datetime.now()),
    ]
    grouped = group_events(events)
    # Each unparseable title gets its own bucket (uses event.id as discriminator)
    assert len(grouped) == 2


def test_group_global_sort_by_next_occurrence():
    now = datetime.now()
    events = [
        _evt("z", "Z-Show", start_at=now + timedelta(days=10)),
        _evt("a", "A-Show", start_at=now + timedelta(days=1)),
        _evt("m", "M-Show", start_at=now + timedelta(days=5)),
    ]
    grouped = group_events(events)
    titles = [g["title"] for g in grouped]
    assert titles == ["A-Show", "M-Show", "Z-Show"]
