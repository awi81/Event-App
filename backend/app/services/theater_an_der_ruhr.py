"""Theater an der Ruhr (Muelheim) event source — server-gerendertes HTML.

Quelle: https://www.theateranderruhr.de/de/kalender/spielplan

Aufbau der Seite (drei Reiter, je eine URL, alle ohne Login, robots.txt:
"User-agent: * / Allow: /"):
  - /de/kalender/spielplan            Theater an der Ruhr (Hauptprogramm)
  - /de/kalender/spielplan?s=723      Junges Theater
  - /de/kalender/spielplan?s=725      VolXbuehne
(/de/programm/spielplan?s=... leitet per 301 auf /de/kalender/... um.)

Zwei Darstellungen in derselben Seite:
  1. Monatsliste: article.schedule__item mit
       span "Fr 23.10. 19:30"          Wochentag, Datum, Beginn (Jahr fehlt!)
       .schedule__top-item--title      Spielort-Label ("Theater an der Ruhr",
                                       "Foyer", "Probebuehne", ...)
       .schedule__middle-tag           Rubrik (z. B. "ZwischenStuecke")
       h1.schedule__middle-title a     Titel + Link /de/kalender/stuecke/<id>-<slug>
       .schedule__middle-subtitle      Untertitel/Regie/"Gastspiel ..."
       .schedule__bottom-item (span)   Preis ("Eintritt frei")
  2. Festival-Raster: div.schedule2 je Tag mit span.schedule2__date--upper
     ("Fr 06.11.") und div.schedule2-item mit top-date ("19:30-21:30" oder
     "ab 18:30"), top-label (Hauptprogramm / Rahmenprogramm / Special),
     middle-attributes ("Premiere"), Titel, Untertitel.

Jahr: fehlt in beiden Darstellungen. Es wird das naechste Vorkommen ab heute
gewaehlt, das zum angegebenen Wochentag passt (Fr 06.11. -> 2026).

Detailseiten /de/kalender/stuecke/<id>-<slug> liefern Beschreibung
(meta Description), Bild (og:image) und den Ort-Block (Adresse). Sie werden nur
je Stueck einmal und hoechstens MAX_DETAIL_FETCHES-mal pro Lauf geholt
(Pause >= 1 s). Requests pro Lauf: 3 Spielplan-Seiten + <= 24 Detailseiten.
"""
import asyncio
import hashlib
import logging
import re
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.services.base_sync import sync_events_to_db
from app.services.crawler_ua import CRAWLER_USER_AGENT

logger = logging.getLogger(__name__)

SITE = "https://www.theateranderruhr.de"
LIST_PATH = "/de/kalender/spielplan"
# (Query-Parameter, Reiter ist Junges Theater)
TABS: List[Tuple[Optional[str], bool]] = [(None, False), ("723", True), ("725", False)]

SOURCE_NAME = "Theater an der Ruhr"
VENUE_NAME = "Theater an der Ruhr"
ADDRESS_TEXT = "Akazienallee 61, 45478 Mülheim an der Ruhr"
CITY = "Mülheim an der Ruhr"

# OSM amenity=theatre "Theater an der Ruhr", Akazienallee 61 (Raffelbergpark),
# per Nominatim verifiziert: 51.4388872, 6.8226813
VENUE_LAT = 51.4388872
VENUE_LON = 6.8226813

MAX_DAYS_AHEAD = 120
MAX_DETAIL_FETCHES = 24
REQUEST_PAUSE_S = 1.5

_BERLIN = ZoneInfo("Europe/Berlin")
_HEADERS = {"User-Agent": CRAWLER_USER_AGENT}

# Spielort-Labels der Monatsliste, die zum Haus an der Akazienallee gehoeren.
# Probebuehne (Ruhrorter Str. 108-110) und VolXbuehne liegen NICHT dort.
_HOME_LABELS = {"theater an der ruhr", "foyer"}

# Begleitprogramm des Festival-Rasters (Premierenparty, Nachgespraech,
# Installationen) ist kein eigenstaendiger Termin und wird uebersprungen.
_SKIP_LABELS = {"rahmenprogramm"}

