"""Offline parser tests for the Katakomben-Theater source (no network)."""
from datetime import date, datetime, time, timedelta

import pytest

from app.services.katakomben import (
    _build_datetimes,
    _extract_header_dates,
    _header_text,
    _parse_iso_published,
    _parse_times,
    parse_katakomben_html,
)

# Realistischer Ausschnitt der Startseite (WordPress 3.0.1 / arras-Theme).
# Jahreszahlen liegen weit in der Zukunft, damit die Fixture nicht "altert";
# die Tests injizieren ein passendes `now`.
NOW = datetime(2031, 9, 18, 9, 0)

KATAKOMBEN_HTML = """
<!DOCTYPE html>
<html lang="de-DE">
<body>
<div id="index-news">
<div class="home-title">Veranstaltungen</div>
<ul class="hfeed posts-default clearfix">

<li class="post-18485 post type-post hentry category-allgemein category-comedy-kabarett
           category-festivals-sonderveranstaltungen category-tanz-theater clearfix">
  <div class="entry-thumbnails">
    <a class="entry-thumbnails-link" href="http://www.katakomben-theater.de/comedyflash-essen/">
      <img class="attachment-news-post-thumb wp-post-image"
           src="http://www.katakomben-theater.de/wp-content/uploads/2031/05/18.9.2031-305x110.jpg"
           width="305" height="110" alt="18.9.2031"/>
      <span class="entry-meta">
        <span class="entry-comments">0</span>
        <abbr class="published" title="2031-09-18T20:00:40+00:00">18. September 2031</abbr>
      </span>
    </a>
  </div>
  <h3 class="entry-title">
    <a href="http://www.katakomben-theater.de/comedyflash-essen/" rel="bookmark">Comedyflash Essen</a>
  </h3>
  <div class="entry-summary">
    FR 18. September 2031 Comedyflash Essen LIVE Stand Up Comedy in Essen! Wir zeigen euch einen Mix
    aus erfahrenen Profi-Comedians und den heißesten Newcomern...
  </div>
</li>

<li class="post-18637 post type-post hentry category-allgemein category-comedy-kabarett
           category-festivals-sonderveranstaltungen category-party-kurse category-tanz-theater clearfix">
  <div class="entry-thumbnails">
    <a class="entry-thumbnails-link" href="http://www.katakomben-theater.de/rampenmonster/">
      <img class="attachment-news-post-thumb wp-post-image"
           src="http://www.katakomben-theater.de/wp-content/uploads/2031/08/Rampenmonster-305x110.jpg"
           width="305" height="110" alt="Rampenmonster"/>
      <span class="entry-meta">
        <span class="entry-comments">0</span>
        <abbr class="published" title="2031-10-03T19:00:38+00:00">3. Oktober 2031</abbr>
      </span>
    </a>
  </div>
  <h3 class="entry-title">
    <a href="http://www.katakomben-theater.de/rampenmonster/" rel="bookmark">Rampenmonster</a>
  </h3>
  <div class="entry-summary">
    SA 03. Oktober 2031, Beginn: 19:00 Uhr (Einlass ab 18:00 Uhr) SO 04. Oktober 2031, Beginn: 15:00 Uhr
    (Einlass ab 14:00 Uhr) Rampenmonster Die tun nix, die wollen nur singen! / Musicalkonzert...
  </div>
</li>

<li class="post-14395 post type-post hentry category-allgemein category-festivals-sonderveranstaltungen
           category-jazz-weltmusik category-party-kurse clearfix">
  <div class="entry-thumbnails">
    <a class="entry-thumbnails-link" href="http://www.katakomben-theater.de/jazz-for-the-people-8/">
      <img class="attachment-news-post-thumb wp-post-image"
           src="http://www.katakomben-theater.de/wp-content/uploads/2031/01/jazz-305x110.jpg"
           width="305" height="110" alt="Jazz"/>
      <span class="entry-meta">
        <span class="entry-comments">0</span>
        <abbr class="published" title="2031-10-07T20:00:19+00:00">7. Oktober 2031</abbr>
      </span>
    </a>
  </div>
  <h3 class="entry-title">
    <a href="http://www.katakomben-theater.de/jazz-for-the-people-8/" rel="bookmark">Jazz for the People</a>
  </h3>
  <div class="entry-summary">
    MI 7. Oktober2031, 20 Uhr Jazz for the People INFOS Folgen… – Eintritt frei, Spenden erwünscht
    – Einlass ab 19:15h, barrierefreier Zugang möglich...
  </div>
</li>

<li class="post-18999 post type-post hentry category-allgemein category-festivals-sonderveranstaltungen
           category-kinder category-tanz-theater clearfix">
  <div class="entry-thumbnails">
    <a class="entry-thumbnails-link" href="http://www.katakomben-theater.de/lila-lindwurm-piet/">
      <span class="entry-meta">
        <span class="entry-comments">0</span>
        <abbr class="published" title="2031-11-25T10:00:00+00:00">25. November 2031</abbr>
      </span>
    </a>
  </div>
  <h3 class="entry-title">
    <a href="http://www.katakomben-theater.de/lila-lindwurm-piet/" rel="bookmark">Lila Lindwurm – Piet, der Weihnachtspirat</a>
  </h3>
  <div class="entry-summary">
    Mi 25. November 2031, 10 und 11.15 Uhr Lila Lindwurm – Piet, der Weihnachtspirat Ein weihnachtliches
    Mitmach- theater für Kinder mit viel Musik...
  </div>
</li>

<!-- Kaputtes Item: kein Titel -->
<li class="post-1 post type-post hentry clearfix">
  <div class="entry-thumbnails">
    <abbr class="published" title="2031-10-01T20:00:00+00:00">1. Oktober 2031</abbr>
  </div>
  <div class="entry-summary">DO 1. Oktober 2031, 20 Uhr Irgendwas</div>
</li>

<!-- Vergangenes Event -->
<li class="post-2 post type-post hentry category-allgemein category-jazz-weltmusik clearfix">
  <div class="entry-thumbnails">
    <abbr class="published" title="2031-09-10T20:00:00+00:00">10. September 2031</abbr>
  </div>
  <h3 class="entry-title">
    <a href="http://www.katakomben-theater.de/altes-konzert/" rel="bookmark">Altes Konzert</a>
  </h3>
  <div class="entry-summary">MI 10. September 2031, 20 Uhr Altes Konzert Schon vorbei.</div>
</li>

<!-- Weit in der Zukunft (> 120 Tage) -->
<li class="post-3 post type-post hentry category-allgemein category-jazz-weltmusik clearfix">
  <div class="entry-thumbnails">
    <abbr class="published" title="2032-03-21T20:00:09+00:00">21. März 2032</abbr>
  </div>
  <h3 class="entry-title">
    <a href="http://www.katakomben-theater.de/wildes-holz/" rel="bookmark">Wildes Holz</a>
  </h3>
  <div class="entry-summary">So. 21. März 2032, 20 Uhr, Wildes Holz Man nehme eine Blockflöte...</div>
</li>

</ul>
</div>
</body>
</html>
"""


