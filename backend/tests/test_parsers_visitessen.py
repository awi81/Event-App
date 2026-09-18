"""Offline parser tests for visitessen.de (destination.one / eT4 Meta API).

Fixtures are trimmed copies of real API items — no network access required.
``now`` is injected so the past/horizon filters are deterministic.
"""
import copy
from datetime import datetime, timedelta

import pytest

from app.services.visitessen import (
    MAX_OCCURRENCES_PER_ITEM,
    build_detail_url,
    extract_meta_token,
    parse_visitessen_items,
    slugify,
)

NOW = datetime(2026, 9, 18, 10, 0)  # Friday, naive Berlin time

SEARCH_PAGE_HTML = """
<!DOCTYPE html>
<html lang="de">
<head><title>Veranstaltungen | visitessen</title></head>
<body>
<script>
  window.META_TOKEN = "t1.abc";
  window.META_CONFIG = {"experience":"visitessen","licensekey":"t1.abc","template":"ET2014A.json"};
</script>
</body>
</html>
"""

# Exhibition: 3 daily intervals, one already in the past. Full texts + price + geo + image.
ITEM_EXHIBITION = {
    "global_id": "e_101281486",
    "id": "101281486",
    "title": "Unter Tage. Unter Zwang. NS-Zwangsarbeit im Ruhrbergbau",
    "type": "Event",
    "categories": ["Ausstellung"],
    "texts": [
        {"rel": "teaser", "type": "text/plain", "value": ""},
        {
            "rel": "details",
            "type": "text/html",
            "value": "<p>Die Ausstellung in <b>Halle 8</b> zeigt,&nbsp;wie Zwangsarbeit "
                     "im Ruhrbergbau funktionierte.</p>",
        },
        {"rel": "PRICE_INFO", "type": "text/plain", "value": "Eintritt frei"},
    ],
    "name": "Halle 8",
    "company": "",
    "street": "UNESCO-Welterbe Zollverein",
    "zip": "45309",
    "city": "Essen",
    "district": "",
    "geo": {"main": {"latitude": 51.48759, "longitude": 7.04479}},
    "media_objects": [
        {"rel": "venuewebsite", "url": "https://www.zollverein.de/"},
        {
            "rel": "default",
            "type": "image/jpeg",
            "url": "https://dam.destination.one/3836403/abc/.jpg",
        },
    ],
    "timeIntervals": [
        {"weekdays": [], "start": "2026-09-10T12:00:00+02:00", "end": "2026-09-10T18:00:00+02:00",
         "tz": "Europe/Berlin", "interval": 1},
        {"weekdays": [], "start": "2026-09-20T12:00:00+02:00", "end": "2026-09-20T18:00:00+02:00",
         "tz": "Europe/Berlin", "interval": 1},
        {"weekdays": [], "start": "2026-09-21T12:00:00+02:00", "end": "2026-09-21T18:00:00+02:00",
         "tz": "Europe/Berlin", "interval": 1},
    ],
    "attributes": [
        {"key": "VO_Id", "value": "224289"},
        {"key": "interval_match_count", "value": "2"},
    ],
}

# Cabaret: no geo, no media, teaser without value, sold out.
ITEM_KABARETT = {
    "global_id": "e_200000001",
    "title": "Kabarett-Abend mit Max Mustermann",
    "categories": ["Kabarett & Co."],
    "texts": [{"rel": "teaser", "type": "text/plain"}],
    "name": "Stratmanns Theater",
    "street": "Kettwiger Str. 2-10",
    "zip": "45127",
    "city": "Essen",
    "geo": {},
    "media_objects": [],
    "timeIntervals": [
        {"weekdays": [], "start": "2026-10-03T20:00:00+02:00", "end": "2026-10-03T22:00:00+02:00",
         "tz": "Europe/Berlin", "interval": 1},
    ],
    "attributes": [{"key": "DETAILS_AUSGEBUCHT", "value": "true"}],
}

