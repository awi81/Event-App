"""Offline parser tests for the Theater an der Ruhr source (no network)."""
from datetime import date, datetime

import pytest

from app.services.theater_an_der_ruhr import (
    _apply_detail,
    _resolve_date,
    parse_detail_html,
    parse_spielplan_html,
)

# Gekuerzte, aus der echten Seite abgeleitete Fixture. Jahre liegen weit in der
# Zukunft; die Tests injizieren ein passendes `now`. Wochentage stimmen mit dem
# Kalender 2031 ueberein (Jahr wird anhand des Wochentags gewaehlt).
# 2031-10-24 = Fr, 2031-11-07 = Fr, 2031-11-08 = Sa, 2031-11-12 = Mi,
# 2031-11-28 = Fr, 2031-10-10 = Fr.
NOW = datetime(2031, 10, 20, 9, 0)

LIST_HTML = """
<div class="schedule">
 <div class="schedule__items js-schedule-items">
  <div class="schedule__item" data-month="10"><div class="schedule__content">
    <div class="schedule__month">Oktober</div></div></div>

  <article class="schedule__item schedule__item--featured-none" data-href="/de/kalender/stuecke/10736-hass-misos-ur">
   <div class="schedule__content">
    <div class="schedule__top">
     <div class="schedule__top-item schedule__top-item--date"><span>Fr 24.10. 19:30</span></div>
     <div class="schedule__top-item schedule__top-item--title"><span>Theater an der Ruhr</span></div>
    </div>
    <div class="schedule__middle">
     <div class="schedule__middle-tags"><div class="schedule__middle-tag">ZwischenStücke</div></div>
     <h1 class="schedule__middle-title"><a href="/de/kalender/stuecke/10736-hass-misos-ur">Hass / Μίσος / Ură</a></h1>
     <div class="schedule__middle-subtitle"><p>nach dem Film „La Haine“&nbsp;von Mathieu&nbsp;Kassovitz<br>
Gastspiel Theaterhaus Jena</p></div>
    </div>
    <div class="schedule__bottom">
     <a href="/de/kalender/stuecke/10736-hass-misos-ur" class="icon-link schedule__bottom-item">Mehr</a>
     <a href="https://example.invalid/tickets" class="icon-link schedule__bottom-item">Karten</a>
    </div>
   </div>
  </article>

  <article class="schedule__item" data-href="/de/kalender/stuecke/10238-theater-trifft-escape-room">
   <div class="schedule__content">
    <div class="schedule__top">
     <div class="schedule__top-item schedule__top-item--date"><span>Mi 22.10. 11:00</span></div>
     <div class="schedule__top-item schedule__top-item--title"><span>Willy Brandt Schule Mülheim</span></div>
    </div>
    <div class="schedule__middle">
     <h1 class="schedule__middle-title"><a href="/de/kalender/stuecke/10238-theater-trifft-escape-room">Theater trifft Escape Room</a></h1>
     <div class="schedule__middle-subtitle"><p>Theaterprojekt in den Herbstferien für 10- bis 14-Jährige<br>Kulturrucksack NRW</p></div>
    </div>
    <div class="schedule__bottom">
     <a href="/de/kalender/stuecke/10238-theater-trifft-escape-room" class="icon-link schedule__bottom-item">Mehr</a>
     <span class="schedule__bottom-item">Eintritt frei</span>
    </div>
   </div>
  </article>

  <article class="schedule__item" data-href="/de/kalender/stuecke/10654-die-nashrner-rhinocros">
   <div class="schedule__content">
    <div class="schedule__top">
     <div class="schedule__top-item schedule__top-item--date"><span>Fr 7.11. 19:00</span><br><span class="no-line-through">Premiere</span></div>
     <div class="schedule__top-item schedule__top-item--title"><span>Probebühne</span></div>
    </div>
    <div class="schedule__middle">
     <h1 class="schedule__middle-title"><a href="/de/kalender/stuecke/10654-die-nashrner-rhinocros">Die Nashörner (Rhinocéros)</a></h1>
     <div class="schedule__middle-subtitle"><p>Stück in 3 Akten von Eugène Ionesco</p><p>Labor II des Jungen Theater an der Ruhr</p></div>
    </div>
   </div>
  </article>

  <!-- vergangen: Fr 10.10. liegt vor NOW, naechstes Vorkommen waere 2032 (> 120 Tage) -->
  <article class="schedule__item" data-href="/de/kalender/stuecke/1-altes">
   <div class="schedule__content">
    <div class="schedule__top">
     <div class="schedule__top-item schedule__top-item--date"><span>Fr 10.10. 20:00</span></div>
     <div class="schedule__top-item schedule__top-item--title"><span>Theater an der Ruhr</span></div>
    </div>
    <div class="schedule__middle">
     <h1 class="schedule__middle-title"><a href="/de/kalender/stuecke/1-altes">Altes Stück</a></h1>
    </div>
   </div>
  </article>
 </div>
</div>

<div class="schedule2">
 <div class="schedule2__date">
  <span class="schedule2__date--upper">Fr 07.11.</span>
  <span class="schedule2__date--lower">Fr 07.11.</span>
 </div>
 <div class="schedule2__above"><div class="schedule2-columns"><div class="schedule2-column">
  <div class="schedule2-item schedule2-item--small" data-href="/de/kalender/stuecke/10681-chaos">
   <div class="schedule2-item__content">
    <div class="schedule2-item__top"><div class="schedule2-item__top-date">ab 18:30</div>
     <div class="schedule2-item__top-label">Rahmenprogramm</div></div>
    <div class="schedule2-item__middle"><h1 class="schedule2-item__middle-title"><a href="/de/kalender/stuecke/10681-chaos">chaos macht ordnung</a></h1></div>
   </div></div>
 </div></div></div>
 <div class="schedule2__container"><div class="schedule2-columns"><div class="schedule2-column">
  <div class="schedule2-item schedule2-item--absolute" data-href="/de/kalender/stuecke/10631-lenz-jahrmarkt-der-verlorenen">
   <div class="schedule2-item__content">
    <div class="schedule2-item__top"><div class="schedule2-item__top-date">19:30-21:30</div>
     <div class="schedule2-item__top-label">Hauptprogramm</div></div>
    <div class="schedule2-item__middle">
     <span class="schedule2-item__middle-attributes">Premiere</span>
     <h1 class="schedule2-item__middle-title"><a href="/de/kalender/stuecke/10631-lenz-jahrmarkt-der-verlorenen">Lenz – Jahrmarkt der Verlorenen</a></h1>
     <h2 class="schedule2-item__middle-subtitle"><p>Nach Georg Büchner<br>Regie: Roberto Ciulli</p></h2>
    </div>
   </div></div>
 </div></div></div>
</div>

<div class="schedule2">
 <div class="schedule2__date">
  <span class="schedule2__date--upper">Sa 08.11.</span>
 </div>
 <div class="schedule2__container"><div class="schedule2-columns"><div class="schedule2-column">
  <div class="schedule2-item schedule2-item--absolute" data-href="/de/kalender/stuecke/10631-lenz-jahrmarkt-der-verlorenen">
   <div class="schedule2-item__content">
    <div class="schedule2-item__top"><div class="schedule2-item__top-date">19:30-21:30</div>
     <div class="schedule2-item__top-label">Hauptprogramm</div></div>
    <div class="schedule2-item__middle">
     <h1 class="schedule2-item__middle-title"><a href="/de/kalender/stuecke/10631-lenz-jahrmarkt-der-verlorenen">Lenz – Jahrmarkt der Verlorenen</a></h1>
    </div>
   </div></div>
 </div></div></div>
</div>

<div class="schedule2">
 <div class="schedule2__date"><span class="schedule2__date--upper">Fr 28.11.</span></div>
 <div class="schedule2__container"><div class="schedule2-columns"><div class="schedule2-column">
  <div class="schedule2-item" data-href="/de/kalender/stuecke/10700-ein-volksbuerger">
   <div class="schedule2-item__content">
    <div class="schedule2-item__top"><div class="schedule2-item__top-date">17:00-19:00</div>
     <div class="schedule2-item__top-label">Special</div></div>
    <div class="schedule2-item__middle">
     <h1 class="schedule2-item__middle-title"><a href="/de/kalender/stuecke/10700-ein-volksbuerger">Ein Volksbürger</a></h1>
    </div>
   </div></div>
 </div></div></div>
</div>
"""

