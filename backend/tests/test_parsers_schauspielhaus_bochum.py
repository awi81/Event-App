"""Offline parser tests for the Schauspielhaus Bochum source (no network)."""
from datetime import datetime

import pytest

from app.services.schauspielhaus_bochum import (
    _parse_times,
    merge_genre_events,
    parse_schauspielhaus_bochum_html,
)

# Gekuerzter, aus der echten Genreseite abgeleiteter Ausschnitt (Struktur 1:1,
# Daten in die ferne Zukunft verschoben; `now` wird injiziert).
NOW = datetime(2031, 11, 20, 9, 0)


def _item(piece_id, stage, title, times, attrs="", sub="", infos=(), ticket=True, extra_stage=""):
    attr_html = f'<div class="schedule__attributes">{attrs}</div>' if attrs else ""
    sub_html = f'<div class="schedule__subtitle2">{sub}</div>' if sub else ""
    times_html = f'<div class="schedule__times">{times}</div>' if times else ""
    info_html = "".join(f'<div class="schedule__info">{i}</div>' for i in infos)
    stage_html = f'<div class="schedule__stage">{stage}{extra_stage}</div>' if stage else ""
    return f"""
    <li><div class="schedule__item" data-id="{piece_id}" data-href="/de/stuecke/{piece_id}/x">
      <div class="schedule__clickable clickable-block" data-href="/de/stuecke/{piece_id}/x">
        {stage_html}{attr_html}
        <div class="schedule__title"><a href="/de/stuecke/{piece_id}/x">{title}</a></div>
        {sub_html}{times_html}{info_html}
      </div>
    </div></li>"""


def _day(iso, *items):
    return f'<ul class="schedule__group" data-groupdate="{iso}">{"".join(items)}</ul>'


def _page(*days):
    return f'<html><body><div class="schedule__items"><section>{"".join(days)}</section></div></body></html>'


HTML = _page(
    _day(
        "2031-11-21",
        _item(33030, "Schauspielhaus", "Die kleine Hexe", "16:00&thinsp;—&thinsp;17:10",
              attrs="Premiere", sub="nach Otfried Preußler",
              infos=["🐬 6+", "+ anschließend Waffeln"]),
    ),
    _day(
        "2031-11-22",
        _item(33030, "Schauspielhaus", "Die kleine Hexe", "18:00&thinsp;—&thinsp;19:10",
              sub="nach Otfried Preußler", infos=["🐬 6+"]),
        # Schulvorstellung: nur per Mail buchbar -> raus
        _item(33100, "Theaterrevier", "Jugend ohne Gott", "10:00 — 11:15", attrs="Schulvorstellung",
              infos=["👽 13+", "Buchung: gruppe [at] schauspielhausbochum.de"]),
        # Premieren-Hinweis ohne Stage und Uhrzeit -> raus
        _item(33045, "", "V wie Verwandlung", "", attrs="Premiere"),
    ),
    _day(
        "2031-11-24",
        _item(33758, "Oval Office", "AMPLIFY!", "17:00 — 04:00",
              infos=["Extra Kartenkontingent an der Abendkasse"]),
        _item(34262, "Kammerspiele", "Mensch, was isst du?", "19:30",
              extra_stage='<br/><a class="schedule__festival-title" href="/de/festival/1/x">Jetzt! Ein Wochenende fürs Klima</a>'),
    ),
    _day(
        "2031-11-10",  # vergangen
        _item(1, "Kammerspiele", "Altes Stück", "19:30"),
    ),
    _day(
        "2032-06-01",  # > 120 Tage
        _item(2, "Schauspielhaus", "Fernes Stück", "19:30"),
    ),
)


def _by_title(events, title):
    return [e for e in events if e["title"] == title]


def test_counts_events_and_drops_invalid_items():
    events = parse_schauspielhaus_bochum_html(HTML, now=NOW, genre="Familienstück")
    # Hexe x2, AMPLIFY, Mensch was isst du — Schulvorstellung, Premieren-Hinweis,
    # Vergangenes und Fernes fallen raus.
    assert len(events) == 4
    titles = {e["title"] for e in events}
    assert titles == {"Die kleine Hexe", "AMPLIFY!", "Mensch, was isst du?"}
    assert "Jugend ohne Gott" not in titles
    assert "Altes Stück" not in titles and "Fernes Stück" not in titles


def test_date_time_end_and_overnight():
    events = parse_schauspielhaus_bochum_html(HTML, now=NOW)
    hexe = sorted(_by_title(events, "Die kleine Hexe"), key=lambda e: e["start_at"])
    assert hexe[0]["start_at"] == datetime(2031, 11, 21, 16, 0)
    assert hexe[0]["end_at"] == datetime(2031, 11, 21, 17, 10)
    assert hexe[1]["start_at"] == datetime(2031, 11, 22, 18, 0)
    assert len({e["canonical_id"] for e in hexe}) == 2
    amplify = _by_title(events, "AMPLIFY!")[0]
    assert amplify["start_at"] == datetime(2031, 11, 24, 17, 0)
    assert amplify["end_at"] == datetime(2031, 11, 25, 4, 0)  # Ende nach Mitternacht
    mensch = _by_title(events, "Mensch, was isst du?")[0]
    assert mensch["start_at"] == datetime(2031, 11, 24, 19, 30)
    assert mensch["end_at"] is None