# Kids programme with a weekly recurrence rule (every Saturday until 10.10.).
ITEM_KINDER = {
    "global_id": "e_300000001",
    "title": "Märchenstunde für Kinder",
    "categories": ["Kinderprogramm", "Festival/Open-Air"],
    "texts": [{"rel": "teaser", "type": "text/plain", "value": "Geschichten im Park."}],
    "name": "Grugapark",
    "street": "Virchowstr. 167a",
    "zip": "45147",
    "city": "",
    "geo": {"main": {"latitude": 51.4295, "longitude": 6.9908}},
    "media_objects": [
        {"rel": "default", "type": "image/png", "url": "https://dam.destination.one/1/kids.png"},
    ],
    "timeIntervals": [
        {"weekdays": ["Saturday"], "start": "2026-09-19T15:00:00+02:00",
         "end": "2026-09-19T16:00:00+02:00", "repeatUntil": "2026-10-10T15:00:00+02:00",
         "tz": "Europe/Berlin", "freq": "Weekly", "interval": 1},
    ],
    "attributes": [],
}

FIXTURE_ITEMS = [ITEM_EXHIBITION, ITEM_KABARETT, ITEM_KINDER]


def _events_for(events, global_id):
    return sorted(
        (e for e in events if f"/{global_id}/" in e["source_url"]),
        key=lambda e: e["start_at"],
    )


# ─────────────────────────────── token ───────────────────────────────────────


def test_extract_meta_token_from_search_page():
    assert extract_meta_token(SEARCH_PAGE_HTML) == "t1.abc"


def test_extract_meta_token_falls_back_to_licensekey():
    html = '<script>var cfg = {"experience":"visitessen","licensekey":"t1.fallback"};</script>'
    assert extract_meta_token(html) == "t1.fallback"


def test_extract_meta_token_missing_returns_none():
    assert extract_meta_token("<html><body>nothing here</body></html>") is None
    assert extract_meta_token("") is None


# ─────────────────────────── basic parsing ───────────────────────────────────


def test_parse_items_basic_fields():
    events = parse_visitessen_items(copy.deepcopy(FIXTURE_ITEMS), now=NOW)
    # Exhibition 2 (future) + Kabarett 1 + Kinder 4 Saturdays (19.9., 26.9., 3.10., 10.10.)
    assert len(events) == 7

    exhibition = _events_for(events, "e_101281486")
    assert len(exhibition) == 2
    first = exhibition[0]
    assert first["title"] == "Unter Tage. Unter Zwang. NS-Zwangsarbeit im Ruhrbergbau"
    assert first["start_at"] == datetime(2026, 9, 20, 12, 0)
    assert first["end_at"] == datetime(2026, 9, 20, 18, 0)
    assert first["start_at"].tzinfo is None
    assert first["venue_name"] == "Halle 8"
    assert first["address_text"] == "UNESCO-Welterbe Zollverein, 45309 Essen"
    assert first["city"] == "Essen"
    assert first["source_name"] == "visitessen.de"
    assert first["category"] == "Ausstellung"
    assert first["is_permanent_offer"] is False
    assert first["source_url"] == (
        "https://pages.visitessen.de/de/visitessen/default/detail/Event/"
        "e_101281486/unter-tage-unter-zwang-ns-zwangsarbeit-im-ruhrbergbau"
    )

    kabarett = _events_for(events, "e_200000001")
    assert len(kabarett) == 1
    assert kabarett[0]["start_at"] == datetime(2026, 10, 3, 20, 0)
    assert kabarett[0]["venue_name"] == "Stratmanns Theater"
    assert kabarett[0]["address_text"] == "Kettwiger Str. 2-10, 45127 Essen"


def test_past_intervals_are_filtered():
    events = parse_visitessen_items([copy.deepcopy(ITEM_EXHIBITION)], now=NOW)
    starts = sorted(e["start_at"] for e in events)
    assert starts == [datetime(2026, 9, 20, 12, 0), datetime(2026, 9, 21, 12, 0)]


