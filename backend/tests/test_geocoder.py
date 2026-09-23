"""Geocoder: candidate cleaning and error semantics (no network)."""
import httpx
import pytest

from app.services import geocoder
from app.services.geocoder import GeocodeUnavailable, clean_venue_name, geocode_event_venue


def test_clean_venue_name_strips_hall_and_slogan():
    assert clean_venue_name("Anneliese Brost Musikforum Ruhr (Großer Saal)") == "Anneliese Brost Musikforum Ruhr"
    assert clean_venue_name("Alleato Arena - Heimat der Füchse") == "Alleato Arena"
    assert clean_venue_name('Kulturraum "Die Flora"') == "Kulturraum Die Flora"
    assert clean_venue_name("Zeche Carl") == "Zeche Carl"


@pytest.mark.asyncio
async def test_candidates_include_cleaned_venue_and_skip_duplicates(monkeypatch):
    queries = []

    async def fake_geocode_address(query, city="Essen"):
        queries.append(query)
        return (51.0, 7.0) if query == "Alleato Arena" else None

    monkeypatch.setattr(geocoder, "geocode_address", fake_geocode_address)
    result = await geocode_event_venue("Alleato Arena - Heimat der Füchse", None, "Duisburg")
    assert result == (51.0, 7.0)
    assert queries == ["Alleato Arena - Heimat der Füchse", "Alleato Arena"]


@pytest.mark.asyncio
async def test_street_address_tried_before_bare_venue_name(monkeypatch):
    queries = []

    async def fake_geocode_address(query, city="Essen"):
        queries.append(query)
        return None

    monkeypatch.setattr(geocoder, "geocode_address", fake_geocode_address)
    await geocode_event_venue("Zentrum 60plus", "Heckstraße 27", "Essen")
    assert queries == ["Zentrum 60plus, Heckstraße 27", "Heckstraße 27", "Zentrum 60plus"]

    queries.clear()
    await geocode_event_venue("Zeche", "Bochum-Süd", "Bochum")
    assert queries == ["Zeche, Bochum-Süd", "Zeche", "Bochum-Süd"]


@pytest.mark.asyncio
async def test_service_error_raises_instead_of_not_found(monkeypatch):
    class FakeResponse:
        status_code = 429

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return FakeResponse()

    monkeypatch.setattr(geocoder.httpx, "AsyncClient", FakeClient)
    with pytest.raises(GeocodeUnavailable):
        await geocoder.geocode_address("Aalto Theater", "Essen")


@pytest.mark.asyncio
async def test_empty_result_is_a_genuine_miss(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return []

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return FakeResponse()

    monkeypatch.setattr(geocoder.httpx, "AsyncClient", FakeClient)
    assert await geocoder.geocode_address("Nirgendwo", "Essen") is None


@pytest.mark.asyncio
async def test_single_timeout_does_not_stop_geocoding_for_the_run(db_session, monkeypatch):
    from app.models.event import Event
    from app.services import pipeline

    for i in range(3):
        db_session.add(Event(canonical_id=f"g{i}", title=f"T{i}", source_name="S", venue_name=f"Unbekannter Ort {i}", city="Essen"))
    db_session.commit()

    calls = []

    async def flaky(venue_name, address_text, city="Essen"):
        calls.append(venue_name)
        if len(calls) == 1:
            raise GeocodeUnavailable("ReadTimeout: ")
        return (51.4, 7.0)

    monkeypatch.setattr(pipeline, "geocode_event_venue", flaky)
    updated = await pipeline.geocode_pending_events(db_session)
    assert len(calls) == 3
    assert updated == 2


@pytest.mark.asyncio
async def test_throttling_stops_geocoding_immediately(db_session, monkeypatch):
    from app.models.event import Event
    from app.services import pipeline

    for i in range(3):
        db_session.add(Event(canonical_id=f"h{i}", title=f"T{i}", source_name="S", venue_name=f"Unbekannter Ort {i}", city="Essen"))
    db_session.commit()

    calls = []

    async def throttled(venue_name, address_text, city="Essen"):
        calls.append(venue_name)
        raise GeocodeUnavailable("HTTP 429")

    monkeypatch.setattr(pipeline, "geocode_event_venue", throttled)
    await pipeline.geocode_pending_events(db_session)
    assert len(calls) == 1
