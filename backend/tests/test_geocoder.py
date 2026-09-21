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
