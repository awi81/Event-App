"""Tests for the quality score service."""
from datetime import datetime, timezone

from app.models.event import Event, KidsSuitable, IndoorOutdoor
from app.services.quality import compute_quality_score, recompute_all_quality_scores


def _make_event(**kwargs) -> Event:
    defaults = dict(
        canonical_id=kwargs.pop("canonical_id", "q_test"),
        title=kwargs.pop("title", "An event"),
        source_name=kwargs.pop("source_name", "Test"),
    )
    return Event(**defaults, **kwargs)


def test_score_minimal_event_is_low():
    event = _make_event()
    score = compute_quality_score(event)
    # Only title is present → score should be near zero.
    assert 0.0 <= score < 0.1


def test_full_event_scores_high():
    event = _make_event(
        start_at=datetime(2026, 6, 1, 19, 0),
        venue_name="Aalto Theater",
        lat=51.45,
        lon=7.01,
        short_description="A long enough description with details about the event.",
        category="Kultur & Sonstiges",
        price_text="10€",
        source_count=2,
        sources_list="A,B",
    )
    assert compute_quality_score(event) >= 0.95


def test_multi_source_bonus_applied():
    base = _make_event(start_at=datetime(2026, 6, 1, 19, 0), venue_name="X")
    single = compute_quality_score(base)
    base.source_count = 3
    base.sources_list = "A,B,C"
    multi = compute_quality_score(base)
    assert multi > single


def test_permanent_offer_counts_as_dated(db_session):
    event = _make_event(canonical_id="perm_q", is_permanent_offer=True)
    # No start_at, but permanent offers should still get the date weight.
    score = compute_quality_score(event)
    assert score >= 0.2


def test_recompute_all_updates_score(db_session):
    db_session.add(_make_event(canonical_id="r_001"))
    db_session.add(_make_event(
        canonical_id="r_002",
        start_at=datetime(2026, 6, 1, 19, 0),
        venue_name="Aalto",
        lat=51.45,
        lon=7.01,
        short_description="A reasonably long description with content.",
        category="Kultur",
        price_text="frei",
        source_count=2,
        sources_list="A,B",
    ))
    db_session.commit()

    n = recompute_all_quality_scores(db_session)
    assert n == 2

    rows = db_session.query(Event).order_by(Event.canonical_id).all()
    minimal, full = rows[0], rows[1]
    assert full.quality_score > minimal.quality_score
