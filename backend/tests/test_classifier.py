"""Tests for the event classification service."""
from app.services.classifier import (
    CANONICAL_CATEGORIES,
    apply_classification,
    classify_event,
    normalize_category,
)


class TestClassifyEvent:
    def test_classifies_kids_event(self):
        event = {"title": "Kinderführung im Museum", "short_description": "", "source_name": "", "venue_name": ""}
        category, indoor_outdoor, kids_suitable = classify_event(event)
        assert category == "Familie & Kinder"

    def test_classifies_music_event(self):
        event = {"title": "Jazz Konzert", "short_description": "Live Musik", "source_name": "", "venue_name": ""}
        category, _, _ = classify_event(event)
        assert category == "Musik & Konzerte"

    def test_classifies_sport_event(self):
        event = {"title": "Yoga im Park", "short_description": "", "source_name": "", "venue_name": ""}
        category, _, _ = classify_event(event)
        assert category == "Freizeitorte & Attraktionen"

    def test_classifies_market(self):
        event = {"title": "Ostermarkt in Werden", "short_description": "", "source_name": "", "venue_name": ""}
        category, _, _ = classify_event(event)
        assert category == "Märkte & Messen"

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

    def test_unknown_event_lands_in_sonstiges(self):
        event = {"title": "Vorstellung", "short_description": "", "source_name": "", "venue_name": ""}
        category, _, _ = classify_event(event)
        assert category == "Sonstiges"

    def test_kids_suitable_none_for_non_ruhrpott_source(self):
        event = {"title": "Konzert", "short_description": "", "source_name": "Rausgegangen", "venue_name": ""}
        _, _, kids_suitable = classify_event(event)
        assert kids_suitable is None


class TestApplyClassification:
    def test_normalises_raw_source_category(self):
        # Raw source labels must never survive — the chip row would explode.
        event = {
            "title": "Woyzeck",
            "short_description": "",
            "source_name": "",
            "venue_name": "",
            "category": "Schauspiel",
        }
        result = apply_classification(event)
        assert result["category"] == "Theater & Bühne"

    def test_keeps_canonical_category(self):
        event = {
            "title": "Konzert",
            "short_description": "Musik live",
            "source_name": "",
            "venue_name": "",
            "category": "Familie & Kinder",
        }
        result = apply_classification(event)
        assert result["category"] == "Familie & Kinder"

    def test_unknown_raw_label_falls_back_to_title(self):
        event = {
            "title": "Techno-Party",
            "short_description": "",
            "source_name": "",
            "venue_name": "",
            "category": "Halle 8",
        }
        result = apply_classification(event)
        assert result["category"] == "Feste & Festivals"

    def test_sets_category_when_missing(self):
        event = {"title": "Konzert", "short_description": "live musik", "source_name": "", "venue_name": ""}
        result = apply_classification(event)
        assert result["category"] == "Musik & Konzerte"

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


class TestNormalizeCategory:
    """The canonical taxonomy is what the frontend chips are built from."""

    def test_every_canonical_name_maps_to_itself(self):
        for name in CANONICAL_CATEGORIES:
            assert normalize_category(name) == name

    def test_raw_labels_from_sources(self):
        cases = {
            "Kabarett & Co.": "Comedy & Kabarett",
            "Musical & Musiktheater": "Theater & Bühne",
            "Eigenproduktion": "Theater & Bühne",
            "Kinder- und Jugendtheater": "Familie & Kinder",
            "Tagesfahrten für Kinder": "Familie & Kinder",
            "Vortrag/Lesung": "Literatur & Vorträge",
            "Zollverein-Führungen": "Führungen & Touren",
            "Ruhr Museum": "Museum & Ausstellung",
            "Party/Nightlife": "Feste & Festivals",
            "Festival/Open-Air": "Feste & Festivals",
            "Weihnachtsmarkt": "Märkte & Messen",
            "Messe": "Märkte & Messen",
            "musik": "Musik & Konzerte",
            "Sportangebote": "Freizeitorte & Attraktionen",
        }
        for raw, expected in cases.items():
            assert normalize_category(raw) == expected, raw

    def test_word_boundaries_avoid_false_positives(self):
        assert normalize_category(None, "Kooperation Ruhr") == "Sonstiges"
        assert normalize_category(None, "Manifest der Zukunft") == "Sonstiges"
        assert normalize_category(None, "Oper: Carmen") == "Theater & Bühne"
        assert normalize_category(None, "Exkursion ins Grüne") == "Führungen & Touren"

    def test_kids_win_over_theater(self):
        assert normalize_category("Schauspiel", "Kindertheater: Der Räuber Hotzenplotz") == "Familie & Kinder"

    def test_unmappable_raw_label_becomes_sonstiges(self):
        assert normalize_category("Halle 8", "Vorstellung") == "Sonstiges"
        assert normalize_category("Stiftung Zollverein", "Jahresempfang") == "Sonstiges"

    def test_sonstiges_without_raw_label_when_nothing_fits(self):
        assert normalize_category(None, "Vorstellung") == "Sonstiges"

    def test_venue_default_beats_source_default(self):
        assert normalize_category(None, "ENTERTAINMENT", venue="Alfried Krupp Saal", source_name="Theater Essen") == "Musik & Konzerte"
        assert normalize_category(None, "Doc Caro", venue="Lichtburg", source_name="Rausgegangen") == "Theater & Bühne"
        assert normalize_category(None, "LipSync 4 Your Shot", venue="DIVINE Bar") == "Feste & Festivals"

    def test_source_default_is_last_resort(self):
        assert normalize_category(None, "FELIX MILDENBERGER", source_name="Theater Essen") == "Theater & Bühne"
        assert normalize_category(None, "Auch Idole bekommen weiche Knie", source_name="Ruhrpott-Kids") == "Familie & Kinder"
        assert normalize_category(None, "Irgendwas", source_name="Unbekannte Quelle") == "Sonstiges"

    def test_title_keywords_beat_venue_default(self):
        assert normalize_category(None, "Salsa Anfängerkurs", venue="Villa Rü") == "Workshops & Mitmachen"
        assert normalize_category(None, "GRENDSLAM Nr. 60", venue="GREND Kulturzentrum") == "Literatur & Vorträge"
        assert normalize_category(None, "Jubiläums Improshow", venue="GREND") == "Comedy & Kabarett"
