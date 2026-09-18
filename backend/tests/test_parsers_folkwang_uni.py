"""Offline parser tests for the Folkwang Universität source (TYPO3 calendarize).

Hand-crafted HTML fixtures — no network access. Dates in the list fixture are
generated relative to ``NOW`` so the time-window filter is exercised
deterministically.
"""
from datetime import datetime, timedelta

import pytest
from bs4 import BeautifulSoup

from app.services.folkwang_uni import (
    CAMPUS_WERDEN_LAT,
    CAMPUS_WERDEN_LON,
    CAMPUS_ZOLLVEREIN_LAT,
    _parse_location,
    _parse_time,
    _resolve_year,
    derive_page_context,
    filter_time_window,
    parse_folkwang_uni_detail_html,
    parse_folkwang_uni_html,
)

# Fixed "now" — a Thursday in September; the page context is derived from
# the prev/next month links, exactly as on the real landing page.
NOW = datetime(2026, 9, 18, 12, 0)

_MONTH_ABBR = {
    1: "Jan", 2: "Feb", 3: "Mär", 4: "Apr", 5: "Mai", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Okt", 11: "Nov", 12: "Dez",
}


def _block(day: int, month: int, time_text: str, location: str, title: str,
           href: str, subtitle: str = "", price: str = "") -> str:
    extra = f"<p>{subtitle}</p>" if subtitle else "<p></p>"
    if price:
        extra += f"<p>{price}</p>"
    return f"""
<div class="cp-module-event city- campus-17 section-1">
 <div class="cp-module-partial-listnew">
  <div class="cp-date"><span class="day">{day:02d}.</span><span class="month">{_MONTH_ABBR[month]}</span></div>
  <div class="cp-event-content">
   <p>{time_text}</p>
   <p>{location}</p>
   <h4>{title}</h4>
   {extra}
   <a class="cp-module-partial-link" href="{href}">mehr</a>
  </div>
 </div>
</div>
"""


def _page(blocks: str, year: int = 2026, month: int = 9) -> str:
    prev_m, prev_y = (month - 1, year) if month > 1 else (12, year - 1)
    next_m, next_y = (month + 1, year) if month < 12 else (1, year + 1)
    return f"""
<!doctype html><html lang="de"><body>
<div class="cp-calendar-nav">
  <span class="cp-calendar-prev"><a href="/home/hochschule/veranstaltungen/monat/{prev_y}/{prev_m}#c150216">zurück</a></span>
  <span class="cp-calendar-next"><a href="/home/hochschule/veranstaltungen/monat/{next_y}/{next_m}#c150216">weiter</a></span>
</div>
{blocks}
</body></html>
"""


DETAIL = "/home/hochschule/veranstaltungen/veranstaltungen-des-laufenden-monats/termin/calendarevent-13267"
DETAIL_SERIES = "/home/hochschule/veranstaltungen/veranstaltungen-des-laufenden-monats/termin/calendarevent-13088-20260924"

# Realistic excerpt of the real landing-page markup (NBSP before "Uhr",
# multi-line room/campus paragraph, empty <p>, series link with date suffix).
LIST_HTML = _page(
    _block(24, 9, "19:30\xa0Uhr",
           "Neue Aula\n\t\t\t\t\t\t\t| Campus Essen-Werden",
           "Mensch. Musik. Maschine: Zeitgenössische Kompositionen für Flöte(n)",
           DETAIL, subtitle="Internationales Flötenfestival Essen 2026")
    + _block(24, 9, "00:00\xa0Uhr", "| Campus Essen-Werden",
             "Internationales Flötenfestival Essen 2026", DETAIL_SERIES)
    + _block(25, 9, "19:00\xa0Uhr",
             "SANAA-Gebäude | Gelsenkirchener Str. 209\n | Campus Welterbe Zollverein",
             "Eröffnung: Folkwang Finale 2026",
             "/home/hochschule/veranstaltungen/veranstaltungen-des-laufenden-monats/termin/calendarevent-13087",
             subtitle="Abschlussarbeiten aus den Studienbereichen Fotografie und Design",
             price="Eintritt frei")
)


