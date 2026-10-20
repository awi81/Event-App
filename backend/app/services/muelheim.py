"""Stadt Mülheim an der Ruhr — Veranstaltungskalender (Listenseiten + wenige Detailseiten).

Quelle: https://www1.muelheim-ruhr.de/veranstaltungen (Drupal 7 "culturebase",
Views-Liste, 20 Zeilen je Seite, Paginierung ?page=1, ?page=2 ...).

robots.txt: "User-agent: * / Crawl-delay: 10"; gesperrt sind nur Drupal-interne
Pfade (/?q=admin/, /?q=search/ ...), /veranstaltungen und seine Query-Parameter
(page, kategorie) sind erlaubt. Der Crawl-delay von 10 s gilt hier zwischen
ALLEN Requests (asyncio.sleep(CRAWL_DELAY)).

Format der Liste (Zeile = ein Termin = eine Detail-URL
/veranstaltungen/<slug>_am_<TT.MM.JJJJ>/<id>):
  - .views-field-field-cbi-period span[content]  ISO-Datum+Uhrzeit (Berliner
    Ortszeit, "+02:00"); Uhrzeit 0:00 = ganztägig/ohne Uhrzeit
  - .views-field-title a                         Titel + Detail-Link
  - .views-field-field-cbi-text-value(-1)        Teaser (~200 Zeichen)
  - .views-field-field-cbi-flag-status           "findet statt" / "abgesagt"
  - img                                          Vorschaubild (350 px)
Die Liste kennt KEINE Spielstätte. Die steckt nur im JSON-LD "Event" der
Detailseite (location.name, streetAddress, postalCode; geo ist meist leer oder
auf zwei Nachkommastellen gerundet und wird nur bei >= 3 Nachkommastellen
übernommen; endDate ist unzuverlässig, teils Datum der Eintragung).

Warum Kategorie-Abfragen: Die ungefilterte Liste ist chronologisch und von
Dauerausstellungen verstopft (~25 Zeilen je Tag, nur Wiederholungen). Der
Filter ?kategorie=<id> liefert dagegen pro Rubrik oft schon die gesamten
kommenden Monate in 1-2 Seiten. Rubrik-Label = Roh-Kategorie der Quelle.

Request-Budget je Lauf (Crawl-delay 10 s => Laufzeit ~ MAX_TOTAL_REQUESTS * 10 s):
  - Listenseiten: erst Seite 1 jeder Rubrik (13), dann Folgeseiten, max. 16
  - Detailseiten: eine je Serie (gleicher Slug ohne Datum), Serien mit den
    meisten Terminen zuerst, max. 10; Spielstätte wird auf alle Termine der
    Serie übertragen. Termine ohne Detailseite haben venue_name None, die
    Pipeline geokodiert nur, was sie hat.
  - Spielstätten-Cache (VENUE_CACHE_FILE, vom Snapshot-Export gesetzt, liegt
    neben events.json): bereits bekannte Serien bekommen ihre Spielstätte aus
    dem Cache, das Detail-Budget geht nur an neue Serien. So wächst die
    Abdeckung von Lauf zu Lauf, ohne mehr Requests. Einträge verfallen nach
    VENUE_CACHE_TTL_DAYS.
  - Gesamt <= 26 Requests (~6 Minuten inkl. Antwortzeit; 32 Requests brauchten live 7,3 Minuten).
Ausstellungen (Rubrik "Ausstellung") erscheinen täglich als eigene Zeile und
werden je Serie zu EINER Zeile mit end_at zusammengefasst.
"""
import asyncio
import hashlib
import html as html_lib
import json
import logging
import re
from collections import deque
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.services.base_sync import sync_events_to_db
from app.services.crawler_ua import CRAWLER_USER_AGENT

logger = logging.getLogger(__name__)

BASE_URL = "https://www1.muelheim-ruhr.de"
LIST_URL = BASE_URL + "/veranstaltungen"

