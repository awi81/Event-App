"""Offline parser tests for Zeiss Planetarium Bochum (culturebase.org event.json API).

Fixtures are trimmed copies of real ``EventOverview`` items captured from
``GET /de_DE/event.json?date=18.09.2026&p=1&dynamic_calendar=calendar`` on
2026-09-18 — no network access required. ``now`` is injected so the
past/horizon filters are deterministic.
"""
import copy
from datetime import datetime, timedelta

import pytest

from app.services.planetarium_bochum import (
    ADDRESS_TEXT,
    CITY,
    VENUE_LAT,
    VENUE_LON,
    VENUE_NAME,
    parse_planetarium_bochum_items,
)

NOW = datetime(2026, 9, 18, 10, 0)  # naive Berlin time

# Real item (trimmed): a music show today at 20:45.
ITEM_MUSIK = {
    "IdEventDate": 18021651,
    "Title": "The Dark Side of The Moon Planetarium Experience",
    "DetailUrl": "/de_DE/calendar/the-dark-side-of-the-moon-planetarium-expe.1381412?event_date=18021651",
    "CalendarDisplayDateTimeStart": "2026-09-18 20:45",
    "City": "Bochum",
    "Location": "Zeiss Planetarium Bochum",
    "ContentCategory": "Musik",
    "Keyword": "MusikShow",
    "Description": "Erleben Sie das legendäre Album «Dark Side of the Moon» von Pink Floyd\nals unvergessliches Planetarium-Erlebnis.",
    "PictureUri": "https://img.culturebase.org/6/b/1/2/7/pic_1771346027_6b127cec511ae0976e8c7c2e5cc11177.jpeg",
    "HasEventPicture": True,
    "IsSoldOut": False,
    "IsCanceled": False,
}

# Real item: a kids show tomorrow with an explicit age note in the description.
ITEM_KINDER = {
    "IdEventDate": 18021380,
    "Title": "Fritz Fliege fliegt ins Weltall",
    "DetailUrl": "/de_DE/calendar/fritz-fliege-fliegt-ins-weltall.1234567?event_date=18021380",
    "CalendarDisplayDateTimeStart": "2026-09-19 11:30",
    "City": "Bochum",
    "Location": "Zeiss Planetarium Bochum",
    "ContentCategory": "Diverses",
    "Keyword": "KinderShow",
    "Description": "Begleiten Sie Fritz, die neugierige Fliege, auf einem Abenteuer durchs Weltall. Empfohlen ab 4 Jahren.",
    "PictureUri": "https://img.culturebase.org/1/1/1/1/1/fritz.jpeg",
    "HasEventPicture": True,
    "IsSoldOut": False,
    "IsCanceled": False,
}

# Real item: a sold-out concert further out, image only via EventPicture (no PictureUri).
ITEM_KONZERT = {
    "IdEventDate": 18021999,
    "Title": "artSPACE - Stradivaris Erben",
    "DetailUrl": "/de_DE/calendar/artspace-stradivaris-erben.7654321?event_date=18021999",
    "CalendarDisplayDateTimeStart": "2026-09-22 20:00",
    "City": "Bochum",
    "Location": "Zeiss Planetarium Bochum",
    "ContentCategory": "Musik",
    "Keyword": "Konzert",
    "Description": "Kammermusik unter der Sternenkuppel.",
    "PictureUri": None,
    "EventPicture": "https://imgtoolkit.culturebase.org?file=stradivaris.jpeg&do=crop",
    "HasEventPicture": True,
    "IsSoldOut": True,
    "IsCanceled": False,
}

FIXTURE_ITEMS = [ITEM_MUSIK, ITEM_KINDER, ITEM_KONZERT]


def _by_title(events, title):
    return next(e for e in events if e["title"] == title)


# ─────────────────────────────── basic parsing ───────────────────────────────


def test_parse_items_basic_fields():
    events = parse_planetarium_bochum_items(copy.deepcopy(FIXTURE_ITEMS), now=NOW)
    assert len(events) == 3

    musik = _by_title(events, "The Dark Side of The Moon Planetarium Experience")
    assert musik["start_at"] == datetime(2026, 9, 18, 20, 45)
    assert musik["venue_name"] == VENUE_NAME == "Zeiss Planetarium Bochum"
    assert musik["address_text"] == ADDRESS_TEXT
    assert musik["city"] == CITY == "Bochum"
    assert musik["lat"] == pytest.approx(VENUE_LAT)
    assert musik["lon"] == pytest.approx(VENUE_LON)
    assert musik["source_url"] == (
        "https://planetarium-bochum.de/de_DE/calendar/"
        "the-dark-side-of-the-moon-planetarium-expe.1381412?event_date=18021651"
    )
    assert musik["source_name"] == "Planetarium Bochum"
    assert musik["indoor_outdoor"] == "indoor"
    assert musik["category"] == "MusikShow"
    assert musik["image_url"] == ITEM_MUSIK["PictureUri"]
    assert "Pink Floyd" in musik["short_description"]


def test_canonical_ids_unique_and_stable():
    events = parse_planetarium_bochum_items(copy.deepcopy(FIXTURE_ITEMS), now=NOW)
    ids = [e["canonical_id"] for e in events]
    assert len(ids) == len(set(ids))
    assert all(len(cid) == 16 for cid in ids)
    again = parse_planetarium_bochum_items(copy.deepcopy(FIXTURE_ITEMS), now=NOW)
    assert [e["canonical_id"] for e in again] == ids


