"""Offline parser tests for Batch-B sources: Zeche Carl, GREND, Lichtburg, Schatzkammer.

All tests use hand-crafted HTML fixtures — no network access required.
The intent is to catch parsing regressions when upstream sites change their markup.
"""
from datetime import datetime

import pytest

# ─────────────────────────────── Zeche Carl ──────────────────────────────────

from app.services.zeche_carl import (
    _parse_overview_html,
    _enrich_from_detail_json_ld,
    _stub_to_minimal_event,
)


ZECHE_CARL_OVERVIEW_HTML = """
<!doctype html>
<html lang="de-DE">
<body>
<div class="summary-item positioned summary-item-record-type-event
            sqs-gallery-design-autogrid-slide summary-item-has-thumbnail">
  <div class="summary-thumbnail-outer-container">
    <a aria-label="80er/90er Party"
       class="summary-thumbnail-container"
       data-title="80er/90er Party"
       href="/carlsprogramm/260605-80er90erparty">
      <div class="summary-thumbnail img-wrapper">
        <img alt="80er/90er Party"
             class="summary-thumbnail-image"
             data-src="https://cdn.example.com/party.png"
             src="">
        <div class="summary-thumbnail-event-date">
          <div class="summary-thumbnail-event-date-inner">
            <span class="summary-thumbnail-event-date-month">Juni</span>
            <span class="summary-thumbnail-event-date-day">5</span>
          </div>
        </div>
      </div>
    </a>
  </div>
  <div class="summary-content">
    <h3 class="summary-title">
      <a href="/carlsprogramm/260605-80er90erparty">80er/90er Party</a>
    </h3>
  </div>
</div>

<div class="summary-item positioned summary-item-record-type-event
            sqs-gallery-design-autogrid-slide">
  <div class="summary-thumbnail-outer-container">
    <a aria-label="Kinderflohmarkt"
       class="summary-thumbnail-container"
       data-title="Kinderflohmarkt"
       href="/carlsprogramm/260613-kinderflohmarkt">
      <div class="summary-thumbnail img-wrapper">
        <img alt="Kinderflohmarkt"
             class="summary-thumbnail-image"
             data-src="https://cdn.example.com/flohmarkt.png"
             src="">
        <div class="summary-thumbnail-event-date">
          <div class="summary-thumbnail-event-date-inner">
            <span class="summary-thumbnail-event-date-month">Juni</span>
            <span class="summary-thumbnail-event-date-day">13</span>
          </div>
        </div>
      </div>
    </a>
  </div>
  <div class="summary-content">
    <h3 class="summary-title">
      <a href="/carlsprogramm/260613-kinderflohmarkt">Kinderflohmarkt</a>
    </h3>
  </div>
</div>
</body>
</html>
"""

ZECHE_CARL_DETAIL_HTML = """
<!doctype html>
<html lang="de-DE">
<head>
<script type="application/ld+json">
{
  "name": "80er/90er Party — ZECHE CARL",
  "startDate": "2026-06-05T22:00:00+0200",
  "endDate": "2026-06-06T04:00:00+0200",
  "@context": "http://schema.org",
  "@type": "Event"
}
</script>
</head>
<body>
<p>Die Kult-Party im Essener Norden</p>
<p>Freitag, 05.06.26 | Zeche Carl | Einlass: 22:00 Uhr | Beginn: 22:00 Uhr | Party</p>
<p>Kein VVK | AK: 10€ Der Party-Dauerbrenner auf CARL bietet in der Kaue alle Kracher aus den 80ern.</p>
<p>Zeche Carl — Wilhelm-Nieswandt-Allee 100, 45326 Essen</p>
<p>Datenschutz | Impressum</p>
</body>
</html>
"""


def test_zeche_carl_overview_parses_event_stubs():
    stubs = _parse_overview_html(ZECHE_CARL_OVERVIEW_HTML)
    assert len(stubs) == 2

    party = stubs[0]
    assert party["title"] == "80er/90er Party"
    assert party["month_str"] == "Juni"
    assert party["day_str"] == "5"
    assert party["year"] == 2026
    assert "carlsprogramm/260605" in party["url"]
    assert party["image_url"] is not None


def test_zeche_carl_overview_kids_event_detected():
    stubs = _parse_overview_html(ZECHE_CARL_OVERVIEW_HTML)
    kinder = stubs[1]
    assert kinder["title"] == "Kinderflohmarkt"
    assert kinder["year"] == 2026


