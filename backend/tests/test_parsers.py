"""Parser tests for every source.

These tests don't hit the network. Each test feeds a hand-crafted minimal
payload (HTML/RSS/JSON/plain text) — shaped like what the live site returns —
to the parser and verifies the resulting event dicts.

The intent is to catch *parsing regressions* quickly: if a site changes its
markup the parser may still return [] silently in production, but a test that
feeds known-good content will keep documenting what we expect to extract.
"""
from datetime import datetime, timedelta, timezone

from app.services.borbeck import convert_rss_entry as borbeck_convert, parse_rss_feed as borbeck_parse
from app.services.ruhrpott_kids import (
    convert_rss_entry as rpk_convert,
    parse_rss_feed as rpk_parse,
    parse_rss_date,
)
from app.services.grugapark import (
    parse_grugapark_html,
    parse_grugapark_date,
)
from app.services.seaside_beach import parse_seaside_html
from app.services.waddische import parse_waddische_html
from app.services.rausgegangen import (
    parse_rausgegangen_html,
    parse_german_date,
    parse_iso_date,
    extract_events_from_text as rg_text_extract,
)
from app.services.zollverein import (
    parse_zollverein_api,
    parse_zollverein_date,
    convert_zollverein_event,
    parse_zollverein_html,
)
from app.services.gasometer import parse_gasometer_text
from app.services.unperfekthaus import parse_uph_text
from app.services.theater_essen import parse_tup_text
from app.services.folkwang import parse_folkwang_text
from app.services.wasgehtapp import extract_events_from_text as wga_extract


# ─────────────────────────────── borbeck.de (RSS) ───────────────────────────


def test_borbeck_parses_rss_entry():
    xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <title>Borbeck Feed</title>
      <item>
        <title>Sommerfest in Borbeck</title>
        <link>https://www.borbeck.de/sommerfest</link>
        <description>Großes Fest mit Live-Musik und Essen</description>
      </item>
    </channel></rss>
    """
    events = borbeck_parse(xml)
    assert len(events) == 1
    e = events[0]
    assert e["title"] == "Sommerfest in Borbeck"
    assert e["source_name"] == "borbeck.de"
    assert e["is_permanent_offer"] is True  # borbeck items treated as standing offers
    assert e["source_url"].startswith("https://")


def test_borbeck_skips_impressum_and_datenschutz():
    xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel><title>F</title>
      <item><title>Impressum</title><link>https://x</link></item>
      <item><title>Datenschutz</title><link>https://x</link></item>
      <item><title>Echtes Event in Borbeck</title><link>https://x</link></item>
    </channel></rss>
    """
    events = borbeck_parse(xml)
    titles = [e["title"] for e in events]
    assert "Impressum" not in titles
    assert "Datenschutz" not in titles
    assert "Echtes Event in Borbeck" in titles


def test_borbeck_convert_returns_none_for_short_title():
    class Entry(dict):
        def get(self, k, default=""):
            return dict.get(self, k, default)

    e = Entry(title="abc", link="https://x", description="d")
    assert borbeck_convert(e) is None


# ─────────────────────────── Ruhrpott-Kids (RSS) ────────────────────────────


