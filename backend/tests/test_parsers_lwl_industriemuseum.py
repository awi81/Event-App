"""Offline parser tests for the LWL-Industriemuseum source (three museum sites).

Fixtures are trimmed copies of the live ``div.event-element`` markup — no
network access. ``now`` is injected so the past/horizon filter is stable.
"""
from datetime import date, datetime, time

import pytest

from app.services.lwl_industriemuseum import (
    SITES,
    SOURCE_NAME,
    _parse_date_text,
    _parse_time_text,
    parse_lwl_html,
)

NOW = datetime(2026, 9, 18, 8, 0)
HENRICHSHUETTE = SITES[0]
ZECHE_HANNOVER = SITES[2]


def _block(date_text, time_text, event_type, title, subtitle, event_id, description="Teaser…", with_link=True, with_image=True):
    link = (
        f'<p><a aria-labelledby="event-title-{event_id}" class="btn btn-link" '
        f'href="/de/veranstaltungen/?id={event_id}">Zu den Veranstaltungsdetails</a></p>'
        if with_link
        else ""
    )
    image = (
        f'<div class="col-sm-3"><div class="event-image"><img alt="{title}" class="w-100" '
        f'src="https://www.lwl.org/lwlkalender/ShowAnlageAction.do?id={event_id}0"/></div></div>'
        if with_image
        else ""
    )
    time_html = f'<p class="event-time">{time_text}</p>' if time_text is not None else ""
    type_html = f"<p class=\"event-type\"><strong>{event_type}</strong></p>" if event_type else ""
    title_html = f'<h4 class="event-title"><span id="event-title-{event_id}">{title}</span></h4>' if title is not None else ""
    return f"""
<div class="event-element col-12">
  <div class="row">
    <div class="event-meta col-sm-3">
      <p class="event-date">{date_text}</p>
      {time_html}
      {type_html}
    </div>
    <div class="event-info col-sm-6">
      {title_html}
      <p class="event-subtitle">{subtitle}</p>
      <p class="event-description">{description}</p>
      {link}
    </div>
    {image}
  </div>
</div>"""


LWL_HTML = "<!doctype html><html><body><div class=\"event-list\">" + "".join([
    # 1: single day with time
    _block("Freitag, 25.9.2026", "17:00 Uhr", "Vernissage", "Wir spannen den Schirm",
           "Eröffnung der neuen Sonderausstellung", 1101498),
    # 2: two-day span with a time range
    _block("Samstag, 26.9. bis Sonntag, 27.9.2026", "10:00 - 18:00 Uhr", "Kurs",
           "Story-Telling mit der Kamera", "Fotoworkshop mit Bernd Meissner", 1101510),
    # 3: Einlass/Beginn
    _block("Donnerstag, 24.9.2026", "Einlass 18:00 Uhr, Beginn 20:00 Uhr", "Theater/Kabarett",
           "Am besten Walli", "Comedy auf der Henrichshütte", 1101507),
    # 4: explicit kids type
    _block("Sonntag, 27.9.2026", "14:30 Uhr", "Für Kinder", "Rattentour",
           "Kinderführung ab 7 Jahre", 1101520),
    # 5: past event → must be dropped
    _block("Montag, 7.9.2026", "19:00 Uhr", "Film", "Hütten-Kino", "Alter Film", 1101400),
    # 6: broken: no title → skipped
    _block("Mittwoch, 30.9.2026", "19:00 Uhr", "Film", None, "Ohne Titel", 1101999),
    # 7: broken: no usable date → skipped
    _block("Demnächst", "19:00 Uhr", "Film", "Datumsloses Event", "Kein Datum", 1101998),
    # 8: beyond the 120-day horizon → dropped
    _block("Samstag, 13.3.2027", "14:00 -15:00 Uhr", "Führung", "Gesichter der Wismut",
           "Kuratorinnenführung", 1102435),
]) + "</div></body></html>"


def test_lwl_parses_expected_events():
    events = parse_lwl_html(LWL_HTML, HENRICHSHUETTE, now=NOW)
    titles = [e["title"] for e in events]
    assert titles == [
        "Wir spannen den Schirm",
        "Story-Telling mit der Kamera",
        "Am besten Walli",
        "Rattentour",
    ]


