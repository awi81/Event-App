"""Parser tests for every source.

These tests don't hit the network. Each test feeds a hand-crafted minimal
payload (HTML/RSS/JSON/plain text) — shaped like what the live site returns —
to the parser and verifies the resulting event dicts.

The intent is to catch *parsing regressions* quickly: if a site changes its
markup the parser may still return [] silently in production, but a test that
feeds known-good content will keep documenting what we expect to extract.
"""
from datetime import date, datetime, timedelta, timezone

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


# Live markup (2026-09): .entry-content sits inside #content > article. The old
# parser matched '#content' first and found 0 events for months.
_WADDISCHE_LIVE_HTML = """
<html><body><div id="content" class="site-content">
 <article class="page"><div class="entry-content">
  <h1>Tipps • Treffs • Termine</h1>
  <h3>Treffs, Kurse und Workshops</h3>
  <h4>Freitag, 18. September</h4>
  <p><strong>11.45 bis 13.45 Uhr und 14 bis 16 Uhr:</strong> Aquarellkurs, Zentrum 60plus. Bitte anmelden.</p>
  <p><strong>10 bis 12 Uhr:</strong> Tourist Information, Zentrum 60plus.</p>
  <p><strong>14.30 bis 16 Uhr:</strong> Mitmachtanzen „Florence“: Blocktanz, Linedance und Folkdance im Pfarrsaal der Kirche Christi Himmelfahrt, Lürsweg 43a.</p>
  <h4>Dienstag, 22. September</h4>
  <p><strong>14 bis 17.30 Uhr:</strong> Offener Treff der Awo Werden.</p>
  <h3>Kinder und Jugend</h3>
  <h4>Donnerstag, 24. September</h4>
  <p><strong>16 bis 19 Uhr:</strong> Offener Kinder- und Jugendtreff, Jubb.</p>
  <h3>Bühne und Musik</h3>
  <h4>Sonntag, 20. September</h4>
  <p><strong>17 Uhr:</strong> Elternzeit-Konzerte: „Große Musik – kleinerer Kreis“. Memela Alija mit Werken von Frédéric Chopin, Edvard Grieg, Alberto Ginastera und Fazıl Say.</p>
  <h4>Mittwoch, 23. September</h4>
  <p><strong>15 bis 17 Uhr:</strong> Literaturcafé: „Im Schnee“ von Tommie Goertz, Teil 1 von 2, Bürgermeisterhaus, 12 Euro. Bitte anmelden.</p>
  <h3>Ausstellungen</h3>
  <p>Klaus Micke: „What You See is What You See“</p>
  <h3>Adressen und Kontakte</h3>
  <p>Awo Werden</p>
  <p>Keller des Rathauses Werden, Eingang Brückstraße Tel. 0201/49 30 62</p>
  <p>Bürgermeisterhaus</p>
  <p>Heckstraße 105 Tel. 0201/49 32 86 E-Mail: info@example.org</p>
  <p>Jugend- und Bürgerbegegnungszentrum (Jubb)</p>
  <p>Wesselswerth 10 Tel. 0201/88 511 49</p>
  <p>Zentrum 60plus</p>
  <p>Heckstraße 27 Infos und Anmeldungen: Tel. 0201/8474-270</p>
  <h3>Apothekennotdienst</h3>
  <h4>Freitag, 18. September</h4>
  <p>Löwen-Apotheke, Brückstraße 1, Tel. 0201/49 00 00.</p>
 </div></article>
</div></body></html>
"""