def test_ruhrpott_kids_marks_entries_as_kid_friendly_and_permanent():
    xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel><title>RPK</title>
      <item>
        <title>Indoor-Spielplatz Test</title>
        <link>https://ruhrpottkids.com/spielplatz</link>
        <description>Toller Spielplatz für Kinder</description>
      </item>
    </channel></rss>
    """
    events = rpk_parse(xml)
    assert len(events) == 1
    e = events[0]
    assert e["kids_suitable"] == "yes"
    assert e["is_permanent_offer"] is True
    assert e["source_name"] == "Ruhrpott-Kids"


def test_ruhrpott_kids_convert_returns_none_without_title():
    class Entry(dict):
        def get(self, k, default=""):
            return dict.get(self, k, default)

    assert rpk_convert(Entry()) is None


def test_parse_rss_date_handles_common_format():
    parsed = parse_rss_date("Mon, 15 Mar 2026 19:30:00 +0100")
    assert parsed is not None
    assert parsed.year == 2026


# ────────────────────────────── Grugapark (HTML) ────────────────────────────


def test_grugapark_extracts_event_with_iso_date():
    html = """
    <html><body>
      <article>
        <h2>Frühlingsfest 2026</h2>
        <time datetime="2026-04-12T10:00">12.04.2026</time>
        <p>Großes Fest im Grugapark mit Musik und Programm.</p>
        <a href="/event/fruehlingsfest">Details</a>
      </article>
    </body></html>
    """
    events = parse_grugapark_html(html)
    assert len(events) == 1
    e = events[0]
    assert e["title"] == "Frühlingsfest 2026"
    assert e["venue_name"] == "Grugapark"
    assert e["lat"] is not None and e["lon"] is not None
    assert e["indoor_outdoor"] == "outdoor"
    assert e["kids_suitable"] == "likely"


def test_grugapark_skips_navigation():
    html = """
    <html><body>
      <article><h2>Impressum</h2><p>x</p></article>
      <article><h2>Frühjahrsmarkt</h2><p>15.05.2026 Markt im Park</p></article>
    </body></html>
    """
    events = parse_grugapark_html(html)
    titles = [e["title"] for e in events]
    assert "Impressum" not in titles
    assert any("Frühjahrsmarkt" in t for t in titles)


def test_parse_grugapark_date_iso_and_german():
    assert parse_grugapark_date("2026-05-01T10:00:00") is not None
    assert parse_grugapark_date("01.05.2026") is not None
    assert parse_grugapark_date(None) is None
    assert parse_grugapark_date("nonsense") is None


# ───────────────────────────── Seaside Beach (HTML) ─────────────────────────


def test_seaside_extracts_future_event():
    future = datetime.now() + timedelta(days=30)
    html = f"""
    <html><body>
      <p>Sommer-Konzert am Baldeneysee</p>
      <p>{future.day:02d}.{future.month:02d}.{future.year} 19:00 Uhr</p>
    </body></html>
    """
    events = parse_seaside_html(html, "https://www.seaside-beach.de/")
    assert any("Konzert" in e["title"] for e in events)
    real = [e for e in events if "Konzert" in e["title"]]
    assert real[0]["lat"] is not None
    assert real[0]["indoor_outdoor"] == "outdoor"


def test_seaside_skips_past_events_returns_permanent_fallback():
    html = "<html><body><p>Strand</p><p>01.01.2000 10:00 Uhr</p></body></html>"
    events = parse_seaside_html(html, "https://www.seaside-beach.de/")
    # No future event → falls back to permanent offer
    assert len(events) == 1
    assert events[0]["is_permanent_offer"] is True


# ───────────────────────────── waddische.de (HTML) ──────────────────────────


def test_waddische_parses_category_date_and_event():
    future_year = datetime.now().year + 1
    html = f"""
    <html><body>
      <article class="entry-content">
        <h3>Kinder und Jugend</h3>
        <h4>Freitag, 12. Dezember:</h4>
        <p>19:00 Uhr Kindertheater im Werdener Markt</p>
      </article>
    </body></html>
    """
    _ = future_year  # silence linter
    events = parse_waddische_html(html)
    assert any("Kindertheater" in e["title"] for e in events)
    e = next(x for x in events if "Kindertheater" in x["title"])
    assert e["kids_suitable"] == "yes"  # because category contains "kinder"
    assert e["source_name"] == "Werdener Nachrichten"


def test_waddische_skips_meta_lines():
    html = """
    <html><body><article class="entry-content">
      <h3>Treff</h3>
      <h4>Montag, 5. Januar:</h4>
      <p>10:00 Uhr Impressum, Datenschutz</p>
      <p>14:00 Uhr Lesung im Stadtteilzentrum</p>
    </article></body></html>
    """
    events = parse_waddische_html(html)
    titles = [e["title"] for e in events]
    assert not any("Impressum" in t for t in titles)
    assert any("Lesung" in t for t in titles)


# ─────────────────────────────── Rausgegangen ───────────────────────────────


def test_rausgegangen_json_ld_extracts_event():
    html = """
    <html><head>
      <script type="application/ld+json">
      {
        "@type": "Event",
        "name": "Open Air am Aalto",
        "startDate": "2026-07-15T19:30:00",
        "description": "Sommer-Konzert mit Special Guests.",
        "url": "https://www.rausgegangen.de/events/open-air/",
        "location": {
          "name": "Aalto-Theater",
          "address": {"streetAddress": "Opernplatz 10"},
          "geo": {"latitude": 51.4516, "longitude": 7.0133}
        }
      }
      </script>
    </head><body></body></html>
    """
    events = parse_rausgegangen_html(html, "essen")
    assert len(events) == 1
    e = events[0]
    assert e["title"] == "Open Air am Aalto"
    assert e["lat"] == 51.4516
    assert e["venue_name"] == "Aalto-Theater"
    assert e["source_name"] == "Rausgegangen"


def test_rausgegangen_parses_german_date():
    d = parse_german_date("Do, 19. Mär | 19:00")
    assert d is not None and d.month == 3 and d.day == 19


def test_rausgegangen_iso_date_with_z():
    d = parse_iso_date("2026-06-01T20:00:00Z")
    assert d is not None and d.year == 2026 and d.day == 1


def test_rausgegangen_text_extractor_finds_event():
    text = """