def test_lwl_single_day_event_fields():
    events = parse_lwl_html(LWL_HTML, HENRICHSHUETTE, now=NOW)
    ev = events[0]
    assert ev["start_at"] == datetime(2026, 9, 25, 17, 0)
    assert ev["end_at"] is None
    assert ev["is_all_day"] is False
    assert ev["venue_name"] == "LWL-Industriemuseum Henrichshütte Hattingen"
    assert ev["address_text"] == "Werksstraße 31-33, 45527 Hattingen"
    assert ev["city"] == "Hattingen"
    assert ev["lat"] == pytest.approx(51.4060305)
    assert ev["lon"] == pytest.approx(7.1881886)
    assert ev["source_url"] == "https://henrichshuette.lwl.org/de/veranstaltungen/?id=1101498"
    assert ev["source_name"] == SOURCE_NAME
    assert ev["category"] == "Vernissage"
    assert ev["indoor_outdoor"] == "both"
    assert ev["kids_suitable"] == "unknown"
    assert ev["image_url"].startswith("https://www.lwl.org/lwlkalender/")
    assert ev["short_description"].startswith("Eröffnung der neuen Sonderausstellung")


def test_lwl_span_uses_start_date_and_end_date_with_times():
    events = parse_lwl_html(LWL_HTML, HENRICHSHUETTE, now=NOW)
    kurs = events[1]
    assert kurs["start_at"] == datetime(2026, 9, 26, 10, 0)
    assert kurs["end_at"] == datetime(2026, 9, 27, 18, 0)
    assert kurs["category"] == "Kurs"
    assert kurs["indoor_outdoor"] == "indoor"


def test_lwl_einlass_beginn_takes_beginn_time():
    events = parse_lwl_html(LWL_HTML, HENRICHSHUETTE, now=NOW)
    walli = events[2]
    assert walli["start_at"] == datetime(2026, 9, 24, 20, 0)
    assert walli["end_at"] is None
    assert walli["indoor_outdoor"] == "indoor"  # Theater/Kabarett


def test_lwl_kids_detection_from_type_and_subtitle():
    events = parse_lwl_html(LWL_HTML, HENRICHSHUETTE, now=NOW)
    ratten = events[3]
    assert ratten["kids_suitable"] == "yes"
    assert ratten["category"] == "Für Kinder"

    likely_html = _block("Freitag, 23.10.2026", "10:00 - 14:00 Uhr", None,
                         "Bergwerk im Schuhkarton", "Herbstferienangebot", 1102768)
    likely = parse_lwl_html(likely_html, HENRICHSHUETTE, now=NOW)
    assert likely[0]["kids_suitable"] == "likely"
    assert likely[0]["category"] is None


def test_lwl_canonical_ids_unique_and_contain_date():
    events = parse_lwl_html(LWL_HTML, HENRICHSHUETTE, now=NOW)
    ids = [e["canonical_id"] for e in events]
    assert len(ids) == len(set(ids))
    # Same block on another date must produce a different id.
    other = parse_lwl_html(
        _block("Samstag, 3.10.2026", "17:00 Uhr", "Vernissage", "Wir spannen den Schirm",
               "Eröffnung der neuen Sonderausstellung", 1101498),
        HENRICHSHUETTE,
        now=NOW,
    )
    assert other[0]["canonical_id"] != events[0]["canonical_id"]


def test_lwl_multiple_start_times_create_multiple_events():
    html = _block("Sonntag, 20.9.2026", "12:00 und 15:00 Uhr", "Führung", "Erlebnisführungen",
                  "mit Vorführung der Dampffördermaschine", 1100691)
    events = parse_lwl_html(html, ZECHE_HANNOVER, now=NOW)
    assert [e["start_at"] for e in events] == [
        datetime(2026, 9, 20, 12, 0),
        datetime(2026, 9, 20, 15, 0),
    ]
    assert len({e["canonical_id"] for e in events}) == 2


def test_lwl_running_exhibition_expands_daily_from_today_capped_at_60():
    html = _block("Samstag, 21.3. bis Sonntag, 25.10.2026", None, "Ausstellung", "Weg der Kohle",
                  "Fotografien von Khalil Noé Döring", 1098999)
    events = parse_lwl_html(html, ZECHE_HANNOVER, now=NOW)
    # 18.9. … 25.10. = 38 days, all in the future, all-day at 10:00
    assert len(events) == 38
    assert events[0]["start_at"] == datetime(2026, 9, 18, 10, 0)
    assert events[-1]["start_at"] == datetime(2026, 10, 25, 10, 0)
    assert all(e["is_all_day"] is True for e in events)
    assert len({e["canonical_id"] for e in events}) == 38

    long_html = _block("Montag, 1.6. bis Donnerstag, 31.12.2026", "10:00 - 18:00 Uhr", "Ausstellung",
                       "Dauerläufer", "Sehr lange Ausstellung", 1000001)
    long_events = parse_lwl_html(long_html, ZECHE_HANNOVER, now=NOW)
    assert len(long_events) == 60
    assert long_events[0]["start_at"] == datetime(2026, 9, 18, 10, 0)
    assert long_events[0]["end_at"] == datetime(2026, 9, 18, 18, 0)
    assert long_events[0]["is_all_day"] is False


