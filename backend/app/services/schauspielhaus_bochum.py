"""Schauspielhaus Bochum event source — HTML scraping der Spielplan-Genreseiten.

Quelle: https://www.schauspielhausbochum.de/de/spielplan/<id>/<slug>
(Spielplan nach Genres; /de/spielplan allein liefert 404).

Format: Server-gerendertes HTML. Pro Tag ein ``ul.schedule__group`` mit
``data-groupdate="2026-11-21"`` (ISO-Datum, kein Jahr-Raten noetig), darin je
Vorstellung ein ``div.schedule__item`` mit:
  - div.schedule__stage        Spielstaette ("Schauspielhaus", "Kammerspiele",
                               "Theaterrevier", "Oval Office", "Foyer Schauspielhaus");
                               bei Festivaltagen steht dahinter ein Link zum Festival
  - div.schedule__attributes   Zusatz wie "Premiere", "Wieder da", "Gastspiel", "Lesung"
  - div.schedule__title a      Titel (Link auf /de/stuecke/<id>/<slug>)
  - div.schedule__subtitle1/2  Untertitel ("nach Otfried Preussler")
  - div.schedule__times        "16:00 — 17:10" (Start/Ende, Ende ggf. nach Mitternacht)
  - div.schedule__info         Altersangabe ("🐬 6+", "👽 13+"), Hinweise, "Buchung: ..."
Eintraege ohne Stage/Uhrzeit (Premieren-Hinweise ohne Termin) und reine
Schul-/Kitavorstellungen (Buchung nur per Mail an die Gruppenbetreuung) werden
verworfen. Das Fenster ist ~8 Monate, wir schneiden auf heute..+120 Tage.

Dubletten: dieselbe Vorstellung steht auf mehreren Genreseiten. Die Genreseiten
werden in Prioritaetsreihenfolge geholt (siehe GENRE_PAGES), die erste
Fundstelle liefert die Roh-Kategorie, Familienstueck/Junges Theater setzen
kids_suitable. Dedup ueber canonical_id (Stueck-ID + Start + Spielstaette).

Requests pro Lauf: 13 (eine je Genreseite), Pause 1,5 s dazwischen. Keine
Detailseiten, keine Bilder (die Liste hat keine).
robots.txt: "User-agent: * / Allow: /" (geprueft 2026-10-21).

Koordinaten: Nominatim "Schauspielhaus Bochum, 15, Koenigsallee" 51.4722432,
7.2174542 (geprueft 2026-10-21, 44789 Bochum). Alle Buehnen (Kammerspiele, Theaterrevier,
Oval Office, Foyer) liegen im selben Haus/Gebaeudekomplex bzw. werden mit
derselben Koordinate gefuehrt.
"""
import asyncio
import hashlib
import logging
import re
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup, NavigableString
from sqlalchemy.orm import Session

from app.services.base_sync import sync_events_to_db
from app.services.crawler_ua import CRAWLER_USER_AGENT

logger = logging.getLogger(__name__)

BASE_URL = "https://www.schauspielhausbochum.de"
SOURCE_NAME = "Schauspielhaus Bochum"
ADDRESS_TEXT = "Königsallee 15, 44789 Bochum"

# Wikipedia/Wikidata (siehe Modul-Docstring) — nicht per OSM verifiziert.
VENUE_LAT = 51.4722432
VENUE_LON = 7.2174542

MAX_DAYS_AHEAD = 120
REQUEST_PAUSE_SECONDS = 1.5

# (id, slug, Roh-Kategorie). Reihenfolge = Prioritaet fuer die Kategorie bei
# Dubletten: breite Genres (Musik, Gastspiel) zuletzt, damit z.B. eine
# Schauspiel-Produktion mit Musik nicht als "Musik" endet.
# Geprueft 2026-10-21; nicht aufgenommen: Vortrag, Figurentheater, Stadtraum
# (nicht abgerufen), Premiere/Wieder da/... (Attribut-Filter, keine Genres).
GENRE_PAGES = [
    (166, "familienstueck", "Familienstück"),
    (266, "junges-theater", "Junges Theater"),
    (13, "schauspiel", "Schauspiel"),
    (168, "lesung", "Lesung"),
    (16199, "stand-up-comedy", "Stand-up Comedy"),
    (14142, "kabarett", "Kabarett"),
    (11, "tanz", "Tanz"),
    (268, "performance", "Performance"),
    (267, "talk", "Talk"),
    (7040, "film", "Film"),
    (21, "musik", "Musik"),
    (257, "gastspiel", "Gastspiel"),
    (14141, "party", "Party"),
]
_KIDS_GENRES = {"Familienstück", "Junges Theater"}