def _by_title(events, title):
    return [e for e in events if e["title"] == title]


def test_parses_events_and_expands_multi_dates():
    events = parse_katakomben_html(KATAKOMBEN_HTML, now=NOW)
    titles = sorted({e["title"] for e in events})
    assert titles == [
        "Comedyflash Essen",
        "Jazz for the People",
        "Lila Lindwurm – Piet, der Weihnachtspirat",
        "Rampenmonster",
    ]
    # 1 + 2 (zwei Tage) + 1 + 2 (zwei Uhrzeiten am selben Tag)
    assert len(events) == 6


def test_event_fields_single_date():
    events = parse_katakomben_html(KATAKOMBEN_HTML, now=NOW)
    comedy = _by_title(events, "Comedyflash Essen")[0]
    # Header hat kein Uhrzeit -> Zeit aus abbr.published (Berliner Lokalzeit)
    assert comedy["start_at"] == datetime(2031, 9, 18, 20, 0)
    assert comedy["venue_name"] == "Katakomben-Theater"
    assert comedy["source_name"] == "Katakomben-Theater"
    assert comedy["source_url"] == "http://www.katakomben-theater.de/comedyflash-essen/"
    assert comedy["city"] == "Essen"
    assert comedy["lat"] == pytest.approx(51.4307774)
    assert comedy["lon"] == pytest.approx(7.0062198)
    assert comedy["indoor_outdoor"] == "indoor"
    assert comedy["category"] == "Comedy, Kabarett"
    assert comedy["kids_suitable"] == "unknown"
    assert comedy["image_url"].endswith("18.9.2031-305x110.jpg")
    assert comedy["short_description"].startswith("LIVE Stand Up Comedy")
    assert "18. September" not in comedy["title"]