def test_lwl_no_time_gives_all_day_at_ten():
    html = _block("Samstag, 3.10.2026", None, "Sonderveranstaltung", "Tag der offenen Tür",
                  "Ohne Uhrzeit", 1000002)
    events = parse_lwl_html(html, HENRICHSHUETTE, now=NOW)
    assert events[0]["start_at"] == datetime(2026, 10, 3, 10, 0)
    assert events[0]["is_all_day"] is True
    assert events[0]["end_at"] is None


def test_lwl_source_url_fallback_when_no_link():
    html = _block("Samstag, 3.10.2026", "12:00 Uhr", "Führung", "Ohne Link", "Untertitel",
                  1000003, with_link=False, with_image=False)
    events = parse_lwl_html(html, HENRICHSHUETTE, now=NOW)
    assert events[0]["source_url"] == (
        "https://henrichshuette.lwl.org/de/veranstaltungen/#event-title-1000003"
    )
    assert events[0]["image_url"] is None


def test_lwl_empty_html_returns_empty_list():
    assert parse_lwl_html("<html><body></body></html>", HENRICHSHUETTE, now=NOW) == []
    assert parse_lwl_html("", HENRICHSHUETTE, now=NOW) == []


# ─────────────────────────────── date / time helpers ──────────────────────────


def test_lwl_date_parser_single_and_span():
    assert _parse_date_text("Freitag, 18.9.2026", NOW) == (date(2026, 9, 18), None)
    assert _parse_date_text("Samstag, 26.9. bis Sonntag, 27.9.2026", NOW) == (
        date(2026, 9, 26), date(2026, 9, 27)
    )
    assert _parse_date_text("Mittwoch, 6.5. bis Sonntag, 4.10.2026", NOW) == (
        date(2026, 5, 6), date(2026, 10, 4)
    )


def test_lwl_date_parser_year_wrap_and_missing_year():
    # Span across New Year: start belongs to the previous year.
    assert _parse_date_text("Samstag, 20.12. bis Sonntag, 5.1.2027", NOW) == (
        date(2026, 12, 20), date(2027, 1, 5)
    )
    # No year at all: next future occurrence (24.6. already passed in Sept 2026).
    assert _parse_date_text("Fr, 24.06.", NOW) == (date(2027, 6, 24), None)
    assert _parse_date_text("Fr, 24.10.", NOW) == (date(2026, 10, 24), None)
    assert _parse_date_text("Demnächst", NOW) == (None, None)
    assert _parse_date_text("Freitag, 31.2.2026", NOW) == (None, None)


def test_lwl_time_parser_variants():
    assert _parse_time_text("17:00 Uhr") == ([time(17, 0)], None)
    assert _parse_time_text("15 - 19:30 Uhr") == ([time(15, 0)], time(19, 30))
    assert _parse_time_text("11:00 -12:30 Uhr") == ([time(11, 0)], time(12, 30))
    assert _parse_time_text("15:00-17:00 Uhr") == ([time(15, 0)], time(17, 0))
    assert _parse_time_text("12:00 bis 18:00 Uhr") == ([time(12, 0)], time(18, 0))
    assert _parse_time_text("Einlass 18:00 Uhr, Beginn 20:00 Uhr") == ([time(20, 0)], None)
    assert _parse_time_text("12:00 und 15:00 Uhr") == ([time(12, 0), time(15, 0)], None)
    assert _parse_time_text("FR 18:00-21:30 Uhr, SA und SO je 10:00-16:00 Uhr") == (
        [time(18, 0)], time(16, 0)
    )
    assert _parse_time_text("") == ([], None)
    assert _parse_time_text(None) == ([], None)


def test_lwl_time_parser_never_reads_date_as_time():
    # "24.06." must not become 24:06; only the real time survives.
    assert _parse_time_text("24.06. 19:00 Uhr") == ([time(19, 0)], None)
    assert _parse_time_text("24.06.") == ([], None)
    assert _parse_time_text("ab 7 Jahre") == ([], None)
    assert _parse_time_text("25:00 Uhr") == ([], None)