def test_waddische_parses_live_markup():
    events = parse_waddische_html(_WADDISCHE_LIVE_HTML, now=datetime(2026, 9, 23, 12))
    by_title = {}
    for e in events:
        by_title.setdefault(e["title"], []).append(e)

    aquarell = by_title["Aquarellkurs"]
    assert [(e["start_at"].hour, e["start_at"].minute, e["end_at"].hour) for e in aquarell] == [(11, 45, 13), (14, 0, 16)]
    assert aquarell[0]["start_at"].date().isoformat() == "2026-09-18"
    assert aquarell[0]["venue_name"] == "Zentrum 60plus"
    assert aquarell[0]["address_text"] == "Heckstraße 27"

    tanz = by_title["Mitmachtanzen „Florence“: Blocktanz"][0]
    assert tanz["venue_name"] == "Pfarrsaal der Kirche Christi Himmelfahrt"
    assert tanz["address_text"] == "Lürsweg 43a"

    assert by_title["Offener Treff der Awo Werden"][0]["venue_name"] == "Awo Werden"

    treff = by_title["Offener Kinder- und Jugendtreff"][0]
    assert treff["kids_suitable"] == "yes"
    assert treff["address_text"] == "Wesselswerth 10"

    konzert = by_title["Elternzeit-Konzerte: „Große Musik – kleinerer Kreis“"][0]
    assert konzert["venue_name"] is None
    assert konzert["end_at"] is None

    cafe = by_title["Literaturcafé: „Im Schnee“ von Tommie Goertz"][0]
    assert cafe["venue_name"] == "Bürgermeisterhaus"
    assert cafe["address_text"] == "Heckstraße 105"
    assert cafe["price_text"] == "12 Euro"

    # Notdienst / Ausstellungen / Adressen are not events
    assert not any("Apotheke" in t or "Micke" in t or "Heckstraße" in t for t in by_title)
    assert len(events) == 7
    assert len({e["canonical_id"] for e in events}) == 7


def test_waddische_infers_nearest_year():
    from app.services.waddische import _infer_year

    assert _infer_year(18, 9, datetime(2026, 9, 23)).year == 2026
    assert _infer_year(2, 1, datetime(2026, 12, 28)).year == 2027
    assert _infer_year(28, 12, datetime(2027, 1, 3)).year == 2026


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
#
# The upstream events.zollverein.de/api/v1/ API 403s on every request (an
# application-level auth gate, confirmed independent of headers). The real
# integration point is the same-origin Nuxt/Nitro route the kalender page
# itself calls: GET /kalender/api/events/{yyyymmdd}. Fixtures below are
# shaped like that route's actual (verified live) response.


def _zollverein_day_fixture():
    return {
        "date": "2026-04-20",
        "next_occurrence": "2026-04-21",
        "data": [
            {
                "type": "events",
                "id": "abc-123",
                "attributes": {
                    "title": "Industriekultur Führung",
                    "slug": "industriekultur-fuehrung",
                    "url": "https://www.zollverein.de/kalender/industriekultur-fuehrung",
                    "image": {"url": "https://zollverein.imgix.net/abc-123/cover.jpeg"},
                },
                "recurring": True,
                "recurrence": {"next": "2026-04-21"},
                "times": [{"all_day": False, "start": "14:00", "end": "16:00", "open_end": False}],
                "content": {
                    "excerpt": {"text": "Geführter Rundgang durch das UNESCO-Welterbe."},
                },
                "terms": [
                    {"type": "terms", "id": "t1", "attributes": {"title": "Familien", "slug": "kinder-und-familien"}},
                ],
                "location": {
                    "type": "locations",
                    "id": "loc-1",
                    "attributes": {"title": "Zollverein Areal A", "slug": "areal-a"},
                },
                "category": {
                    "type": "categories",
                    "id": "cat-1",
                    "attributes": {"title": "Führung", "slug": "fuehrung"},
                },
            }
        ],
    }


def test_zollverein_api_parses_day_response():
    data = _zollverein_day_fixture()
    events = parse_zollverein_api(data, date(2026, 4, 20))
    assert len(events) == 1
    e = events[0]
    assert e["title"] == "Industriekultur Führung"
    assert e["source_url"].startswith("https://www.zollverein.de")
    assert e["start_at"] == datetime(2026, 4, 20, 14, 0)
    assert e["end_at"] == datetime(2026, 4, 20, 16, 0)
    assert e["category"] == "Führung"
    assert e["venue_name"] == "Zollverein Areal A"
    assert e["kids_suitable"] == "yes"
    assert e["image_url"].startswith("https://zollverein.imgix.net")
    assert e["lat"] is not None and e["lon"] is not None


def test_zollverein_api_empty_day_returns_no_events():
    assert parse_zollverein_api({"date": "2026-04-20", "data": []}, date(2026, 4, 20)) == []