def test_multi_day_post_becomes_two_events_with_begin_not_einlass():
    events = parse_katakomben_html(KATAKOMBEN_HTML, now=NOW)
    monster = sorted(_by_title(events, "Rampenmonster"), key=lambda e: e["start_at"])
    assert [e["start_at"] for e in monster] == [
        datetime(2031, 10, 3, 19, 0),
        datetime(2031, 10, 4, 15, 0),
    ]
    assert len({e["canonical_id"] for e in monster}) == 2


def test_two_times_same_day_and_kids_category():
    events = parse_katakomben_html(KATAKOMBEN_HTML, now=NOW)
    piet = sorted(_by_title(events, "Lila Lindwurm – Piet, der Weihnachtspirat"), key=lambda e: e["start_at"])
    assert [e["start_at"] for e in piet] == [
        datetime(2031, 11, 25, 10, 0),
        datetime(2031, 11, 25, 11, 15),
    ]
    assert all(e["kids_suitable"] == "yes" for e in piet)
    assert all(e["category"] == "Kindertheater" for e in piet)
    assert piet[0]["image_url"] is None


def test_price_and_category_from_summary():
    events = parse_katakomben_html(KATAKOMBEN_HTML, now=NOW)
    jazz = _by_title(events, "Jazz for the People")[0]
    assert jazz["start_at"] == datetime(2031, 10, 7, 20, 0)  # "7. Oktober2031, 20 Uhr"
    assert jazz["price_text"].startswith("Eintritt frei")
    assert jazz["category"] == "Jazz, Weltmusik"


def test_broken_past_and_far_future_items_are_skipped():
    events = parse_katakomben_html(KATAKOMBEN_HTML, now=NOW)
    titles = {e["title"] for e in events}
    assert "Altes Konzert" not in titles  # vergangen
    assert "Wildes Holz" not in titles  # > 120 Tage
    assert all(e["title"] for e in events)  # Item ohne Titel verworfen


def test_window_shifts_with_now():
    later = datetime(2031, 10, 4, 12, 0)
    events = parse_katakomben_html(KATAKOMBEN_HTML, now=later)
    monster = _by_title(events, "Rampenmonster")
    # 03.10. ist vorbei, 04.10. (heute, 15 Uhr) bleibt
    assert [e["start_at"] for e in monster] == [datetime(2031, 10, 4, 15, 0)]
    assert not _by_title(events, "Comedyflash Essen")


def test_empty_html_returns_empty_list():
    assert parse_katakomben_html("<html><body></body></html>", now=NOW) == []


# ───────────────────────── Datum-/Zeit-Parser Edge-Cases ─────────────────────


def test_iso_published_ignores_bogus_utc_offset():
    assert _parse_iso_published("2031-09-18T20:00:40+00:00") == datetime(2031, 9, 18, 20, 0)
    assert _parse_iso_published("garbage") is None


def test_header_text_stops_before_title():
    header = _header_text("MUSICAL NIGHT 2031", "10.10. 19:30 Uhr 11.10. 15:00 Uhr MUSICAL NIGHT 2031 Lass dich...")
    assert header.strip() == "10.10. 19:30 Uhr 11.10. 15:00 Uhr"


def test_numeric_dates_without_year_are_not_read_as_times():
    """'10.10. 19:30 Uhr 24.06. ...' — '24.06.' darf nie 24:06 Uhr werden."""
    anchor = datetime(2031, 10, 10, 19, 30)
    hits = _extract_header_dates("10.10. 19:30 Uhr 11.10. 15:00 Uhr 24.06.", anchor, NOW)
    assert hits[0] == (date(2031, 10, 10), time(19, 30))
    assert hits[1] == (date(2031, 10, 11), time(15, 0))
    # 24.06. ohne Uhrzeit -> Jahr rollt ueber (liegt vor dem Anker)
    assert hits[2] == (date(2032, 6, 24), None)


def test_month_name_dates_two_digit_year_and_time_variants():
    anchor = datetime(2031, 12, 27, 20, 0)
    hits = _extract_header_dates(
        "SO 27. Dezember 2031, 20 Uhr Sa, 19. September 2031, 19.30 Uhr, Premiere 4.1.32 20 h",
        anchor,
        NOW,
    )
    assert (date(2031, 12, 27), time(20, 0)) in hits
    assert (date(2031, 9, 19), time(19, 30)) in hits
    assert (date(2032, 1, 4), time(20, 0)) in hits