_DATE_RE = re.compile(
    r"(?:(Mo|Di|Mi|Do|Fr|Sa|So)\.?\s+)?(\d{1,2})\.(\d{1,2})\.(?!\d{2,4}\b)"
)
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")
_WEEKDAYS = {"Mo": 0, "Di": 1, "Mi": 2, "Do": 3, "Fr": 4, "Sa": 5, "So": 6}

_KIDS_STRONG = re.compile(r"kinder|jährige|jaehrige|familie|schüler|schueler", re.I)
_KIDS_WEAK = re.compile(r"jugend|junges|ab \d{1,2} jahren|märchen|maerchen", re.I)


def _berlin_now() -> datetime:
    return datetime.now(_BERLIN).replace(tzinfo=None)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def _resolve_date(
    weekday: Optional[str], day: int, month: int, now: datetime
) -> Optional[date]:
    """Naechstes Vorkommen von day.month ab heute; Wochentag wählt das Jahr."""
    today = now.date()
    fallback: Optional[date] = None
    for year in (today.year, today.year + 1, today.year + 2):
        try:
            cand = date(year, month, day)
        except ValueError:
            continue
        if cand < today:
            continue
        if weekday is None or cand.weekday() == _WEEKDAYS.get(weekday, -1):
            return cand
        fallback = fallback or cand
        if year > today.year + 1:
            break
    # Wochentag passt in keinem der naechsten Jahre -> Tippfehler der Seite,
    # naechstes Vorkommen nehmen.
    return fallback


def _stueck_id(url: str) -> str:
    m = re.search(r"/stuecke/(\d+)", url or "")
    return m.group(1) if m else (url or "")


def _abs(url: str) -> str:
    return SITE + url if url.startswith("/") else url


def _make_canonical(url: str, start_at: datetime) -> str:
    return hashlib.md5(
        f"tar_{_stueck_id(url)}_{start_at.isoformat()}".encode()
    ).hexdigest()[:16]


def _venue_from_label(label: str) -> Tuple[str, str, Optional[float], Optional[float]]:
    """Spielort-Label der Monatsliste -> (venue, adresse, lat, lon)."""
    label = _clean(label)
    if not label or label.lower() in _HOME_LABELS:
        return VENUE_NAME, ADDRESS_TEXT, VENUE_LAT, VENUE_LON
    # Gastspiel/Projekt an anderem Ort: Name aus dem Text, keine festen Koordinaten
    # (der Geocoder der Pipeline loest ueber address_text auf).
    return label, f"{label}, {CITY}", None, None


def _kids(text: str, junges_theater: bool) -> str:
    if _KIDS_STRONG.search(text):
        return "yes" if junges_theater or re.search(r"kinder|j[äa]hrige", text, re.I) else "likely"
    if junges_theater or _KIDS_WEAK.search(text):
        return "likely"
    return "unknown"


def _event(
    *,
    title: str,
    url: str,
    start_at: datetime,
    end_at: Optional[datetime],
    description: Optional[str],
    venue: Tuple[str, str, Optional[float], Optional[float]],
    category: Optional[str],
    price: Optional[str],
    junges_theater: bool,
) -> Dict:
    venue_name, address, lat, lon = venue
    return {
        "canonical_id": _make_canonical(url, start_at),
        "title": title[:500],
        "short_description": (description or None) and description[:500],
        "start_at": start_at,
        "end_at": end_at,
        "venue_name": venue_name,
        "address_text": address,
        "city": CITY,
        "lat": lat,
        "lon": lon,
        "source_url": url[:500],
        "source_name": SOURCE_NAME,
        "indoor_outdoor": "indoor",
        "kids_suitable": _kids(f"{title} {description or ''}", junges_theater),
        "price_text": price,
        "category": category,
        "image_url": None,
    }


def _in_window(start_at: datetime, now: datetime) -> bool:
    start = datetime.combine(now.date(), time(0, 0))
    return start <= start_at < start + timedelta(days=MAX_DAYS_AHEAD)


