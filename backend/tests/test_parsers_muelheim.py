"""Offline parser tests for the Stadt-Mülheim source (no network)."""
import asyncio
from datetime import datetime

import pytest

from app.services import muelheim
from app.services.muelheim import (
    _parse_detail,
    _parse_end_date,
    _series_key,
    build_events,
    parse_muelheim_html,
    _parse_rows,
    _next_page_url,
)

# Jahreszahlen weit in der Zukunft, damit die Fixture nicht "altert"; die
# Tests injizieren ein passendes `now`.
NOW = datetime(2031, 10, 21, 9, 0)


def _row(n, day, hhmm, title, slug, ev_id, teaser="", status="findet statt"):
    """Eine Zeile der Hauptliste, Markup 1:1 wie auf der echten Seite."""
    iso = f"2031-{day[3:5]}-{day[0:2]}T{hhmm}:00+01:00"
    shown = hhmm.lstrip("0") if hhmm != "00:00" else "0:00"
    return f"""
  <div class="views-row views-row-{n} views-row-odd col-sm-4">
  <div class="views-field views-field-field-cbi-image-1">        <div class="field-content"><a href="/veranstaltungen/{slug}_am_{day}.2031/{ev_id}" title=""><img typeof="foaf:Image" class="img-responsive" src="https://www1.muelheim-ruhr.de/sites/x/files/styles/events__350x_/public/imgcache_ext/{ev_id}.jpeg" width="350" height="197" alt="" /></a></div>  </div>
  <div class="views-field views-field-field-cbi-period">        <div class="field-content"><span class="date-display-single" property="dc:date" datatype="xsd:dateTime" content="{iso}">{day}.2031</span></div>  </div>
  <div class="views-field views-field-field-cbi-period-1">        <div class="field-content period-{hhmm.replace(':', '')}"><span class="date-display-single" property="dc:date" datatype="xsd:dateTime" content="{iso}">{shown}</span></div>  </div>
  <div class="views-field views-field-field-cbi-flag-status">        <div class="field-content"><span class="flag-status-1">{status}</span></div>  </div>
  <div class="views-field views-field-title">        <span class="field-content"><a href="/veranstaltungen/{slug}_am_{day}.2031/{ev_id}">{title}</a></span>  </div>
  <div class="views-field views-field-field-cbi-text-value-1">        <span class="field-content">{teaser}... <a href="/veranstaltungen/{slug}_am_{day}.2031/{ev_id}" class="views-more-link">mehr</a></span>  </div></div>
"""


def _page(rows, next_href=None):
    pager = (
        f'<ul class="pager"><li class="pager__item"><a href="{next_href}">Weitere Termine laden</a></li></ul>'
        if next_href
        else ""
    )
    # Das Slideshow-Karussell (gleiche Felder, ohne col-sm-4) steht auf jeder
    # Seite und darf NICHT als Termin zählen.
    slideshow = """
    <div class="view-content"><div class="views-slideshow-cycle-main-frame-row">
      <div class="views-slideshow-cycle-main-frame-row-item views-row views-row-0 views-row-odd">
        <div class="views-field views-field-field-cbi-period"><span class="date-display-single" content="2031-10-21T10:00:00+02:00">21. Oktober 2031</span></div>
        <div class="views-field views-field-title"><span class="field-content h3"><a href="/veranstaltungen/slide_am_21.10.2031/1">Karussell-Tipp</a></span></div>
      </div></div></div>"""
    return f"<html><body>{slideshow}<div class=\"view-content\">{''.join(rows)}</div>{pager}</body></html>"


LIST_HTML = _page(
    [
        _row(1, "20.10", "19:30", "Gestriges Konzert", "gestern", 100, "Schon vorbei"),
        _row(2, "23.10", "19:30", "Hass / Μίσος / Ură", "hass", 101, "ab 16 Jahre auf Deutsch, Eintritt 15 €"),
        _row(3, "24.10", "19:00", "Der Gott des Gemetzels", "gott", 102, "Komödie von Yasmina Reza"),
        _row(4, "25.10", "16:00", "Der Gott des Gemetzels", "gott", 103, "Komödie von Yasmina Reza"),
        _row(5, "26.10", "10:00", "Abgesagtes Konzert", "abg", 104, "x", status="abgesagt"),
        _row(6, "27.10", "00:00", "Stadtfest auf dem Rathausmarkt", "fest", 105, "Eintritt frei"),
        # weit hinter dem 120-Tage-Fenster (2031-10-21 + 120 d = 2032-02-18)
        _row(7, "19.03", "20:00", "Carmela de Feo", "carmela", 106, "Kabarett"),
        # dieselbe ID erscheint auf einer zweiten Listenseite nochmal -> Dublette
        _row(8, "23.10", "19:30", "Hass / Μίσος / Ură", "hass", 101, "ab 16 Jahre auf Deutsch, Eintritt 15 €"),
    ],
    next_href="/veranstaltungen?page=1&kategorie=7059",
)