# ───────────────────────────── list page ─────────────────────────────────────

def test_parses_all_three_events():
    events = parse_folkwang_uni_html(LIST_HTML, now=NOW)
    assert len(events) == 3


def test_concert_fields():
    events = parse_folkwang_uni_html(LIST_HTML, now=NOW)
    concert = events[0]
    assert concert["title"] == "Mensch. Musik. Maschine: Zeitgenössische Kompositionen für Flöte(n)"
    assert concert["start_at"] == datetime(2026, 9, 24, 19, 30)
    assert concert["is_all_day"] is False
    assert concert["venue_name"] == "Neue Aula, Campus Essen-Werden"
    assert concert["city"] == "Essen"
    assert concert["address_text"] == "Klemensborn 39, 45239 Essen"
    assert concert["lat"] == pytest.approx(CAMPUS_WERDEN_LAT)
    assert concert["lon"] == pytest.approx(CAMPUS_WERDEN_LON)
    assert concert["source_url"] == "https://www.folkwang-uni.de" + DETAIL
    assert concert["source_name"] == "Folkwang Universität"
    assert concert["indoor_outdoor"] == "indoor"
    assert concert["kids_suitable"] == "unknown"
    assert concert["category"] == "Konzert"
    assert concert["short_description"] == "Internationales Flötenfestival Essen 2026"
    assert concert["price_text"] is None


def test_all_day_series_entry():
    events = parse_folkwang_uni_html(LIST_HTML, now=NOW)
    festival = events[1]
    assert festival["title"] == "Internationales Flötenfestival Essen 2026"
    assert festival["is_all_day"] is True
    assert festival["start_at"] == datetime(2026, 9, 24, 0, 0)
    # Room is empty → venue is just the campus.
    assert festival["venue_name"] == "Campus Essen-Werden"
    assert festival["category"] == "Festival"
    assert festival["short_description"] is None


def test_zollverein_event_with_price():
    events = parse_folkwang_uni_html(LIST_HTML, now=NOW)
    finale = events[2]
    assert finale["start_at"] == datetime(2026, 9, 25, 19, 0)
    assert finale["venue_name"] == "SANAA-Gebäude, Campus Welterbe Zollverein"
    assert finale["address_text"] == "Gelsenkirchener Str. 209, 45309 Essen"
    assert finale["lat"] == pytest.approx(CAMPUS_ZOLLVEREIN_LAT)
    assert finale["price_text"] == "Eintritt frei"
    assert finale["short_description"].startswith("Abschlussarbeiten")


def test_canonical_ids_unique_and_contain_date():
    events = parse_folkwang_uni_html(LIST_HTML, now=NOW)
    ids = [e["canonical_id"] for e in events]
    assert len(ids) == len(set(ids))
    # Same series link on another day must yield a different canonical id.
    other_day = _page(_block(25, 9, "00:00 Uhr", "| Campus Essen-Werden",
                             "Internationales Flötenfestival Essen 2026",
                             DETAIL_SERIES.replace("20260924", "20260925")))
    other = parse_folkwang_uni_html(other_day, now=NOW)[0]
    assert other["canonical_id"] != events[1]["canonical_id"]


def test_duplicate_block_same_url_and_date_is_dropped():
    dup = _block(24, 9, "19:30 Uhr", "Neue Aula | Campus Essen-Werden",
                 "Mensch. Musik. Maschine: Zeitgenössische Kompositionen für Flöte(n)", DETAIL)
    events = parse_folkwang_uni_html(_page(dup + dup), now=NOW)
    assert len(events) == 1


