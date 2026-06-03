"""Offline-Tests für die drei neuen Parser (Batch A):
- Ferienspatz Essen
- Artistical Theater Essen (GOP Varieté)
- Villa Hügel / Krupp-Stiftung

Alle Tests sind netzwerkfrei und verwenden eingebettete HTML/JS-Fixtures,
die aus den echten Seiten gekürzt wurden.
"""
from datetime import datetime

from app.services.ferienspatz import (
    parse_ferienspatz_html,
    _parse_date,
    _find_date_col_index,
    _extract_address_from_detail,
    _is_essen_address,
)
from bs4 import BeautifulSoup
from app.services.artistical import _extract_events_from_chunk, _kids_suitable
from app.services.villa_huegel import (
    parse_villa_huegel_programs,
    _parse_date_as_string,
    _clean_title,
)


# ─────────────────────────────── FERIENSPATZ ─────────────────────────────────

FERIENSPATZ_FIXTURE = """
<!DOCTYPE html>
<html>
<body>
<div class="g-col-12">
  <div class="card mb-3">
    <div class="card-header border-bottom-0">
      <div class="row">
        <div class="col-md">
          <a class="text-decoration-none" href="/Event/Details/9524">
            <h2 class="align-middle">Malworkshop f&#xFC;r Kinder</h2>
          </a>
        </div>
        <div class="col-md-auto text-md-end">
          <a class="text-decoration-none" href="/Event/Details/9524#priceinformation">
            <img src="/img/tb_kostenlos.svg" alt="Symbol f&#xFC;r kostenlose Veranstltungen" />
          </a>
        </div>
      </div>
    </div>
    <div class="card-header pt-0">
      <div class="row">
        <div class="col-md-8">
          <span class="text-muted align-middle">Kunstzentrum Essen e.V.</span>
        </div>
      </div>
    </div>
    <div class="card-body">
      <div class="row">
        <div class="col-md mb-2">
          <span class="badge bg-primary">Kreatives</span>
        </div>
      </div>
      <h4 class="card-title">Beschreibung</h4>
      <p class="card-text">Kinder malen mit verschiedenen Techniken.</p>
    </div>
    <h5 class="card-header" id="allappointments">Termine <span class="badge bg-secondary">2</span></h5>
    <div class="table-responsive">
      <table class="table card-table">
        <thead><tr>
          <th scope="col">Beginn/Ende</th>
          <th scope="col">Altersgruppe</th>
          <th scope="col">Hinweis</th>
        </tr></thead>
        <tbody>
          <tr>
            <td>12.07.2026</td>
            <td>von 6 bis 12 Jahren</td>
            <td>&nbsp;</td>
          </tr>
          <tr>
            <td>19.07.2026</td>
            <td>von 6 bis 12 Jahren</td>
            <td>&nbsp;</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="card-footer border-top-0 text-end">
      <a class="btn btn-outline-primary" href="/Event/Details/9524">Weitere Informationen</a>
    </div>
  </div>
</div>
</body>
</html>
"""

FERIENSPATZ_NO_DATES_FIXTURE = """
<!DOCTYPE html>
<html><body>
<div class="g-col-12">
  <div class="card mb-3">
    <div class="card-header border-bottom-0">
      <div class="row"><div class="col-md">
        <a href="/Event/Details/9999"><h2 class="align-middle">Zirkusprojekt</h2></a>
      </div></div>
    </div>
    <div class="card-header pt-0">
      <div class="row"><div class="col-md-8">
        <span class="text-muted align-middle">Zirkus Olé</span>
      </div></div>
    </div>
    <div class="card-body">
      <p class="card-text">Akrobatik und mehr.</p>
    </div>
    <h5 class="card-header" id="allappointments">Termine <span class="badge bg-secondary">0</span></h5>
    <div class="table-responsive">
      <table class="table card-table"><tbody></tbody></table>
    </div>
  </div>
</div>
</body></html>
"""


