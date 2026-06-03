"""Tests for the distance / travel time service."""
from app.services.distance import haversine_km, estimate_travel_time, ESSEN_WERDEN_LAT, ESSEN_WERDEN_LON, calculate_distances
from app.models.event import Event


def test_haversine_zero_distance():
    assert haversine_km(51.0, 7.0, 51.0, 7.0) == 0.0


def test_haversine_symmetric():
    a = haversine_km(51.0, 7.0, 51.5, 7.5)
    b = haversine_km(51.5, 7.5, 51.0, 7.0)
    assert abs(a - b) < 1e-9


def test_haversine_realistic_essen_to_grugapark():
    # Essen Werden -> Grugapark, approx 6 km
    dist = haversine_km(ESSEN_WERDEN_LAT, ESSEN_WERDEN_LON, 51.4293, 7.0561)
    assert 4 <= dist <= 8


def test_estimate_travel_time_short_distance():
    assert estimate_travel_time(0) == 0
    # 5 km should still be reasonable
    t = estimate_travel_time(5)
    assert 10 <= t <= 20


def test_estimate_travel_time_includes_base():
    # Tiny distance still has the parking baseline
    assert estimate_travel_time(0.1) >= 5


def test_calculate_distances_populates_fields(db_session):
    event = Event(
        canonical_id="dist_001",
        title="Test",
        source_name="Test",
        lat=51.4293,
        lon=7.0561,
    )
    db_session.add(event)
    db_session.commit()

    updated = calculate_distances(db_session)
    assert updated == 1

    fresh = db_session.query(Event).filter(Event.canonical_id == "dist_001").first()
    assert fresh.distance_km is not None
    assert fresh.distance_km > 0
    assert fresh.travel_time_minutes is not None
    assert fresh.travel_time_minutes > 0


def test_calculate_distances_skips_events_without_coords(db_session):
    db_session.add(Event(canonical_id="no_coords", title="X", source_name="T"))
    db_session.commit()

    updated = calculate_distances(db_session)
    assert updated == 0