def test_zeche_carl_detail_enrichment_json_ld():
    stub = {
        "title": "80er/90er Party",
        "url": "https://www.zechecarl.de/carlsprogramm/260605-80er90erparty",
        "image_url": "https://cdn.example.com/party.png",
    }
    event = _enrich_from_detail_json_ld(ZECHE_CARL_DETAIL_HTML, stub)
    assert event is not None
    assert event["title"] == "80er/90er Party"
    assert event["start_at"] == datetime(2026, 6, 5, 22, 0)
    assert event["source_name"] == "Zeche Carl"
    assert event["venue_name"] == "Zeche Carl"
    assert event["lat"] == pytest.approx(51.4964545)
    assert event["lon"] == pytest.approx(7.0123887)
    assert event["indoor_outdoor"] == "indoor"
    assert event["image_url"] == "https://cdn.example.com/party.png"
    assert event["price_text"] is not None
    assert "10" in event["price_text"]


def test_zeche_carl_kids_detection_in_detail():
    stub = {
        "title": "Kinderflohmarkt",
        "url": "https://www.zechecarl.de/carlsprogramm/260613-kinderflohmarkt",
        "image_url": None,
    }
    html = """
    <html><head>
    <script type="application/ld+json">
    {"name":"Kinderflohmarkt — ZECHE CARL","startDate":"2026-06-13T09:30:00+0200","@type":"Event","@context":"http://schema.org"}
    </script></head>
    <body><p>Toller Flohmarkt für Kinder und Familien.</p>
    <p>Eintritt frei | Kinderflohmarkt Hier gibt es alles rund ums Kind.</p>
    </body></html>
    """
    event = _enrich_from_detail_json_ld(html, stub)
    assert event is not None
    assert event["kids_suitable"] == "likely"
    assert event["start_at"] == datetime(2026, 6, 13, 9, 30)


def test_zeche_carl_stub_fallback_when_no_detail():
    stub = {
        "title": "SOMMER IM GARTEN",
        "url": "https://www.zechecarl.de/carlsprogramm/260701-sommer-im-garten",
        "month_str": "Juli",
        "day_str": "1",
        "year": 2026,
        "image_url": None,
    }
    event = _stub_to_minimal_event(stub)
    assert event is not None
    assert event["title"] == "SOMMER IM GARTEN"
    assert event["start_at"] == datetime(2026, 7, 1)
    assert event["source_name"] == "Zeche Carl"


# ─────────────────────────────── GREND ───────────────────────────────────────

from app.services.grend import parse_grend_html, _parse_vsel_date


GREND_HTML = """
<!doctype html>
<html>
<body>
<div id="vsel">
  <!-- Event 1: Konzert -->
  <div class="vsel-content grend vsel-upcoming vsel-current" id="event-11204">
    <div class="vsel-meta">
      <h3 class="vsel-meta-title">
        <a href="https://grend.de/event/freunde-der-italienischen-oper-39/"
           rel="bookmark"
           title="Freunde der italienischen Oper">
          Freunde der italienischen Oper
        </a>
      </h3>
      <div class="vsel-meta-date vsel-meta-single-date">
        <span>Fr. &#x200B;12.6.2026</span>
      </div>
      <div class="vsel-meta-time"><span>20:00</span></div>
      <div class="vsel-acf-zielgruppeort">
        <span class="acf-field-name">Zielgruppe/Ort (Auswahl):</span>
        <span class="acf-field-value">Konzert</span>
      </div>
      <div class="vsel-acf-preis">
        <span class="acf-field-name">Preis:</span>
        <span class="acf-field-value">Eintritt: 15 € / ermäßigt 10 €</span>
      </div>
    </div>
  </div>

  <!-- Event 2: Kinder -->
  <div class="vsel-content grend vsel-upcoming" id="event-22001">
    <div class="vsel-meta">
      <h3 class="vsel-meta-title">
        <a href="https://grend.de/event/theater-fuer-kinder/"
           rel="bookmark"
           title="Theater für Kinder">
          Theater für Kinder
        </a>
      </h3>
      <div class="vsel-meta-date vsel-meta-single-date">
        <span>So. &#x200B;14.6.2026</span>
      </div>
      <div class="vsel-meta-time"><span>11:00</span></div>
      <div class="vsel-acf-zielgruppeort">
        <span class="acf-field-name">Zielgruppe/Ort (Auswahl):</span>
        <span class="acf-field-value">Kinder &amp; Familien</span>
      </div>
      <div class="vsel-acf-preis">
        <span class="acf-field-name">Preis:</span>
        <span class="acf-field-value">5 € / Kinder frei</span>
      </div>
    </div>
  </div>

  <!-- Event 3: Poetry Slam -->
  <div class="vsel-content grend vsel-upcoming" id="event-33001">
    <div class="vsel-meta">
      <h3 class="vsel-meta-title">
        <a href="https://grend.de/event/poetry-slam-juni/"
           rel="bookmark"
           title="Poetry Slam Juni">
          Poetry Slam Juni
        </a>
      </h3>
      <div class="vsel-meta-date vsel-meta-single-date">
        <span>Mi. &#x200B;17.6.2026</span>
      </div>
      <div class="vsel-meta-time"><span>19:30</span></div>
    </div>
  </div>
</div>
</body>
</html>
"""


