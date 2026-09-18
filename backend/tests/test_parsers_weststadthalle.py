"""Offline parser tests for the Weststadthalle source (no network)."""
from datetime import datetime, timedelta

import pytest
from bs4 import BeautifulSoup

from app.services.weststadthalle import (
    _clean_url,
    _merge_detail,
    _parse_start,
    parse_weststadthalle_detail_html,
    parse_weststadthalle_html,
)

# Realistischer Ausschnitt von /veranstaltungen/ (TYPO3 tx_news, Microdata).
# Jahreszahlen weit in der Zukunft; die Tests injizieren ein passendes `now`.
NOW = datetime(2031, 9, 18, 9, 0)

WSH_LIST_HTML = """
<!doctype html>
<html lang="de">
<body>
<div id="news-container-6" class="news-list-view row thumbnails">

<div class="col-sm-12 filter-item Comedy">
 <li class="animated fadeInUp media mb-2 pb-2 odd" itemscope="" itemtype="http://schema.org/Event">
  <a href="/veranstaltung/news/merve-mervenzusammenbruch/?cHash=b00063b682089b9a36936b92e8154f27&amp;L=0" title="MERVE • MERVENZUSAMMENBRUCH">
   <img alt="" class="mr-3" height="100" src="/fileadmin/_processed_/1/f/csm_Bild3_c3112dc3b6.jpeg" width="100"/>
  </a>
  <div class="media-body">
   <time datetime="2031-09-20" itemprop="startDate">
    <strong>Sonntag, 20.09.2031</strong> - <strong>Beginn: 20:00 Uhr</strong>
   </time>
   <h5 class="mt-0 mb-1">
    <a href="/veranstaltung/news/merve-mervenzusammenbruch/?cHash=b00063b682089b9a36936b92e8154f27&amp;L=0" title="MERVE • MERVENZUSAMMENBRUCH">
     <span itemprop="name">MERVE • MERVENZUSAMMENBRUCH</span>
    </a>
    <span class="badge badge-danger">Ausverkauft</span>
   </h5>
   <div class="d-none d-sm-block">
    <span class="category hidden-xs">[Comedy]</span>
   </div>
   <a class="btn btn-info more float-right d-none d-sm-block" href="/veranstaltung/news/merve-mervenzusammenbruch/?cHash=b00063b682089b9a36936b92e8154f27&amp;L=0">Infos</a>
   <a class="more float-right btn btn-success d-none d-sm-block" href="https://www.190a.de/merve/" target="_blank">Tickets</a>
  </div>
 </li>
</div>

<div class="col-sm-12 filter-item Lesung">
 <li class="animated fadeInUp media mb-2 pb-2 even" itemscope="" itemtype="http://schema.org/Event">
  <a href="/veranstaltung/news/marc-friedrich-wenn-es-nacht-wird-im-westen/?cHash=f7817be436760347a23aed7859850675&amp;L=0">
   <img alt="" class="mr-3" height="100" src="/fileadmin/_processed_/4/4/csm_2_8e2f4403d6.png" width="100"/>
  </a>
  <div class="media-body">
   <time datetime="2031-09-23" itemprop="startDate">
    <strong>Mittwoch, 23.09.2031</strong> - <strong>Beginn: 19:00 Uhr</strong>
   </time>
   <h5 class="mt-0 mb-1">
    <a href="/veranstaltung/news/marc-friedrich-wenn-es-nacht-wird-im-westen/?cHash=f7817be436760347a23aed7859850675&amp;L=0" title="Marc Friedrich • Wenn es Nacht wird im Westen">
     <span itemprop="name">Marc Friedrich • Wenn es Nacht wird im Westen</span>
    </a>
   </h5>
   <div class="d-none d-sm-block"><span class="category hidden-xs">[Lesung]</span></div>
   <a class="more float-right btn btn-success d-none d-sm-block" href="https://www.reservix.de/p/reservix/event/2566781" target="_blank">Tickets</a>
  </div>
 </li>
</div>

<!-- Kein Kategorie-Span, keine Filter-Klasse, Kids-Keyword im Titel -->
<div class="col-sm-12 filter-item">
 <li class="animated fadeInUp media mb-2 pb-2 odd" itemscope="" itemtype="http://schema.org/Event">
  <a href="/veranstaltung/news/ema-kids-die-magische-schule/?cHash=abc&amp;L=0">
   <img alt="" class="mr-3" height="100" src="/fileadmin/_processed_/a/b/csm_kids_76967a5f0b.jpg" width="100"/>
  </a>
  <div class="media-body">
   <time datetime="2031-09-26" itemprop="startDate">
    <strong>Freitag, 26.09.2031</strong> - <strong>Beginn: 16:00 Uhr</strong>
   </time>
   <h5 class="mt-0 mb-1">
    <a href="/veranstaltung/news/ema-kids-die-magische-schule/?cHash=abc&amp;L=0" title="EMA KIDS • Die magische Schule">
     <span itemprop="name">EMA KIDS • Die magische Schule</span>
    </a>
   </h5>
   <div class="d-none d-sm-block"><span class="category hidden-xs"></span></div>
  </div>
 </li>
</div>

<!-- Alter Termin einer Verlegung -> verwerfen -->
<div class="col-sm-12 filter-item Comedy">
 <li class="media" itemscope="" itemtype="http://schema.org/Event">
  <div class="media-body">
   <time datetime="2031-10-03" itemprop="startDate">
    <strong>Freitag, 03.10.2031</strong> - <strong>Beginn: 20:00 Uhr</strong>
   </time>
   <h5 class="mt-0 mb-1">
    <a href="/veranstaltung/news/daniel-luis-autotune0/?cHash=x" title="Daniel Luis • AUTOTUNE">
     <span itemprop="name">Daniel Luis • AUTOTUNE</span>
    </a>
    <span class="badge badge-warning">Verlegt auf 14.05.2032</span>
   </h5>
  </div>
 </li>
</div>

<!-- Ersatztermin -> behalten, Hinweis in Beschreibung -->
<div class="col-sm-12 filter-item Konzert">
 <li class="media" itemscope="" itemtype="http://schema.org/Event">
  <div class="media-body">
   <time datetime="2031-10-10" itemprop="startDate">
    <strong>Freitag, 10.10.2031</strong> - <strong>Beginn: 20:00 Uhr</strong>
   </time>
   <h5 class="mt-0 mb-1">
    <a href="/veranstaltung/news/prinz-pi/?cHash=y" title="Prinz Pi • Abschiedstour">
     <span itemprop="name">Prinz Pi • Abschiedstour</span>
    </a>
    <span class="badge badge-info">Ersatztermin für den 14.05.31</span>
   </h5>
  </div>
 </li>
</div>

<!-- Kaputt: kein Titel -->
<div class="col-sm-12 filter-item Konzert">
 <li class="media" itemscope="" itemtype="http://schema.org/Event">
  <div class="media-body">
   <time datetime="2031-10-11" itemprop="startDate"><strong>Samstag, 11.10.2031</strong></time>
   <h5 class="mt-0 mb-1"></h5>
  </div>
 </li>
</div>

<!-- Kaputt: kein Datum -->
<div class="col-sm-12 filter-item Konzert">
 <li class="media" itemscope="" itemtype="http://schema.org/Event">
  <div class="media-body">
   <h5 class="mt-0 mb-1"><a href="/veranstaltung/news/ohne-datum/"><span itemprop="name">Ohne Datum</span></a></h5>
  </div>
 </li>
</div>

<!-- Vergangen -->
<div class="col-sm-12 filter-item Konzert">
 <li class="media" itemscope="" itemtype="http://schema.org/Event">
  <div class="media-body">
   <time datetime="2031-09-10" itemprop="startDate"><strong>Mittwoch, 10.09.2031</strong> - <strong>Beginn: 20:00 Uhr</strong></time>
   <h5 class="mt-0 mb-1"><a href="/veranstaltung/news/alt/"><span itemprop="name">Altes Konzert</span></a></h5>
  </div>
 </li>
</div>

<!-- > 120 Tage -->
<div class="col-sm-12 filter-item Party">
 <li class="media" itemscope="" itemtype="http://schema.org/Event">
  <div class="media-body">
   <time datetime="2032-01-27" itemprop="startDate"><strong>Dienstag, 27.01.2032</strong> - <strong>Beginn: 20:00 Uhr</strong></time>
   <h5 class="mt-0 mb-1"><a href="/veranstaltung/news/roeschen/"><span itemprop="name">Röschen Sitzung</span></a></h5>
  </div>
 </li>
</div>

</div>
</body>
</html>
"""