def test_ferienspatz_parses_two_appointments():
    """Each appointment row in the table should produce one event dict."""
    events = parse_ferienspatz_html(FERIENSPATZ_FIXTURE)
    assert len(events) == 2
    titles = [e["title"] for e in events]
    assert all(t == "Malworkshop für Kinder" for t in titles)
    dates = [e["start_at"] for e in events]
    assert datetime(2026, 7, 12) in dates
    assert datetime(2026, 7, 19) in dates


def test_ferienspatz_kids_suitable_always_yes():
    events = parse_ferienspatz_html(FERIENSPATZ_FIXTURE)
    assert all(e["kids_suitable"] == "yes" for e in events)


def test_ferienspatz_price_text_kostenlos():
    events = parse_ferienspatz_html(FERIENSPATZ_FIXTURE)
    assert all(e["price_text"] == "kostenlos" for e in events)


def test_ferienspatz_venue_name_extracted():
    events = parse_ferienspatz_html(FERIENSPATZ_FIXTURE)
    assert all(e["venue_name"] == "Kunstzentrum Essen e.V." for e in events)


def test_ferienspatz_age_group_in_description():
    events = parse_ferienspatz_html(FERIENSPATZ_FIXTURE)
    for e in events:
        assert "Altersgruppe" in (e["short_description"] or "")
        assert "6 bis 12" in (e["short_description"] or "")


def test_ferienspatz_no_date_rows_emits_placeholder():
    """When no valid date rows exist, one placeholder entry is emitted."""
    events = parse_ferienspatz_html(FERIENSPATZ_NO_DATES_FIXTURE)
    assert len(events) == 1
    e = events[0]
    assert e["title"] == "Zirkusprojekt"
    assert e["start_at"] is None
    assert e["is_permanent_offer"] is True


def test_ferienspatz_date_parsing_short_year():
    """2-digit year in list view (05.06.26) should parse to 2026."""
    dt = _parse_date("05.06.26")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 6
    assert dt.day == 5


def test_ferienspatz_date_parsing_full_year():
    dt = _parse_date("17.07.2026")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 7
    assert dt.day == 17


def test_ferienspatz_source_name():
    events = parse_ferienspatz_html(FERIENSPATZ_FIXTURE)
    assert all(e["source_name"] == "Ferienspatz" for e in events)


# --- Neue Datum-Formate (Live aus ferienspatz.essen.de extrahiert) ---

# Fixture: Karte mit Datum+Uhrzeit-Format "18.07.26, 15:30 - 17:30"
# entspricht Karte "Biene Maja" auf Seite 1 der Listenseite
FERIENSPATZ_DATE_WITH_TIME_FIXTURE = """
<!DOCTYPE html><html><body>
<div class="card mb-3">
  <div class="card-header border-bottom-0">
    <div class="row"><div class="col-md">
      <a class="text-decoration-none" href="/Event/Details/9436">
        <h2 class="align-middle">Biene Maja</h2>
      </a>
    </div></div>
  </div>
  <div class="card-header pt-0">
    <div class="row"><div class="col-md-8">
      <span class="text-muted align-middle">Theater Concept</span>
    </div></div>
  </div>
  <div class="card-body">
    <div class="row"><div class="col-md mb-2">
      <span class="badge bg-primary">Theater</span>
    </div></div>
    <p class="card-text">Ein Theaterstück für Kinder.</p>
  </div>
  <div class="table-responsive">
    <table class="table card-table">
      <thead><tr>
        <th scope="col">Beginn/Ende</th>
        <th scope="col">Altersgruppe</th>
        <th scope="col">Hinweis</th>
      </tr></thead>
      <tbody>
        <tr>
          <td>18.07.26, 15:30 - 17:30</td>
          <td>ab 3 Jahren</td>
          <td></td>
        </tr>
        <tr>
          <td>19.07.26, 15:30 - 17:30</td>
          <td>ab 3 Jahren</td>
          <td></td>
        </tr>
        <tr>
          <td>22.07.26, 15:30 - 17:30</td>
          <td>ab 3 Jahren</td>
          <td></td>
        </tr>
        <tr>
          <td colspan="3"><a href="/Event/Details/9436#allappointments">weitere Termine verfügbar</a></td>
        </tr>
      </tbody>
    </table>
  </div>
</div>
</body></html>
"""