DETAIL_HTML = """
<html><head>
<meta name="Description" content="Hass // Gastspiel Theaterhaus Jena // ab 16 Jahre // Rückbank eines Citroën.">
<meta property="og:image" content="https://www.theateranderruhr.de/images/Hass.jpg?w=2000">
</head><body>
<div class="article-column article-column--details"><h3>Informationen</h3>
<h4>Ort</h4><p>Theater an der Ruhr<br>Akazienallee 61<br>45478 Mülheim an der Ruhr</p></div>
</body></html>
"""

DETAIL_EXTERN_HTML = """
<html><head><meta name="Description" content="Projekt in der Schule."></head><body>
<h4>Ort</h4><p>Willy Brandt Schule<br>Dohne 90<br>45468 Mülheim an der Ruhr</p>
</body></html>
"""


def _by_title(events, title):
    return [e for e in events if e["title"] == title]


def test_counts_and_titles():
    events = parse_spielplan_html(LIST_HTML, now=NOW)
    titles = sorted({e["title"] for e in events})
    assert titles == [
        "Die Nashörner (Rhinocéros)",
        "Ein Volksbürger",
        "Hass / Μίσος / Ură",
        "Lenz – Jahrmarkt der Verlorenen",
        "Theater trifft Escape Room",
    ]
    # 3 Listenstuecke + Lenz (2 Tage) + Volksbuerger; Rahmenprogramm und
    # vergangener Termin fallen raus
    assert len(events) == 6
    assert len({e["canonical_id"] for e in events}) == 6