WSH_DETAIL_HTML = """
<!doctype html>
<html>
<body>
<div class="news news-single">
 <div class="article" itemscope="itemscope" itemtype="http://schema.org/Article">
  <h1 itemprop="headline">Marc Friedrich • Wenn es Nacht wird im Westen</h1>
  <div class="alert alert-secondary row" role="alert">
   <div class="col-11">
    <time datetime="2031-09-23">
     <strong>Mittwoch, 23.09.2031</strong><br/>
     <strong>Beginn: 19:00 Uhr</strong><br/>
     <div class="extrainfo">
      <p>Einlass: 18:30 Uhr</p>
      <p></p>
      <p>VVK: ab 10,90€</p>
     </div>
    </time>
    <span class="news-list-category">[Lesung]</span>
   </div>
  </div>
  <div class="row">
   <div class="col-md-8">
    <div class="news-text-wrap" itemprop="articleBody">
     <p>Marc Friedrich liest aus seinem neuen Kriminalroman "Wenn es Nacht wird im Westen".<br/><br/>
        Premierenlesung mit dem Autoren und anschließender Talkrunde</p>
    </div>
   </div>
   <div class="col-md-4 gallery">
    <figure class="image">
     <a data-caption="" href="/fileadmin/_processed_/4/4/csm_2_d1cbfd62c6.png">
      <img alt="image-1425" class="img-fluid" src="/fileadmin/_processed_/4/4/csm_2_a6a991faa6.png" width="282"/>
     </a>
    </figure>
   </div>
  </div>
 </div>
</div>
</body>
</html>
"""