Do, 19. Mär | 19:00
Konzert im Goethebunker
Goethebunker
""".strip()
    events = rg_text_extract(text, "essen")
    assert any("Konzert" in e["title"] for e in events)


# ──────────────────────────────── Zollverein ────────────────────────────────


def test_zollverein_api_parses_event_list():
    data = {
        "events": [
            {
                "title": "Industriekultur Führung",
                "url": "/event/123",
                "startDate": "2026-04-20T14:00:00",
                "description": "Geführter Rundgang durch das UNESCO-Welterbe.",
                "location": {"name": "Zollverein Areal A"},
                "category": "Führung",
            }
        ]
    }
    events = parse_zollverein_api(data)
    assert len(events) == 1
    e = events[0]
    assert e["title"] == "Industriekultur Führung"
    assert e["source_url"].startswith("https://www.zollverein.de")
    assert e["start_at"] is not None
    assert e["category"] == "Führung"


def test_zollverein_convert_skips_event_without_title():
    assert convert_zollverein_event({"description": "x"}) is None


def test_zollverein_date_handles_iso_and_z_suffix():
    assert parse_zollverein_date("2026-05-01T19:00:00Z") is not None
    assert parse_zollverein_date("2026-05-01") is not None
    assert parse_zollverein_date(None) is None


def test_zollverein_html_fallback_extracts_event():
    html = """
    <html><body>
      <li class="mb-4">
        <h3><a href="/event/abc">Ausstellung Bergbau</a></h3>
        <p>20.05.2026</p>
        <p>Eine Ausstellung über den Bergbau im Ruhrgebiet.</p>
      </li>
    </body></html>
    """
    events = parse_zollverein_html(html)
    assert len(events) == 1
    assert events[0]["title"] == "Ausstellung Bergbau"
    assert events[0]["lat"] is not None  # known venue


# ──────────────────────────────── Gasometer ─────────────────────────────────


def test_gasometer_extracts_event_with_date_and_title():
    text = """
08. Juli
GROSSE BÄUME, KLEINE HELDEN
Ein besonderer Abend mit Vortrag und Diskussion.
Einlass ab 18:30
""".strip()
    events = parse_gasometer_text(text)
    assert len(events) == 1
    e = events[0]
    assert "BÄUME" in e["title"].upper()
    assert e["venue_name"] == "Gasometer Oberhausen"
    assert e["city"] == "Oberhausen"
    assert e["start_at"] is not None
    # Time should be inferred from "Einlass ab 18:30"
    assert e["start_at"].hour == 18 and e["start_at"].minute == 30


def test_gasometer_handles_unknown_month_gracefully():
    text = "99. Mondtag\nIRGENDWAS\n"
    events = parse_gasometer_text(text)
    assert events == []


# ─────────────────────────────── Unperfekthaus ──────────────────────────────


def test_uph_parses_future_event():
    future = datetime.now() + timedelta(days=20)
    text = f"""
Workshop: Improvisationstheater
{future.day:02d}.{future.month:02d}.{future.year} 19:00 Uhr
Anmeldung über die Webseite
""".strip()
    events = parse_uph_text(text)
    assert any("Improvisationstheater" in e["title"] for e in events)


def test_uph_skips_past_dates():
    text = "Konzert\n01.01.2000 20:00 Uhr\n"
    events = parse_uph_text(text)
    assert events == []


# ────────────────────────────── Theater Essen ───────────────────────────────


def test_tup_extracts_event_with_venue_and_time():
    future = datetime.now() + timedelta(days=30)
    date_str = f"{future.day:02d}.{future.month:02d}.{future.year}"
    text = f"""
AALTO-MUSIKTHEATER
Donnerstag
{date_str}
19:30 - 22:00
La Traviata
Oper von Verdi
""".strip()
    events = parse_tup_text(text)
    assert len(events) == 1
    e = events[0]
    assert e["title"] == "La Traviata"
    assert e["venue_name"] == "AALTO-MUSIKTHEATER"
    assert e["start_at"].hour == 19 and e["start_at"].minute == 30
    assert e["indoor_outdoor"] == "indoor"


def test_tup_skips_past_event():
    text = """