SOURCE_NAME = "Stadt Mülheim"
DEFAULT_CITY = "Mülheim an der Ruhr"

MAX_DAYS_AHEAD = 120
CRAWL_DELAY = 10  # Sekunden, robots.txt "Crawl-delay: 10"
MAX_LIST_REQUESTS = 16
MAX_DETAIL_REQUESTS = 10
MAX_TOTAL_REQUESTS = 26

# Serie -> Spielstätte, über Läufe hinweg (Actions-DB ist jedes Mal frisch).
# None = kein Cache (Tests, lokaler Sync); export_snapshot setzt den Pfad.
VENUE_CACHE_FILE: Optional[Path] = None
VENUE_CACHE_TTL_DAYS = 180
_CACHED_FIELDS = ("venue_name", "address_text", "postal", "lat", "lon", "image_url")

_BERLIN = ZoneInfo("Europe/Berlin")
_HEADERS = {"User-Agent": CRAWLER_USER_AGENT}

# Rubriken des Kalenders (Filter ?kategorie=<id>), Reihenfolge = Priorität
# beim Roh-Label, falls ein Termin in mehreren Rubriken steht.
CATEGORIES: List[Tuple[int, str]] = [
    (7055, "Kinder / Familie"),
    (7059, "Theater"),
    (7056, "Comedy / Kabarett"),
    (7058, "Musik"),
    (7053, "Film"),
    (7057, "Literatur"),
    (7050, "Tanz"),
    (7052, "Fest"),
    (7051, "Kunst / Kreatives"),
    (7054, "Gesellschaft"),
    (7049, "Sport / Bewegung"),
    (7048, "und sonst (Verschiedenes)"),
    (7060, "Ausstellung"),
]
_CAT_LABEL = dict(CATEGORIES)
_CAT_RANK = {label: i for i, (_, label) in enumerate(CATEGORIES)}
KIDS_CATEGORY = "Kinder / Familie"
EXHIBITION_CATEGORY = "Ausstellung"

_MONTH_MAP = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5,
    "juni": 6, "juli": 7, "august": 8, "september": 9, "oktober": 10,
    "november": 11, "dezember": 12,
}

_ISO_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})")
_SLUG_DATE_RE = re.compile(r"_am_\d{2}\.\d{2}\.\d{4}$")
_END_RE = re.compile(
    r"\bbis\s+(?:zum\s+)?(\d{1,2})\.\s*([A-Za-zäÄ]+)\s*(\d{4})?", re.I
)
_PRICE_RE = re.compile(
    r"Eintritt\s*frei|Eintritt\s*:?\s*(?:ab\s*)?\d{1,3}(?:[.,]\d{2})?\s*(?:€|Euro)"
    r"|\d{1,3}(?:[.,]\d{2})?\s*(?:€|Euro)",
    re.I,
)
_KIDS_RE = re.compile(
    r"kinder|familie|kids|ab\s*(?:[3-9]|1[0-2])\s*Jahr|schulkinder|für\s+kleine",
    re.I,
)
_OUTDOOR_RE = re.compile(
    r"open[- ]?air|draußen|draussen|wanderung|spaziergang|stadtrundgang|radtour",
    re.I,
)


def _berlin_now() -> datetime:
    return datetime.now(_BERLIN).replace(tzinfo=None)


def _parse_iso(value: str) -> Optional[datetime]:
    """'2026-10-21T19:30:00+02:00' -> naive Berliner Zeit (Offset ignoriert)."""
    m = _ISO_RE.search(value or "")
    if not m:
        return None
    try:
        return datetime(*(int(g) for g in m.groups()))
    except ValueError:
        return None


def _event_id(href: str) -> str:
    """Letztes Pfadsegment der Detail-URL (numerische Termin-ID)."""
    return href.rstrip("/").rsplit("/", 1)[-1]