def _parse_articles(soup, now: datetime, junges_theater: bool) -> List[Dict]:
    events: List[Dict] = []
    for art in soup.select("article.schedule__item"):
        link = art.select_one("h1.schedule__middle-title a[href]")
        date_el = art.select_one(".schedule__top-item--date span")
        if not link or not date_el:
            continue
        title = _clean(link.get_text(" ", strip=True))
        dm = _DATE_RE.search(_clean(date_el.get_text(" ", strip=True)))
        tm = _TIME_RE.search(_clean(date_el.get_text(" ", strip=True)))
        if not title or not dm:
            continue
        d = _resolve_date(dm.group(1), int(dm.group(2)), int(dm.group(3)), now)
        if d is None:
            continue
        start_at = datetime.combine(
            d, time(int(tm.group(1)), int(tm.group(2))) if tm else time(0, 0)
        )
        if not _in_window(start_at, now):
            continue

        label_el = art.select_one(".schedule__top-item--title span")
        tag_el = art.select_one(".schedule__middle-tag")
        sub_el = art.select_one(".schedule__middle-subtitle")
        subtitle = _clean(sub_el.get_text(" ", strip=True)) if sub_el else ""
        attr = [
            _clean(s.get_text())
            for s in art.select(".schedule__top-item--date .no-line-through")
        ]
        desc = " – ".join(p for p in [", ".join(a for a in attr if a), subtitle] if p)
        price_el = art.select_one(".schedule__bottom span.schedule__bottom-item")
        events.append(
            _event(
                title=title,
                url=_abs(link["href"]),
                start_at=start_at,
                end_at=None,
                description=desc or None,
                venue=_venue_from_label(label_el.get_text() if label_el else ""),
                category=_clean(tag_el.get_text()) if tag_el else None,
                price=_clean(price_el.get_text())[:100] if price_el else None,
                junges_theater=junges_theater,
            )
        )
    return events


def _parse_festival_grid(soup, now: datetime) -> List[Dict]:
    events: List[Dict] = []
    for block in soup.select("div.schedule2"):
        date_el = block.select_one(".schedule2__date--upper")
        if not date_el:
            continue
        dm = _DATE_RE.search(_clean(date_el.get_text()))
        if not dm:
            continue
        d = _resolve_date(dm.group(1), int(dm.group(2)), int(dm.group(3)), now)
        if d is None:
            continue
        for item in block.select("div.schedule2-item"):
            link = item.select_one("h1.schedule2-item__middle-title a[href]")
            if not link:
                continue
            title = _clean(link.get_text(" ", strip=True))
            times = _TIME_RE.findall(
                _clean(
                    (item.select_one(".schedule2-item__top-date") or item).get_text()
                )
            )
            if not title or not times:
                continue
            start_at = datetime.combine(d, time(int(times[0][0]), int(times[0][1])))
            end_at = None
            if len(times) > 1:
                end_at = datetime.combine(d, time(int(times[1][0]), int(times[1][1])))
                if end_at <= start_at:
                    end_at = None
            if not _in_window(start_at, now):
                continue
            label_el = item.select_one(".schedule2-item__top-label")
            if label_el and _clean(label_el.get_text()).lower() in _SKIP_LABELS:
                continue
            attr_el = item.select_one(".schedule2-item__middle-attributes")
            sub_el = item.select_one(".schedule2-item__middle-subtitle")
            subtitle = _clean(sub_el.get_text(" ", strip=True)) if sub_el else ""
            attr = _clean(attr_el.get_text()) if attr_el else ""
            desc = " – ".join(p for p in [attr, subtitle] if p)
            events.append(
                _event(
                    title=title,
                    url=_abs(link["href"]),
                    start_at=start_at,
                    end_at=end_at,
                    description=desc or None,
                    venue=_venue_from_label(""),
                    category=_clean(label_el.get_text()) if label_el else None,
                    price=None,
                    junges_theater=False,
                )
            )
    return events


