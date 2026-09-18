"""Offline parser tests for the Kulturlöwen Velbert source (JSON-LD + klive HTML).

Hand-crafted fixture modelled on the real kulturloewen.de/veranstaltungen/
markup — no network access. Dates are absolute, so ``NOW`` is injected.
"""
from datetime import datetime, timedelta

import pytest

from app.services.kulturloewen import (
    _format_price,
    _venue_coords,
    filter_time_window,
    parse_kulturloewen_html,
)

NOW = datetime(2026, 9, 18, 12, 0)


def _box(tid: str, day: str, month: str, time: str, rubrik: str, artist: str,
         titel: str = "", subtitle: str = "", label: str = "", ende: str = "") -> str:
    titel_span = f'<span class="klive-titel-titel">{titel}</span>' if titel else ""
    sub_span = f'<span class="klive-titel-subtitel">{subtitle}</span>' if subtitle else ""
    label_span = f'<span class="klive-label">{label}</span>' if label else ""
    return f"""
<div class="klive-terminbox">
 <div class="klive-kurzfassung">
  <div class="klive-kurzfassung-links">
   <div class="klive-datumuhrzeit">
    <div class="klive-datum"><span class="klive-datum-tag">{day}.</span><span class="klive-datum-monat">{month}.</span></div>
    <div class="klive-tag">Samstag</div>
    <div class="klive-zeit">{time} <span class="ende">{ende}</span> Uhr</div>
   </div>
   <div class="klive-foto" style="background-image: url(https://www.neanderticket.de/fotos/v216/{tid}_thumb.png); background-size:cover;"></div>
  </div>
  <a href="javascript:launchTicket({tid}, 1)"><div class="klive-ticketbutton-jetzt-kaufen">Tickets buchen</div></a>
  <div class="klive-titel">
   <span class="klive-tags">
    <span class="klive-location-notdefault"><span class="klive-location-notdefault-hinweistext">Veranstaltungsort:</span> Forum</span>
    <span class="klive-city-notdefault">Velbert</span>
    <span class="klive-rubrik">{rubrik}</span>
    <span class="klive-kurzrubrik">{rubrik}</span>
    {label_span}
   </span>
   <span class="klive-titel-pretitel">Die Velberter Kulturloewen pr&auml;sentieren</span>
   <span class="klive-titel-artist">{artist}</span>
   {titel_span}
   {sub_span}
   <a class="klive-mehr-infos aufklapplink" href="javascript:void(0)" id="a{tid}"><span id="plus{tid}">+ mehr Infos</span></a>
  </div>
 </div>
 <div id="termin{tid}" style="clear: both; display:none"></div>
</div>
"""


# One ld+json script holding an ARRAY of Event objects — exactly like the live
# page (entities such as &szlig; are left unescaped inside the JSON strings).
JSON_LD = """
<script type="application/ld+json">
 [
{"@context":"http://schema.org","@type":"Event", "url":"http://neanderticket.de/614321","name": "NRW-Slam 2026 | Halbfinale in Velbert","startDate":"2026-09-19T20:00:00", "location":{"@type":"Place","name":"Forum Velbert","address":{"@type":"PostalAddress","streetAddress":"Oststra&szlig;e 20","addressLocality":"Velbert","postalCode":"42551","addressCountry":"DE"}}, "offers":{"@type":"Offer","category":"primary","availability":"InStock","url":"http://neanderticket.de/shop/614321","price":"18.00 ","priceCurrency":"EUR"},"eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode"}
,
{"@context":"http://schema.org","@type":"Event", "url":"http://neanderticket.de/597117","name": "Voll Karacho!","startDate":"2026-09-25T20:00:00", "location":{"@type":"Place","name":"Historisches B&uuml;rgerhaus Langenberg","address":{"@type":"PostalAddress","streetAddress":"Hauptstra&szlig;e 64","addressLocality":"Velbert","postalCode":"42555","addressCountry":"DE"}}, "offers":{"@type":"Offer","category":"primary","availability":"InStock","url":"http://neanderticket.de/shop/597117","price":"39.90 ","priceCurrency":"EUR"},"performer":"Herbert Knebels Affentheater","eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode"}
,
{"@context":"http://schema.org","@type":"Event", "url":"http://neanderticket.de/656414","name": "Nur wir alle","startDate":"2026-10-09T16:00:00", "location":{"@type":"Place","name":"Vorburg Schloss Hardenberg","address":{"@type":"PostalAddress","streetAddress":"Zum Hardenberger Schloss 1","addressLocality":"Velbert","postalCode":"42553","addressCountry":"DE"}}, "offers":{"@type":"Offer","category":"primary","availability":"InStock","url":"http://neanderticket.de/shop/656414","price":"7.00  ","priceCurrency":"EUR"},"eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode"}
,
{"@context":"http://schema.org","@type":"Event", "url":"http://neanderticket.de/999001","name": "Kaputt ohne Datum", "location":{"@type":"Place","name":"Forum Velbert"}}
,
{"@context":"http://schema.org","@type":"Event", "url":"http://neanderticket.de/999002","name": "Weit in der Zukunft","startDate":"2027-11-13T20:00:00", "location":{"@type":"Place","name":"Forum Velbert"}}
,
{"@context":"http://schema.org","@type":"Event", "url":"http://neanderticket.de/999003","name": "Gestern gewesen","startDate":"2026-09-17T20:00:00", "location":{"@type":"Place","name":"Forum Velbert"}}
]
</script>
"""