# Fixture: Karte mit Datumsbereich "10.07.26 - 11.07.26" (kein Komma)
# entspricht "Werwolf-Weekend" auf Seite 1
FERIENSPATZ_DATE_RANGE_FIXTURE = """
<!DOCTYPE html><html><body>
<div class="card mb-3">
  <div class="card-header border-bottom-0">
    <div class="row"><div class="col-md">
      <a class="text-decoration-none" href="/Event/Details/9565">
        <h2 class="align-middle">Werwolf-Weekend</h2>
      </a>
    </div></div>
  </div>
  <div class="card-header pt-0">
    <div class="row"><div class="col-md-8">
      <span class="text-muted align-middle">CVJM Essen</span>
    </div></div>
  </div>
  <div class="card-body">
    <p class="card-text">Ein Wochenendlager.</p>
  </div>
  <div class="table-responsive">
    <table class="table card-table">
      <thead><tr>
        <th scope="col">Beginn/Ende</th>
        <th scope="col">Altersgruppe</th>
        <th scope="col">Hinweis</th>
      </tr></thead>
      <tbody>
        <tr>
          <td>10.07.26 - 11.07.26</td>
          <td>von 8 bis 12 Jahren</td>
          <td></td>
        </tr>
      </tbody>
    </table>
  </div>
</div>
</body></html>
"""

# Fixture: Karte mit Titel-Spalte vor Beginn/Ende [Titel, Beginn/Ende, Altersgruppe, Hinweis]
# entspricht "Fahrten mit der Hespertalbahn" auf Seite 1
FERIENSPATZ_TITLE_COL_FIXTURE = """
<!DOCTYPE html><html><body>
<div class="card mb-3">
  <div class="card-header border-bottom-0">
    <div class="row"><div class="col-md">
      <a class="text-decoration-none" href="/Event/Details/5484">
        <h2 class="align-middle">Fahrten mit der Hespertalbahn</h2>
      </a>
    </div></div>
  </div>
  <div class="card-header pt-0">
    <div class="row"><div class="col-md-8">
      <span class="text-muted align-middle">Hespertalbahn e. V.</span>
    </div></div>
  </div>
  <div class="card-body">
    <p class="card-text">Nostalgiebahn im Ruhrgebiet.</p>
  </div>
  <div class="table-responsive">
    <table class="table card-table">
      <thead><tr>
        <th scope="col">Titel</th>
        <th scope="col">Beginn/Ende</th>
        <th scope="col">Altersgruppe</th>
        <th scope="col">Hinweis</th>
      </tr></thead>
      <tbody>
        <tr>
          <td>Dieselbetrieb</td>
          <td>19.07.26, 10:30 - 16:45</td>
          <td></td>
          <td></td>
        </tr>
        <tr>
          <td>Dampfbetrieb</td>
          <td>02.08.26, 10:30 - 16:45</td>
          <td></td>
          <td></td>
        </tr>
        <tr>
          <td>Dieselbetrieb</td>
          <td>16.08.26, 10:30 - 16:45</td>
          <td></td>
          <td></td>
        </tr>
        <tr>
          <td colspan="4"><a href="/Event/Details/5484#allappointments">weitere Termine verfügbar</a></td>
        </tr>
      </tbody>
    </table>
  </div>
</div>
</body></html>
"""


def test_ferienspatz_date_with_time_parses_correctly():
    """Datum+Uhrzeit-Format '18.07.26, 15:30 - 17:30' muss korrekt geparst werden."""
    dt = _parse_date("18.07.26, 15:30 - 17:30")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 7
    assert dt.day == 18
    assert dt.hour == 15
    assert dt.minute == 30