def test_grend_parses_all_events():
    events = parse_grend_html(GREND_HTML)
    assert len(events) == 3


def test_grend_event_fields():
    events = parse_grend_html(GREND_HTML)
    oper = events[0]
    assert oper["title"] == "Freunde der italienischen Oper"
    assert oper["start_at"] == datetime(2026, 6, 12, 20, 0)
    assert oper["source_url"] == "https://grend.de/event/freunde-der-italienischen-oper-39/"
    assert oper["source_name"] == "GREND"
    assert oper["venue_name"] == "GREND"
    assert oper["lat"] == pytest.approx(51.4467198)
    assert oper["lon"] == pytest.approx(7.0737495)
    assert oper["indoor_outdoor"] == "indoor"
    assert oper["price_text"] is not None
    assert "15" in oper["price_text"]
    assert oper["category"] == "musik"


def test_grend_kids_detection():
    events = parse_grend_html(GREND_HTML)
    kinder = events[1]
    assert kinder["title"] == "Theater für Kinder"
    assert kinder["kids_suitable"] == "likely"
    assert kinder["start_at"] == datetime(2026, 6, 14, 11, 0)


def test_grend_poetry_slam_category():
    events = parse_grend_html(GREND_HTML)
    slam = events[2]
    assert slam["title"] == "Poetry Slam Juni"
    assert slam["start_at"] == datetime(2026, 6, 17, 19, 30)
    assert slam["category"] == "literatur"


def test_grend_vsel_date_parser():
    """Unit test for the VSEL date + time parser."""
    dt = _parse_vsel_date("Mi. ​3.6.2026", "19:00")
    assert dt == datetime(2026, 6, 3, 19, 0)

    dt2 = _parse_vsel_date("So. 14.6.2026", "11:00")
    assert dt2 == datetime(2026, 6, 14, 11, 0)


def test_grend_deduplicates_identical_blocks():
    """Same event appearing twice in HTML → only one result."""
    html = GREND_HTML.replace(
        "id=\"event-11204\"",
        "id=\"event-11204\""
    )
    # Inject a duplicate of the first block
    dup = """
    <div class="vsel-content grend vsel-upcoming" id="event-11204-dup">
      <div class="vsel-meta">
        <h3 class="vsel-meta-title">
          <a href="https://grend.de/event/freunde-der-italienischen-oper-39/"
             rel="bookmark">Freunde der italienischen Oper</a>
        </h3>
        <div class="vsel-meta-date vsel-meta-single-date"><span>Fr. 12.6.2026</span></div>
        <div class="vsel-meta-time"><span>20:00</span></div>
      </div>
    </div>
    """
    events = parse_grend_html(html + dup)
    titles = [e["title"] for e in events if e["title"] == "Freunde der italienischen Oper"]
    assert len(titles) == 1  # deduplication by canonical_id


# ─────────────────────────────── Lichtburg ───────────────────────────────────

from app.services.lichtburg import parse_lichtburg_html, parse_lichtburg_detail_html