def _by_title(events, title):
    return [e for e in events if e["title"] == title]


def test_parses_valid_items_only():
    events = parse_weststadthalle_html(WSH_LIST_HTML, now=NOW)
    titles = [e["title"] for e in events]
    assert titles == [
        "MERVE • MERVENZUSAMMENBRUCH",
        "Marc Friedrich • Wenn es Nacht wird im Westen",
        "EMA KIDS • Die magische Schule",
        "Prinz Pi • Abschiedstour",
    ]
    # verworfen: Verlegt-auf (alter Termin), ohne Titel, ohne Datum, vergangen, > 120 Tage
    assert "Daniel Luis • AUTOTUNE" not in titles
    assert "Ohne Datum" not in titles
    assert "Altes Konzert" not in titles
    assert "Röschen Sitzung" not in titles


def test_event_fields():
    events = parse_weststadthalle_html(WSH_LIST_HTML, now=NOW)
    merve = _by_title(events, "MERVE • MERVENZUSAMMENBRUCH")[0]
    assert merve["start_at"] == datetime(2031, 9, 20, 20, 0)
    assert merve["venue_name"] == "Weststadthalle"
    assert merve["source_name"] == "Weststadthalle"
    assert merve["city"] == "Essen"
    assert merve["lat"] == pytest.approx(51.4581367)
    assert merve["lon"] == pytest.approx(7.0027362)
    assert merve["indoor_outdoor"] == "indoor"
    assert merve["category"] == "Comedy"
    assert merve["price_text"] == "Ausverkauft"
    assert merve["image_url"] == "https://www.weststadthalle.de/fileadmin/_processed_/1/f/csm_Bild3_c3112dc3b6.jpeg"
    # Titel ohne Badge-Text
    assert "Ausverkauft" not in merve["title"]


def test_source_url_has_no_chash():
    """robots.txt verbietet /*cHash — Deep-Link muss ohne Query sein."""
    events = parse_weststadthalle_html(WSH_LIST_HTML, now=NOW)
    for e in events:
        assert "cHash" not in e["source_url"]
        assert e["source_url"].startswith("https://www.weststadthalle.de/veranstaltung/news/")
    lesung = _by_title(events, "Marc Friedrich • Wenn es Nacht wird im Westen")[0]
    assert lesung["source_url"] == "https://www.weststadthalle.de/veranstaltung/news/marc-friedrich-wenn-es-nacht-wird-im-westen/"
    assert lesung["category"] == "Lesung"
    assert lesung["start_at"] == datetime(2031, 9, 23, 19, 0)


def test_kids_keyword_and_missing_category():
    events = parse_weststadthalle_html(WSH_LIST_HTML, now=NOW)
    kids = _by_title(events, "EMA KIDS • Die magische Schule")[0]
    assert kids["kids_suitable"] == "likely"
    assert kids["category"] is None
    assert kids["start_at"] == datetime(2031, 9, 26, 16, 0)


def test_ersatztermin_note_goes_to_description():
    events = parse_weststadthalle_html(WSH_LIST_HTML, now=NOW)
    pi = _by_title(events, "Prinz Pi • Abschiedstour")[0]
    assert pi["short_description"] == "Ersatztermin für den 14.05.31"
    assert pi["price_text"] is None
    assert pi["category"] == "Konzert"


