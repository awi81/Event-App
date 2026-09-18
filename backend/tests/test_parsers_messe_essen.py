"""Offline parser tests for the Messe Essen source (/event-kalender/ list + detail).

Fixtures are trimmed copies of the live TYPO3 markup — no network access.
``now`` is injected so the past/horizon filter is stable.
"""
from datetime import date, datetime

import pytest

from app.services.messe_essen import (
    SOURCE_NAME,
    _merge_detail,
    _parse_date_range,
    parse_messe_essen_detail_html,
    parse_messe_essen_html,
)

NOW = datetime(2026, 9, 18, 8, 0)


def _item(date_text, categories, title, slug, teaser="Teaser", with_link=True, with_image=True):
    title_html = (
        f'<a class="list-item_link" href="/event-kalender/detail/{slug}">{title}</a>'
        if with_link
        else title
    )
    teaser_html = f'<p class="ce-veranstaltungen__teaser">{teaser}</p>' if teaser else ""
    image_html = (
        f'<img alt="{title}" height="1299" src="/fileadmin/_processed_/x/y/csm_Logo_{slug}.webp" width="1299"/>'
        if with_image
        else ""
    )
    return f"""
<article class="list-item">
  <div class="list-item-content">
    <div class="ce-veranstaltungen__list-content list-item__text">
      <div class="list-item_infos">
        <span class="event-date">
          {date_text}
        </span>
        <br/>
        <span class="ce-veranstaltungen__categories">{categories}</span>
      </div>
      <h3 class="ce-veranstaltungen__title">{title_html}</h3>
      {teaser_html}
    </div>
  </div>
  <div class="list-item_right">
    <div class="ce-veranstaltungen__list-image list-item__image">{image_html}</div>
    <div class="btn btn-transparent btn-big btn-icon icon-link-external"></div>
  </div>
</article>"""


MESSE_HTML = "<!doctype html><html><body><div class=\"ce-veranstaltungen__list list\">" + "".join([
    # 1: multi-day Publikumsmesse, kids keyword in title
    _item("22.10.2026\n  -\n  25.10.2026", "Publikumsmesse <span>|</span> <span>Essen</span>",
          "SPIEL ESSEN", "spiel-essen", "Weltweit größte Brettspielemesse"),
    # 2: Fachmesse, multi-day
    _item("22.09.2026 - 25.09.2026", "Fachmesse <span>|</span> <span>Essen</span>",
          "security essen", "security-essen", "Die Leitmesse für Sicherheit"),
    # 3: single-day public fair without teaser
    _item("12.11.2026", "Publikumsmesse <span>|</span> <span>Essen</span>",
          "Dinosaurier Erlebniswelt", "dinosaurier-erlebniswelt", teaser=None),
    # 4: abroad → skipped
    _item("30.11.2026 - 02.12.2026", "Fachmesse <span>|</span> <span>Ausland</span>",
          "INDIA ESSEN WELDING &amp; CUTTING", "india-essen-welding-cutting"),
    # 5: already started → skipped
    _item("10.09.2026 - 13.09.2026", "Publikumsmesse <span>|</span> <span>Essen</span>",
          "Vergangene Messe", "vergangene-messe"),
    # 6: beyond +180 days → skipped
    _item("21.03.2028 - 24.03.2028", "Fachmesse <span>|</span> <span>Essen</span>",
          "SHK+E ESSEN", "shk-e-essen"),
    # 7: broken: no link → skipped
    _item("05.11.2026 - 08.11.2026", "Publikumsmesse <span>|</span> <span>Essen</span>",
          "Ohne Link", "ohne-link", with_link=False),
    # 8: broken: no date → skipped
    _item("Termin folgt", "Publikumsmesse <span>|</span> <span>Essen</span>",
          "Ohne Datum", "ohne-datum"),
]) + "</div></body></html>"