def test_broken_block_is_skipped():
    broken = """
<div class="cp-module-event">
 <div class="cp-module-partial-listnew">
  <div class="cp-date"><span class="day">xx.</span><span class="month">Sep</span></div>
  <div class="cp-event-content"><h4>Kaputt</h4></div>
 </div>
</div>
<div class="cp-module-event">
 <div class="cp-event-content"><p>19:00 Uhr</p><h4></h4></div>
</div>
"""
    good = _block(30, 9, "19:30 Uhr", "Kammermusiksaal | Campus Essen-Werden",
                  "Klavierabend", DETAIL)
    events = parse_folkwang_uni_html(_page(broken + good), now=NOW)
    assert [e["title"] for e in events] == ["Klavierabend"]


def test_online_event_is_skipped():
    online = _block(30, 9, "18:00 Uhr", "| Online", "Online-Vortrag Musikpädagogik", DETAIL)
    assert parse_folkwang_uni_html(_page(online), now=NOW) == []


def test_kids_and_category_detection():
    blocks = (
        _block(28, 9, "11:00 Uhr", "Pina Bausch Theater | Campus Essen-Werden",
               "Familienkonzert: Peter und der Wolf", DETAIL)
        + _block(29, 9, "19:30 Uhr", "Pina Bausch Theater | Campus Essen-Werden",
                 "Tanzabend der Studierenden", DETAIL + "x")
        + _block(30, 9, "18:00 Uhr", "Kleiner Konzertsaal | Campus Bochum",
                 "Vortrag: Musik und Gesellschaft", DETAIL + "y")
    )
    events = parse_folkwang_uni_html(_page(blocks), now=NOW)
    assert events[0]["kids_suitable"] == "likely"
    assert events[1]["category"] == "Tanz"
    assert events[2]["category"] == "Vortrag"
    assert events[2]["city"] == "Bochum"
    assert "lat" not in events[2]


# ───────────────────────────── time window ───────────────────────────────────

def test_past_and_far_future_events_are_filtered():
    today = NOW.replace(hour=0, minute=0)
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    far = today + timedelta(days=200)
    events = [
        {"title": "gestern", "start_at": yesterday.replace(hour=19)},
        {"title": "heute", "start_at": today},
        {"title": "morgen", "start_at": tomorrow.replace(hour=20)},
        {"title": "fern", "start_at": far},
        {"title": "ohne datum", "start_at": None},
    ]
    kept = [e["title"] for e in filter_time_window(events, NOW)]
    assert kept == ["heute", "morgen"]


def test_past_event_dropped_from_page():
    # 1 Sep is in the past relative to NOW (18 Sep) → dropped; 30 Sep stays.
    blocks = (
        _block(1, 9, "19:30 Uhr", "Neue Aula | Campus Essen-Werden", "Vergangen", DETAIL)
        + _block(30, 9, "19:30 Uhr", "Neue Aula | Campus Essen-Werden", "Zukunft", DETAIL + "z")
    )
    events = parse_folkwang_uni_html(_page(blocks), now=NOW)
    assert [e["title"] for e in events] == ["Zukunft"]


# ───────────────────────────── date helpers ──────────────────────────────────

def test_parse_time_variants():
    assert _parse_time("19:30\xa0Uhr") == (19, 30, False)
    assert _parse_time("00:00 Uhr") == (0, 0, True)
    assert _parse_time("") == (0, 0, True)
    # A date must never be read as a time (24.06. ≠ 24:06).
    assert _parse_time("24.06.") == (0, 0, True)
    assert _parse_time("24:06 Uhr") == (0, 0, True)


def test_resolve_year_wraps_around_new_year():
    # Nov page showing an Oct exhibition → same year.
    assert _resolve_year(10, 2026, 11) == 2026
    # Jan page showing a Dec event → previous year.
    assert _resolve_year(12, 2027, 1) == 2026
    # Dec page listing a Jan event → next year.
    assert _resolve_year(1, 2026, 12) == 2027