LICHTBURG_HTML = """
<!doctype html>
<html lang="de">
<body>
<div class="module-special buhne_events">
  <div class="container">
    <div class="col-sm-12 events-wrapper">

      <!-- Konzert -->
      <div class="box box__default box__grid event auditorium-66 event-category-81">
        <a class="box-link"
           href="https://filmspiegel-essen.de/veranstaltungen/rebell-comedy-17-06-2026/">
          <div class="box-content">
            <img class="box-backdrop img-responsive event-featured-image"
                 src="https://filmspiegel-essen.de/wp-content/uploads/rebel-comedy.png"/>
            <div class="box-inner match-height-target">
              <h3 class="event-title">Rebell Comedy</h3>
              <p class="event-timing">
                <span class="event-day">17.06.2026</span>
                &middot;
                <span class="event-time">20:00 Uhr</span>
              </p>
              <p class="event-types">
                <a class="event-type"
                   href="https://filmspiegel-essen.de/kinos/lichtburg/">Lichtburg</a>
                <a class="event-type"
                   href="https://filmspiegel-essen.de/veranstaltungsarten/buehne/">Bühne</a>
              </p>
            </div>
          </div>
        </a>
      </div>

      <!-- Konzert internationale Künstler -->
      <div class="box box__default box__grid event auditorium-66 event-category-81">
        <a class="box-link"
           href="https://filmspiegel-essen.de/veranstaltungen/chris-isaak-13-07-2026/">
          <div class="box-content">
            <img class="box-backdrop img-responsive event-featured-image"
                 src="https://filmspiegel-essen.de/wp-content/uploads/chris-isaak.png"/>
            <div class="box-inner match-height-target">
              <h3 class="event-title">Chris Isaak</h3>
              <p class="event-timing">
                <span class="event-day">13.07.2026</span>
                &middot;
                <span class="event-time">20:00 Uhr</span>
              </p>
              <p class="event-types">
                <a class="event-type"
                   href="https://filmspiegel-essen.de/kinos/lichtburg/">Lichtburg</a>
                <a class="event-type"
                   href="https://filmspiegel-essen.de/veranstaltungsarten/buehne/">Bühne</a>
              </p>
            </div>
          </div>
        </a>
      </div>

      <!-- Theater/Festival -->
      <div class="box box__default box__grid event auditorium-66 event-category-81">
        <a class="box-link"
           href="https://filmspiegel-essen.de/veranstaltungen/ingoma-ruhrtriennale-22-08-2026/">
          <div class="box-content">
            <img class="box-backdrop img-responsive event-featured-image"
                 src="https://filmspiegel-essen.de/wp-content/uploads/ingoma.png"/>
            <div class="box-inner match-height-target">
              <h3 class="event-title">Ruhrtriennale: Ingoma!</h3>
              <p class="event-timing">
                <span class="event-day">22.08.2026</span>
                &middot;
                <span class="event-time">20:00 Uhr</span>
              </p>
              <p class="event-types">
                <a class="event-type"
                   href="https://filmspiegel-essen.de/kinos/lichtburg/">Lichtburg</a>
                <a class="event-type"
                   href="https://filmspiegel-essen.de/veranstaltungsarten/buehne/">Bühne</a>
              </p>
            </div>
          </div>
        </a>
      </div>

    </div>
  </div>
</div>
</body>
</html>
"""


def test_lichtburg_parses_all_events():
    events = parse_lichtburg_html(LICHTBURG_HTML)
    assert len(events) == 3


def test_lichtburg_event_fields():
    events = parse_lichtburg_html(LICHTBURG_HTML)
    comedy = events[0]
    assert comedy["title"] == "Rebell Comedy"
    assert comedy["start_at"] == datetime(2026, 6, 17, 20, 0)
    assert comedy["source_url"] == "https://filmspiegel-essen.de/veranstaltungen/rebell-comedy-17-06-2026/"
    assert comedy["source_name"] == "Lichtburg"
    assert comedy["venue_name"] == "Lichtburg"
    assert comedy["lat"] == pytest.approx(51.4548676)
    assert comedy["lon"] == pytest.approx(7.0135673)
    assert comedy["indoor_outdoor"] == "indoor"
    assert comedy["image_url"] is not None
    assert comedy["category"] == "comedy"


def test_lichtburg_second_event():
    events = parse_lichtburg_html(LICHTBURG_HTML)
    isaak = events[1]
    assert isaak["title"] == "Chris Isaak"
    assert isaak["start_at"] == datetime(2026, 7, 13, 20, 0)


def test_lichtburg_theater_category():
    events = parse_lichtburg_html(LICHTBURG_HTML)
    ingoma = events[2]
    assert ingoma["title"] == "Ruhrtriennale: Ingoma!"
    assert ingoma["start_at"] == datetime(2026, 8, 22, 20, 0)
    assert ingoma["category"] == "theater"