def test_messe_parses_expected_fairs():
    events = parse_messe_essen_html(MESSE_HTML, now=NOW)
    # "security essen" (Fachmesse) is trade-only and therefore skipped.
    assert [e["title"] for e in events] == ["SPIEL ESSEN", "Dinosaurier Erlebniswelt"]


def test_messe_multi_day_fair_is_one_event_with_range():
    events = parse_messe_essen_html(MESSE_HTML, now=NOW)
    spiel = events[0]
    assert spiel["start_at"] == datetime(2026, 10, 22, 10, 0)
    assert spiel["end_at"] == datetime(2026, 10, 25, 18, 0)
    assert spiel["is_all_day"] is True
    assert spiel["venue_name"] == "Messe Essen"
    assert spiel["address_text"] == "Messeplatz 1, 45131 Essen"
    assert spiel["city"] == "Essen"
    assert spiel["lat"] == pytest.approx(51.4286847)
    assert spiel["lon"] == pytest.approx(6.9943796)
    assert spiel["source_url"] == "https://www.messe-essen.de/event-kalender/detail/spiel-essen"
    assert spiel["source_name"] == SOURCE_NAME
    assert spiel["indoor_outdoor"] == "indoor"
    assert spiel["category"] == "Publikumsmesse"
    assert spiel["kids_suitable"] == "likely"
    assert spiel["short_description"] == "Weltweit größte Brettspielemesse"
    assert spiel["image_url"] == (
        "https://www.messe-essen.de/fileadmin/_processed_/x/y/csm_Logo_spiel-essen.webp"
    )


def test_messe_fachmesse_is_skipped():
    events = parse_messe_essen_html(MESSE_HTML, now=NOW)
    assert all(e["category"] != "Fachmesse" for e in events)
    assert "security essen" not in [e["title"] for e in events]


def test_messe_single_day_fair_without_teaser():
    events = parse_messe_essen_html(MESSE_HTML, now=NOW)
    dino = events[1]
    assert dino["start_at"] == datetime(2026, 11, 12, 10, 0)
    assert dino["end_at"] == datetime(2026, 11, 12, 18, 0)
    assert dino["short_description"] is None
    assert dino["kids_suitable"] == "likely"


def test_messe_canonical_ids_unique_and_date_dependent():
    events = parse_messe_essen_html(MESSE_HTML, now=NOW)
    ids = [e["canonical_id"] for e in events]
    assert len(ids) == len(set(ids))
    shifted = parse_messe_essen_html(
        _item("29.10.2026 - 01.11.2026", "Publikumsmesse <span>|</span> <span>Essen</span>",
              "SPIEL ESSEN", "spiel-essen"),
        now=NOW,
    )
    assert shifted[0]["canonical_id"] != events[0]["canonical_id"]


def test_messe_missing_location_is_kept_and_missing_category_defaults():
    html = _item("22.10.2026 - 25.10.2026", "", "Ohne Kategorie", "ohne-kategorie")
    events = parse_messe_essen_html(html, now=NOW)
    assert len(events) == 1
    assert events[0]["category"] == "Messe"


def test_messe_empty_html_returns_empty_list():
    assert parse_messe_essen_html("<html><body></body></html>", now=NOW) == []
    assert parse_messe_essen_html("", now=NOW) == []


def test_messe_date_range_parser():
    assert _parse_date_range("22.09.2026 - 25.09.2026") == (date(2026, 9, 22), date(2026, 9, 25))
    assert _parse_date_range("22.09.2026\n   -\n   25.09.2026") == (date(2026, 9, 22), date(2026, 9, 25))
    assert _parse_date_range("12.11.2026") == (date(2026, 11, 12), date(2026, 11, 12))
    assert _parse_date_range("19.12.2026 - 10.01.2027") == (date(2026, 12, 19), date(2027, 1, 10))
    assert _parse_date_range("Termin folgt") == (None, None)
    assert _parse_date_range("31.02.2026") == (None, None)
    # Reversed range is clamped to the first date.
    assert _parse_date_range("25.09.2026 - 22.09.2026") == (date(2026, 9, 25), date(2026, 9, 25))


