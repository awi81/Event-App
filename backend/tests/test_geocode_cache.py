"""Tests for the persistent geocode cache."""
from datetime import datetime, timezone, timedelta

from app.services.geocode_cache import (
    get_cached_geocode,
    store_geocode,
    _normalize,
    POSITIVE_TTL,
    NEGATIVE_TTL,
)
from app.models.cache import GeocodeCache


def test_normalize_lowercases_and_trims():
    assert _normalize("  Zollverein  ESSEN ") == "zollverein essen"


def test_store_and_retrieve_positive(db_session):
    store_geocode(db_session, "Zollverein, Essen", 51.4864, 7.0403)
    result = get_cached_geocode(db_session, "Zollverein, Essen")
    assert result == (51.4864, 7.0403)


def test_retrieve_unknown_returns_none(db_session):
    assert get_cached_geocode(db_session, "Unknown venue") is None


def test_store_negative_result(db_session):
    store_geocode(db_session, "Nope", None, None)
    result = get_cached_geocode(db_session, "Nope")
    assert result == (None, None)


def test_overwrites_existing(db_session):
    store_geocode(db_session, "Place", 1.0, 2.0)
    store_geocode(db_session, "Place", 3.0, 4.0)
    rows = db_session.query(GeocodeCache).filter(GeocodeCache.query == "place").all()
    assert len(rows) == 1
    assert rows[0].lat == 3.0


def test_normalize_makes_lookup_case_insensitive(db_session):
    store_geocode(db_session, "Cafe Z", 51.1, 7.1)
    assert get_cached_geocode(db_session, "CAFE Z") == (51.1, 7.1)
    assert get_cached_geocode(db_session, "  cafe z ") == (51.1, 7.1)


def test_positive_ttl_expiry(db_session):
    store_geocode(db_session, "Old hit", 51.0, 7.0)
    # Backdate
    row = db_session.query(GeocodeCache).filter(GeocodeCache.query == "old hit").first()
    row.fetched_at = datetime.now(timezone.utc) - (POSITIVE_TTL + timedelta(days=1))
    db_session.commit()

    assert get_cached_geocode(db_session, "Old hit") is None


def test_negative_ttl_shorter_than_positive(db_session):
    store_geocode(db_session, "Old miss", None, None)
    row = db_session.query(GeocodeCache).filter(GeocodeCache.query == "old miss").first()
    row.fetched_at = datetime.now(timezone.utc) - (NEGATIVE_TTL + timedelta(days=1))
    db_session.commit()

    assert get_cached_geocode(db_session, "Old miss") is None