def test_counts_titles_and_window():
    events = parse_muelheim_html(LIST_HTML, "Theater", now=NOW)
    titles = [e["title"] for e in events]
    # gestern, abgesagt, > 120 Tage und Dublette fallen raus; Karussell zählt nicht
    assert titles == [
        "Hass / Μίσος / Ură",
        "Der Gott des Gemetzels",
        "Der Gott des Gemetzels",
        "Stadtfest auf dem Rathausmarkt",
    ]
    assert "Karussell-Tipp" not in titles
    assert "Gestriges Konzert" not in titles
    assert "Abgesagtes Konzert" not in titles
    assert "Carmela de Feo" not in titles
    assert len({e["canonical_id"] for e in events}) == 4


def test_datetime_fields_and_defaults():
    events = parse_muelheim_html(LIST_HTML, "Theater", now=NOW)
    hass = events[0]
    assert hass["start_at"] == datetime(2031, 10, 23, 19, 30)
    assert hass["category"] == "Theater"
    assert hass["source_name"] == "Stadt Mülheim"
    assert hass["source_url"] == "https://www1.muelheim-ruhr.de/veranstaltungen/hass_am_23.10.2031/101"
    assert hass["price_text"] == "Eintritt 15 €"
    assert hass["image_url"].endswith("/101.jpeg")
    assert hass["short_description"].startswith("ab 16 Jahre")
    assert not hass["short_description"].endswith(".")
    assert len(hass["canonical_id"]) == 16
    # Spielstätte steckt nur im Detail -> ohne Detail None, Stadt-Default
    assert hass["venue_name"] is None
    assert hass["lat"] is None and hass["lon"] is None
    assert hass["city"] == "Mülheim an der Ruhr"
    # zwei Aufführungen derselben Serie bleiben zwei Termine
    gott = [e for e in events if e["title"] == "Der Gott des Gemetzels"]
    assert [e["start_at"].day for e in gott] == [24, 25]
    # 0:00 = ohne Uhrzeit (ganztägig)
    fest = events[-1]
    assert fest["start_at"] == datetime(2031, 10, 27, 0, 0)
    assert fest["price_text"] == "Eintritt frei"


def test_window_shifts_with_now():
    events = parse_muelheim_html(LIST_HTML, "Theater", now=datetime(2031, 10, 25, 12, 0))
    assert [e["start_at"].day for e in events] == [25, 27]


def test_pager_link_and_empty_page():
    assert _next_page_url(LIST_HTML) == "https://www1.muelheim-ruhr.de/veranstaltungen?page=1&kategorie=7059"
    assert _next_page_url(_page([])) is None
    assert parse_muelheim_html("<html><body></body></html>", now=NOW) == []


def test_kids_detection():
    kids_page = _page([_row(1, "24.10", "15:00", "Wir lesen eine Geschichte", "lesen", 200, "Vorlesen")])
    ev = parse_muelheim_html(kids_page, "Kinder / Familie", now=NOW)[0]
    assert ev["kids_suitable"] == "yes"

    # Kinder-Rubrik hat Vorrang vor Theater, wenn derselbe Termin in beiden steht
    rows = _parse_rows(kids_page, "Theater") + _parse_rows(kids_page, "Kinder / Familie")
    merged = build_events(rows, None, NOW)
    assert len(merged) == 1
    assert merged[0]["category"] == "Kinder / Familie"
    assert merged[0]["kids_suitable"] == "yes"

    page = _page(
        [
            _row(1, "24.10", "15:00", "Das Theater Töfte spielt für Kinder", "toefte", 201, "ab 4 Jahren"),
            _row(2, "25.10", "20:00", "Rockabend", "rock", 202, "Live-Musik"),
        ]
    )
    ev = parse_muelheim_html(page, "Theater", now=NOW)
    assert ev[0]["kids_suitable"] == "likely"
    assert ev[1]["kids_suitable"] == "unknown"