def parse_spielplan_html(
    html: str, now: Optional[datetime] = None, junges_theater: bool = False
) -> List[Dict]:
    """Eine Spielplan-Seite (Monatsliste + Festival-Raster) -> Event-Dicts.

    `now` (naive Berliner Zeit) ist fuer Tests injizierbar; Fenster heute..+120 d.
    """
    now = now or _berlin_now()
    soup = BeautifulSoup(html, "lxml")
    raw = _parse_articles(soup, now, junges_theater) + _parse_festival_grid(soup, now)
    events: List[Dict] = []
    seen: set = set()
    for ev in raw:
        if ev["canonical_id"] in seen:
            continue
        seen.add(ev["canonical_id"])
        events.append(ev)
    return events


def parse_detail_html(html: str) -> Dict:
    """Detailseite -> {description, image_url, venue_name, address_text}."""
    soup = BeautifulSoup(html, "lxml")
    out: Dict = {}
    meta = soup.find("meta", attrs={"name": "Description"}) or soup.find(
        "meta", attrs={"property": "og:description"}
    )
    if meta and meta.get("content"):
        out["description"] = _clean(meta["content"])[:500]
    img = soup.find("meta", attrs={"property": "og:image"})
    if img and img.get("content"):
        out["image_url"] = _abs(img["content"])[:500]
    for h4 in soup.find_all("h4"):
        if _clean(h4.get_text()).lower() == "ort":
            p = h4.find_next("p")
            if p:
                lines = [_clean(x) for x in p.get_text("\n").split("\n") if _clean(x)]
                if lines:
                    out["venue_name"] = lines[0]
                    out["address_text"] = ", ".join(lines[1:]) or None
            break
    return out


def _apply_detail(ev: Dict, detail: Dict) -> None:
    if detail.get("description"):
        ev["short_description"] = detail["description"]
    if detail.get("image_url"):
        ev["image_url"] = detail["image_url"]
    addr = detail.get("address_text") or ""
    venue = detail.get("venue_name")
    # Ort-Block nur uebernehmen, wenn er einen anderen Spielort als das Haus nennt.
    if venue and addr and "Akazienallee" not in addr:
        ev["venue_name"] = venue[:200]
        ev["address_text"] = addr
        ev["lat"] = None
        ev["lon"] = None


async def fetch_theater_an_der_ruhr_events() -> List[Dict]:
    """Fetch Theater-an-der-Ruhr events (3 Listen + begrenzte Detailseiten; never raises)."""
    events: List[Dict] = []
    try:
        async with httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, headers=_HEADERS
        ) as client:
            for idx, (param, junges) in enumerate(TABS):
                if idx:
                    await asyncio.sleep(REQUEST_PAUSE_S)
                url = SITE + LIST_PATH + (f"?s={param}" if param else "")
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    events.extend(parse_spielplan_html(resp.text, junges_theater=junges))
                except Exception as exc:
                    logger.error(f"Theater an der Ruhr list {url} failed: {exc}")

            # Dasselbe Stueck steht oft in mehreren Reitern: nach ID entdoppeln.
            unique: Dict[str, Dict] = {}
            for ev in events:
                unique.setdefault(ev["canonical_id"], ev)
            events = list(unique.values())

            # Detailseiten: je Stueck einmal, frueheste Termine zuerst, begrenzt.
            by_url: Dict[str, List[Dict]] = {}
            for ev in sorted(events, key=lambda e: e["start_at"]):
                by_url.setdefault(ev["source_url"], []).append(ev)
            for url in list(by_url)[:MAX_DETAIL_FETCHES]:
                await asyncio.sleep(REQUEST_PAUSE_S)
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    detail = parse_detail_html(resp.text)
                except Exception as exc:
                    logger.debug(f"Theater an der Ruhr detail {url} failed: {exc}")
                    continue
                for ev in by_url[url]:
                    _apply_detail(ev, detail)
    except Exception as exc:
        logger.error(f"Theater an der Ruhr fetch failed: {exc}")
    logger.info(f"Theater an der Ruhr: {len(events)} events")
    return events


async def sync_theater_an_der_ruhr(db: Session) -> dict:
    """Sync Theater-an-der-Ruhr events to database."""
    events_data = await fetch_theater_an_der_ruhr_events()
    return sync_events_to_db(db, events_data, SOURCE_NAME)
