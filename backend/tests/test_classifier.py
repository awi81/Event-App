"""Tests for the event classification service."""
from app.services.classifier import classify_event, apply_classification


class TestClassifyEvent:
    def test_classifies_kids_event(self):
        event = {"title": "Kinderführung im Museum", "short_description": "", "source_name": "", "venue_name": ""}
        category, indoor_outdoor, kids_suitable = classify_event(event)
        assert category == "Familie & Kinder"

    def test_classifies_music_event(self):
        event = {"title": "Jazz Konzert", "short_description": "Live Musik", "source_name": "", "venue_name": ""}
        category, _, _ = classify_event(event)
        assert category == "Kultur & Sonstiges"

    def test_classifies_sport_event(self):
        event = {"title": "Yoga im Park", "short_description": "", "source_name": "", "venue_name": ""}
        category, _, _ = classify_event(event)
        assert category == "Freizeitorte & Attraktionen"

    def test_classifies_market(self):
        event = {"title": "Ostermarkt in Werden", "short_description": "", "source_name": "", "venue_name": ""}
        category, _, _ = classify_event(event)
        assert category == "Märkte"

    def test_classifies_indoor_by_venue(self):
        event = {"title": "Event", "short_description": "", "source_name": "", "venue_name": "Museum Folkwang"}
        _, indoor_outdoor, _ = classify_event(event)
        assert indoor_outdoor == "indoor"

    def test_classifies_outdoor_by_venue(self):
        event = {"title": "Spaziergang", "short_description": "durch den park", "source_name": "", "venue_name": ""}
        _, indoor_outdoor, _ = classify_event(event)
        assert indoor_outdoor == "outdoor"

    def test_ruhrpottkids_always_kid_suitable(self):
        event = {"title": "Whatever", "short_description": "", "source_name": "Ruhrpott-Kids", "venue_name": ""}
        _, _, kids_suitable = classify_event(event)
        assert kids_suitable == "yes"

    def test_zollverein_override_indoor(self):
        event = {"title": "Outdoor Event", "short_description": "im freien", "source_name": "", "venue_name": "Zollverein"}
        _, indoor_outdoor, _ = classify_event(event)
        assert indoor_outdoor == "indoor"

    def test_grugapark_override_outdoor(self):
        event = {"title": "Konzert", "short_description": "", "source_name": "", "venue_name": "Grugapark"}
        _, indoor_outdoor, _ = classify_event(event)
        assert indoor_outdoor == "outdoor"

    def test_unknown_event_returns_none_category(self):
        event = {"title": "Sonstiges", "short_description": "", "source_name": "", "venue_name": ""}
        category, _, _ = classify_event(event)
        assert category is None

    def test_kids_suitable_none_for_non_ruhrpott_source(self):
        event = {"title": "Konzert", "short_description": "", "source_name": "Rausgegangen", "venue_name": ""}
        _, _, kids_suitable = classify_event(event)
        assert kids_suitable is None


class TestApplyClassification:
    def test_does_not_overwrite_existing_category(self):
        event = {
            "title": "Konzert",
            "short_description": "Musik live",
            "source_name": "",
            "venue_name": "",
            "category": "Spezial",
        }
        result = apply_classification(event)
        assert result["category"] == "Spezial"

    def test_sets_category_when_missing(self):
        event = {"title": "Konzert", "short_description": "live musik", "source_name": "", "venue_name": ""}
        result = apply_classification(event)
        assert result["category"] == "Kultur & Sonstiges"

    def test_sets_kids_from_source(self):
        event = {"title": "Event", "short_description": "", "source_name": "Ruhrpott-Kids", "venue_name": ""}
        result = apply_classification(event)
        assert result["kids_suitable"] == "yes"

    def test_does_not_overwrite_existing_indoor_outdoor(self):
        event = {
            "title": "Spaziergang",
            "short_description": "durch den park",
            "source_name": "",
            "venue_name": "",
            "indoor_outdoor": "indoor",
        }
        result = apply_classification(event)
        assert result["indoor_outdoor"] == "indoor"

    def test_does_not_overwrite_existing_kids_suitable(self):
        event = {
            "title": "Whatever",
            "short_description": "",
            "source_name": "Ruhrpott-Kids",
            "venue_name": "",
            "kids_suitable": "no",
        }
        result = apply_classification(event)
        assert result["kids_suitable"] == "no"

    def test_returns_event_data_with_all_keys(self):
        event = {"title": "Konzert", "short_description": "live musik", "source_name": "", "venue_name": ""}
        result = apply_classification(event)
        # Original keys are preserved
        assert "title" in result
        assert "short_description" in result