def test_parse_times_handles_und_chain_and_einlass():
    assert _parse_times(", 10 und 11.15 Uhr ") == [time(10, 0), time(11, 15)]
    assert _parse_times(", Beginn: 19:00 Uhr (Einlass ab 18:00 Uhr)") == [time(19, 0)]
    assert _parse_times(", 20 Uhr (Einlass 19 Uhr)") == [time(20, 0)]
    assert _parse_times(" 19 und 21 Uhr ") == [time(19, 0), time(21, 0)]
    assert _parse_times(" 2031 Text ohne Zeit ") == []


def test_build_datetimes_adds_anchor_when_header_has_typo_year():
    """REMBETIKO-Fall: Summary sagt 2030, Post-Datum 2031 -> Post-Datum bleibt."""
    anchor = datetime(2031, 12, 24, 22, 0)
    dts = _build_datetimes(anchor, [(date(2030, 12, 24), time(22, 0))])
    assert anchor in dts
    assert datetime(2030, 12, 24, 22, 0) in dts  # wird spaeter vom Fenster gefiltert


def test_build_datetimes_uses_header_time_for_anchor_day():
    anchor = datetime(2031, 9, 19, 0, 0)  # Post ohne Uhrzeit
    dts = _build_datetimes(anchor, [(date(2031, 9, 19), time(19, 30)), (date(2031, 9, 20), None)])
    assert dts == [datetime(2031, 9, 19, 19, 30), datetime(2031, 9, 20, 19, 30)]


def test_cross_post_duplicate_is_not_created_twice():
    """Premiere-Post nennt auch den 2. Tag, fuer den ein eigener Post existiert."""
    html = """
    <ul class="hfeed">
      <li class="post type-post hentry category-tanz-theater">
        <abbr class="published" title="2031-09-19T19:30:24+00:00">19. September 2031</abbr>
        <h3 class="entry-title"><a href="http://www.katakomben-theater.de/gatsby-musical/">Der große Gatsby – Musical</a></h3>
        <div class="entry-summary">Sa, 19. September 2031, 19.30 Uhr, Premiere SO, 20. September 2031, 17 Uhr Der große Gatsby Musical Bühnenadaption...</div>
      </li>
      <li class="post type-post hentry category-tanz-theater">
        <abbr class="published" title="2031-09-20T17:00:18+00:00">20. September 2031</abbr>
        <h3 class="entry-title"><a href="http://www.katakomben-theater.de/gatsby/">Der große Gatsby</a></h3>
        <div class="entry-summary">SO, 20. September 2031, 17 Uhr Der große Gatsby Musical Bühnenadaption...</div>
      </li>
    </ul>
    """
    events = parse_katakomben_html(html, now=NOW)
    on_20th = [e for e in events if e["start_at"].date() == date(2031, 9, 20)]
    assert len(on_20th) == 1
    assert on_20th[0]["title"] == "Der große Gatsby"
    assert len(events) == 2


def test_relative_fixture_stays_in_window():
    """Fixture relativ zu datetime.now() — Termin morgen wird geliefert, gestern nicht."""
    tomorrow = datetime.now() + timedelta(days=1)
    yesterday = datetime.now() - timedelta(days=1)
    html = f"""
    <ul class="hfeed">
      <li class="post type-post hentry category-jazz-weltmusik">
        <abbr class="published" title="{tomorrow:%Y-%m-%dT20:00:00}+00:00">x</abbr>
        <h3 class="entry-title"><a href="http://www.katakomben-theater.de/morgen/">Konzert Morgen</a></h3>
        <div class="entry-summary">{tomorrow:%d.%m.%Y}, 20 Uhr Konzert Morgen Text</div>
      </li>
      <li class="post type-post hentry category-jazz-weltmusik">
        <abbr class="published" title="{yesterday:%Y-%m-%dT20:00:00}+00:00">x</abbr>
        <h3 class="entry-title"><a href="http://www.katakomben-theater.de/gestern/">Konzert Gestern</a></h3>
        <div class="entry-summary">{yesterday:%d.%m.%Y}, 20 Uhr Konzert Gestern Text</div>
      </li>
    </ul>
    """
    events = parse_katakomben_html(html)
    assert [e["title"] for e in events] == ["Konzert Morgen"]
    assert events[0]["start_at"] == tomorrow.replace(hour=20, minute=0, second=0, microsecond=0)