def test_list_event_fields():
    ev = _by_title(parse_spielplan_html(LIST_HTML, now=NOW), "Hass / Μίσος / Ură")[0]
    assert ev["start_at"] == datetime(2031, 10, 24, 19, 30)
    assert ev["end_at"] is None
    assert ev["venue_name"] == "Theater an der Ruhr"
    assert ev["city"] == "Mülheim an der Ruhr"
    assert ev["address_text"].startswith("Akazienallee 61")
    assert ev["lat"] == pytest.approx(51.4388872)
    assert ev["lon"] == pytest.approx(6.8226813)
    assert ev["category"] == "ZwischenStücke"
    assert ev["source_name"] == "Theater an der Ruhr"
    assert ev["source_url"].endswith("/de/kalender/stuecke/10736-hass-misos-ur")
    assert ev["indoor_outdoor"] == "indoor"
    assert "Gastspiel Theaterhaus Jena" in ev["short_description"]
    assert len(ev["canonical_id"]) == 16


def test_year_is_inferred_from_weekday():
    # "Fr 7.11." ohne Jahr -> 2031 (Freitag), nicht 2032
    ev = _by_title(parse_spielplan_html(LIST_HTML, now=NOW), "Die Nashörner (Rhinocéros)")[0]
    assert ev["start_at"] == datetime(2031, 11, 7, 19, 0)
    assert "Premiere" in ev["short_description"]
    assert ev["venue_name"] == "Probebühne"  # eigener Ort (Ruhrorter Str.), keine Hauskoordinaten
    assert ev["lat"] is None
    assert _resolve_date("Fr", 7, 11, NOW) == date(2031, 11, 7)
    assert _resolve_date(None, 10, 10, NOW) == date(2032, 10, 10)  # naechstes Vorkommen


