"""Tests for the shared sync logic."""
from datetime import datetime, timezone, timedelta

from app.services.base_sync import sync_events_to_db, _title_similarity, _normalize_title
from app.models.event import Event


class TestSyncEventsToDb:
    def test_inserts_new_events(self, db_session):
        events = [
            {
                "canonical_id": "sync_test_001",
                "title": "Test Event 1",
                "city": "Essen",
                "source_name": "Test",
            },
            {
                "canonical_id": "sync_test_002",
                "title": "Test Event 2",
                "city": "Essen",
                "source_name": "Test",
            },
        ]
        stats = sync_events_to_db(db_session, events, "Test")
        assert stats["created"] == 2
        assert stats["updated"] == 0
        assert stats["found"] == 2

    def test_deduplicates_within_batch(self, db_session):
        events = [
            {"canonical_id": "dup_001", "title": "Event A", "source_name": "Test"},
            {"canonical_id": "dup_001", "title": "Event A Copy", "source_name": "Test"},
        ]
        stats = sync_events_to_db(db_session, events, "Test")
        assert stats["found"] == 1
        assert stats["created"] == 1

    def test_updates_existing_event(self, db_session):
        events = [{"canonical_id": "update_001", "title": "Original", "source_name": "Test"}]
        sync_events_to_db(db_session, events, "Test")

        events = [{"canonical_id": "update_001", "title": "Updated Title", "source_name": "Test"}]
        stats = sync_events_to_db(db_session, events, "Test")
        assert stats["updated"] == 1
        assert stats["created"] == 0

    def test_handles_empty_list(self, db_session):
        stats = sync_events_to_db(db_session, [], "Test")
        assert stats["created"] == 0
        assert stats["found"] == 0

    def test_handles_special_characters(self, db_session):
        """Verify parameterized queries handle special chars (no SQL injection)."""
        events = [
            {
                "canonical_id": "special_001",
                "title": "Event with 'quotes' and \"doubles\"",
                "city": "Essen",
                "source_name": "Test",
            },
        ]
        stats = sync_events_to_db(db_session, events, "Test")
        assert stats["created"] == 1

    def test_skips_events_without_canonical_id(self, db_session):
        """Events without canonical_id should be skipped during deduplication."""
        events = [
            {"title": "No ID Event", "source_name": "Test"},
            {"canonical_id": "valid_id_001", "title": "Valid Event", "source_name": "Test"},
        ]
        stats = sync_events_to_db(db_session, events, "Test")
        assert stats["created"] == 1

    def test_persists_event_data_to_database(self, db_session):
        """Inserted event data should be retrievable from the database."""
        from sqlalchemy import text

        events = [
            {
                "canonical_id": "persist_001",
                "title": "Persisted Event",
                "city": "Essen",
                "source_name": "Test",
            }
        ]
        sync_events_to_db(db_session, events, "Test")

        row = db_session.execute(
            text("SELECT title, city FROM events WHERE canonical_id = :cid"),
            {"cid": "persist_001"},
        ).fetchone()
        assert row is not None
        assert row[0] == "Persisted Event"
        assert row[1] == "Essen"

    def test_update_changes_title_in_database(self, db_session):
        """After update, the new title should be stored in the database."""
        from sqlalchemy import text

        events = [{"canonical_id": "upd_check_001", "title": "Old Title", "source_name": "Test"}]
        sync_events_to_db(db_session, events, "Test")

        updated_events = [{"canonical_id": "upd_check_001", "title": "New Title", "source_name": "Test"}]
        sync_events_to_db(db_session, updated_events, "Test")

        row = db_session.execute(
            text("SELECT title FROM events WHERE canonical_id = :cid"),
            {"cid": "upd_check_001"},
        ).fetchone()
        assert row is not None
        assert row[0] == "New Title"

    def test_returns_count_matching_number_of_processed_events(self, db_session):
        events = [
            {"canonical_id": f"batch_{i:03d}", "title": f"Event {i}", "source_name": "Test"}
            for i in range(5)
        ]
        stats = sync_events_to_db(db_session, events, "Test")
        assert stats["created"] == 5

    def test_cross_source_duplicate_is_merged(self, db_session):
        """Same event from a second source should bump source_count, not insert."""
        start = datetime(2026, 4, 15, 19, 0)
        first = [{
            "canonical_id": "cross_001",
            "title": "Jazz Konzert im Aalto",
            "start_at": start,
            "source_name": "SourceA",
        }]
        sync_events_to_db(db_session, first, "SourceA")

        second = [{
            "canonical_id": "cross_002",
            "title": "Jazz Konzert Aalto",  # similar enough
            "start_at": start + timedelta(hours=1),
            "source_name": "SourceB",
        }]
        stats = sync_events_to_db(db_session, second, "SourceB")
        assert stats["merged"] == 1
        assert stats["created"] == 0

        rows = db_session.query(Event).filter(Event.canonical_id == "cross_001").all()
        assert len(rows) == 1
        assert rows[0].source_count == 2
        assert "SourceB" in (rows[0].sources_list or "")

    def test_dissimilar_events_are_not_merged(self, db_session):
        start = datetime(2026, 4, 15, 19, 0)
        first = [{
            "canonical_id": "diff_001",
            "title": "Jazz Konzert",
            "start_at": start,
            "source_name": "SourceA",
        }]
        sync_events_to_db(db_session, first, "SourceA")

        second = [{
            "canonical_id": "diff_002",
            "title": "Vortrag über Physik",
            "start_at": start,
            "source_name": "SourceB",
        }]
        stats = sync_events_to_db(db_session, second, "SourceB")
        assert stats["created"] == 1
        assert stats["merged"] == 0


class TestTitleNormalization:
    def test_normalizes_umlauts_and_case(self):
        assert _normalize_title("Konzert IM Großen Saal") == "konzert großen saal"

    def test_strips_stopwords(self):
        assert "im" not in _normalize_title("Vortrag im Museum")

    def test_strips_punctuation(self):
        assert _normalize_title("Jazz - Konzert!") == "jazz konzert"

    def test_similarity_identical(self):
        assert _title_similarity("Jazz Konzert", "Jazz Konzert") == 1.0

    def test_similarity_partial(self):
        sim = _title_similarity("Jazz Konzert im Aalto", "Jazz Konzert Aalto Theater")
        assert sim >= 0.5

    def test_similarity_dissimilar(self):
        sim = _title_similarity("Jazz Konzert", "Vortrag Physik")
        assert sim == 0.0
