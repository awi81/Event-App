"""Offline parser tests for the Bergbau-Museum Bochum source (no network)."""
from datetime import datetime

from app.services.bergbaumuseum import (
    parse_bergbaumuseum_html,
    parse_month_urls,
)

# Gekuerzter Ausschnitt der Kalender-Listenseite (TYPO3 ig_event). Jahreszahlen
# liegen weit in der Zukunft; die Tests injizieren ein passendes `now`.
NOW = datetime(2031, 10, 21, 9, 0)


def _item(day: str, item_id: str, cats: str, slug: str, date_txt: str, title: str,
          suggest: str, time_txt: str = "", note: str = "") -> str:
    """Ein li.cal-list-item im Original-Markup (DDMMYYYY als li-ID)."""
    time_row = (
        f'<div class="row"><div class="col"><span class="res-font eventtime">{time_txt}</span></div></div>'
        if time_txt else ""
    )
    note_html = f'<span class="custom-eventnote">{note}</span>' if note else ""
    year, month_name, d = day[4:], "Oktober", int(day[:2])
    return f"""
<li class="cal-list-item " id="cal-day-{day}">
  <div class="" data-cal-item="{item_id}" data-cal-suggest='{suggest}' data-cal-categories="{cats}">
    <div class="container cli-con" data-cal-list-item="">
      <a class="cal-list-item-title res-font" href="/veranstaltungen-detailseite/{slug}/{year}/{month_name}/{d}">
        <div class="row pt-4 pb-3 pl-1 pr-1 position-relative">
          <div class="col-4 col-md-3 pl-0">
            <div class="row"><div class="col"><span class="cal-list-item-date-day subhead-l res-font"> So </span></div>
            <div class="col"><span class="subhead-l res-font"> {date_txt} </span></div></div>
            {time_row}
          </div>
          <div class="col-8 col-md-9 pl-0 pr-5 event-item-arrow event-title-cell"> {note_html} {title} </div>
        </div>
      </a>
    </div>
  </div>
</li>"""


FAMILIE_SUGGEST = (
    "Familienführung unter Tage &lt;p&gt;Tief unten in der Erde liegt der Arbeitsplatz des Bergmanns. "
    "Kommt mit und entdeckt die Welt unter Tage.&lt;/p&gt;&lt;ul&gt; &lt;li&gt;Dauer: ca. 40 Minuten&lt;/li&gt; "
    "&lt;li&gt;Kosten: 3 € zzgl. Eintritt&lt;/li&gt; &lt;li&gt;Teilnehmendenzahl begrenzt&lt;/li&gt; &lt;/ul&gt; "
)
GRUBIS_SUGGEST = (
    "Mit den Grubis unter Tage &lt;p&gt;Unsere Experten sind mit dem Anschauungsbergwerk bestens vertraut.&lt;/p&gt;"
    "&lt;ul&gt; &lt;li&gt;Kosten: 8 € zzgl. Eintritt&lt;/li&gt; &lt;li&gt;Zielgruppe ab 14 Jahren&lt;/li&gt; &lt;/ul&gt; "
)
FASZINATION_SUGGEST = (
    "Faszination über und unter Tage &lt;p&gt;Ganz individuell lässt sich das Deutsche Bergbau-Museum "
    "auf eigene Faust erkunden.&lt;/p&gt;&lt;p&gt;Öffnungszeiten&lt;/p&gt;&lt;ul&gt; &lt;li&gt;Dienstag bis Sonntag: "
    "09:30 bis 17:30 Uhr&lt;/li&gt; &lt;/ul&gt;"
)
FUEHRUNG_SUGGEST = (
    "Führung im Anschauungsbergwerk - unter Tage &lt;p&gt;&lt;em&gt;Start jeweils um 11:00 Uhr, 12:00 Uhr, "
    "13:00 Uhr &amp; 14:00 Uhr, &lt;/em&gt;&lt;br /&gt; nicht an Feiertagen!&lt;/p&gt;&lt;ul&gt; &lt;li&gt;Kosten: 3 € zzgl. "
    "Eintritt&lt;/li&gt; &lt;/ul&gt; "
)
WERKSTATT_SUGGEST = (
    "Geschichtenwerkstatt &lt;p&gt;Das Museum lädt in den Herbstferien Kinder zwischen 10 und 12 Jahren ein.&lt;/p&gt;"
    "&lt;ul&gt; &lt;li&gt;Kostenlos&lt;/li&gt; &lt;li&gt;Anmeldung erforderlich&lt;/li&gt; &lt;/ul&gt; "
)
LESUNG_SUGGEST = (
    "Lesung: Beispielautor &lt;p&gt;Eine Lesung für Erwachsene.&lt;/p&gt;&lt;ul&gt; &lt;li&gt;Kosten: 12 €&lt;/li&gt; &lt;/ul&gt; "
)