def test_ferienspatz_date_range_parses_first_date():
    """Datumsbereich '10.07.26 - 11.07.26' → start_at = 10. Juli 2026."""
    dt = _parse_date("10.07.26 - 11.07.26")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 7
    assert dt.day == 10


def test_ferienspatz_date_range_with_full_year():
    """Datumsbereich '18.07.26 - 28.07.26' → start_at = 18. Juli 2026."""
    dt = _parse_date("18.07.26 - 28.07.26")
    assert dt is not None
    assert dt.day == 18
    assert dt.month == 7


def test_ferienspatz_cards_with_time_emit_events():
    """Karten mit Datum+Uhrzeit-Format ergeben Events mit start_at != None."""
    events = parse_ferienspatz_html(FERIENSPATZ_DATE_WITH_TIME_FIXTURE)
    # 3 Terminzeilen (4. ist "weitere Termine" und wird gefiltert)
    assert len(events) == 3
    for e in events:
        assert e["start_at"] is not None
        assert e["is_permanent_offer"] is False
    dates = [e["start_at"].date() for e in events]
    from datetime import date
    assert date(2026, 7, 18) in dates
    assert date(2026, 7, 19) in dates
    assert date(2026, 7, 22) in dates


def test_ferienspatz_date_range_card_emits_event():
    """Karte mit Datumsbereich ergibt ein Event mit start_at = Startdatum."""
    events = parse_ferienspatz_html(FERIENSPATZ_DATE_RANGE_FIXTURE)
    assert len(events) == 1
    assert events[0]["start_at"] is not None
    assert events[0]["start_at"].day == 10
    assert events[0]["start_at"].month == 7
    assert events[0]["is_permanent_offer"] is False


def test_ferienspatz_titel_col_detected():
    """_find_date_col_index gibt 1 zurück wenn die erste Spalte 'Titel' heißt."""
    html = FERIENSPATZ_TITLE_COL_FIXTURE
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.card-table")
    assert _find_date_col_index(table) == 1


def test_ferienspatz_title_col_card_emits_dated_events():
    """Karte mit Titel-Spalte vor Beginn/Ende parst die Termine korrekt."""
    events = parse_ferienspatz_html(FERIENSPATZ_TITLE_COL_FIXTURE)
    # 3 Terminzeilen (4. ist "weitere Termine")
    assert len(events) == 3
    for e in events:
        assert e["start_at"] is not None, f"start_at ist None: {e['title']}"
        assert e["is_permanent_offer"] is False
    start_dates = [e["start_at"].date() for e in events]
    from datetime import date
    assert date(2026, 7, 19) in start_dates
    assert date(2026, 8, 2) in start_dates
    assert date(2026, 8, 16) in start_dates


# --- Fix A: Detailadress-Extraktion ---

FERIENSPATZ_DETAIL_WITH_ADDRESS_FIXTURE = """
<!DOCTYPE html>
<html><body>
<div class="container">
  <div class="row mb-3 mt-3">
    <label class="col-md-4 fw-bold" for="Event_FullAdresse">Adresse</label>
    <div class="col-md-8">
      <p class="card-text">Gustav-Heinemann-Platz 1 , 45309 Essen</p>
    </div>
  </div>
  <div class="row mb-3 mt-3">
    <label class="col-md-4 fw-bold" for="Event_Treffpunkt">Treffpunkt</label>
    <div class="col-md-8">
      <p class="card-text">Sportplatz an der Gustav-Heinemann-Gesamtschule</p>
    </div>
  </div>
</div>
</body></html>
"""

FERIENSPATZ_DETAIL_WITHOUT_ADDRESS_FIXTURE = """
<!DOCTYPE html>
<html><body>
<div class="container">
  <div class="row mb-3 mt-3">
    <label class="col-md-4 fw-bold" for="Event_Treffpunkt">Treffpunkt</label>
    <div class="col-md-8">
      <p class="card-text">Wiese hinter dem Spielplatz</p>
    </div>
  </div>
</div>
</body></html>
"""