def test_occurrence_today_is_kept_and_horizon_is_enforced():
    item = copy.deepcopy(ITEM_KABARETT)
    item["timeIntervals"] = [
        {"start": "2026-09-18T09:00:00+02:00", "end": "2026-09-18T10:00:00+02:00"},  # today, earlier
        {"start": (NOW + timedelta(days=119)).strftime("%Y-%m-%dT20:00:00+01:00")},
        {"start": (NOW + timedelta(days=121)).strftime("%Y-%m-%dT20:00:00+01:00")},
    ]
    events = parse_visitessen_items([item], now=NOW)
    starts = sorted(e["start_at"] for e in events)
    assert len(starts) == 2
    assert starts[0] == datetime(2026, 9, 18, 9, 0)
    assert starts[1].date() == (NOW + timedelta(days=119)).date()


def test_canonical_ids_unique_per_occurrence_and_stable():
    events = parse_visitessen_items(copy.deepcopy(FIXTURE_ITEMS), now=NOW)
    ids = [e["canonical_id"] for e in events]
    assert len(ids) == len(set(ids))
    assert all(len(cid) == 16 for cid in ids)
    again = parse_visitessen_items(copy.deepcopy(FIXTURE_ITEMS), now=NOW)
    assert [e["canonical_id"] for e in again] == ids


# ────────────────────────── recurrence / caps ────────────────────────────────


def test_series_capped_at_60_occurrences():
    item = copy.deepcopy(ITEM_EXHIBITION)
    item["timeIntervals"] = [
        {
            "weekdays": [],
            "start": (NOW + timedelta(days=i)).strftime("%Y-%m-%dT12:00:00+02:00"),
            "end": (NOW + timedelta(days=i)).strftime("%Y-%m-%dT18:00:00+02:00"),
            "interval": 1,
        }
        for i in range(90)
    ]
    events = parse_visitessen_items([item], now=NOW)
    assert len(events) == MAX_OCCURRENCES_PER_ITEM == 60
    # chronological: the first 60 days, not an arbitrary subset
    assert events[0]["start_at"].date() == NOW.date()
    assert events[-1]["start_at"].date() == (NOW + timedelta(days=59)).date()


def test_daily_rule_is_expanded_and_capped():
    item = copy.deepcopy(ITEM_EXHIBITION)
    item["timeIntervals"] = [
        {"weekdays": [], "start": "2026-08-11T12:00:00+02:00", "end": "2026-08-11T18:00:00+02:00",
         "tz": "Europe/Berlin", "freq": "Daily", "interval": 1},  # open-ended
    ]
    events = parse_visitessen_items([item], now=NOW)
    assert len(events) == 60
    assert events[0]["start_at"] == datetime(2026, 9, 18, 12, 0)
    assert events[1]["start_at"] == datetime(2026, 9, 19, 12, 0)


def test_weekly_rule_expansion():
    events = parse_visitessen_items([copy.deepcopy(ITEM_KINDER)], now=NOW)
    starts = [e["start_at"] for e in events]
    assert starts == [
        datetime(2026, 9, 19, 15, 0),
        datetime(2026, 9, 26, 15, 0),
        datetime(2026, 10, 3, 15, 0),
        datetime(2026, 10, 10, 15, 0),
    ]
    assert all(e["end_at"] == e["start_at"] + timedelta(hours=1) for e in events)


def test_weekly_rule_keeps_wall_clock_across_dst_change():
    # Tuesdays 19:30 from 22.09. (CEST) until 17.11. (CET) — must stay 19:30.
    item = copy.deepcopy(ITEM_KABARETT)
    item["timeIntervals"] = [
        {"weekdays": ["Tuesday"], "start": "2026-09-22T19:30:00+02:00",
         "end": "2026-09-22T21:00:00+02:00", "repeatUntil": "2026-11-17T19:30:00+01:00",
         "tz": "Europe/Berlin", "freq": "Weekly", "interval": 1},
    ]
    events = parse_visitessen_items([item], now=NOW)
    assert len(events) == 9
    assert {e["start_at"].time() for e in events} == {datetime(2026, 1, 1, 19, 30).time()}
    assert events[-1]["start_at"] == datetime(2026, 11, 17, 19, 30)