def _merge_days(items_html: list) -> str:
    """Wie auf der echten Seite: mehrere Veranstaltungen eines Tages in einem li."""
    from bs4 import BeautifulSoup

    days: dict = {}
    for h in items_html:
        li = BeautifulSoup(h, "lxml").find("li")
        days.setdefault(li["id"], []).append(li.decode_contents())
    return "".join(
        f'<li class="cal-list-item " id="{k}">{"".join(v)}</li>' for k, v in days.items()
    )


ITEMS = _merge_days([
    # vergangen (gestern, mit Uhrzeit) und ganztaegig gestern
    _item("20102031", "1742", "(148)(93)(87)(78)", "familienfuehrung-unter-tage", "20.10.",
          "Familienführung unter Tage", FAMILIE_SUGGEST, "15:00"),
    _item("20102031", "1784", "(86)", "faszination-ueber-und-unter-tage", "20.10.",
          "Faszination über und unter Tage", FASZINATION_SUGGEST),
    # heute: ganztaegig bleibt, 12:00 (vor now=09:00? nein, danach) bleibt, 19:00 bleibt
    _item("21102031", "1784", "(86)", "faszination-ueber-und-unter-tage", "21.10.",
          "Faszination über und unter Tage", FASZINATION_SUGGEST),
    _item("21102031", "1808", "(149)(80)", "lesung-beispielautor", "21.10.",
          "Lesung: Beispielautor", LESUNG_SUGGEST, "19:00"),
    # Familienfuehrung (Kinder-Tag 78)
    _item("25102031", "1742", "(148)(93)(87)(78)", "familienfuehrung-unter-tage", "25.10.",
          "Familienführung unter Tage", FAMILIE_SUGGEST, "15:00"),
    # Familien-Tag, aber ab 14 Jahren
    _item("22102031", "1738", "(146)(147)(87)(79)(83)", "mit-den-grubis-unter-tage", "22.10.",
          "Mit den Grubis unter Tage", GRUBIS_SUGGEST, "13:15"),
    # Hinweis im Titelfeld ("geaenderte Uhrzeit")
    _item("22102031", "1740", "(86)(146)(87)(79)(80)(83)", "nachts-im-bergwerk", "22.10.",
          "Nachts im Bergwerk", "Nachts im Bergwerk &lt;p&gt;Eine besondere Tour.&lt;/p&gt;", "16:30",
          note="geänderte Uhrzeit: 16:00 - 17:30 Uhr"),
    # Uhrzeit nur in der Beschreibung ("Start jeweils um ...")
    _item("23102031", "1812", "(146)(87)(83)", "fuehrung-im-anschauungsbergwerk-unter-tage", "23.10.",
          "Führung im Anschauungsbergwerk - unter Tage", FUEHRUNG_SUGGEST),
    # mehrtaegiges Angebot: ein li pro Tag, ohne Kategorie, nur Text-Hinweis auf Kinder
    _item("23102031", "1958", "", "kulturrucksack", "19.10.- 24.10.",
          "„Von Werwölfen, Seherinnen &amp; Kupferkerln“ Geschichtenwerkstatt", WERKSTATT_SUGGEST),
    _item("24102031", "1958", "", "kulturrucksack", "19.10.- 24.10.",
          "„Von Werwölfen, Seherinnen &amp; Kupferkerln“ Geschichtenwerkstatt", WERKSTATT_SUGGEST),
    # Randtag des Folgemonats: derselbe Termin erscheint auch auf der Nachbarseite -> nur einmal
    _item("25102031", "1742", "(148)(93)(87)(78)", "familienfuehrung-unter-tage", "25.10.",
          "Familienführung unter Tage", FAMILIE_SUGGEST, "15:00"),
    # weit in der Zukunft (> 120 Tage)
    _item("05052032", "1999", "(86)", "zukunft", "05.05.", "Zukunftstermin", "Zukunftstermin", "10:00"),
])

