"""Tests for the known venues service."""
from app.services.known_venues import find_known_venue


class TestFindKnownVenue:
    def test_finds_zollverein(self):
        result = find_known_venue("Zollverein", "")
        assert result is not None
        assert result["lat"] == 51.4864
        assert result["lon"] == 7.0403

    def test_finds_by_title(self):
        result = find_known_venue("", "Führung auf Zollverein")
        assert result is not None

    def test_finds_grugapark(self):
        result = find_known_venue("Grugapark", "")
        assert result is not None
        assert result["lat"] == 51.4293

    def test_finds_folkwang(self):
        result = find_known_venue("Folkwang Museum", "")
        assert result is not None

    def test_returns_none_for_unknown(self):
        result = find_known_venue("Unbekannter Ort", "Irgendein Event")
        assert result is None

    def test_finds_grillo_theater(self):
        result = find_known_venue("Grillo-Theater", "")
        assert result is not None

    def test_case_insensitive(self):
        result = find_known_venue("ZOLLVEREIN", "")
        assert result is not None

    def test_does_not_match_generic_museum(self):
        """Only specific known venue keywords should produce a match."""
        # "Museum für XYZ" contains no specific known keyword (like folkwang, ruhr museum, etc.)
        result = find_known_venue("Museum für XYZ", "")
        # Should not match since no specific keyword like "folkwang" or "ruhr museum" is present
        if result is not None:
            assert any(kw in "museum für xyz" for kw in ["folkwang", "ruhr museum", "red dot"])

    def test_finds_ruhr_museum(self):
        result = find_known_venue("Ruhr Museum", "")
        assert result is not None
        assert result["lat"] == 51.4864

    def test_finds_by_partial_title(self):
        result = find_known_venue("", "Konzert im Grugapark")
        assert result is not None
        assert result["lat"] == 51.4293

    def test_returns_dict_with_required_keys(self):
        result = find_known_venue("Zollverein", "")
        assert result is not None
        assert "lat" in result
        assert "lon" in result
        assert "address" in result

    def test_finds_pact(self):
        result = find_known_venue("PACT Zollverein", "")
        assert result is not None

    def test_empty_inputs_return_none(self):
        result = find_known_venue("", "")
        assert result is None

    # --- corrected entries ---

    def test_zeche_carl_corrected_coords(self):
        """Zeche Carl liegt in Altenessen, nicht Werrastr."""
        result = find_known_venue("Zeche Carl", "")
        assert result is not None
        assert abs(result["lat"] - 51.4965) < 0.001
        assert abs(result["lon"] - 7.0124) < 0.001
        assert "Altenessen" in result["address"]

    def test_lichtburg_corrected_coords(self):
        """Lichtburg: Kettwiger Str., nicht Altmarkt."""
        result = find_known_venue("Lichtburg", "")
        assert result is not None
        assert abs(result["lat"] - 51.4549) < 0.001
        assert "Kettwiger" in result["address"]

    def test_villa_huegel_corrected_coords(self):
        result = find_known_venue("Villa Hügel", "")
        assert result is not None
        assert abs(result["lat"] - 51.4069) < 0.001
        assert abs(result["lon"] - 7.0090) < 0.001

    def test_aalto_theater_corrected_coords(self):
        result = find_known_venue("Aalto-Theater", "")
        assert result is not None
        assert abs(result["lat"] - 51.4469) < 0.001
        assert "Opernplatz" in result["address"]

    def test_turock_corrected_coords(self):
        """Turock liegt am Viehofer Platz, nicht Werrastr."""
        result = find_known_venue("Turock", "")
        assert result is not None
        assert abs(result["lat"] - 51.4615) < 0.001
        assert "Viehofer" in result["address"]

    def test_rabbit_hole_corrected_coords(self):
        result = find_known_venue("Rabbit Hole Theater", "")
        assert result is not None
        assert abs(result["lat"] - 51.4617) < 0.001
        assert "Viehofer" in result["address"]

    def test_theater_courage_corrected_coords(self):
        result = find_known_venue("Theater Courage", "")
        assert result is not None
        assert abs(result["lat"] - 51.4388) < 0.001
        assert "Goethestr" in result["address"]

    def test_studio_buehne_corrected_coords(self):
        result = find_known_venue("Studio-Buehne Essen", "")
        assert result is not None
        assert abs(result["lat"] - 51.4651) < 0.001
        assert "Korumhöhe" in result["address"]

    # --- new venues ---

    def test_finds_albert_schweitzer_tierheim(self):
        result = find_known_venue("Albert-Schweitzer-Tierheim", "")
        assert result is not None
        assert abs(result["lat"] - 51.4696) < 0.001

    def test_finds_tierheim_essen(self):
        result = find_known_venue("Tierheim Essen", "")
        assert result is not None

    def test_finds_essen_hauptbahnhof(self):
        result = find_known_venue("Essen Hauptbahnhof", "")
        assert result is not None
        assert abs(result["lat"] - 51.4515) < 0.001

    def test_finds_messe_essen(self):
        result = find_known_venue("Messe Essen", "")
        assert result is not None
        assert abs(result["lat"] - 51.4287) < 0.001

    def test_finds_domschatzkammer(self):
        result = find_known_venue("Domschatzkammer Essen", "")
        assert result is not None
        assert abs(result["lat"] - 51.4557) < 0.001

    def test_finds_kunsthaus_essen(self):
        result = find_known_venue("Kunsthaus Essen", "")
        assert result is not None
        assert abs(result["lat"] - 51.4258) < 0.001

    def test_finds_katakomben_theater(self):
        result = find_known_venue("Katakomben-Theater Essen", "")
        assert result is not None
        assert abs(result["lat"] - 51.4308) < 0.001

    def test_finds_neoliet(self):
        result = find_known_venue("Boulderbar Neoliet Essen", "")
        assert result is not None
        assert abs(result["lat"] - 51.4479) < 0.001

    def test_finds_element_boulders(self):
        result = find_known_venue("Element Boulders Essen", "")
        assert result is not None
        assert abs(result["lat"] - 51.4553) < 0.001

    def test_finds_hespertalbahn(self):
        result = find_known_venue("Hespertalbahn Kupferdreh", "")
        assert result is not None
        assert abs(result["lat"] - 51.3883) < 0.001

    def test_finds_musikpalette(self):
        result = find_known_venue("Musikpalette Essen", "")
        assert result is not None
        assert abs(result["lat"] - 51.4537) < 0.001

    def test_finds_neue_musik_zentrale(self):
        result = find_known_venue("Neue Musik Zentrale", "")
        assert result is not None
        assert abs(result["lat"] - 51.4617) < 0.001

    def test_no_generic_essen_keyword(self):
        """'essen' allein als Keyword ist nicht vorhanden — würde sonst alles matchen."""
        from app.services.known_venues import KNOWN_VENUES
        assert "essen" not in KNOWN_VENUES
