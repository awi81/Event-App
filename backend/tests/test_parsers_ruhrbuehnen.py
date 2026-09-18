"""Offline parser tests for Ruhrbühnen (ruhrbuehnen.de Spielplan aggregator).

Fixture is a trimmed copy of the real markup captured on 2026-09-18 — no
network access required. ``now`` is injected so past/horizon filtering is
deterministic. The three ``data-date`` unix timestamps below correspond to
2026-09-17 (yesterday), 2026-09-18 (today) and 2026-09-19 (tomorrow) at
noon Europe/Berlin.
"""
from datetime import datetime, timedelta

import pytest

from app.services.ruhrbuehnen import parse_ruhrbuehnen_html

NOW = datetime(2026, 9, 18, 10, 0)  # naive Berlin time

TS_YESTERDAY = 1789639200  # 2026-09-17 12:00 Europe/Berlin
TS_TODAY = 1789725600  # 2026-09-18 12:00 Europe/Berlin
TS_TOMORROW = 1789812000  # 2026-09-19 12:00 Europe/Berlin
TS_BEYOND_HORIZON = 1801479600  # 2027-02-01 12:00 Europe/Berlin (>120 days ahead)


def _grid_item(href, title, meta, spans, img=True):
    img_html = (
        '<img class="responsive-lg" data-responsive-src="/media/x.jpg" src="x.gif"/>'
        if img
        else ""
    )
    span_html = "".join(f"<span>{s}</span>" for s in spans)
    return f"""
    <div class="grid-item col-xs-12 col-sm-6 col-md-6 col-lg-4 ">
      <a href="{href}">
        <span class="img">{img_html}</span>
        <h3 class="event-title">{title}</h3>
        <h4 class="demi hidden-xs event-meta">{meta}</h4>
        <div class="h5 light venue-info event-locations">
          {span_html}
        </div>
      </a>
    </div>
    """


_ITEM_BRUCKNER = _grid_item(
    "/de/spielplan/bruckner-3/events/222754/",
    "Bruckner 3",
    "19:30 |\n      Musical &amp; Konzert |\n      Essen",
    ["19:30", "Theater und Philharmonie Essen", "Philharmonie Essen"],
)
_ITEM_AQUA = _grid_item(
    "/de/spielplan/aquacycles-2/events/223883/",
    "AQUA@CYCLES",
    "19:30 |\n      Mülheim an der Ruhr",
    ["19:30", "Theater an der Ruhr", "VolXbühne (Theaterstudio)"],
)
_ITEM_KINDER = _grid_item(
    "/de/spielplan/theater-fuer-kinder/events/999001/",
    "Theater für Kinder",
    "16:00 |\n      Kinder &amp; Jugend |\n      Bochum",
    ["16:00", "Schauspielhaus Bochum"],
)
_ITEM_DORTMUND = _grid_item(
    "https://example-theater-dortmund.de/stueck",
    "Nicht im Ruhrgebiet unserer App",
    "20:00 |\n      Schauspiel |\n      Dortmund",
    ["20:00", "Theater Dortmund"],
)
_ITEM_SYMPOSIUM = _grid_item(
    "/de/spielplan/symposium-3/events/223912/",
    "Symposium",
    "10:00 |\n      Mülheim an der Ruhr",
    ["10:00", "Theater an der Ruhr"],
    img=False,
)
_ITEM_YESTERDAY = _grid_item(
    "/de/spielplan/gestern/events/1/",
    "Vergangene Vorstellung",
    "19:00 |\n      Essen",
    ["19:00", "Grillo-Theater"],
)
_ITEM_BEYOND_HORIZON = _grid_item(
    "/de/spielplan/weit-weg/events/1/",
    "Weit in der Zukunft",
    "19:00 |\n      Essen",
    ["19:00", "Grillo-Theater"],
)

RUHRBUEHNEN_HTML = f"""
<!doctype html>
<html lang="de">
<body>
<div class="grid endless-loader grid-datepicker">
  <div class="schedule-date" data-date="{TS_TODAY}">
    <div><h2 class="grid-datepicker-target">Fr, 18. September</h2></div>
  </div>
  <div class="row" data-date="{TS_TODAY}">
    {_ITEM_BRUCKNER}
    {_ITEM_AQUA}
    {_ITEM_KINDER}
    {_ITEM_DORTMUND}
    <div class="grid-item col-xs-12">
      <a href="/de/spielplan/kaputt/events/1/">
        <h4 class="demi hidden-xs event-meta">19:00 | Essen</h4>
      </a>
    </div>
  </div>
  <div class="space"></div>
  <div class="schedule-date" data-date="{TS_TOMORROW}">
    <div><h2 class="grid-datepicker-target">Sa, 19. September</h2></div>
  </div>
  <div class="row" data-date="{TS_TOMORROW}">
    {_ITEM_SYMPOSIUM}
  </div>
  <div class="space"></div>
  <div class="schedule-date" data-date="{TS_YESTERDAY}">
    <div><h2 class="grid-datepicker-target">Do, 17. September</h2></div>
  </div>
  <div class="row" data-date="{TS_YESTERDAY}">
    {_ITEM_YESTERDAY}
  </div>
  <div class="space"></div>
  <div class="schedule-date" data-date="{TS_BEYOND_HORIZON}">
    <div><h2 class="grid-datepicker-target">Mo, 1. Februar</h2></div>
  </div>
  <div class="row" data-date="{TS_BEYOND_HORIZON}">
    {_ITEM_BEYOND_HORIZON}
  </div>
</div>
</body>
</html>
"""