HTML = f"""
<!doctype html><html lang="de"><head>{JSON_LD}</head><body>
<div id="eventContainer"><div id="klive-kalenderbox">
{_box("614321", "19", "09", "20:00", "Poetry Slam", "NRW-Slam 2026 | Halbfinale in Velbert",
      subtitle="Die Nordrhein-Westf&auml;lische Meisterschaft im Poetry Slam 2026")}
{_box("597117", "25", "09", "20:00", "Kabarett, Comedy", "Herbert Knebels Affentheater",
      titel="Voll Karacho!", label="Kabarett", ende="&nbsp;22:15")}
{_box("656414", "09", "10", "16:00", "Kinderprogramm", "Theater Fusion, Berlin",
      titel="Nur wir alle", subtitle="Im Rahmen des Kinder-Herbstfestivals", label="Kinder/Jugend")}
</div></div>
</body></html>
"""


# ───────────────────────────── list page ─────────────────────────────────────

def test_parses_events_in_window_only():
    events = parse_kulturloewen_html(HTML, now=NOW)
    # 6 JSON-LD items: 1 without date, 1 too far, 1 yesterday → 3 remain
    assert [e["title"] for e in events] == [
        "NRW-Slam 2026 | Halbfinale in Velbert",
        "Herbert Knebels Affentheater: Voll Karacho!",
        "Theater Fusion, Berlin: Nur wir alle",
    ]


def test_slam_fields():
    slam = parse_kulturloewen_html(HTML, now=NOW)[0]
    assert slam["start_at"] == datetime(2026, 9, 19, 20, 0)
    assert slam["start_at"].tzinfo is None
    assert slam["venue_name"] == "Forum Velbert"
    assert slam["address_text"] == "Oststraße 20, 42551 Velbert"  # &szlig; unescaped
    assert slam["city"] == "Velbert"
    assert slam["lat"] == pytest.approx(51.3415978)
    assert slam["lon"] == pytest.approx(7.0463150)
    assert slam["source_url"] == "http://neanderticket.de/614321"
    assert slam["source_name"] == "Kulturlöwen Velbert"
    assert slam["price_text"] == "ab 18 €"
    assert slam["category"] == "Poetry Slam"
    assert slam["kids_suitable"] == "unknown"
    assert slam["indoor_outdoor"] == "indoor"
    assert slam["short_description"] == "Die Nordrhein-Westfälische Meisterschaft im Poetry Slam 2026"
    assert slam["image_url"] == "https://www.neanderticket.de/fotos/v216/614321_thumb.png"
    assert slam["end_at"] is None