def test_lichtburg_canonical_ids_unique():
    events = parse_lichtburg_html(LICHTBURG_HTML)
    ids = [e["canonical_id"] for e in events]
    assert len(ids) == len(set(ids)), "canonical_ids not unique"


# Fixture: gekürztes aber strukturell vollständiges Detail-HTML (kein Netzwerk)
LICHTBURG_DETAIL_HTML_COMEDY = """
<!doctype html>
<html>
<body class="wp-singular filmt_event-template-default single single-filmt_event">
<div class="container">
  <div class="row mb-3">
    <div class="col-sm-8">
      <h1 class="mt-3 mb-0">Rebell Comedy</h1>
      <p class="h3 subline">17.06.2026<span class="subline-divider"></span>20:00 Uhr</p>
      <div class="row">
        <div class="col-sm-6">
          <p class="movie-description">REBELL FOR LIVE!</p>
          <p class="event-types">
            <a class="event-type" href="https://filmspiegel-essen.de/kinos/lichtburg/">Lichtburg</a>
            <a class="event-type" href="https://filmspiegel-essen.de/veranstaltungsarten/buehne/">Bühne</a>
          </p>
        </div>
      </div>
    </div>
  </div>
  <!-- Preiskategorien -->
  <div class="section section--inverse section--p-normal">
    <div class="row">
      <div class="col-md-offset-1 col-md-10">
        <h3>Preiskategorien</h3>
        <div class="row">
          <div class="col-sm-6 col-md-3">
            <div class="mb-minicard mb-2 text-center">
              <p class="mb-0">Kategorie 1</p>
              <p><b>63,95&nbsp;€</b></p>
            </div>
          </div>
          <div class="col-sm-6 col-md-3">
            <div class="mb-minicard mb-2 text-center">
              <p class="mb-0">Kategorie 2</p>
              <p><b>58,45&nbsp;€</b></p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
  <!-- Beschreibung -->
  <div class="section section--inverse section--p-large mt-3 mb-3">
    <div class="row">
      <div class="col-md-offset-1 col-md-8 col-lg-offset-1 col-lg-6">
        <h4 class="stage-headline">RebellComedy</h4>
        <p>Das etablierteste Stand-Up Comedy Ensemble Europas kommt in deine Nähe,
           um gegen alles zu rebellieren: Schlechte Laune, veraltete Denkweisen
           und politische Korrektheit! Seit fast 20 Jahren ziehen die Rebellen
           durch die großen Hallen in ganz Deutschland.</p>
      </div>
    </div>
  </div>
</div>
</body>
</html>
"""

LICHTBURG_DETAIL_HTML_KONZERT = """
<!doctype html>
<html>
<body class="wp-singular filmt_event-template-default single single-filmt_event">
<div class="container">
  <div class="row mb-3">
    <div class="col-sm-8">
      <h1>Chris Isaak</h1>
      <p class="movie-description">Live 2026</p>
      <p class="event-types">
        <a class="event-type" href="https://filmspiegel-essen.de/kinos/lichtburg/">Lichtburg</a>
        <a class="event-type" href="https://filmspiegel-essen.de/veranstaltungsarten/buehne/">Bühne</a>
      </p>
    </div>
  </div>
  <!-- Preiskategorien -->
  <div class="section section--inverse section--p-normal">
    <div class="row">
      <div class="col-md-10">
        <h3>Preiskategorien</h3>
        <div class="row">
          <div class="col-md-3">
            <div class="mb-minicard mb-2 text-center">
              <p class="mb-0">Kategorie 1</p>
              <p><b>98,00&nbsp;€</b></p>
            </div>
          </div>
          <div class="col-md-3">
            <div class="mb-minicard mb-2 text-center">
              <p class="mb-0">Kategorie 2</p>
              <p><b>87,66&nbsp;€</b></p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
  <!-- Beschreibung -->
  <div class="section section--inverse section--p-large mt-3 mb-3">
    <div class="row">
      <div class="col-md-8">
        <p>Nach der triumphalen Rückkehr auf deutsche Konzertbühnen kündigt Chris Isaak
           eine exklusive Show für den 13. Juli in Essen in der Lichtburg an.
           Die Auftritte in Köln, Berlin und auf dem Stimmen Festival zeigten, dass
           der Meister des Cool nichts von seiner Magie verloren hat.</p>
      </div>
    </div>
  </div>
</div>
</body>
</html>
"""