def _series_key(href: str) -> str:
    """Slug ohne '_am_TT.MM.JJJJ' und ohne ID: gleiche Serie, anderer Tag."""
    path = href.split("?")[0].rstrip("/")
    slug = path.rsplit("/", 1)[0] if re.search(r"/\d+$", path) else path
    return _SLUG_DATE_RE.sub("", slug)


def _clean_teaser(text: str) -> str:
    text = re.sub(r"\s*mehr\s*$", "", text.strip())
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_end_date(text: str, start: date) -> Optional[date]:
    """'... bis 29. März 2027' / 'bis 31. Dezember 2026' -> date (>= start)."""
    for m in _END_RE.finditer(text or ""):
        month = _MONTH_MAP.get(m.group(2).lower())
        if not month:
            continue
        day = int(m.group(1))
        years = [int(m.group(3))] if m.group(3) else [start.year, start.year + 1]
        for year in years:
            try:
                d = date(year, month, day)
            except ValueError:
                continue
            if d >= start:
                return d
    return None


def _extract_price(text: str) -> Optional[str]:
    m = _PRICE_RE.search(text or "")
    return m.group(0).strip()[:100] if m else None


def _make_canonical(event_id: str, start_at: datetime) -> str:
    return hashlib.md5(
        f"muelheim_{event_id}_{start_at.isoformat()}".encode()
    ).hexdigest()[:16]


def _parse_rows(html: str, category: str) -> List[Dict]:
    """Listenseite -> Roh-Zeilen (ein Dict je Termin), ohne Fensterfilter."""
    soup = BeautifulSoup(html, "lxml")
    rows: List[Dict] = []
    # div.views-row.col-sm-4 = Hauptliste; das Slideshow-Block-Teaser-Karussell
    # (gleiche Klassen ohne col-sm-4) wiederholt sich auf jeder Seite und fehlt hier.
    for row in soup.select("div.views-row.col-sm-4"):
        link = row.select_one(".views-field-title a[href]")
        stamp = row.select_one(".views-field-field-cbi-period span[content]")
        if not link or not stamp:
            continue
        start = _parse_iso(stamp.get("content", ""))
        title = re.sub(r"\s+", " ", link.get_text(" ", strip=True)).strip()
        if not start or not title:
            continue
        status = row.select_one(".views-field-field-cbi-flag-status")
        status_text = status.get_text(" ", strip=True).lower() if status else ""
        if any(w in status_text for w in ("abgesagt", "verschoben", "entfällt")):
            continue
        teaser_el = row.select_one(
            ".views-field-field-cbi-text-value-1, .views-field-field-cbi-text-value"
        )
        teaser = _clean_teaser(teaser_el.get_text(" ", strip=True)) if teaser_el else ""
        img = row.select_one("img[src]")
        href = link["href"]
        rows.append(
            {
                "href": href,
                "url": urljoin(BASE_URL, href),
                "id": _event_id(href),
                "series": _series_key(href),
                "title": title,
                "start": start,
                "teaser": teaser,
                "image": img["src"] if img else None,
                "category": category,
            }
        )
    return rows


def _next_page_url(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "lxml")
    a = soup.select_one("li.pager__item a[href]")
    return urljoin(BASE_URL, a["href"]) if a else None


