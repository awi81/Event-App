"""Tests for the Events API endpoints."""
import pytest
from datetime import date, datetime, timezone, timedelta


class TestHealthCheck:
    def test_health_responds_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] in ("healthy", "degraded")
        assert "db" in body


class TestGetEvents:
    def test_returns_empty_list_when_no_events(self, client):
        response = client.get("/api/v1/events")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_all_events(self, client, sample_events):
        response = client.get("/api/v1/events")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 5

    def test_limit_parameter(self, client, sample_events):
        response = client.get("/api/v1/events?limit=2")
        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_limit_max_enforced(self, client, sample_events):
        response = client.get("/api/v1/events?limit=500")
        assert response.status_code == 422  # Validation error

    def test_kids_only_filter(self, client, sample_events):
        response = client.get("/api/v1/events?kids_only=true")
        assert response.status_code == 200
        data = response.json()
        # Should only return yes and likely
        for event in data:
            assert event["kids_suitable"] in ["yes", "likely"]

    def test_category_filter(self, client, sample_events):
        response = client.get("/api/v1/events?category=Musik")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Jazz Konzert im Grillo"

    def test_indoor_filter(self, client, sample_events):
        response = client.get("/api/v1/events?indoor_outdoor=indoor")
        assert response.status_code == 200
        data = response.json()
        # Indoor filter includes "indoor" and "both"
        for event in data:
            assert event["indoor_outdoor"] in ["indoor", "both"]

    def test_outdoor_filter(self, client, sample_events):
        response = client.get("/api/v1/events?indoor_outdoor=outdoor")
        assert response.status_code == 200
        data = response.json()
        for event in data:
            assert event["indoor_outdoor"] in ["outdoor", "both"]

    def test_date_filter(self, client, sample_events):
        response = client.get("/api/v1/events?start_date=2099-03-21&end_date=2099-03-22")
        assert response.status_code == 200
        data = response.json()
        # Should include events on March 21 and 22
        assert any(e["canonical_id"] == "test_001" for e in data)
        assert any(e["canonical_id"] == "test_002" for e in data)

    def test_response_includes_source_name(self, client, sample_events):
        response = client.get("/api/v1/events")
        data = response.json()
        assert any(e["source_name"] == "Zollverein" for e in data)
        assert any(e["source_name"] == "Rausgegangen" for e in data)

    def test_response_includes_permanent_offer(self, client, sample_events):
        response = client.get("/api/v1/events")
        data = response.json()
        permanent = [e for e in data if e.get("is_permanent_offer")]
        assert len(permanent) >= 1

    def test_events_ordered_by_start_at(self, client, sample_events):
        response = client.get("/api/v1/events")
        data = response.json()
        # Events with start_at should be ordered
        dates = [e["start_at"] for e in data if e.get("start_at")]
        assert dates == sorted(dates)


class TestGetEventById:
    def test_returns_event(self, client, sample_events):
        # First get events to find an ID
        response = client.get("/api/v1/events")
        event_id = response.json()[0]["id"]

        response = client.get(f"/api/v1/events/{event_id}")
        assert response.status_code == 200
        assert response.json()["id"] == event_id

    def test_returns_404_for_missing_event(self, client):
        response = client.get("/api/v1/events/99999")
        assert response.status_code == 404
        assert "nicht gefunden" in response.json()["detail"]


class TestPastEventHiding:
    def test_past_events_are_not_returned(self, client, db_session):
        """Events whose start_at is in the past must not show up in /events."""
        from app.models.event import Event

        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        db_session.add(Event(
            canonical_id="past_999",
            title="Gestern Konzert",
            start_at=yesterday.replace(tzinfo=None),
            source_name="Test",
        ))
        db_session.commit()

        response = client.get("/api/v1/events")
        assert response.status_code == 200
        ids = [e["canonical_id"] for e in response.json()]
        assert "past_999" not in ids

    def test_permanent_offer_past_still_shown(self, client, db_session):
        """Permanent offers ignore the past-date filter."""
        from app.models.event import Event

        ancient = datetime.now(timezone.utc) - timedelta(days=365)
        db_session.add(Event(
            canonical_id="perm_999",
            title="Permanente Ausstellung",
            start_at=ancient.replace(tzinfo=None),
            is_permanent_offer=True,
            source_name="Test",
        ))
        db_session.commit()

        response = client.get("/api/v1/events")
        ids = [e["canonical_id"] for e in response.json()]
        assert "perm_999" in ids