def test_biweekly_rule_uses_interval():
    item = copy.deepcopy(ITEM_KABARETT)
    item["timeIntervals"] = [
        {"weekdays": ["Saturday"], "start": "2026-11-14T12:00:00+01:00",
         "end": "2026-11-14T16:30:00+01:00", "repeatUntil": "2026-12-27T12:00:00+01:00",
         "tz": "Europe/Berlin", "freq": "Weekly", "interval": 2},
    ]
    events = parse_visitessen_items([item], now=NOW)
    assert [e["start_at"].date() for e in events] == [
        datetime(2026, 11, 14).date(),
        datetime(2026, 11, 28).date(),
        datetime(2026, 12, 12).date(),
        datetime(2026, 12, 26).date(),
    ]


def test_monthly_nth_weekday_rule():
    # 2nd Tuesday of every month starting 11.08.2026, open-ended.
    item = copy.deepcopy(ITEM_KABARETT)
    item["timeIntervals"] = [
        {"weekdays": [], "start": "2026-08-11T12:00:00+02:00", "end": "2026-08-11T16:00:00+02:00",
         "tz": "Europe/Berlin", "freq": "Monthly", "dayOrdinal": 2, "weekday": "Tuesday",
         "interval": 1},
    ]
    events = parse_visitessen_items([item], now=NOW)
    assert [e["start_at"].date() for e in events] == [
        datetime(2026, 10, 13).date(),
        datetime(2026, 11, 10).date(),
        datetime(2026, 12, 8).date(),
        datetime(2027, 1, 12).date(),
    ]


def test_hide_end_drops_end_at():
    item = copy.deepcopy(ITEM_KABARETT)
    item["timeIntervals"][0]["hideEnd"] = True
    events = parse_visitessen_items([item], now=NOW)
    assert len(events) == 1
    assert events[0]["end_at"] is None


# ───────────────────────── slug / deep link ──────────────────────────────────


def test_slugify_handles_umlauts_and_punctuation():
    assert slugify("Märchenstückchen – eine Komödie für Erwachsene") == (
        "maerchenstueckchen-eine-komoedie-fuer-erwachsene"
    )
    assert slugify("Straße & Café!") == "strasse-cafe"
    assert slugify("  ---  ") == ""


def test_build_detail_url():
    assert build_detail_url("e_101281486", "Unter Tage. Unter Zwang.") == (
        "https://pages.visitessen.de/de/visitessen/default/detail/Event/"
        "e_101281486/unter-tage-unter-zwang"
    )
    assert build_detail_url("e_1", "???").endswith("/e_1/event")


# ───────────────────────── kids / indoor mapping ─────────────────────────────


def test_kids_and_indoor_outdoor_mapping():
    events = parse_visitessen_items(copy.deepcopy(FIXTURE_ITEMS), now=NOW)

    exhibition = _events_for(events, "e_101281486")[0]
    assert exhibition["kids_suitable"] == "unknown"
    assert exhibition["indoor_outdoor"] == "indoor"

    kabarett = _events_for(events, "e_200000001")[0]
    assert kabarett["indoor_outdoor"] == "indoor"

    kinder = _events_for(events, "e_300000001")[0]
    assert kinder["kids_suitable"] == "yes"  # category "Kinderprogramm"
    assert kinder["indoor_outdoor"] == "outdoor"  # "Festival/Open-Air"
    assert kinder["category"] == "Kinderprogramm"  # first raw category, unchanged


def test_kids_likely_from_title_keyword():
    item = copy.deepcopy(ITEM_KABARETT)
    item["title"] = "Puppentheater am Nachmittag"
    item["categories"] = ["Sonstiges"]
    events = parse_visitessen_items([item], now=NOW)
    assert events[0]["kids_suitable"] == "likely"
    assert events[0]["indoor_outdoor"] == "unknown"
    assert events[0]["category"] == "Sonstiges"


def test_indoor_and_outdoor_categories_give_both():
    item = copy.deepcopy(ITEM_KABARETT)
    item["categories"] = ["Schauspiel", "Festival/Open-Air"]
    events = parse_visitessen_items([item], now=NOW)
    assert events[0]["indoor_outdoor"] == "both"


# ─────────────────────── geo / image / texts / price ─────────────────────────