def _parse_detail(html: str) -> Optional[Dict]:
    """JSON-LD 'Event' der Detailseite -> Spielstätte, Adresse, Geo, Bild, Ende."""
    for m in re.finditer(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S
    ):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        nodes = data.get("@graph", [data]) if isinstance(data, dict) else data
        for node in nodes:
            if not isinstance(node, dict) or node.get("@type") != "Event":
                continue
            place = node.get("location") or {}
            addr = place.get("address") or {}
            street = (addr.get("streetAddress") or "").strip()
            postal = (addr.get("postalCode") or "").strip()
            name = html_lib.unescape((place.get("name") or "").strip())
            address_text = ", ".join(
                p for p in (street, f"{postal} {DEFAULT_CITY}".strip() if postal else "") if p
            ) or None
            geo = place.get("geo") or {}
            lat = lon = None
            try:
                lat_s, lon_s = str(geo.get("latitude", "")), str(geo.get("longitude", ""))
                # Nur genaue Koordinaten (>= 3 Nachkommastellen); "51.43" ist Stadtmitte.
                if (
                    lat_s and lon_s
                    and len(lat_s.split(".")[-1]) >= 3
                    and len(lon_s.split(".")[-1]) >= 3
                ):
                    lat, lon = float(lat_s), float(lon_s)
            except ValueError:
                lat = lon = None
            image = node.get("image")
            image_url = image.get("url") if isinstance(image, dict) else image
            return {
                "venue_name": name[:255] or None,
                "address_text": address_text,
                "postal": postal or None,
                "lat": lat,
                "lon": lon,
                "image_url": image_url if isinstance(image_url, str) else None,
                "start": _parse_iso(node.get("startDate", "")),
                "end": _parse_iso(node.get("endDate", "")),
            }
    return None


def _city_for(postal: Optional[str]) -> Optional[str]:
    """Mülheim hat PLZ 454xx; andere PLZ -> Stadt unbekannt (Pipeline klärt)."""
    if not postal or postal.startswith("454"):
        return DEFAULT_CITY
    return None


def _merge_categories(rows: List[Dict]) -> List[Dict]:
    """Gleiche Termin-ID aus mehreren Rubriken -> eine Zeile, Rubriken gesammelt."""
    merged: Dict[Tuple[str, datetime], Dict] = {}
    for r in rows:
        key = (r["id"], r["start"])
        if key not in merged:
            merged[key] = {**r, "categories": {r["category"]}}
        else:
            merged[key]["categories"].add(r["category"])
    for r in merged.values():
        if EXHIBITION_CATEGORY in r["categories"]:
            # Dauerausstellung bleibt Ausstellung, auch wenn sie zusätzlich als
            # "Kunst" gelistet ist — sonst gäbe es wieder Tageszeilen.
            r["category"] = EXHIBITION_CATEGORY
        else:
            r["category"] = min(r["categories"], key=lambda c: _CAT_RANK.get(c, 99))
    return list(merged.values())