def test_exhibition_series_collapses_to_one_row_with_end():
    rows = [
        _row(i, f"{d}.10", "11:00", "TOMAS KLEINER. IM WIND", "tomas", 300 + i,
             "11. Oktober 2031 bis 29. März 2032 Vom 11. Oktober 2031 bis zum 29. März lädt das Kunstmuseum ein")
        for i, d in enumerate(["21", "22", "23"], start=1)
    ]
    rows.append(_row(4, "22.10"[:2] + ".10", "10:00", "Gjakmarrje", "gjak", 400, "Fotografien bis 31. Dezember 2031"))
    page = _page(rows)
    events = parse_muelheim_html(page, "Ausstellung", now=NOW)
    assert len(events) == 2
    tomas = [e for e in events if e["title"].startswith("TOMAS")][0]
    assert tomas["start_at"] == datetime(2031, 10, 21, 11, 0)  # max(start, heute 00:00)
    assert tomas["end_at"] == datetime(2032, 3, 29, 23, 59)
    assert tomas["category"] == "Ausstellung"
    assert not tomas["short_description"].startswith("11. Oktober")
    gjak = [e for e in events if e["title"] == "Gjakmarrje"][0]
    assert gjak["end_at"] == datetime(2031, 12, 31, 23, 59)


def test_exhibition_started_in_past_starts_today():
    # Serie lief schon vor "heute": erste sichtbare Zeile ist heute 0:00.
    page = _page([_row(1, "21.10", "00:00", "Villa Artis", "villa", 500, "bis 31. Dezember 2031")])
    ev = parse_muelheim_html(page, "Ausstellung", now=datetime(2031, 10, 21, 15, 0))[0]
    assert ev["start_at"] == datetime(2031, 10, 21, 0, 0)
    assert ev["end_at"] == datetime(2031, 12, 31, 23, 59)


def test_parse_end_date_variants():
    from datetime import date
    start = date(2031, 10, 21)
    assert _parse_end_date("11. Oktober 2031 bis 29. März 2032", start) == date(2032, 3, 29)
    assert _parse_end_date("läuft bis 31. Dezember", start) == date(2031, 12, 31)
    assert _parse_end_date("bis 18 Uhr geöffnet", start) is None
    assert _parse_end_date("", start) is None


def test_series_key_strips_date_and_id():
    assert _series_key("/veranstaltungen/theater_trifft_escape_room_am_21.10.2031/464442") == \
        _series_key("/veranstaltungen/theater_trifft_escape_room_am_22.10.2031/464443")


DETAIL_HTML = """
<html><head><script type="application/ld+json">
{"@context": "http://schema.org", "@graph": [{
 "@type": "Event", "name": "JUNOKILL am 29.10.2031",
 "image": {"@type": "ImageObject", "url": "https://img.culturebase.org/3/e/pic_t0.jpeg"},
 "startDate": "2031-10-29T19:00:00+0100", "endDate": "2031-10-21T00:35:37+0200",
 "location": {"@type": "Place", "name": "DAS KAFF \\u2013 bagel Bar \\u0026 coffee salon",
   "address": {"@type": "PostalAddress", "streetAddress": "Bachstraße 12", "postalCode": "45468"},
   "geo": {"@type": "GeoCoordinates", "latitude": "", "longitude": ""}}}]}
</script></head><body>x</body></html>
"""

DETAIL_GEO_HTML = DETAIL_HTML.replace('"latitude": "", "longitude": ""', '"latitude": "51.4318", "longitude": "6.8790"')
DETAIL_COARSE_HTML = DETAIL_HTML.replace('"latitude": "", "longitude": ""', '"latitude": "51.43", "longitude": "6.88"')


def test_parse_detail_json_ld():
    d = _parse_detail(DETAIL_HTML)
    assert d["venue_name"] == "DAS KAFF – bagel Bar & coffee salon"
    assert d["address_text"] == "Bachstraße 12, 45468 Mülheim an der Ruhr"
    assert d["lat"] is None and d["lon"] is None
    assert d["image_url"] == "https://img.culturebase.org/3/e/pic_t0.jpeg"
    assert _parse_detail("<html>Seite nicht gefunden</html>") is None