def test_parses_expected_events_within_window():
    events = parse_ruhrbuehnen_html(RUHRBUEHNEN_HTML, now=NOW)
    titles = {e["title"] for e in events}
    # Dortmund dropped (out of scope), yesterday dropped (past), Feb dropped (>120d),
    # the item without a title/link dropped (broken).
    assert titles == {"Bruckner 3", "AQUA@CYCLES", "Theater für Kinder", "Symposium"}


def test_event_fields_and_venue_extraction():
    events = parse_ruhrbuehnen_html(RUHRBUEHNEN_HTML, now=NOW)
    bruckner = next(e for e in events if e["title"] == "Bruckner 3")
    assert bruckner["start_at"] == datetime(2026, 9, 18, 19, 30)
    assert bruckner["source_url"] == (
        "https://www.ruhrbuehnen.de/de/spielplan/bruckner-3/events/222754/"
    )
    assert bruckner["source_name"] == "Ruhrbühnen"
    assert bruckner["venue_name"] == "Philharmonie Essen"  # specific stage, not the company
    assert bruckner["city"] == "Essen"
    assert bruckner["indoor_outdoor"] == "indoor"
    assert bruckner["category"] == "Musical & Konzert"
    assert bruckner["kids_suitable"] == "unknown"
    assert bruckner["image_url"] == "https://www.ruhrbuehnen.de/media/x.jpg"

    aqua = next(e for e in events if e["title"] == "AQUA@CYCLES")
    assert aqua["city"] == "Mülheim an der Ruhr"
    assert aqua["venue_name"] == "VolXbühne (Theaterstudio)"
    assert aqua["start_at"] == datetime(2026, 9, 18, 19, 30)

    symposium = next(e for e in events if e["title"] == "Symposium")
    # Only one venue span present -> falls back to it instead of the stage.
    assert symposium["venue_name"] == "Theater an der Ruhr"
    assert symposium["category"] is None  # no Sparte in the meta line
    assert symposium["image_url"] is None
    assert symposium["start_at"] == datetime(2026, 9, 19, 10, 0)


def test_kids_suitable_yes_for_kinder_jugend_sparte():
    events = parse_ruhrbuehnen_html(RUHRBUEHNEN_HTML, now=NOW)
    kinder = next(e for e in events if e["title"] == "Theater für Kinder")
    assert kinder["kids_suitable"] == "yes"
    assert kinder["category"] == "Kinder & Jugend"


def test_geographic_filter_drops_dortmund():
    events = parse_ruhrbuehnen_html(RUHRBUEHNEN_HTML, now=NOW)
    assert not any("Dortmund" in e.get("city", "") for e in events)
    assert not any(e["title"] == "Nicht im Ruhrgebiet unserer App" for e in events)


def test_broken_item_without_title_is_skipped():
    events = parse_ruhrbuehnen_html(RUHRBUEHNEN_HTML, now=NOW)
    assert all(e["title"] for e in events)


def test_past_and_beyond_horizon_events_are_filtered():
    events = parse_ruhrbuehnen_html(RUHRBUEHNEN_HTML, now=NOW)
    starts = [e["start_at"] for e in events]
    assert all(NOW.date() <= s.date() <= NOW.date() + timedelta(days=120) for s in starts)
    assert not any(e["title"] == "Vergangene Vorstellung" for e in events)
    assert not any(e["title"] == "Weit in der Zukunft" for e in events)


def test_canonical_ids_unique_and_stable():
    events = parse_ruhrbuehnen_html(RUHRBUEHNEN_HTML, now=NOW)
    ids = [e["canonical_id"] for e in events]
    assert len(ids) == len(set(ids))
    assert all(len(cid) == 16 for cid in ids)
    again = parse_ruhrbuehnen_html(RUHRBUEHNEN_HTML, now=NOW)
    assert [e["canonical_id"] for e in again] == ids


def test_event_meta_without_sparte_still_extracts_city_and_time():
    events = parse_ruhrbuehnen_html(RUHRBUEHNEN_HTML, now=NOW)
    symposium = next(e for e in events if e["title"] == "Symposium")
    assert symposium["city"] == "Mülheim an der Ruhr"
    assert symposium["start_at"].time() == datetime(2026, 9, 19, 10, 0).time()


def test_empty_html_returns_empty_list():
    assert parse_ruhrbuehnen_html("<html><body></body></html>", now=NOW) == []