def build_events(
    rows: List[Dict],
    details: Optional[Dict[str, Dict]] = None,
    now: Optional[datetime] = None,
) -> List[Dict]:
    """Roh-Zeilen (+ Detail-Daten je Serie) -> Event-Dicts.

    `details` bildet Serien-Slug -> _parse_detail()-Ergebnis ab. `now` (naive
    Berliner Zeit) ist für Tests injizierbar. Fenster: heute 00:00 .. +120 Tage.
    """
    now = now or _berlin_now()
    details = details or {}
    window_start = datetime.combine(now.date(), time(0, 0))
    window_end = window_start + timedelta(days=MAX_DAYS_AHEAD)

    rows = _merge_categories(rows)
    rows = [r for r in rows if window_start <= r["start"] < window_end]
    rows.sort(key=lambda r: (r["start"], r["title"]))

    # Ausstellungen: je Serie eine Zeile (start = erster Tag im Fenster).
    exhibitions: Dict[str, Dict] = {}
    singles: List[Dict] = []
    for r in rows:
        if r["category"] == EXHIBITION_CATEGORY:
            first = exhibitions.get(r["series"])
            if first is None:
                exhibitions[r["series"]] = {**r, "last": r["start"]}
            else:
                first["last"] = max(first["last"], r["start"])
        else:
            singles.append(r)

    events: List[Dict] = []
    seen_ids: set = set()
    entries = [(r, None) for r in singles]
    for r in exhibitions.values():
        end_day = _parse_end_date(r["teaser"], r["start"].date())
        last_day = r["last"].date()
        end_day = max(end_day, last_day) if end_day else last_day
        end_at = (
            datetime.combine(end_day, time(23, 59)) if end_day > r["start"].date() else None
        )
        entries.append((r, end_at))

    for r, end_at in entries:
        d = details.get(r["series"]) or {}
        start_at = r["start"]
        if end_at is None and d.get("end") and r["category"] != EXHIBITION_CATEGORY:
            # endDate nur, wenn plausibel (gleicher Tag, danach, <= 12 h) — sonst Rauschen.
            same_day = d["end"].date() == start_at.date()
            if same_day and start_at < d["end"] <= start_at + timedelta(hours=12) \
                    and d.get("start") == start_at:
                end_at = d["end"]
        canonical = _make_canonical(r["id"], start_at)
        if canonical in seen_ids:
            continue
        seen_ids.add(canonical)

        teaser = r["teaser"]
        if r["category"] == EXHIBITION_CATEGORY:
            teaser = re.sub(
                r"^\s*(?:\d{1,2}\.\s*[A-Za-zäÄ]+\s*(?:\d{4})?\s*)?bis\s+\d{1,2}\.\s*"
                r"[A-Za-zäÄ]+\s*\d{4}\s*",
                "",
                teaser,
            )
        teaser = teaser.rstrip(" .…").strip()
        text = f"{r['title']} {teaser}"
        if KIDS_CATEGORY in r["categories"]:
            kids = "yes"
        elif _KIDS_RE.search(text):
            kids = "likely"
        else:
            kids = "unknown"

        image = d.get("image_url") or r["image"]
        events.append(
            {
                "canonical_id": canonical,
                "title": r["title"][:500],
                "short_description": teaser[:500] or None,
                "start_at": start_at,
                "end_at": end_at,
                "venue_name": d.get("venue_name"),
                "address_text": d.get("address_text"),
                "city": _city_for(d.get("postal")),
                "lat": d.get("lat"),
                "lon": d.get("lon"),
                "source_url": r["url"][:500],
                "source_name": SOURCE_NAME,
                "indoor_outdoor": "outdoor" if _OUTDOOR_RE.search(text) else "unknown",
                "kids_suitable": kids,
                "price_text": _extract_price(teaser),
                "category": r["category"],
                "image_url": image[:500] if image else None,
            }
        )

    events.sort(key=lambda e: e["start_at"])
    logger.info(f"Mülheim: {len(events)} events from {len(rows)} list rows")
    return events


def parse_muelheim_html(
    html: str, category: str = "", now: Optional[datetime] = None
) -> List[Dict]:
    """Eine Listenseite -> Event-Dicts (ohne Spielstätte; die steckt im Detail)."""
    return build_events(_parse_rows(html, category), None, now)


def load_venue_cache(path: Optional[Path], now: datetime) -> Dict[str, Dict]:
    """Spielstätten-Cache lesen; abgelaufene oder kaputte Einträge fallen weg."""
    if path is None or not path.exists():
        return {}
    try:
        entries = json.loads(path.read_text(encoding="utf-8")).get("entries", {})
    except (OSError, ValueError) as exc:
        logger.warning(f"Mülheim: Spielstätten-Cache unlesbar ({exc})")
        return {}
    oldest = (now - timedelta(days=VENUE_CACHE_TTL_DAYS)).date().isoformat()
    return {
        series: e for series, e in entries.items()
        if isinstance(e, dict) and e.get("venue_name") and e.get("fetched", "") >= oldest
    }


def save_venue_cache(path: Optional[Path], cache: Dict[str, Dict]) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"entries": dict(sorted(cache.items()))}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning(f"Mülheim: Spielstätten-Cache nicht geschrieben ({exc})")


def _pick_detail_targets(
    rows: List[Dict], limit: int, now: datetime, known: frozenset = frozenset()
) -> List[Dict]:
    """Je Serie eine Detailseite: Serien mit den meisten Terminen zuerst.

    Serien aus `known` (schon im Spielstätten-Cache) werden übersprungen.
    """
    window_start = datetime.combine(now.date(), time(0, 0))
    window_end = window_start + timedelta(days=MAX_DAYS_AHEAD)
    by_series: Dict[str, List[Dict]] = {}
    for r in rows:
        if r["series"] in known:
            continue
        if window_start <= r["start"] < window_end:
            by_series.setdefault(r["series"], []).append(r)
    ranked = sorted(
        by_series.values(),
        key=lambda rs: (-len(rs), min(x["start"] for x in rs)),
    )
    return [min(rs, key=lambda x: x["start"]) for rs in ranked[:limit]]