def test_festival_grid_times_and_end_at():
    lenz = sorted(
        _by_title(parse_spielplan_html(LIST_HTML, now=NOW), "Lenz – Jahrmarkt der Verlorenen"),
        key=lambda e: e["start_at"],
    )
    assert [e["start_at"] for e in lenz] == [
        datetime(2031, 11, 7, 19, 30),
        datetime(2031, 11, 8, 19, 30),
    ]
    assert lenz[0]["end_at"] == datetime(2031, 11, 7, 21, 30)
    assert lenz[0]["category"] == "Hauptprogramm"
    assert lenz[0]["short_description"].startswith("Premiere")
    special = _by_title(parse_spielplan_html(LIST_HTML, now=NOW), "Ein Volksbürger")[0]
    assert special["category"] == "Special"
    assert special["start_at"] == datetime(2031, 11, 28, 17, 0)


def test_rahmenprogramm_and_past_dates_are_skipped():
    events = parse_spielplan_html(LIST_HTML, now=NOW)
    titles = {e["title"] for e in events}
    assert "chaos macht ordnung" not in titles
    assert "Altes Stück" not in titles


def test_external_venue_has_no_fixed_coordinates():
    ev = _by_title(parse_spielplan_html(LIST_HTML, now=NOW), "Theater trifft Escape Room")[0]
    assert ev["venue_name"] == "Willy Brandt Schule Mülheim"
    assert ev["lat"] is None and ev["lon"] is None
    assert "Mülheim" in ev["address_text"]
    assert ev["price_text"] == "Eintritt frei"
    assert ev["start_at"] == datetime(2031, 10, 22, 11, 0)


def test_kids_detection():
    events = parse_spielplan_html(LIST_HTML, now=NOW)
    assert _by_title(events, "Theater trifft Escape Room")[0]["kids_suitable"] == "yes"
    assert _by_title(events, "Hass / Μίσος / Ură")[0]["kids_suitable"] == "unknown"
    # Reiter "Junges Theater": ohne weiteres Kinder-Stichwort -> likely
    jt = parse_spielplan_html(LIST_HTML, now=NOW, junges_theater=True)
    assert _by_title(jt, "Die Nashörner (Rhinocéros)")[0]["kids_suitable"] == "likely"


def test_window_shifts_with_now():
    later = datetime(2031, 11, 8, 12, 0)
    events = parse_spielplan_html(LIST_HTML, now=later)
    lenz = _by_title(events, "Lenz – Jahrmarkt der Verlorenen")
    assert [e["start_at"] for e in lenz] == [datetime(2031, 11, 8, 19, 30)]
    assert not _by_title(events, "Hass / Μίσος / Ură")


def test_far_future_is_cut_off():
    far = datetime(2031, 6, 1, 9, 0)  # alle Termine > 120 Tage entfernt
    assert parse_spielplan_html(LIST_HTML, now=far) == []


def test_empty_html_returns_empty_list():
    assert parse_spielplan_html("<html><body></body></html>", now=NOW) == []


def test_detail_enrichment_home_venue():
    detail = parse_detail_html(DETAIL_HTML)
    assert detail["image_url"].endswith("Hass.jpg?w=2000")
    assert detail["venue_name"] == "Theater an der Ruhr"
    ev = _by_title(parse_spielplan_html(LIST_HTML, now=NOW), "Hass / Μίσος / Ură")[0]
    _apply_detail(ev, detail)
    assert ev["image_url"].endswith("Hass.jpg?w=2000")
    assert ev["short_description"].startswith("Hass // Gastspiel")
    assert ev["lat"] == pytest.approx(51.4388872)  # Haus bleibt


def test_detail_enrichment_external_venue():
    detail = parse_detail_html(DETAIL_EXTERN_HTML)
    ev = _by_title(parse_spielplan_html(LIST_HTML, now=NOW), "Theater trifft Escape Room")[0]
    _apply_detail(ev, detail)
    assert ev["venue_name"] == "Willy Brandt Schule"
    assert ev["address_text"] == "Dohne 90, 45468 Mülheim an der Ruhr"
    assert ev["lat"] is None