def test_canonical_ids_unique_and_sorted():
    events = parse_weststadthalle_html(WSH_LIST_HTML, now=NOW)
    ids = [e["canonical_id"] for e in events]
    assert len(ids) == len(set(ids))
    starts = [e["start_at"] for e in events]
    assert starts == sorted(starts)


def test_window_relative_to_now():
    """Fixture relativ zu datetime.now(): morgen bleibt, gestern faellt raus."""
    tomorrow = datetime.now() + timedelta(days=1)
    yesterday = datetime.now() - timedelta(days=1)

    def item(day, title):
        return f"""
        <div class="col-sm-12 filter-item Konzert">
         <li class="media" itemscope="" itemtype="http://schema.org/Event">
          <div class="media-body">
           <time datetime="{day:%Y-%m-%d}" itemprop="startDate">
            <strong>{day:%d.%m.%Y}</strong> - <strong>Beginn: 20:00 Uhr</strong>
           </time>
           <h5><a href="/veranstaltung/news/{title.lower()}/"><span itemprop="name">{title}</span></a></h5>
          </div>
         </li>
        </div>"""

    html = f"<html><body>{item(tomorrow, 'Morgen')}{item(yesterday, 'Gestern')}</body></html>"
    events = parse_weststadthalle_html(html)
    assert [e["title"] for e in events] == ["Morgen"]
    assert events[0]["start_at"] == tomorrow.replace(hour=20, minute=0, second=0, microsecond=0)


def test_empty_html():
    assert parse_weststadthalle_html("<html><body></body></html>", now=NOW) == []


# ───────────────────────────── Datum-Parser ──────────────────────────────────


def _time_el(html):
    return BeautifulSoup(html, "lxml").find("time")


def test_parse_start_prefers_datetime_attr_and_begin_time():
    el = _time_el('<time datetime="2031-09-20"><strong>Sonntag, 20.09.2031</strong> - <strong>Beginn: 20:00 Uhr</strong></time>')
    assert _parse_start(el) == datetime(2031, 9, 20, 20, 0)


def test_parse_start_date_from_text_when_attr_missing():
    el = _time_el("<time>Sonntag, 24.06.2031 - 19:30 Uhr</time>")
    # "24.06." darf nicht als 24:06 Uhr gelesen werden
    assert _parse_start(el) == datetime(2031, 6, 24, 19, 30)


def test_parse_start_without_time_is_midnight():
    el = _time_el('<time datetime="2031-11-02">Sonntag, 02.11.2031</time>')
    assert _parse_start(el) == datetime(2031, 11, 2, 0, 0)


def test_parse_start_invalid_returns_none():
    assert _parse_start(None) is None
    assert _parse_start(_time_el("<time>kein Datum</time>")) is None
    assert _parse_start(_time_el('<time datetime="2031-13-40">x</time>')) is None


def test_clean_url_strips_query_and_makes_absolute():
    assert _clean_url("/veranstaltung/news/x/?cHash=abc&L=0") == "https://www.weststadthalle.de/veranstaltung/news/x/"
    assert _clean_url("https://www.weststadthalle.de/veranstaltung/news/y/") == "https://www.weststadthalle.de/veranstaltung/news/y/"


# ─────────────────────────── Detail-Enrichment ──────────────────────────────


def test_detail_page_extracts_price_description_image():
    detail = parse_weststadthalle_detail_html(WSH_DETAIL_HTML)
    assert detail["price_text"] == "VVK: ab 10,90€"
    assert detail["short_description"].startswith("Einlass 18:30 Uhr · Marc Friedrich liest")
    assert "Premierenlesung" in detail["short_description"]
    assert detail["image_url"] == "https://www.weststadthalle.de/fileadmin/_processed_/4/4/csm_2_d1cbfd62c6.png"


def test_detail_page_empty_returns_empty_dict():
    assert parse_weststadthalle_detail_html("<html><body></body></html>") == {}


def test_merge_detail_keeps_sold_out_and_note():
    event = {
        "title": "MERVE",
        "short_description": "Ersatztermin für den 14.05.31",
        "price_text": "Ausverkauft",
        "image_url": "https://www.weststadthalle.de/thumb.jpg",
        "kids_suitable": "unknown",
    }
    _merge_detail(event, parse_weststadthalle_detail_html(WSH_DETAIL_HTML))
    assert event["price_text"] == "Ausverkauft (VVK: ab 10,90€)"
    assert event["short_description"].startswith("Ersatztermin für den 14.05.31 – Einlass 18:30 Uhr")
    assert event["image_url"].endswith("csm_2_d1cbfd62c6.png")
    assert len(event["short_description"]) <= 500