async def fetch_muelheim_events() -> List[Dict]:
    """Fetch Mülheim events (Listen je Rubrik + wenige Details); never raises."""
    now = _berlin_now()
    window_end = datetime.combine(now.date(), time(0, 0)) + timedelta(days=MAX_DAYS_AHEAD)
    requests_made = 0
    blocked = False
    rows: List[Dict] = []
    cache = load_venue_cache(VENUE_CACHE_FILE, now)
    # Aus dem Cache nur Ort und Bild; start/end gehören zum damals geholten Termin.
    details: Dict[str, Dict] = {s: dict(e) for s, e in cache.items()}
    fresh = 0

    async def get(client: httpx.AsyncClient, url: str) -> Optional[str]:
        """GET mit Crawl-delay vor jedem Request außer dem ersten."""
        nonlocal requests_made, blocked
        if blocked or requests_made >= MAX_TOTAL_REQUESTS:
            return None
        if requests_made:
            await asyncio.sleep(CRAWL_DELAY)
        requests_made += 1
        try:
            resp = await client.get(url)
        except Exception as exc:
            logger.error(f"Mülheim fetch failed ({url}): {exc}")
            return None
        if resp.status_code in (403, 429):
            logger.error(f"Mülheim: HTTP {resp.status_code} — Abbruch, keine Umgehung")
            blocked = True
            return None
        if resp.status_code != 200:
            logger.warning(f"Mülheim: HTTP {resp.status_code} für {url}")
            return None
        return resp.text

    try:
        async with httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, headers=_HEADERS
        ) as client:
            queue = deque((label, f"{LIST_URL}?kategorie={cid}") for cid, label in CATEGORIES)
            list_requests = 0
            while queue and list_requests < MAX_LIST_REQUESTS:
                label, url = queue.popleft()
                text = await get(client, url)
                list_requests += 1
                if text is None:
                    if blocked:
                        break
                    continue
                page_rows = _parse_rows(text, label)
                rows.extend(page_rows)
                nxt = _next_page_url(text)
                covered = page_rows and max(r["start"] for r in page_rows) >= window_end
                if nxt and page_rows and not covered:
                    queue.append((label, nxt))

            budget = min(MAX_DETAIL_REQUESTS, MAX_TOTAL_REQUESTS - requests_made)
            targets = _pick_detail_targets(rows, max(budget, 0), now, frozenset(cache))
            for target in targets:
                text = await get(client, target["url"])
                if text is None:
                    if blocked:
                        break
                    continue
                parsed = _parse_detail(text)
                if parsed and parsed.get("venue_name"):
                    details[target["series"]] = parsed
                    cache[target["series"]] = {
                        **{k: parsed.get(k) for k in _CACHED_FIELDS},
                        "fetched": now.date().isoformat(),
                    }
                    fresh += 1
    except Exception as exc:
        logger.error(f"Mülheim fetch failed: {exc}")

    save_venue_cache(VENUE_CACHE_FILE, cache)
    logger.info(
        f"Mülheim: {requests_made} requests, {fresh} neue Detailseiten, "
        f"{len(cache)} Serien im Spielstätten-Cache"
    )
    try:
        return build_events(rows, details, now)
    except Exception as exc:
        logger.error(f"Mülheim parse failed: {exc}")
        return []


async def sync_muelheim(db: Session) -> dict:
    """Sync Stadt-Mülheim events to database."""
    events_data = await fetch_muelheim_events()
    return sync_events_to_db(db, events_data, SOURCE_NAME)