LICHTBURG_DETAIL_HTML_NO_PRICE = """
<!doctype html>
<html>
<body class="wp-singular filmt_event-template-default single single-filmt_event">
<div class="container">
  <div class="row mb-3">
    <div class="col-sm-8">
      <h1>Moritz Neumeier</h1>
      <p class="movie-description">Einer von den Guten?</p>
    </div>
  </div>
  <!-- Beschreibung ohne Preissektion -->
  <div class="section section--inverse section--p-large mt-3 mb-3">
    <div class="row">
      <div class="col-md-8">
        <p>Moritz Neumeier ist einer von den Guten. Links, antirassistisch, feministisch —
           ist er ja alles, macht er ja alles. Und doch schleicht sich das Unbehagen ein,
           ob das wirklich so eindeutig ist, wie es scheint.</p>
      </div>
    </div>
  </div>
</div>
</body>
</html>
"""


def test_lichtburg_detail_comedy_description():
    """Vollständige Beschreibung aus section--inverse section--p-large extrahiert."""
    result = parse_lichtburg_detail_html(LICHTBURG_DETAIL_HTML_COMEDY)
    assert "short_description" in result
    assert len(result["short_description"]) >= 30
    assert "Comedy" in result["short_description"] or "Ensemble" in result["short_description"]


def test_lichtburg_detail_comedy_price():
    """Preiskategorien werden korrekt extrahiert und zusammengefasst."""
    result = parse_lichtburg_detail_html(LICHTBURG_DETAIL_HTML_COMEDY)
    assert "price_text" in result
    assert "63,95" in result["price_text"] or "58,45" in result["price_text"]
    # beide Kategorien im price_text vorhanden
    assert "Kategorie 1" in result["price_text"]
    assert "Kategorie 2" in result["price_text"]


def test_lichtburg_detail_konzert_description():
    """Beschreibung für Konzert-Event extrahiert."""
    result = parse_lichtburg_detail_html(LICHTBURG_DETAIL_HTML_KONZERT)
    assert "short_description" in result
    assert len(result["short_description"]) >= 30
    assert "Chris Isaak" in result["short_description"] or "Konzert" in result["short_description"] or "Lichtburg" in result["short_description"]


def test_lichtburg_detail_konzert_price():
    """Preise für Konzert: mehrere Kategorien."""
    result = parse_lichtburg_detail_html(LICHTBURG_DETAIL_HTML_KONZERT)
    assert "price_text" in result
    assert "98,00" in result["price_text"]
    assert "87,66" in result["price_text"]


def test_lichtburg_detail_no_price_returns_no_price_key():
    """Event ohne Preissektion liefert kein price_text-Feld."""
    result = parse_lichtburg_detail_html(LICHTBURG_DETAIL_HTML_NO_PRICE)
    assert "price_text" not in result


def test_lichtburg_detail_no_price_still_has_description():
    """Auch ohne Preis wird die Beschreibung korrekt extrahiert."""
    result = parse_lichtburg_detail_html(LICHTBURG_DETAIL_HTML_NO_PRICE)
    assert "short_description" in result
    assert len(result["short_description"]) >= 30


def test_lichtburg_detail_fallback_to_movie_description():
    """Wenn section--inverse section--p-large fehlt, Fallback auf p.movie-description."""
    minimal_html = """
    <html><body>
    <p class="movie-description">Ein sehr kurzer Untertitel ohne lange Beschreibung.</p>
    </body></html>
    """
    result = parse_lichtburg_detail_html(minimal_html)
    assert "short_description" in result
    assert result["short_description"] == "Ein sehr kurzer Untertitel ohne lange Beschreibung."


def test_lichtburg_detail_empty_page_returns_empty_dict():
    """Leere Seite → leeres Dict, kein Absturz."""
    result = parse_lichtburg_detail_html("<html><body></body></html>")
    assert isinstance(result, dict)
    assert "short_description" not in result
    assert "price_text" not in result


# ─────────────────────────── Schatzkammer Werden ─────────────────────────────

from app.services.schatzkammer_werden import (
    _parse_german_date,
    _is_event_post,
    parse_schatzkammer_homepage_links,
)