_BERLIN = ZoneInfo("Europe/Berlin")
_HEADERS = {"User-Agent": CRAWLER_USER_AGENT}

_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})(?:\D+?(\d{1,2}):(\d{2}))?")
_AGE_RE = re.compile(r"(\d{1,2})\s*\+")
# Nicht oeffentliche Gruppenvorstellungen (Buchung nur per Mail).
_GROUP_ONLY_RE = re.compile(r"schul|kita", re.I)
# Keine Beschreibung: Buchungs-/Kartenstatus.
_NOISE_INFO_RE = re.compile(r"buchung:|restkarten|wenige karten|2-für-1|kartenkontingent", re.I)


def _berlin_now() -> datetime:
    return datetime.now(_BERLIN).replace(tzinfo=None)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace(" ", " ")).strip()


def _own_text(el) -> str:
    """Nur die direkten Textknoten (ohne verlinkte Festival-Titel)."""
    parts = [str(c) for c in el.children if isinstance(c, NavigableString)]
    return _clean(" ".join(parts))


def _parse_times(text: str, day: date) -> Optional[tuple]:
    """'19:30 — 21:10' -> (start, end|None); Ende vor Start = naechster Tag."""
    m = _TIME_RE.search(text or "")
    if not m:
        return None
    try:
        start = datetime.combine(day, time(int(m.group(1)), int(m.group(2))))
        end = None
        if m.group(3):
            end = datetime.combine(day, time(int(m.group(3)), int(m.group(4))))
            if end <= start:
                end += timedelta(days=1)
    except ValueError:
        return None
    return start, end


def _venue_name(stage: str) -> str:
    if stage == "Schauspielhaus":
        return "Schauspielhaus Bochum"
    if "Schauspielhaus" in stage:
        return f"{stage} Bochum"  # "Foyer Schauspielhaus Bochum"
    return f"{stage} (Schauspielhaus Bochum)"


def _make_canonical(piece_id: str, start_at: datetime, stage: str) -> str:
    return hashlib.md5(
        f"schauspielhaus_bochum_{piece_id}_{start_at.isoformat()}_{stage}".encode()
    ).hexdigest()[:16]


def _detect_kids(genre: Optional[str], age: Optional[int], infos: str) -> str:
    """Familienstueck/Junges Theater -> yes (ab 13+ nur likely, es sind Jugendstuecke)."""
    if genre in _KIDS_GENRES:
        return "likely" if (age is not None and age >= 13) else "yes"
    if age is not None and age <= 12:
        return "yes"
    if "familie" in infos.lower():
        return "likely"
    return "unknown"


def _parse_item(item, day: date, genre: Optional[str]) -> Optional[Dict]:
    stage_el = item.select_one(".schedule__stage")
    title_el = item.select_one(".schedule__title")
    times_el = item.select_one(".schedule__times")
    if not (stage_el and title_el and times_el):
        return None  # Premieren-Hinweis ohne Termin
    stage = _own_text(stage_el)
    title = _clean(title_el.get_text(" ", strip=True))
    times = _parse_times(times_el.get_text(" ", strip=True), day)
    if not (stage and title and times):
        return None
    start_at, end_at = times

    attr_el = item.select_one(".schedule__attributes")
    attributes = _clean(attr_el.get_text(" ", strip=True)) if attr_el else ""
    if _GROUP_ONLY_RE.search(attributes):
        return None

    link = title_el.find("a", href=True)
    href = (link["href"] if link else item.get("data-href")) or ""
    url = BASE_URL + href if href.startswith("/") else (href or BASE_URL)
    piece_id = item.get("data-id") or href

    infos = [
        _clean(i.get_text(" ", strip=True)) for i in item.select(".schedule__info")
    ]
    infos = [i for i in infos if i and not _NOISE_INFO_RE.search(i)]
    age_m = next((_AGE_RE.search(i) for i in infos if _AGE_RE.search(i)), None)
    age = int(age_m.group(1)) if age_m else None

    festival_el = stage_el.find("a")
    festival = _clean(festival_el.get_text(" ", strip=True)) if festival_el else ""

    sub_el = item.select_one(".schedule__subtitle1, .schedule__subtitle2")
    subtitle = _clean(sub_el.get_text(" ", strip=True)) if sub_el else ""
    desc_parts = [subtitle]
    if attributes:
        desc_parts.append(attributes)
    if festival:
        desc_parts.append(f"Festival: {festival}")
    desc_parts.extend(
        i for i in infos if not _AGE_RE.fullmatch(re.sub(r"^\W+", "", i))
    )
    if age is not None:
        desc_parts.append(f"Ab {age} Jahren")
    description = ". ".join(p.rstrip(". ") for p in desc_parts if p)[:500] or None

    return {
        "canonical_id": _make_canonical(str(piece_id), start_at, stage),
        "title": title[:500],
        "short_description": description,
        "start_at": start_at,
        "end_at": end_at,
        "venue_name": _venue_name(stage),
        "address_text": ADDRESS_TEXT,
        "city": "Bochum",
        "lat": VENUE_LAT,
        "lon": VENUE_LON,
        "source_url": url[:500],
        "source_name": SOURCE_NAME,
        "indoor_outdoor": "indoor",
        "kids_suitable": _detect_kids(genre, age, " ".join(infos)),
        "price_text": None,
        "category": genre,
        "image_url": None,
    }