MONTH_SELECT = """
<select data-event-filter="month" class="form-control" id="eventmonthpagination" name="monthpagination">
  <option value="/besuch/veranstaltungskalender?tx_igevent_event%5Bmonthpagination%5D=1000&amp;cHash=aaa"> September 2031 </option>
  <option value="/besuch/veranstaltungskalender?tx_igevent_event%5Bmonthpagination%5D=2000&amp;cHash=bbb" selected="selected"> Oktober 2031 </option>
  <option value="/besuch/veranstaltungskalender?tx_igevent_event%5Bmonthpagination%5D=3000&amp;cHash=ccc"> November 2031 </option>
  <option value="/besuch/veranstaltungskalender?tx_igevent_event%5Bmonthpagination%5D=4000&amp;cHash=ddd"> Dezember 2031 </option>
  <option value="/besuch/veranstaltungskalender?tx_igevent_event%5Bmonthpagination%5D=5000&amp;cHash=eee"> Januar 2032 </option>
</select>
"""

HTML = f"""<!DOCTYPE html><html lang="de"><body>
{MONTH_SELECT}
<ul class="cal-list-item-wrapper desktab-event-listview">{ITEMS}</ul>
</body></html>"""


def _by_title(events, start):
    return [e for e in events if e["title"].startswith(start)]


def test_counts_and_past_dates_dropped():
    events = parse_bergbaumuseum_html(HTML, now=NOW)
    # Gestern (2 Items) und > 120 Tage fallen raus; 25.10. nur einmal (Dublette).
    # heute: Faszination + Lesung | 22.: Grubis, Nachts | 23.: Fuehrung, Kulturrucksack
    # 24.: Kulturrucksack | 25.: Familienfuehrung
    assert len(events) == 8
    assert not any(e["start_at"].date() == datetime(2031, 10, 20).date() for e in events)
    assert not _by_title(events, "Zukunftstermin")


def test_today_item_with_passed_time_is_dropped_but_allday_kept():
    later = datetime(2031, 10, 21, 20, 0)
    events = parse_bergbaumuseum_html(HTML, now=later)
    titles_today = [e["title"] for e in events if e["start_at"].date() == later.date()]
    assert "Lesung: Beispielautor" not in titles_today  # 19:00 ist vorbei
    assert "Faszination über und unter Tage" in titles_today  # ganztaegig


def test_fields_familienfuehrung():
    events = parse_bergbaumuseum_html(HTML, now=NOW)
    ev = _by_title(events, "Familienführung")
    assert len(ev) == 1
    ev = ev[0]
    assert ev["start_at"] == datetime(2031, 10, 25, 15, 0)
    assert ev["venue_name"] == "Deutsches Bergbau-Museum Bochum"
    assert ev["address_text"] == "Am Bergbaumuseum 28, 44791 Bochum"
    assert ev["city"] == "Bochum"
    assert ev["lat"] == 51.4886284 and ev["lon"] == 7.2164106
    assert ev["source_name"] == "Bergbau-Museum Bochum"
    assert ev["source_url"] == (
        "https://www.bergbaumuseum.de/veranstaltungen-detailseite/familienfuehrung-unter-tage/2031/Oktober/25"
    )
    assert ev["kids_suitable"] == "yes"
    assert ev["price_text"] == "3 € zzgl. Eintritt"
    assert ev["category"] == "Führung"
    assert ev["indoor_outdoor"] == "indoor"
    assert ev["short_description"].startswith("Tief unten in der Erde")
    assert len(ev["short_description"]) <= 500
    assert "Familienführung unter Tage" not in ev["short_description"][:5]
    assert len(ev["canonical_id"]) == 16