def test_geo_image_description_and_price():
    events = parse_visitessen_items(copy.deepcopy(FIXTURE_ITEMS), now=NOW)

    exhibition = _events_for(events, "e_101281486")[0]
    assert exhibition["lat"] == pytest.approx(51.48759)
    assert exhibition["lon"] == pytest.approx(7.04479)
    assert exhibition["image_url"] == "https://dam.destination.one/3836403/abc/.jpg"
    # empty teaser → details HTML stripped
    assert exhibition["short_description"] == (
        "Die Ausstellung in Halle 8 zeigt, wie Zwangsarbeit im Ruhrbergbau funktionierte."
    )
    assert exhibition["price_text"] == "Eintritt frei"

    kabarett = _events_for(events, "e_200000001")[0]
    assert "lat" not in kabarett and "lon" not in kabarett
    assert kabarett["image_url"] is None
    assert kabarett["short_description"] is None
    assert kabarett["price_text"] == "Ausverkauft"

    kinder = _events_for(events, "e_300000001")[0]
    assert kinder["short_description"] == "Geschichten im Park."
    assert kinder["image_url"] == "https://dam.destination.one/1/kids.png"
    assert kinder["city"] == "Essen"  # empty city → default


def test_implausible_coordinates_are_dropped():
    item = copy.deepcopy(ITEM_EXHIBITION)
    item["geo"] = {"main": {"latitude": 0.0, "longitude": 0.0}}
    events = parse_visitessen_items([item], now=NOW)
    assert "lat" not in events[0]


def test_multiline_price_is_joined():
    item = copy.deepcopy(ITEM_EXHIBITION)
    item["texts"].append({"rel": "PRICE_INFO", "type": "text/plain", "value": "VVK 12€\nAK 14€"})
    item["texts"] = [t for t in item["texts"] if t.get("value") != "Eintritt frei"]
    events = parse_visitessen_items([item], now=NOW)
    assert events[0]["price_text"] == "VVK 12€ | AK 14€"


# ───────────────────────────── robustness ────────────────────────────────────


def test_broken_items_are_skipped_but_rest_survives():
    broken = [
        None,
        "not a dict",
        {"global_id": "e_400", "title": "Ohne Termine"},
        {"global_id": "e_401", "title": "Kaputte Intervalle", "timeIntervals": "nope"},
        {"global_id": "e_402", "title": "Kaputtes Datum",
         "timeIntervals": [{"start": "kein datum"}]},
        {"title": "Ohne global_id", "timeIntervals": [{"start": "2026-10-01T10:00:00+02:00"}]},
        {"global_id": "e_403", "title": "",
         "timeIntervals": [{"start": "2026-10-01T10:00:00+02:00"}]},
        {"global_id": "e_404", "title": "Kaputte Metadaten", "categories": None,
         "texts": [None, 5], "media_objects": [None], "geo": "x", "attributes": [None],
         "timeIntervals": [{"start": "2026-10-01T10:00:00+02:00"}]},
    ]
    events = parse_visitessen_items(broken + [copy.deepcopy(ITEM_KABARETT)], now=NOW)
    titles = {e["title"] for e in events}
    assert titles == {"Kaputte Metadaten", "Kabarett-Abend mit Max Mustermann"}


def test_cancelled_item_is_skipped():
    item = copy.deepcopy(ITEM_KABARETT)
    item["attributes"] = [{"key": "DETAILS_ABGESAGT", "value": "true"}]
    assert parse_visitessen_items([item], now=NOW) == []


def test_soft_hyphen_in_title_is_removed():
    item = copy.deepcopy(ITEM_KABARETT)
    item["title"] = 'Öffent­licher Proben­besuch zu "Der Nussknacker"'
    events = parse_visitessen_items([item], now=NOW)
    assert events[0]["title"] == 'Öffentlicher Probenbesuch zu "Der Nussknacker"'
    assert "oeffentlicher-probenbesuch" in events[0]["source_url"]


def test_empty_input():
    assert parse_visitessen_items([], now=NOW) == []
    assert parse_visitessen_items(None, now=NOW) == []