def parse_schauspielhaus_bochum_html(
    html: str, now: Optional[datetime] = None, genre: Optional[str] = None
) -> List[Dict]:
    """Eine Genre-Seite -> Event-Dicts (ein Dict je Vorstellung).

    `now` (naive Berliner Zeit) ist fuer Tests injizierbar; Fenster = heute..+120 Tage.
    `genre` = Roh-Kategorie der Seite ("Familienstück", "Schauspiel", ...).
    """
    now = now or _berlin_now()
    window_start = datetime.combine(now.date(), time(0, 0))
    window_end = window_start + timedelta(days=MAX_DAYS_AHEAD)

    soup = BeautifulSoup(html, "lxml")
    events: List[Dict] = []
    seen: set = set()
    for group in soup.select("ul.schedule__group"):
        try:
            day = date.fromisoformat(group.get("data-groupdate", ""))
        except ValueError:
            continue
        for item in group.select("div.schedule__item"):
            try:
                ev = _parse_item(item, day, genre)
            except Exception as exc:
                logger.debug(f"Schauspielhaus Bochum item parse error: {exc}")
                continue
            if not ev or ev["canonical_id"] in seen:
                continue
            if not (window_start <= ev["start_at"] < window_end):
                continue
            # Vorbei = Ende (bzw. Start) < jetzt; heute fruehere Vorstellungen raus.
            if (ev["end_at"] or ev["start_at"]) < now:
                continue
            seen.add(ev["canonical_id"])
            events.append(ev)
    return events


def merge_genre_events(per_genre: List[List[Dict]]) -> List[Dict]:
    """Genreseiten in Prioritaetsreihenfolge zusammenfuehren (Dedup per canonical_id).

    Erste Fundstelle bestimmt die Kategorie; kids_suitable "yes" gewinnt immer.
    """
    merged: Dict[str, Dict] = {}
    for events in per_genre:
        for ev in events:
            known = merged.get(ev["canonical_id"])
            if known is None:
                merged[ev["canonical_id"]] = ev
            elif ev["kids_suitable"] == "yes" and known["kids_suitable"] != "yes":
                known["kids_suitable"] = "yes"
    result = sorted(merged.values(), key=lambda e: (e["start_at"], e["title"]))
    logger.info(f"Schauspielhaus Bochum: {len(result)} events")
    return result


async def fetch_schauspielhaus_bochum_events() -> List[Dict]:
    """Fetch Schauspielhaus Bochum events from all genre pages (never raises)."""
    per_genre: List[List[Dict]] = []
    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True, headers=_HEADERS
    ) as client:
        for idx, (gid, slug, label) in enumerate(GENRE_PAGES):
            if idx:
                await asyncio.sleep(REQUEST_PAUSE_SECONDS)
            url = f"{BASE_URL}/de/spielplan/{gid}/{slug}"
            try:
                resp = await client.get(url)
                if resp.status_code in (401, 403, 429):
                    logger.error(
                        f"Schauspielhaus Bochum: HTTP {resp.status_code} bei {url} — Abbruch"
                    )
                    break
                resp.raise_for_status()
                per_genre.append(
                    parse_schauspielhaus_bochum_html(resp.text, genre=label)
                )
            except Exception as exc:
                logger.error(f"Schauspielhaus Bochum fetch failed ({slug}): {exc}")
    return merge_genre_events(per_genre)


async def sync_schauspielhaus_bochum(db: Session) -> dict:
    """Sync Schauspielhaus Bochum events to database."""
    events_data = await fetch_schauspielhaus_bochum_events()
    return sync_events_to_db(db, events_data, SOURCE_NAME)