def test_fields_venue_and_description():
    events = parse_schauspielhaus_bochum_html(HTML, now=NOW, genre="Familienstück")
    hexe = sorted(_by_title(events, "Die kleine Hexe"), key=lambda e: e["start_at"])[0]
    assert hexe["venue_name"] == "Schauspielhaus Bochum"
    assert hexe["city"] == "Bochum"
    assert hexe["address_text"] == "Königsallee 15, 44789 Bochum"
    assert hexe["lat"] == pytest.approx(51.4722, abs=1e-4)
    assert hexe["lon"] == pytest.approx(7.2167, abs=1e-3)
    assert hexe["source_name"] == "Schauspielhaus Bochum"
    assert hexe["source_url"] == "https://www.schauspielhausbochum.de/de/stuecke/33030/x"
    assert hexe["category"] == "Familienstück"
    assert hexe["indoor_outdoor"] == "indoor"
    assert "nach Otfried Preußler" in hexe["short_description"]
    assert "Premiere" in hexe["short_description"]
    assert "Ab 6 Jahren" in hexe["short_description"]
    assert len(hexe["short_description"]) <= 500
    amplify = _by_title(events, "AMPLIFY!")[0]
    assert amplify["venue_name"] == "Oval Office (Schauspielhaus Bochum)"
    assert "Abendkasse" not in (amplify["short_description"] or "")  # Rauschen raus
    mensch = _by_title(events, "Mensch, was isst du?")[0]
    assert mensch["venue_name"] == "Kammerspiele (Schauspielhaus Bochum)"  # Festival-Link nicht im Namen
    assert "Jetzt! Ein Wochenende fürs Klima" in mensch["short_description"]


def test_kids_detection_by_genre_and_age():
    fam = parse_schauspielhaus_bochum_html(HTML, now=NOW, genre="Familienstück")
    assert all(e["kids_suitable"] == "yes" for e in _by_title(fam, "Die kleine Hexe"))
    # Fremdes Genre, aber Altersangabe 6+ -> trotzdem Kinder
    other = parse_schauspielhaus_bochum_html(HTML, now=NOW, genre="Musik")
    assert all(e["kids_suitable"] == "yes" for e in _by_title(other, "Die kleine Hexe"))
    assert _by_title(other, "AMPLIFY!")[0]["kids_suitable"] == "unknown"
    # Junges Theater, aber 13+ (Jugendstueck) -> nur likely
    teen = _page(_day("2031-11-25", _item(5, "Theaterrevier", "Jugend ohne Gott", "19:30 — 20:45", infos=["👽 13+"])))
    ev = parse_schauspielhaus_bochum_html(teen, now=NOW, genre="Junges Theater")
    assert ev[0]["kids_suitable"] == "likely"


def test_today_earlier_performances_are_dropped():
    html = _page(_day("2031-11-20",
                      _item(7, "Kammerspiele", "Vormittag", "08:00 — 08:30"),
                      _item(8, "Kammerspiele", "Abend", "19:30 — 21:00")))
    events = parse_schauspielhaus_bochum_html(html, now=NOW)
    assert [e["title"] for e in events] == ["Abend"]


def test_merge_dedups_across_genre_pages_first_category_wins():
    a = parse_schauspielhaus_bochum_html(HTML, now=NOW, genre="Schauspiel")
    b = parse_schauspielhaus_bochum_html(HTML, now=NOW, genre="Familienstück")
    merged = merge_genre_events([a, b])
    assert len(merged) == 4  # nicht 8
    hexe = _by_title(merged, "Die kleine Hexe")
    assert all(e["category"] == "Schauspiel" for e in hexe)  # erste Fundstelle
    assert all(e["kids_suitable"] == "yes" for e in hexe)
    assert [e["start_at"] for e in merged] == sorted(e["start_at"] for e in merged)


def test_merge_upgrades_kids_from_later_page():
    plain = _page(_day("2031-11-26", _item(9, "Schauspielhaus", "Weihnachtsliedersingen", "15:00")))
    ev_a = parse_schauspielhaus_bochum_html(plain, now=NOW, genre="Schauspiel")
    ev_b = parse_schauspielhaus_bochum_html(plain, now=NOW, genre="Familienstück")
    assert ev_a[0]["kids_suitable"] == "unknown"
    merged = merge_genre_events([ev_a, ev_b])
    assert len(merged) == 1 and merged[0]["kids_suitable"] == "yes"


def test_parse_times_variants():
    from datetime import date

    d = date(2031, 11, 21)
    assert _parse_times("19:30", d) == (datetime(2031, 11, 21, 19, 30), None)
    assert _parse_times("19:30 — 21:10", d) == (
        datetime(2031, 11, 21, 19, 30), datetime(2031, 11, 21, 21, 10))
    assert _parse_times("", d) is None


def test_empty_html_returns_empty_list():
    assert parse_schauspielhaus_bochum_html("<html><body></body></html>", now=NOW) == []
