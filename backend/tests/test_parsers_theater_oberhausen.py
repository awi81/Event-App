"""Offline parser tests for the Theater Oberhausen source (no network)."""
from datetime import datetime

import pytest

from app.services.theater_oberhausen import parse_theater_oberhausen_html

# Gekuerzter Ausschnitt des Spielplans (div.programmlisting). Jahreszahlen weit
# in der Zukunft; die Tests injizieren ein passendes `now`.
NOW = datetime(2031, 10, 20, 8, 0)


def _item(zeit, loc, titel, url, kat="", subs="", status="", cls="programm-item"):
    kat_html = f"<b>{kat}</b>" if kat else ""
    return (
        f'<div class="{cls}"><div class="zeit">{zeit} Uhr </div>'
        f'<div class="location border-l">{loc}</div>'
        f'<div class="statusurauffuhrung">{status}</div>'
        f'<div class="kategorie border-l">{kat_html}</div>'
        '<div class="karten border-l"><span class="karten-link">'
        f'<a href="webcal://theater-oberhausen.de/event/x/?ical=1" class="btn btn-ical"></a>'
        "</span></div>"
        f'<div class="inhalt"><h4 data-href="{url}">{titel}</h4>{subs}</div></div>'
    )


HTML = (
    "<html><body><div class='eventprogramm'><div id='KalenderContainer'></div>"
    '<div class="programmlisting"><h2 class="">Oktober</h2>'
    '<h3 data-date="1">Mo. 20.10.31</h3>'
    + _item(
        "07:00", "Studio", "Schon vorbei heute",
        "https://theater-oberhausen.de/event/vorbei/", kat="Schauspiel",
    )
    + _item(
        "16:00", "Satellit der Guten Hoffnung",
        "Die Frauenberatungsstelle zu Gast im Satelliten",
        "https://theater-oberhausen.de/event/frauenberatung/",
        subs='<p class="untertitel1">Das Theater Oberhausen auf der Marktstraße</p>'
        '<p class="untertitel2">Eintritt frei</p>',
    )
    + '<h3 data-date="2">Fr. 24.10.31</h3>'
    + _item(
        "19:30", "Raumbühne Großes Haus", "KIPPPUNKTE",
        "https://theater-oberhausen.de/event/kipppunkte-24-10-2031-1930/",
        kat="Urban Arts", status="Premiere Uraufführung", cls="programm-item is-premiere",
        subs='<p class="untertitel1">Choreographischer Doppelabend</p>',
    )
    + '<h2 class="">November</h2>'
    + '<h3 data-date="3">So. 21.11.31</h3>'
    + _item(
        "16:00", "Theaterzelt", "Pippi Langstrumpf 6+",
        "https://theater-oberhausen.de/event/pippi-21-11-2031-1600/",
        kat="Junges Theater",
        subs='<p class="untertitel1">Familienstück von Astrid Lindgren</p>',
    )
    + _item(
        "15:00", "Ebertplatz", "Ebertplätzchen",
        "https://theater-oberhausen.de/event/ebertplaetzchen/", kat="Open Haus",
        subs='<p class="untertitel1">Nachbarschaftstreff</p>',
    )
    + '<h3 data-date="4">Sa. 14.11.32</h3>'
    + _item(
        "19:30", "Studio", "Zu weit in der Zukunft",
        "https://theater-oberhausen.de/event/weit/", kat="Schauspiel",
    )
    + "</div></div></body></html>"
)


def _by_title(events, title):
    return [e for e in events if e["title"] == title]


def test_counts_events_and_drops_past_and_far_future():
    events = parse_theater_oberhausen_html(HTML, now=NOW)
    titles = sorted(e["title"] for e in events)
    assert titles == [
        "Die Frauenberatungsstelle zu Gast im Satelliten",
        "Ebertplätzchen",
        "KIPPPUNKTE",
        "Pippi Langstrumpf 6+",
    ]
    assert len({e["canonical_id"] for e in events}) == 4


def test_date_time_and_two_digit_year():
    events = parse_theater_oberhausen_html(HTML, now=NOW)
    kipp = _by_title(events, "KIPPPUNKTE")[0]
    assert kipp["start_at"] == datetime(2031, 10, 24, 19, 30)
    assert kipp["start_at"].tzinfo is None
    pippi = _by_title(events, "Pippi Langstrumpf 6+")[0]
    assert pippi["start_at"] == datetime(2031, 11, 21, 16, 0)


def test_main_house_fields():
    kipp = _by_title(parse_theater_oberhausen_html(HTML, now=NOW), "KIPPPUNKTE")[0]
    assert kipp["venue_name"] == "Raumbühne Großes Haus"
    assert kipp["address_text"] == "Will-Quadflieg-Platz 1, 46045 Oberhausen"
    assert kipp["city"] == "Oberhausen"
    assert kipp["lat"] == pytest.approx(51.4762667)
    assert kipp["lon"] == pytest.approx(6.8607018)
    assert kipp["category"] == "Urban Arts"
    assert kipp["source_name"] == "Theater Oberhausen"
    assert kipp["source_url"].endswith("kipppunkte-24-10-2031-1930/")
    assert kipp["indoor_outdoor"] == "indoor"
    assert kipp["short_description"].startswith("Premiere Uraufführung")
    assert "Choreographischer Doppelabend" in kipp["short_description"]


def test_satellit_free_entry_without_coords_and_boilerplate_removed():
    ev = _by_title(
        parse_theater_oberhausen_html(HTML, now=NOW),
        "Die Frauenberatungsstelle zu Gast im Satelliten",
    )[0]
    assert ev["start_at"] == datetime(2031, 10, 20, 16, 0)
    assert ev["venue_name"] == "Satellit der Guten Hoffnung"
    assert ev["price_text"] == "Eintritt frei"
    assert ev["category"] is None
    assert ev["lat"] is None and ev["lon"] is None
    assert not ev["short_description"]  # nur Boilerplate + "Eintritt frei"


def test_kids_detection_and_outdoor_venue():
    events = parse_theater_oberhausen_html(HTML, now=NOW)
    pippi = _by_title(events, "Pippi Langstrumpf 6+")[0]
    assert pippi["kids_suitable"] == "yes"
    assert pippi["category"] == "Junges Theater"
    assert pippi["indoor_outdoor"] == "both"
    ebert = _by_title(events, "Ebertplätzchen")[0]
    assert ebert["indoor_outdoor"] == "outdoor"
    assert ebert["lat"] == pytest.approx(51.4764684)
    assert ebert["kids_suitable"] == "unknown"
    assert _by_title(events, "KIPPPUNKTE")[0]["kids_suitable"] == "unknown"


def test_window_shifts_with_now():
    later = datetime(2031, 10, 20, 17, 0)  # 16-Uhr-Termin ist vorbei
    titles = {e["title"] for e in parse_theater_oberhausen_html(HTML, now=later)}
    assert "Die Frauenberatungsstelle zu Gast im Satelliten" not in titles
    assert "KIPPPUNKTE" in titles


def test_empty_or_unknown_html_returns_empty_list():
    assert parse_theater_oberhausen_html("<html><body></body></html>", now=NOW) == []