def test_link_date_suffix_takes_precedence_over_page_context():
    # Page context says Dec 2026, link suffix says 2027-01-05 → Jan 2027.
    href = DETAIL_SERIES.replace("20260924", "20270105")
    html = _page(_block(5, 1, "00:00 Uhr", "| Campus Essen-Werden", "Neujahrskonzert", href),
                 year=2026, month=12)
    events = parse_folkwang_uni_html(html, page_year=2026, page_month=12,
                                     now=datetime(2026, 12, 20))
    assert events[0]["start_at"] == datetime(2027, 1, 5)


def test_page_context_from_nav_links_and_fallback():
    soup = BeautifulSoup(_page("", year=2026, month=12), "lxml")
    assert derive_page_context(soup, NOW) == (2026, 12)
    # January page: next link is /monat/2027/2, prev is /monat/2026/12.
    soup = BeautifulSoup(_page("", year=2027, month=1), "lxml")
    assert derive_page_context(soup, NOW) == (2027, 1)
    # No nav links → falls back to now.
    soup = BeautifulSoup("<html><body></body></html>", "lxml")
    assert derive_page_context(soup, NOW) == (2026, 9)


# ───────────────────────────── location parsing ──────────────────────────────

def test_location_variants():
    loc = _parse_location("Schauspielhaus Bochum | Oval Office | Bochum")
    assert loc["venue_name"] == "Schauspielhaus Bochum, Oval Office"
    assert loc["city"] == "Bochum"
    assert loc["lat"] is None

    loc = _parse_location("Bürgermeisterhaus | Heckstr. 105 | Essen-Werden | Essen")
    assert loc["venue_name"] == "Bürgermeisterhaus"
    assert loc["address_text"] == "Heckstr. 105, Essen"
    # Not on campus → no fixed coordinates, geocoder fills later.
    assert loc["lat"] is None

    loc = _parse_location("Innenhof der Alten Abtei | Campus Essen-Werden")
    assert loc["indoor_outdoor"] == "outdoor"
    assert loc["lat"] == pytest.approx(CAMPUS_WERDEN_LAT)

    loc = _parse_location("Kleiner Konzertsaal | Campus Duisburg")
    assert loc["city"] == "Duisburg"

    assert _parse_location("")["venue_name"] == "Folkwang Universität der Künste"


# ───────────────────────────── detail page ───────────────────────────────────

DETAIL_HTML = """
<html><body>
<div class="calendarize"><div class="panel panel-default"><div class="panel-body">
<section class="cp-module-head cp-module-block">
  <h1>Mensch. Musik. Maschine</h1>
  <h4>Internationales Flötenfestival Essen 2026</h4>
</section>
<section class="cp-module-event cp-module-block">
 <div class="cp-module-partial-txtwrapper"><article>
  <p>24. September 2026\n\n\t\t19:30\xa0Uhr</p>
  <p>Campus Essen-Werden<br/>Neue Aula<br/></p>
  <p>_Zwischen Atem und Algorithmus, Körperklang und digitaler Transformation entfaltet
     sich ein Konzertprogramm, das die Beziehung zwischen Mensch und Technik auslotet.</p>
  <p><strong>Steve Reich, Vermont Counterpoint</strong><br/>Lehrende der Musikhochschulen in NRW</p>
  <p>_Karten unter: <a href="https://example.org/tickets">example.org</a> — Eintritt: 12 €</p>
 </article></div>
</section>
</div></div></div>
</body></html>
"""


def test_detail_description_and_price():
    result = parse_folkwang_uni_detail_html(DETAIL_HTML)
    assert result["short_description"].startswith("Zwischen Atem und Algorithmus")
    assert len(result["short_description"]) <= 500
    assert "12" in result["price_text"]


def test_detail_empty_page():
    assert parse_folkwang_uni_detail_html("<html><body></body></html>") == {}