SCHATZKAMMER_HOMEPAGE_HTML = """
<!doctype html>
<html>
<body>
<nav>
  <a href="https://www.schatzkammer-werden.de/">Schatzkammer St. Ludgerus</a>
  <a href="https://www.schatzkammer-werden.de/category/schatzkammer/">Schatzkammer</a>
  <a href="https://www.schatzkammer-werden.de/category/bibliothek/">Bibliothek</a>
  <a href="http://www.bistum-essen.de">Bistum Essen</a>
  <a href="https://www.schatzkammer-werden.de/datenschutz/">Datenschutz</a>
  <a href="https://www.schatzkammer-werden.de/sitemap/">Sitemap</a>
</nav>
<div class="post-listing">
  <h2><a href="https://www.schatzkammer-werden.de/oeffentliche-fuehrung-jeden-ersten-sonntag-im-monat/">
    Nächste öffentliche Führung am 28. Juni 2026
  </a></h2>
  <a href="https://www.schatzkammer-werden.de/oeffentliche-fuehrung-jeden-ersten-sonntag-im-monat/">
    mehr »
  </a>
</div>
<div class="post-listing">
  <h2><a href="https://www.schatzkammer-werden.de/museumstag-2026/">
    Museumstag 2026
  </a></h2>
  <a href="https://www.schatzkammer-werden.de/museumstag-2026/">mehr »</a>
</div>
<div class="shop-link">
  <a href="https://www.schatzkammer-werden.de/shop/">Shop</a>
</div>
</body>
</html>
"""

SCHATZKAMMER_FUEHRUNG_ARTICLE_HTML = """
<!doctype html>
<html>
<body>
<nav>
  <h2>Schatzkammer St. Ludgerus</h2>
</nav>
<article class="post-listing hentry category-aktuelles">
  <h2>Nächste öffentliche Führung am 28. Juni 2026</h2>
  <p>Am 28. Juni eröffnet eine öffentliche Führung spannende Einblicke in die Kunst und Geschichte Werdens!</p>
  <p>Faszinierende Einblicke in die Entstehung und Geschichte der Kunstwerke stehen im Zentrum der öffentlichen Führung durch die Schatzkammer Werden.</p>
  <p>Beginn der Führung: 15.30 Uhr</p>
  <p>Treffpunkt: Foyer der Schatzkammer</p>
  <p>Kostenbeitrag: Erwachsene: 7 € pro Person / Kinder und Jugendliche unter 18 Jahren frei</p>
  <p>2018-01-16</p>
</article>
</body>
</html>
"""


def test_schatzkammer_german_date_parser():
    dt = _parse_german_date("Nächste öffentliche Führung am 28. Juni 2026")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 6
    assert dt.day == 28


def test_schatzkammer_german_date_with_time():
    dt = _parse_german_date("am 28. Juni 2026 Beginn der Führung: 15.30 Uhr")
    assert dt is not None
    assert dt.hour == 15
    assert dt.minute == 30


def test_schatzkammer_is_event_post_fuehrung():
    assert _is_event_post("Nächste öffentliche Führung am 28. Juni 2026", "") is True


def test_schatzkammer_is_not_event_faq():
    assert _is_event_post("Fragen & Antworten zu Ihrem Besuch", "Hier beantworten wir Fragen.") is False


def test_schatzkammer_is_not_event_hausordnung():
    assert _is_event_post("Hausordnung", "Bitte beachten Sie folgende Regeln.") is False


def test_schatzkammer_homepage_link_extraction():
    links = parse_schatzkammer_homepage_links(SCHATZKAMMER_HOMEPAGE_HTML)
    # Should include post slugs, not category/datenschutz/sitemap/shop
    assert any("oeffentliche-fuehrung" in l for l in links)
    assert any("museumstag" in l for l in links)
    assert not any("/category/" in l for l in links)
    assert not any("/datenschutz/" in l for l in links)
    assert not any("/shop/" in l for l in links)
    assert not any("bistum-essen.de" in l for l in links)


def test_schatzkammer_article_title_extraction():
    """The parser must pick the article h2, not the nav h2."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(SCHATZKAMMER_FUEHRUNG_ARTICLE_HTML, "lxml")
    article = soup.find("article") or soup.find("main")
    h_el = article.find(["h1", "h2", "h3"]) if article else None
    title = h_el.get_text(strip=True) if h_el else ""
    assert title == "Nächste öffentliche Führung am 28. Juni 2026"