def test_zollverein_convert_skips_event_without_title():
    assert convert_zollverein_event({"attributes": {}}, date(2026, 4, 20)) is None


def test_zollverein_convert_canonical_id_includes_date():
    item = _zollverein_day_fixture()["data"][0]
    e1 = convert_zollverein_event(item, date(2026, 4, 20))
    e2 = convert_zollverein_event(item, date(2026, 4, 21))
    assert e1["canonical_id"] != e2["canonical_id"]


def test_zollverein_convert_kids_suitable_no_for_adults_only():
    item = _zollverein_day_fixture()["data"][0]
    item = {**item, "terms": [{"attributes": {"title": "Erwachsene", "slug": "erwachsee"}}]}
    e = convert_zollverein_event(item, date(2026, 4, 20))
    assert e["kids_suitable"] == "no"


def test_zollverein_date_combines_date_and_time():
    assert parse_zollverein_date("2026-05-01", "17:30") == datetime(2026, 5, 1, 17, 30)
    assert parse_zollverein_date("2026-05-01") == datetime(2026, 5, 1, 0, 0)
    assert parse_zollverein_date(None) is None


def test_zollverein_date_returns_naive():
    result = parse_zollverein_date("2026-05-01", "17:00")
    assert result is not None
    assert result.tzinfo is None


def test_zollverein_html_fallback_extracts_event():
    html = """
    <html><body>
      <ul>
        <li class="mb-8 lg:mb-12">
          <h2 class="sr-only"><span class="sr-only">Veranstaltungen am Montag, Mai 20, 2026</span></h2>
          <ul>
            <li class="mb-4">
              <div role="button">
                <div aria-label="Kategorie Ausstellung" class="inline-block">Kategorie</div>
                <span class="sr-only">Veranstaltungszeitraum 10:00 - 18:00 Uhr</span>
                <div class="uppercase tracking-widest">Ruhr Museum</div>
                <h3><a href="/event/abc">Ausstellung Bergbau</a></h3>
                <p class="text-gray-700">Eine Ausstellung über den Bergbau im Ruhrgebiet.</p>
              </div>
            </li>
          </ul>
        </li>
      </ul>
    </body></html>
    """
    events = parse_zollverein_html(html)
    assert len(events) == 1
    e = events[0]
    assert e["title"] == "Ausstellung Bergbau"
    assert e["lat"] is not None  # Zollverein-wide fallback coords
    assert e["venue_name"] == "Ruhr Museum"
    assert e["category"] == "Ausstellung"
    assert e["start_at"] == datetime(2026, 5, 20, 10, 0)
    assert e["end_at"] == datetime(2026, 5, 20, 18, 0)


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


def test_rausgegangen_iso_date_returns_naive():
    from app.services.rausgegangen import parse_iso_date
    result = parse_iso_date("2026-06-01T17:00:00Z")
    assert result is not None
    assert result.tzinfo is None


def test_zollverein_cap_occurrences_limits_daily_exhibitions():
    from datetime import datetime as _dt, timedelta as _td

    from app.services.zollverein import cap_occurrences

    base = _dt(2026, 9, 20, 10, 0)
    daily = [
        {"title": "Dauerausstellung", "source_url": "https://z/a", "start_at": base + _td(days=i)}
        for i in range(120)
    ]
    single = [{"title": "Konzert", "source_url": "https://z/b", "start_at": base}]
    kept = cap_occurrences(daily + single, limit=60)
    assert len(kept) == 61
    assert max(e["start_at"] for e in kept if e["source_url"] == "https://z/a") == base + _td(days=59)


def test_zollverein_day_heading_accepts_german_and_english_months():
    from datetime import date

    from app.services.zollverein import _parse_german_day_heading

    assert _parse_german_day_heading("Veranstaltungen am Sonntag, September 20, 2026") == date(2026, 9, 20)
    assert _parse_german_day_heading("Veranstaltungen am Samstag, October 3, 2026") == date(2026, 10, 3)
    assert _parse_german_day_heading("Veranstaltungen am Samstag, Oktober 3, 2026") == date(2026, 10, 3)