PHILHARMONIE ESSEN
01.01.2000
19:30
Altes Konzert
""".strip()
    events = parse_tup_text(text)
    assert events == []


# ────────────────────────────── Museum Folkwang ─────────────────────────────


def test_folkwang_parses_event_block():
    future = datetime.now() + timedelta(days=40)
    months = ["", "JANUAR", "FEBRUAR", "MÄRZ", "APRIL", "MAI", "JUNI",
              "JULI", "AUGUST", "SEPTEMBER", "OKTOBER", "NOVEMBER", "DEZEMBER"]
    month_name = months[future.month]
    text = f"""
DIENSTAG, {future.day}. {month_name} {future.year}
14:30
Familienführung Highlights
Führung
""".strip()
    events = parse_folkwang_text(text)
    assert len(events) == 1
    e = events[0]
    assert "Familienführung Highlights" in e["title"]
    assert e["venue_name"] == "Museum Folkwang"
    assert e["kids_suitable"] == "yes"
    assert e["indoor_outdoor"] == "indoor"


def test_folkwang_no_match_without_date_header():
    text = "14:30\nIrgendwas\nOhne Datum\n"
    events = parse_folkwang_text(text)
    assert events == []


# ─────────────────────────────── wasgehtapp.de ──────────────────────────────


def test_wasgehtapp_extracts_event_from_text():
    text = """
Konzert im Stadtgarten Essen
Fr, 20.03, 19:30 Uhr   pin Stadtgarten Essen
""".strip()
    events = wga_extract(text, "Essen")
    assert any("Konzert" in e["title"] for e in events)
    e = next(x for x in events if "Konzert" in x["title"])
    assert e["start_at"].hour == 19 and e["start_at"].minute == 30
    assert e["source_name"] == "wasgehtapp.de"


def test_wasgehtapp_filters_known_meta_lines():
    text = """
3,50 €
Fr, 20.03, 19:30 Uhr   pin X
""".strip()
    events = wga_extract(text, "Essen")
    # No proper title above the date → should yield nothing
    titles = [e["title"] for e in events]
    assert "3,50 €" not in titles


def test_wasgehtapp_invalid_date_skips_single_event():
    """Ein ungültiges Datum (z.B. Monat=13) darf nur dieses Event überspringen."""
    # Monat 13 ist ungültig → ValueError im datetime()-Konstruktor
    text = """
Gültiges Konzert
Fr, 20.03, 19:30 Uhr
Ungültiges Event
Sa, 05.13, 20:00 Uhr
""".strip()
    # Kein Exception, und das gültige Event wird trotzdem gefunden
    events = wga_extract(text, "Essen")
    assert any("Konzert" in e["title"] for e in events)
    # Das ungültige Event ist nicht dabei
    assert not any("Ungültig" in e.get("title", "") for e in events)


# ──────────────────────────── to_berlin_naive ───────────────────────────────


def test_to_berlin_naive_strips_utc_tzinfo():
    from app.services.base_sync import to_berlin_naive
    dt_utc = datetime(2026, 6, 1, 17, 0, 0, tzinfo=timezone.utc)
    result = to_berlin_naive(dt_utc)
    assert result.tzinfo is None
    # UTC 17:00 → Berlin CEST (UTC+2) = 19:00
    assert result.hour == 19


def test_to_berlin_naive_keeps_naive_unchanged():
    from app.services.base_sync import to_berlin_naive
    dt_naive = datetime(2026, 6, 1, 19, 0, 0)
    result = to_berlin_naive(dt_naive)
    assert result == dt_naive
    assert result.tzinfo is None


def test_to_berlin_naive_handles_none():
    from app.services.base_sync import to_berlin_naive
    assert to_berlin_naive(None) is None


def test_zollverein_date_returns_naive():
    from app.services.zollverein import parse_zollverein_date
    result = parse_zollverein_date("2026-05-01T17:00:00Z")
    assert result is not None
    assert result.tzinfo is None
    # UTC 17:00 → Berlin CEST 19:00
    assert result.hour == 19


def test_rausgegangen_iso_date_returns_naive():
    from app.services.rausgegangen import parse_iso_date
    result = parse_iso_date("2026-06-01T17:00:00Z")
    assert result is not None
    assert result.tzinfo is None