FERIENSPATZ_DETAIL_NON_ESSEN_FIXTURE = """
<!DOCTYPE html>
<html><body>
<div class="container">
  <div class="row mb-3 mt-3">
    <label class="col-md-4 fw-bold" for="Event_FullAdresse">Adresse</label>
    <div class="col-md-8">
      <p class="card-text">Zum Blauen See 20, 40878 Ratingen</p>
    </div>
  </div>
</div>
</body></html>
"""


def test_ferienspatz_detail_address_extracted():
    """_extract_address_from_detail liest die echte Veranstaltungsadresse."""
    addr = _extract_address_from_detail(FERIENSPATZ_DETAIL_WITH_ADDRESS_FIXTURE)
    assert addr == "Gustav-Heinemann-Platz 1 , 45309 Essen"


def test_ferienspatz_detail_address_none_when_absent():
    """Fehlendes Adressfeld ergibt None – kein Absturz."""
    addr = _extract_address_from_detail(FERIENSPATZ_DETAIL_WITHOUT_ADDRESS_FIXTURE)
    assert addr is None


# --- Fix B: Essen-Filter ---


def test_is_essen_address_known_plz():
    """Bekannte Essener PLZ wird als Essen erkannt."""
    assert _is_essen_address("Gustav-Heinemann-Platz 1 , 45309 Essen") is True
    assert _is_essen_address("Karnaper Str. 20 , 45329 Essen") is True
    assert _is_essen_address("Möllhoven 62, 45355 Essen") is True


def test_is_essen_address_non_essen_plz():
    """Nicht-Essener PLZ wird korrekt abgelehnt."""
    assert _is_essen_address("Zum Blauen See 20, 40878 Ratingen") is False
    assert _is_essen_address("Juri-Gerus-Weg 10, 44623 Herne") is False
    assert _is_essen_address("Bruchstraße 28a, 45525 Hattingen") is False
    assert _is_essen_address("Gewerkenstraße 28, 45881 Gelsenkirchen") is False
    assert _is_essen_address("Werdener Weg 8, 45470 Mülheim an der Ruhr") is False


def test_is_essen_address_no_plz_essen_name():
    """Kein PLZ, aber 'Essen' im Ortsnamen → akzeptiert."""
    assert _is_essen_address("Marktplatz, Essen") is True
    assert _is_essen_address("Irgendwo, 45309 Essen") is True


def test_is_essen_address_no_plz_unknown():
    """Weder PLZ noch Stadtname → konservativ akzeptiert (kein False-Positive-Filter)."""
    assert _is_essen_address("Wiese hinter dem Spielplatz") is True


def test_ferienspatz_detail_non_essen_identified():
    """Detailseite mit Ratingen-Adresse: _extract liefert Adresse, _is_essen lehnt ab."""
    addr = _extract_address_from_detail(FERIENSPATZ_DETAIL_NON_ESSEN_FIXTURE)
    assert addr == "Zum Blauen See 20, 40878 Ratingen"
    assert _is_essen_address(addr) is False


# ──────────────────────────── ARTISTICAL (GOP Varieté) ───────────────────────