def test_duplicate_items_are_deduplicated():
    events = parse_planetarium_bochum_items(
        [copy.deepcopy(ITEM_MUSIK), copy.deepcopy(ITEM_MUSIK)], now=NOW
    )
    assert len(events) == 1


# ────────────────────────────── kids / category ──────────────────────────────


def test_kids_suitable_yes_for_kindershow_keyword():
    events = parse_planetarium_bochum_items(copy.deepcopy(FIXTURE_ITEMS), now=NOW)
    kinder = _by_title(events, "Fritz Fliege fliegt ins Weltall")
    assert kinder["kids_suitable"] == "yes"
    assert kinder["category"] == "KinderShow"


def test_kids_suitable_yes_from_age_note_without_kinder_keyword():
    item = copy.deepcopy(ITEM_KONZERT)
    item["Keyword"] = "Konzert"
    item["Description"] = "Ein Familienkonzert, empfohlen ab 6 Jahren."
    events = parse_planetarium_bochum_items([item], now=NOW)
    assert events[0]["kids_suitable"] == "yes"


def test_kids_suitable_unknown_without_signal():
    events = parse_planetarium_bochum_items(copy.deepcopy(FIXTURE_ITEMS), now=NOW)
    musik = _by_title(events, "The Dark Side of The Moon Planetarium Experience")
    assert musik["kids_suitable"] == "unknown"


# ───────────────────────────── price / image ─────────────────────────────────


def test_sold_out_sets_price_text():
    events = parse_planetarium_bochum_items(copy.deepcopy(FIXTURE_ITEMS), now=NOW)
    konzert = _by_title(events, "artSPACE - Stradivaris Erben")
    assert konzert["price_text"] == "Ausverkauft"
    assert konzert["category"] == "Konzert"


def test_image_falls_back_to_event_picture_when_no_picture_uri():
    events = parse_planetarium_bochum_items(copy.deepcopy(FIXTURE_ITEMS), now=NOW)
    konzert = _by_title(events, "artSPACE - Stradivaris Erben")
    assert konzert["image_url"] == ITEM_KONZERT["EventPicture"]


def test_no_price_text_when_not_sold_out():
    events = parse_planetarium_bochum_items(copy.deepcopy(FIXTURE_ITEMS), now=NOW)
    musik = _by_title(events, "The Dark Side of The Moon Planetarium Experience")
    assert musik["price_text"] is None


# ───────────────────────── past / horizon / canceled ──────────────────────────


def test_past_event_is_filtered():
    item = copy.deepcopy(ITEM_MUSIK)
    item["CalendarDisplayDateTimeStart"] = "2026-09-10 20:00"  # 8 days before NOW
    assert parse_planetarium_bochum_items([item], now=NOW) == []


def test_today_earlier_time_is_kept():
    item = copy.deepcopy(ITEM_MUSIK)
    item["CalendarDisplayDateTimeStart"] = "2026-09-18 09:00"  # today, before NOW's 10:00
    events = parse_planetarium_bochum_items([item], now=NOW)
    assert len(events) == 1
    assert events[0]["start_at"] == datetime(2026, 9, 18, 9, 0)


def test_beyond_60_day_horizon_is_filtered():
    item = copy.deepcopy(ITEM_MUSIK)
    item["CalendarDisplayDateTimeStart"] = (NOW + timedelta(days=61)).strftime("%Y-%m-%d 20:00")
    assert parse_planetarium_bochum_items([item], now=NOW) == []


def test_within_60_day_horizon_is_kept():
    item = copy.deepcopy(ITEM_MUSIK)
    item["CalendarDisplayDateTimeStart"] = (NOW + timedelta(days=59)).strftime("%Y-%m-%d 20:00")
    events = parse_planetarium_bochum_items([item], now=NOW)
    assert len(events) == 1


def test_canceled_event_is_skipped():
    item = copy.deepcopy(ITEM_MUSIK)
    item["IsCanceled"] = True
    assert parse_planetarium_bochum_items([item], now=NOW) == []


# ───────────────────────────── robustness ────────────────────────────────────


def test_broken_items_are_skipped_but_rest_survives():
    broken = [
        None,
        "not a dict",
        {},
        {"Title": "Ohne Datum"},
        {"Title": "Kaputtes Datum", "CalendarDisplayDateTimeStart": "kein-datum",
         "DetailUrl": "/de_DE/calendar/x.1?event_date=1"},
        {"Title": "Ohne DetailUrl", "CalendarDisplayDateTimeStart": "2026-09-20 10:00"},
        {"Title": "", "CalendarDisplayDateTimeStart": "2026-09-20 10:00",
         "DetailUrl": "/de_DE/calendar/leer.1?event_date=1"},
    ]
    events = parse_planetarium_bochum_items(broken + [copy.deepcopy(ITEM_KINDER)], now=NOW)
    titles = {e["title"] for e in events}
    assert titles == {"Fritz Fliege fliegt ins Weltall"}


def test_empty_input():
    assert parse_planetarium_bochum_items([], now=NOW) == []
    assert parse_planetarium_bochum_items(None, now=NOW) == []