def test_parse_detail_geo_only_when_precise():
    assert _parse_detail(DETAIL_GEO_HTML)["lat"] == pytest.approx(51.4318)
    assert _parse_detail(DETAIL_GEO_HTML)["lon"] == pytest.approx(6.8790)
    coarse = _parse_detail(DETAIL_COARSE_HTML)
    assert coarse["lat"] is None and coarse["lon"] is None


def test_details_propagate_to_whole_series_and_ignore_garbage_end():
    page = _page(
        [
            _row(1, "24.10", "19:00", "Der Gott des Gemetzels", "gott", 102),
            _row(2, "25.10", "16:00", "Der Gott des Gemetzels", "gott", 103),
            _row(3, "29.10", "19:00", "JUNOKILL", "junokill", 478),
        ]
    )
    rows = _parse_rows(page, "Musik")
    details = {
        _series_key("/veranstaltungen/gott_am_24.10.2031/102"): {
            "venue_name": "Theater an der Ruhr", "address_text": "Akazienallee 61, 45478 Mülheim an der Ruhr",
            "postal": "45478", "lat": 51.4, "lon": 6.9, "image_url": "https://img.culturebase.org/g.jpeg",
            "start": datetime(2031, 10, 24, 19, 0), "end": datetime(2031, 10, 24, 21, 0),
        },
        _series_key("/veranstaltungen/junokill_am_29.10.2031/478"): {
            "venue_name": "DAS KAFF", "address_text": None, "postal": "45468", "lat": None, "lon": None,
            "image_url": None, "start": datetime(2031, 10, 29, 19, 0),
            "end": datetime(2031, 10, 21, 0, 35),  # Müll-endDate vor dem Start
        },
    }
    events = build_events(rows, details, NOW)
    gott = [e for e in events if e["title"].startswith("Der Gott")]
    assert [e["venue_name"] for e in gott] == ["Theater an der Ruhr"] * 2
    assert gott[0]["end_at"] == datetime(2031, 10, 24, 21, 0)  # plausibles endDate, nur am Detail-Tag
    assert gott[1]["end_at"] is None
    assert gott[1]["image_url"] == "https://img.culturebase.org/g.jpeg"
    kaff = [e for e in events if e["title"] == "JUNOKILL"][0]
    assert kaff["venue_name"] == "DAS KAFF"
    assert kaff["end_at"] is None


# ───────────────────────── Fetch-Verhalten (Crawl-delay, Budget) ───────────────


class _FakeResp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


def _patch_client(monkeypatch, handler):
    calls = []

    class FakeClient:
        def __init__(self, *a, **kw):
            assert kw["headers"]["User-Agent"].startswith("Event-App-Essen")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            calls.append(url)
            return handler(url)

    sleeps = []

    async def fake_sleep(sec):
        sleeps.append(sec)

    monkeypatch.setattr(muelheim.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(muelheim.asyncio, "sleep", fake_sleep)
    return calls, sleeps


def test_fetch_respects_crawl_delay_and_request_budget(monkeypatch):
    soon = datetime.now()
    day = (soon + muelheim.timedelta(days=2)).strftime("%d.%m")
    year = (soon + muelheim.timedelta(days=2)).year
    page_tpl = _page([_row(1, day, "19:00", "Test", "test", 1)], next_href="/veranstaltungen?page=1&kategorie=7059").replace("2031", str(year))

    def handler(url):
        if "/veranstaltungen/test_am" in url:
            return _FakeResp(200, DETAIL_HTML)
        return _FakeResp(200, page_tpl)

    calls, sleeps = _patch_client(monkeypatch, handler)
    events = asyncio.run(muelheim.fetch_muelheim_events())
    assert 0 < len(calls) <= muelheim.MAX_TOTAL_REQUESTS
    assert len(sleeps) == len(calls) - 1
    assert all(s >= 10 for s in sleeps)
    assert any("kategorie=7060" in c for c in calls)
    assert events and all(e["source_name"] == "Stadt Mülheim" for e in events)
    assert events[0]["venue_name"] == "DAS KAFF – bagel Bar & coffee salon"


def test_fetch_stops_on_403_without_workaround(monkeypatch):
    calls, _ = _patch_client(monkeypatch, lambda url: _FakeResp(403))
    assert asyncio.run(muelheim.fetch_muelheim_events()) == []
    assert len(calls) == 1  # sofort abgebrochen


def test_fetch_never_raises(monkeypatch):
    def boom(url):
        raise RuntimeError("netz weg")

    _patch_client(monkeypatch, boom)
    assert asyncio.run(muelheim.fetch_muelheim_events()) == []