# Minimal JS fixture modelled after the real chunk structure
# (reduced to one Kindermusical show with two dates and one show without dates)
ARTISTICAL_CHUNK_FIXTURE = r"""
(function(){
let l=[{id:"pk1",name:"PK 1",priceFrom:69}];
let c=[{slug:"dschungelbuch",label:"Kindermusical",title:"Das Dschungelbuch",shortDescription:"Ein Musical f\xfcr die ganze Familie.",imageUrl:"/media/events/event-dschungelbuch.jpg",heroImageUrl:"/media/events/event-dschungelbuch-hero.jpg",ageRecommendation:"Ab 4 Jahren",ticketUrl:"https://tixu-shop.variete.de/tickets/3",priceCategories:l,dates:[{iso:"2026-12-05",ticketUrl:"https://tixu-shop.variete.de/tickets/3/100"},{iso:"2026-12-06",ticketUrl:"https://tixu-shop.variete.de/tickets/3/101"}]},{slug:"groove",label:"Eigenproduktion",title:"GROOVE",shortDescription:"Disco, Artistik, Livemusik.",imageUrl:"/media/events/event-groove.jpg",heroImageUrl:"/media/events/event-groove-hero.jpg",ageRecommendation:"Familienfreundlich",ticketUrl:"https://tixu-shop.variete.de/tickets/20",priceCategories:l}];
function EventsSection(){}
})();
"""


def test_artistical_parses_dated_show():
    events = _extract_events_from_chunk(ARTISTICAL_CHUNK_FIXTURE)
    dschungel = [e for e in events if e["title"] == "Das Dschungelbuch"]
    assert len(dschungel) == 2
    dates = {e["start_at"] for e in dschungel}
    assert datetime(2026, 12, 5) in dates
    assert datetime(2026, 12, 6) in dates


def test_artistical_kindermusical_kids_yes():
    events = _extract_events_from_chunk(ARTISTICAL_CHUNK_FIXTURE)
    for e in [ev for ev in events if ev["title"] == "Das Dschungelbuch"]:
        assert e["kids_suitable"] == "yes"


def test_artistical_permanent_show_no_date():
    events = _extract_events_from_chunk(ARTISTICAL_CHUNK_FIXTURE)
    groove = [e for e in events if e["title"] == "GROOVE"]
    assert len(groove) == 1
    assert groove[0]["start_at"] is None
    assert groove[0]["is_permanent_offer"] is True


def test_artistical_venue_and_coordinates():
    events = _extract_events_from_chunk(ARTISTICAL_CHUNK_FIXTURE)
    for e in events:
        assert e["venue_name"] == "Artistical Theater Essen (GOP Varieté)"
        assert abs(e["lat"] - 51.45230) < 0.001
        assert abs(e["lon"] - 7.01330) < 0.001
        assert e["indoor_outdoor"] == "indoor"
        assert e["city"] == "Essen"


def test_artistical_source_name():
    events = _extract_events_from_chunk(ARTISTICAL_CHUNK_FIXTURE)
    for e in events:
        assert e["source_name"] == "GOP Varieté"


def test_artistical_kids_suitable_familienfreundlich():
    assert _kids_suitable("Eigenproduktion", "Familienfreundlich") == "yes"
    assert _kids_suitable("Kindermusical", "") == "yes"
    assert _kids_suitable("Gastveranstaltung", "Ab 16 Jahren") == "unknown"


def test_artistical_image_url_absolute():
    events = _extract_events_from_chunk(ARTISTICAL_CHUNK_FIXTURE)
    for e in events:
        if e.get("image_url"):
            assert e["image_url"].startswith("https://")


# ─────────────────────────────── VILLA HÜGEL ─────────────────────────────────

VILLA_HUEGEL_PROGRAMS_FIXTURE = [
    {
        "id": 25292,
        "title": "Der Hügel\r\nist Vortrag",
        "slug": "der-huegel-ist-vortrag-4",
        "subtitle": "Wie wird Deutschland wieder reformfähig",
        "date_as_string": "7. Juli 2026",
        "thumbnail": {
            "src": "https://www.krupp-stiftung.de/app/uploads/2026/04/Vortrag_750x750.jpg",
        },
    },
    {
        "id": 12329,
        "title": "Der Hügel\r\nist Family",
        "slug": "der-huegel-ist-family",
        "subtitle": "Kinder- und Familienprogramm in der Villa Hügel",
        "date_as_string": "Ganzjährig",
        "thumbnail": {
            "src": "https://www.krupp-stiftung.de/app/uploads/2023/12/family-750x750.jpg",
        },
    },
    {
        "id": 9923,
        "title": "Tag des offenen Hügels",
        "slug": "tag-des-offenen-huegels",
        "subtitle": "Ganztägig freier Eintritt in Villa & Park",
        "date_as_string": "Ab 6. Februar jeden ersten Freitag im Monat",
        "thumbnail": {"src": "https://www.krupp-stiftung.de/app/uploads/2023/01/open-750x750.jpg"},
    },
    {
        "id": 9861,
        "title": "Der Hügel ist Kino",
        "slug": "der-huegel-ist-kino",
        "subtitle": "Kino im ehemaligen Wohnzimmer der Krupps",
        "date_as_string": "Abgeschlossen",
        "thumbnail": None,
    },
]