def test_artist_and_title_are_combined():
    knebel = parse_kulturloewen_html(HTML, now=NOW)[1]
    assert knebel["title"] == "Herbert Knebels Affentheater: Voll Karacho!"
    assert knebel["venue_name"] == "Historisches Bürgerhaus Langenberg"
    assert knebel["address_text"] == "Hauptstraße 64, 42555 Velbert"
    assert knebel["lat"] == pytest.approx(51.3511495)
    assert knebel["price_text"] == "ab 39,90 €"
    assert knebel["category"] == "Kabarett, Comedy"
    # End time from the HTML "ende" span, same day.
    assert knebel["end_at"] == datetime(2026, 9, 25, 22, 15)


def test_kids_programme_is_yes():
    kids = parse_kulturloewen_html(HTML, now=NOW)[2]
    assert kids["kids_suitable"] == "yes"
    assert kids["category"] == "Kinderprogramm"
    assert kids["venue_name"] == "Vorburg Schloss Hardenberg"
    assert kids["lat"] == pytest.approx(51.3166270)
    assert kids["price_text"] == "ab 7 €"
    assert kids["short_description"] == "Im Rahmen des Kinder-Herbstfestivals"


def test_canonical_ids_unique_and_date_dependent():
    events = parse_kulturloewen_html(HTML, now=NOW)
    ids = [e["canonical_id"] for e in events]
    assert len(ids) == len(set(ids))
    # Same event on another day → different canonical id.
    shifted = HTML.replace("2026-09-19T20:00:00", "2026-09-20T20:00:00")
    assert parse_kulturloewen_html(shifted, now=NOW)[0]["canonical_id"] != ids[0]


def test_broken_json_ld_block_is_skipped():
    html = HTML.replace("</head>", '<script type="application/ld+json">{not json</script></head>')
    assert len(parse_kulturloewen_html(html, now=NOW)) == 3


def test_event_without_html_box_falls_back_to_json_ld_only():
    html = f"<html><head>{JSON_LD}</head><body></body></html>"
    events = parse_kulturloewen_html(html, now=NOW)
    assert len(events) == 3
    knebel = events[1]
    assert knebel["title"] == "Voll Karacho!"          # no artist span → plain name
    assert knebel["image_url"] is None
    assert knebel["end_at"] is None
    assert knebel["category"] is None                 # no Rubrik, no keyword
    assert knebel["lat"] == pytest.approx(51.3511495)  # coords still from venue name


def test_unknown_venue_has_no_coordinates():
    html = HTML.replace('"name":"Forum Velbert"', '"name":"Neue Halle Velbert"')
    slam = parse_kulturloewen_html(html, now=NOW)[0]
    assert slam["venue_name"] == "Neue Halle Velbert"
    assert "lat" not in slam


def test_empty_page():
    assert parse_kulturloewen_html("<html><body></body></html>", now=NOW) == []


# ───────────────────────────── helpers ───────────────────────────────────────

def test_price_formatting():
    assert _format_price({"price": "18.00 ", "priceCurrency": "EUR"}) == "ab 18 €"
    assert _format_price({"price": "37.90", "priceCurrency": "EUR"}) == "ab 37,90 €"
    assert _format_price({"price": "7.00  "}) == "ab 7 €"
    assert _format_price({"price": "0"}) == "Eintritt frei"
    assert _format_price({"price": ""}) is None
    assert _format_price({}) is None
    assert _format_price(None) is None
    assert _format_price([{"price": "12,50"}]) == "ab 12,50 €"


def test_venue_coords_lookup():
    assert _venue_coords("Forum Velbert") == pytest.approx((51.3415978, 7.0463150))
    assert _venue_coords("Vorburg Schloss Hardenberg") is not None
    assert _venue_coords("Irgendwo anders") is None


def test_time_window_filter_relative_to_now():
    today = NOW.replace(hour=0, minute=0)
    events = [
        {"title": "gestern", "start_at": today - timedelta(hours=4)},
        {"title": "heute", "start_at": today.replace(hour=20)},
        {"title": "in 120 tagen", "start_at": today + timedelta(days=120)},
        {"title": "in 121 tagen", "start_at": today + timedelta(days=121)},
        {"title": "kein datum", "start_at": None},
    ]
    assert [e["title"] for e in filter_time_window(events, NOW)] == ["heute", "in 120 tagen"]