def test_family_tag_with_min_age_14_is_only_likely():
    events = parse_bergbaumuseum_html(HTML, now=NOW)
    grubis = _by_title(events, "Mit den Grubis")[0]
    assert grubis["start_at"] == datetime(2031, 10, 22, 13, 15)
    assert grubis["kids_suitable"] == "likely"
    assert grubis["price_text"] == "8 € zzgl. Eintritt"


def test_note_removed_from_title_and_kept_in_description():
    events = parse_bergbaumuseum_html(HTML, now=NOW)
    nachts = _by_title(events, "Nachts im Bergwerk")[0]
    assert nachts["title"] == "Nachts im Bergwerk"
    assert nachts["start_at"] == datetime(2031, 10, 22, 16, 30)
    assert "geänderte Uhrzeit: 16:00 - 17:30 Uhr" in nachts["short_description"]


def test_allday_and_start_time_from_description():
    events = parse_bergbaumuseum_html(HTML, now=NOW)
    faszination = _by_title(events, "Faszination")
    assert len(faszination) == 1  # nur heute (gestern vorbei)
    assert faszination[0]["start_at"] == datetime(2031, 10, 21, 0, 0)
    assert faszination[0]["kids_suitable"] == "unknown"
    fuehrung = _by_title(events, "Führung im Anschauungsbergwerk")[0]
    assert fuehrung["start_at"] == datetime(2031, 10, 23, 11, 0)  # erste "Start jeweils"-Zeit
    assert fuehrung["kids_suitable"] == "unknown"


def test_multi_day_offer_gives_one_event_per_day_and_text_kids_hint():
    events = parse_bergbaumuseum_html(HTML, now=NOW)
    rucksack = sorted(_by_title(events, "„Von Werwölfen"), key=lambda e: e["start_at"])
    assert [e["start_at"].date().day for e in rucksack] == [23, 24]
    assert len({e["canonical_id"] for e in rucksack}) == 2
    assert all(e["kids_suitable"] == "likely" for e in rucksack)  # "Kinder" im Text
    assert all(e["price_text"] == "Kostenlos" for e in rucksack)
    assert rucksack[0]["category"] == "Workshop"
    assert "&amp;" not in rucksack[0]["title"]


def test_lesung_category_and_adult():
    events = parse_bergbaumuseum_html(HTML, now=NOW)
    lesung = _by_title(events, "Lesung")[0]
    assert lesung["start_at"] == datetime(2031, 10, 21, 19, 0)
    assert lesung["category"] == "Lesung"
    assert lesung["price_text"] == "12 €"


def test_month_urls_follow_selected_month():
    urls = parse_month_urls(HTML)
    assert len(urls) == 2
    assert urls[0].startswith("https://www.bergbaumuseum.de/besuch/veranstaltungskalender?")
    assert "monthpagination%5D=3000&cHash=ccc" in urls[0]  # November
    assert "monthpagination%5D=4000&cHash=ddd" in urls[1]  # Dezember


def test_empty_and_broken_html():
    assert parse_bergbaumuseum_html("<html><body></body></html>", now=NOW) == []
    assert parse_month_urls("<html><body></body></html>") == []
    broken = '<ul><li class="cal-list-item" id="cal-day-xx"><div data-cal-item="1"></div></li></ul>'
    assert parse_bergbaumuseum_html(broken, now=NOW) == []