def test_villa_huegel_parses_dated_event():
    events = parse_villa_huegel_programs(VILLA_HUEGEL_PROGRAMS_FIXTURE)
    vortrag = [e for e in events if "Vortrag" in e["title"]]
    assert len(vortrag) == 1
    assert vortrag[0]["start_at"] == datetime(2026, 7, 7)
    assert vortrag[0]["is_permanent_offer"] is False


def test_villa_huegel_skips_abgeschlossen():
    events = parse_villa_huegel_programs(VILLA_HUEGEL_PROGRAMS_FIXTURE)
    titles = [e["title"] for e in events]
    assert not any("Kino" in t for t in titles)


def test_villa_huegel_permanent_offer_ganzjaehrig():
    events = parse_villa_huegel_programs(VILLA_HUEGEL_PROGRAMS_FIXTURE)
    family = [e for e in events if "Family" in e["title"]]
    assert len(family) == 1
    assert family[0]["is_permanent_offer"] is True
    assert family[0]["start_at"] is None


def test_villa_huegel_family_kids_yes():
    events = parse_villa_huegel_programs(VILLA_HUEGEL_PROGRAMS_FIXTURE)
    family = [e for e in events if "Family" in e["title"]]
    assert family[0]["kids_suitable"] == "yes"


def test_villa_huegel_coordinates():
    events = parse_villa_huegel_programs(VILLA_HUEGEL_PROGRAMS_FIXTURE)
    for e in events:
        assert abs(e["lat"] - 51.40780) < 0.001
        assert abs(e["lon"] - 7.01270) < 0.001
        assert e["city"] == "Essen"
        assert e["venue_name"] == "Villa Hügel"


def test_villa_huegel_source_name():
    events = parse_villa_huegel_programs(VILLA_HUEGEL_PROGRAMS_FIXTURE)
    for e in events:
        assert e["source_name"] == "Villa Hügel"


def test_villa_huegel_clean_title_strips_newlines():
    assert _clean_title("Der Hügel\r\nist Family") == "Der Hügel ist Family"
    assert _clean_title("Vortrag\rvon Prof.") == "Vortrag von Prof."


def test_villa_huegel_date_parsing():
    assert _parse_date_as_string("7. Juli 2026") == datetime(2026, 7, 7)
    assert _parse_date_as_string("2. Juni 2026") == datetime(2026, 6, 2)
    assert _parse_date_as_string("Ganzjährig") is None
    assert _parse_date_as_string("Ab 6. Februar jeden ersten Freitag") is None
    assert _parse_date_as_string("Abgeschlossen") is None
    assert _parse_date_as_string("") is None


def test_villa_huegel_image_url():
    events = parse_villa_huegel_programs(VILLA_HUEGEL_PROGRAMS_FIXTURE)
    vortrag = [e for e in events if "Vortrag" in e["title"]]
    assert vortrag[0]["image_url"].startswith("https://")


def test_villa_huegel_subtitle_in_description():
    events = parse_villa_huegel_programs(VILLA_HUEGEL_PROGRAMS_FIXTURE)
    vortrag = [e for e in events if "Vortrag" in e["title"]]
    assert "reformfähig" in (vortrag[0]["short_description"] or "")