# ─────────────────────────────── detail page ──────────────────────────────────

MESSE_DETAIL_HTML = """
<!doctype html><html><body>
<main id="main" role="main">
 <article class="ce-veranstaltungen__detail">
  <h1 class="ce-veranstaltungen__title headline_2">SPIEL ESSEN</h1>
  <div class="ce-veranstaltungen__detail-content">
   <p><strong>Internationale Spieltage</strong></p>
   <p>Die Internationalen Spieltage SPIEL - die weltweit größte Publikumsmesse für
      Gesellschaftsspiele - bieten ihren Besucher*innen eine einmalige Möglichkeit.</p>
   <p>Weitere Informationen finden Sie beim <a class="external" href="https://www.spiel-essen.de/de/">Veranstalter.</a></p>
   <p>Tageskarte: 18 € (Kinder bis 12 Jahre frei)</p>
  </div>
  <div class="info-column">
   <div class="event-info sheet bg-white">
    <h2>Infos</h2>
    <table>
     <tr><td><strong><span>Startdatum:</span></strong></td><td>22.10.2026</td></tr>
     <tr><td><strong><span>Enddatum:</span></strong></td><td>25.10.2026</td></tr>
    </table>
   </div>
   <div class="event-info sheet bg-white">
    <h2>Öffnungszeiten</h2>
    <div class="event-opening-hours">
     <p><strong>Donnerstag - Samstag:</strong><br/>10:00 - 19:00 Uhr</p>
     <p><strong>Sonntag:</strong><br/>10:00 - 18:00 Uhr</p>
    </div>
   </div>
  </div>
 </article>
</main>
</body></html>
"""


def test_messe_detail_description_skips_boilerplate():
    detail = parse_messe_essen_detail_html(MESSE_DETAIL_HTML)
    assert detail["short_description"].startswith("Internationale Spieltage Die Internationalen Spieltage")
    assert "Weitere Informationen" not in detail["short_description"]
    assert len(detail["short_description"]) <= 500


def test_messe_detail_opening_hours_and_price():
    detail = parse_messe_essen_detail_html(MESSE_DETAIL_HTML)
    assert detail["opening_hours"] == "Donnerstag - Samstag: 10:00 - 19:00 Uhr; Sonntag: 10:00 - 18:00 Uhr"
    assert "18 €" in detail["price_text"]
    assert detail["price_text"].lower().startswith("tageskarte")


def test_messe_detail_empty_page_returns_empty_dict():
    assert parse_messe_essen_detail_html("<html><body></body></html>") == {}


def test_messe_merge_detail_prefers_longer_description_and_adds_hours():
    events = parse_messe_essen_html(MESSE_HTML, now=NOW)
    spiel = dict(events[0])
    merged = _merge_detail(spiel, parse_messe_essen_detail_html(MESSE_DETAIL_HTML))
    assert merged["short_description"].startswith("Internationale Spieltage")
    assert "Öffnungszeiten: Donnerstag - Samstag: 10:00 - 19:00 Uhr" in merged["short_description"]
    assert len(merged["short_description"]) <= 500
    assert "18 €" in merged["price_text"]
    # Dates are untouched by enrichment.
    assert merged["start_at"] == datetime(2026, 10, 22, 10, 0)
    assert merged["end_at"] == datetime(2026, 10, 25, 18, 0)


def test_messe_merge_detail_keeps_teaser_when_detail_is_empty():
    events = parse_messe_essen_html(MESSE_HTML, now=NOW)
    spiel = dict(events[0])
    merged = _merge_detail(spiel, {})
    assert merged["short_description"] == "Weltweit größte Brettspielemesse"
    assert "price_text" not in merged
