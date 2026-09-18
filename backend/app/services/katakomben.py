"""Katakomben-Theater Essen event source — WordPress HTML scraping (Startseite).

Quelle: http://www.katakomben-theater.de/ (WordPress 3.0.1, Theme "arras").

Warum http:// statt https://: Der Server liefert auf Port 443 einen
TLS-Handshake-Fehler (SSLV3_ALERT_HANDSHAKE_FAILURE, keine gemeinsame
Cipher-Suite). Die Seite ist nur per Klartext-HTTP erreichbar.

Warum HTML statt API/RSS: WordPress 3.0.1 hat keine REST-API (/wp-json/ und
?rest_route= liefern 404 bzw. die Startseite). Der RSS-Feed (?feed=rss2)
enthaelt nur die 10 naechsten Posts. Die Startseite listet dagegen alle
kommenden Veranstaltungen (~50, aufsteigend nach Datum) in
ul.hfeed > li.post mit:
  - abbr.published[title="2026-09-18T20:00:40+00:00"]  Datum + Uhrzeit des
    Termins in Berliner Lokalzeit (das "+00:00" ist ein WP-3.0-Bug; der
    RSS-pubDate desselben Posts liegt 2h frueher in echtem UTC)
  - h3.entry-title a                                     Titel + Permalink
  - div.entry-summary                                    "FR 18. September 2026, 20 Uhr <Titel> <Text>..."
  - img.wp-post-image                                    Banner 305x110
  - li-Klassen category-<slug>                           Rubriken der Seite

Posts mit mehreren Terminen ("SA 03. Oktober 2026, Beginn: 19:00 Uhr ...
SO 04. Oktober 2026, Beginn: 15:00 Uhr") werden in ein Event pro Termin
aufgeloest; der Datumsblock steht in der Summary immer vor dem Titel.
robots.txt: "User-agent: * / Disallow:" — alles erlaubt.
"""
import hashlib
import logging
import re
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.services.base_sync import (
    _normalize_title,
    _title_similarity,
    sync_events_to_db,
)

logger = logging.getLogger(__name__)

# Nur http:// — siehe Modul-Docstring (TLS-Handshake auf 443 schlaegt fehl).
BASE_URL = "http://www.katakomben-theater.de/"

SOURCE_NAME = "Katakomben-Theater"
VENUE_NAME = "Katakomben-Theater"
ADDRESS_TEXT = "Girardetstraße 2-38, 45131 Essen"

# Venue coordinates (OSM amenity=theatre "Katakomben-Theater", Girardetstraße
# 2-38, Rüttenscheid — Nominatim verified: 51.4307774, 7.0062198)
VENUE_LAT = 51.4307774
VENUE_LON = 7.0062198

MAX_DAYS_AHEAD = 120
MAX_DATES_PER_POST = 60

_BERLIN = ZoneInfo("Europe/Berlin")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

_MONTH_MAP = {
    "januar": 1, "jan": 1, "februar": 2, "feb": 2, "märz": 3, "maerz": 3,
    "mär": 3, "mrz": 3, "april": 4, "apr": 4, "mai": 5, "juni": 6, "jun": 6,
    "juli": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sept": 9,
    "sep": 9, "oktober": 10, "okt": 10, "november": 11, "nov": 11,
    "dezember": 12, "dez": 12,
}

# Anzeigenamen der Rubriken (aus dem RSS-Feed / der Navigation der Seite).
# Die li-Klassen liefern nur Slugs; "party-kurse" ist eine Alt-Schreibweise.
_CATEGORY_NAMES = {
    "comedy-kabarett": "Comedy, Kabarett",
    "jazz-weltmusik": "Jazz, Weltmusik",
    "tanz-theater": "Tanz, Theater",
    "partys-kurse": "Partys, Kurse",
    "party-kurse": "Partys, Kurse",
    "festivals-sonderveranstaltungen": "Festivals, Sonderveranstaltungen",
    "comedywoche": "Comedywoche",
    "kinder": "Kindertheater",
}
_GENERIC_SLUGS = {"allgemein", "festivals-sonderveranstaltungen"}

# Fast jeder Post traegt 4-5 Rubriken gleichzeitig (Redaktion klickt alles
# an). Um trotzdem die passende Roh-Rubrik zu waehlen, wird per Keyword auf
# Titel+Summary entschieden — aber nur unter den Rubriken, die der Post
# tatsaechlich traegt. Reihenfolge = Prioritaet.
_CATEGORY_HINTS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"kinder|familie|mitmach|märchen|maerchen", re.I), "kinder"),
    (
        re.compile(r"comedy|kabarett|stand-?up|satire|comedian|jahresrück", re.I),
        "comedy-kabarett",
    ),
    (
        re.compile(
            r"musical|theater|tanz|schauspiel|bühne|buehne|premiere|krimi", re.I
        ),
        "tanz-theater",
    ),
    (
        re.compile(
            r"jazz|konzert|musik|band|trio|chor|orchester|sänger|stimm|piano|gitarre", re.I
        ),
        "jazz-weltmusik",
    ),
    (re.compile(r"party|disco|\bdj\b|kurs|workshop", re.I), "partys-kurse"),
    (re.compile(r"festival|comedywoche", re.I), "festivals-sonderveranstaltungen"),
]

_KIDS_KEYWORDS = [
    "kinder", "kind ", "familie", "familien", "mitmach", "märchen", "maerchen",
    "jugend", "kids", "kindertheater",
]

# ISO-Timestamp im abbr.published-title, z.B. "2026-09-18T20:00:40+00:00".
_ISO_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})")

# Datum: "18. September 2026", "7. Oktober2026", "23. September" (ohne Jahr),
# "10.10." / "27.12.26" / "18.9.2026". Der negative Lookahead verhindert,
# dass "10.10. 19:30" die "19" als zweistelliges Jahr frisst.
_DATE_RE = re.compile(
    r"(?<![\d.])(\d{1,2})\.\s*"
    r"(?:(\d{1,2})\.(\d{4}|\d{2})?(?![\d:])"
    r"|([A-Za-zÄÖÜäöü]+)\.?\s*(\d{4})?)"
)

# "Einlass ab 18:00 Uhr" / "(Einlass 19 Uhr)" darf nie als Beginn gelten.
_EINLASS_RE = re.compile(
    r"\(?\s*Einlass\s*(?:ab|:)?\s*\d{1,2}(?:[:.]\d{2})?\s*(?:Uhr|h\b)?\s*\)?",
    re.I,
)

# Uhrzeit-Kette: "20 Uhr", "19.30 Uhr", "19:00 Uhr", "10 und 11.15 Uhr",
# "19 und 21 Uhr", "20 h". Die Kette wird anschliessend an den Trennern
# aufgeteilt, damit "10 und 11.15 Uhr" zwei Termine ergibt.
_TIME_CHAIN_RE = re.compile(
    r"(?<![\d.:])((?:\d{1,2}(?:[:.]\d{2})?\s*(?:und|u\.|&|\+|/|,)\s*)*"
    r"\d{1,2}(?:[:.]\d{2})?)\s*(?:Uhr|h\b)",
    re.I,
)
_TIME_SPLIT_RE = re.compile(r"\s*(?:und|u\.|&|\+|/|,)\s*", re.I)

_PRICE_RE = re.compile(
    r"Eintritt\s*frei(?:,\s*Spenden\s*erwünscht)?"
    r"|(?:Eintritt|VVK|AK|Tickets?|Karten|Preis)\s*:?\s*(?:ab\s*)?"
    r"\d{1,3}(?:[.,]\d{2})?\s*(?:€|Euro)"
    r"|\d{1,3}(?:[.,]\d{2})?\s*(?:€|Euro)",
    re.I,
)


def _berlin_now() -> datetime:
    return datetime.now(_BERLIN).replace(tzinfo=None)


def _parse_iso_published(value: str) -> Optional[datetime]:
    """'2026-09-18T20:00:40+00:00' -> naive datetime(2026, 9, 18, 20, 0).

    Der Offset wird bewusst ignoriert: WP 3.0 schreibt Berliner Lokalzeit
    mit falschem "+00:00". Sekunden sind Rauschen der Post-Erstellung.
    """
    m = _ISO_RE.search(value or "")
    if not m:
        return None
    try:
        return datetime(*(int(g) for g in m.groups()))
    except ValueError:
        return None


def _header_text(title: str, summary: str) -> str:
    """Datumsblock der Summary = alles vor der ersten Wiederholung des Titels."""
    words = [w for w in re.findall(r"\w+", title, re.UNICODE) if len(w) >= 3][:2]
    if words:
        pattern = r"\W+".join(re.escape(w) for w in words)
        m = re.search(pattern, summary, re.I | re.UNICODE)
        if m and m.start() > 0:
            return summary[: m.start()]
    return summary[:120]


def _parse_times(segment: str) -> List[time]:
    """Alle Beginn-Uhrzeiten eines Datumsabschnitts (Einlass ausgeschlossen)."""
    cleaned = _EINLASS_RE.sub(" ", segment)
    times: List[time] = []
    for m in _TIME_CHAIN_RE.finditer(cleaned):
        for token in _TIME_SPLIT_RE.split(m.group(1)):
            tm = re.match(r"(\d{1,2})(?:[:.](\d{2}))?$", token.strip())
            if not tm:
                continue
            hour = int(tm.group(1))
            minute = int(tm.group(2) or 0)
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                t = time(hour, minute)
                if t not in times:
                    times.append(t)
    return times


def _resolve_year(
    day: int, month: int, anchor: Optional[datetime], now: datetime
) -> Optional[date]:
    """Jahr fuer ein Datum ohne Jahresangabe waehlen.

    Mit Anker (Post-Datum): dessen Jahr, +1 wenn das Datum deutlich vor dem
    Anker laege (Jahreswechsel). Ohne Anker: naechstes Vorkommen ab heute.
    """
    base_year = (anchor or now).year
    floor = (anchor.date() if anchor else now.date()) - timedelta(days=30)
    for year in (base_year, base_year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate >= floor:
            return candidate
    return None


def _extract_header_dates(
    header: str, anchor: Optional[datetime], now: datetime
) -> List[Tuple[date, Optional[time]]]:
    """Alle (Datum, Uhrzeit|None)-Paare aus dem Datumsblock der Summary."""
    matches = list(_DATE_RE.finditer(header))
    hits: List[Tuple[date, Optional[time]]] = []
    for idx, m in enumerate(matches):
        day = int(m.group(1))
        year_raw = None
        if m.group(2):  # numerisch: 10.10. / 27.12.26 / 18.9.2026
            month = int(m.group(2))
            year_raw = m.group(3)
        else:  # Monatsname
            month = _MONTH_MAP.get(m.group(4).lower(), 0)
            year_raw = m.group(5)
        if not (1 <= month <= 12 and 1 <= day <= 31):
            continue

        d: Optional[date]
        if year_raw:
            year = int(year_raw)
            if year < 100:
                year += 2000
            try:
                d = date(year, month, day)
            except ValueError:
                continue
        else:
            d = _resolve_year(day, month, anchor, now)
        if d is None:
            continue

        # Uhrzeiten stehen zwischen diesem und dem naechsten Datum.
        seg_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(header)
        segment = header[m.end(): seg_end]
        times = _parse_times(segment)
        if times:
            for t in times:
                hits.append((d, t))
        else:
            hits.append((d, None))
    return hits


def _build_datetimes(
    anchor: Optional[datetime], header_hits: List[Tuple[date, Optional[time]]]
) -> List[datetime]:
    """Header-Termine + Post-Datum zu einer sortierten, dedupierten Liste."""
    default_time: Optional[time] = None
    if anchor and anchor.time() != time(0, 0):
        default_time = anchor.time()
    if default_time is None:
        default_time = next((t for _, t in header_hits if t), None)
    if default_time is None:
        default_time = anchor.time() if anchor else time(0, 0)

    results: List[datetime] = []
    for d, t in header_hits:
        if t is None:
            t = anchor.time() if (anchor and d == anchor.date()) else default_time
        results.append(datetime.combine(d, t))

    # Das Post-Datum ist die zuverlaessigste Angabe — immer dabei, sofern der
    # Tag nicht schon aus dem Header kommt (dort ggf. mit genauerer Zeit).
    if anchor and anchor.date() not in {r.date() for r in results}:
        results.append(anchor)

    unique = sorted(set(results))
    return unique[:MAX_DATES_PER_POST]


def _category_slugs(li) -> List[str]:
    classes = li.get("class", [])
    return [c[len("category-"):] for c in classes if c.startswith("category-")]


def _pick_category(slugs: List[str], text: str) -> Optional[str]:
    """Roh-Rubrik der Seite waehlen (siehe _CATEGORY_HINTS)."""
    present = set(slugs)
    if "party-kurse" in present:
        present.add("partys-kurse")
    for pattern, slug in _CATEGORY_HINTS:
        if slug in present and pattern.search(text):
            return _CATEGORY_NAMES[slug]
    specific = [s for s in slugs if s not in _GENERIC_SLUGS and s in _CATEGORY_NAMES]
    if len({_CATEGORY_NAMES[s] for s in specific}) == 1:
        return _CATEGORY_NAMES[specific[0]]
    return None


def _detect_kids(slugs: List[str], text: str) -> str:
    if "kinder" in slugs:
        return "yes"
    lowered = text.lower()
    if any(kw in lowered for kw in _KIDS_KEYWORDS):
        return "likely"
    return "unknown"


def _extract_price(text: str) -> Optional[str]:
    m = _PRICE_RE.search(text)
    return m.group(0).strip()[:100] if m else None


def _make_canonical(title: str, start_at: datetime, url: str) -> str:
    return hashlib.md5(
        f"katakomben_{title}_{start_at.isoformat()}_{url}".encode()
    ).hexdigest()[:16]


def _parse_post(li, now: datetime) -> Optional[Dict]:
    """Ein li.post -> Roh-Dict mit title, url, anchor, datetimes, summary, ..."""
    title_el = li.find("h3", class_="entry-title")
    if not title_el:
        return None
    title = re.sub(r"\s+", " ", title_el.get_text(" ", strip=True)).strip()
    if not title:
        return None
    link_el = title_el.find("a", href=True)
    url = link_el["href"] if link_el else BASE_URL
    if url.startswith("/"):
        url = BASE_URL.rstrip("/") + url

    abbr = li.find("abbr", class_="published")
    anchor = _parse_iso_published(abbr.get("title", "")) if abbr else None

    summary_el = li.find("div", class_="entry-summary")
    summary = ""
    if summary_el:
        summary = re.sub(r"\s+", " ", summary_el.get_text(" ", strip=True))

    header = _header_text(title, summary) if summary else ""
    header_hits = _extract_header_dates(header, anchor, now) if header else []
    datetimes = _build_datetimes(anchor, header_hits)
    if not datetimes:
        return None

    # Beschreibung = Summary ohne Datumsblock und ohne Titelwiederholung.
    body = summary
    if header and summary.startswith(header):
        body = summary[len(header):].strip()
    if body.lower().startswith(title.lower()):
        body = body[len(title):]
    body = body.strip(" -–—:,.").rstrip(".").strip()

    img = li.find("img", class_="wp-post-image") or li.find("img", src=True)
    image_url = img.get("src") if img else None
    if image_url and image_url.startswith("/"):
        image_url = BASE_URL.rstrip("/") + image_url

    slugs = _category_slugs(li)
    # Venue-Nennungen ("... im Katakomben-Theater Essen") duerfen die
    # Rubrik-Heuristik nicht auf "Theater" ziehen.
    text = re.sub(r"katakomben[- ]?theaters?", " ", f"{title} {summary}", flags=re.I)
    return {
        "title": title,
        "url": url,
        "anchor": anchor,
        "datetimes": datetimes,
        "description": body[:500] or None,
        "image_url": image_url,
        "category": _pick_category(slugs, text),
        "kids": _detect_kids(slugs, text),
        "price_text": _extract_price(summary),
    }


def _titles_overlap(a: str, b: str) -> bool:
    """Jaccard >= 0.6 (wie base_sync) oder kurzer Titel komplett im langen."""
    if _title_similarity(a, b) >= 0.6:
        return True
    ta, tb = set(_normalize_title(a).split()), set(_normalize_title(b).split())
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return len(small) >= 2 and small <= big


def _is_covered_by_other_post(post: Dict, when: datetime, posts: List[Dict]) -> bool:
    """Zusatztermin schon als eigener Post vorhanden (z.B. Premiere + 2. Tag)?"""
    for other in posts:
        if other is post or not other["anchor"]:
            continue
        if other["anchor"].date() != when.date():
            continue
        if _titles_overlap(post["title"], other["title"]):
            return True
    return False


def parse_katakomben_html(html: str, now: Optional[datetime] = None) -> List[Dict]:
    """Parse the Katakomben homepage into one event dict per Termin.

    `now` (naive Berlin time) is injectable for tests; window = today .. +120d.
    """
    now = now or _berlin_now()
    window_start = datetime.combine(now.date(), time(0, 0))
    window_end = window_start + timedelta(days=MAX_DAYS_AHEAD)

    soup = BeautifulSoup(html, "lxml")
    feed = soup.find("ul", class_="hfeed")
    if feed:
        items = feed.find_all("li", recursive=False)
    else:
        items = soup.find_all("li", class_="post")
    logger.debug(f"Katakomben: {len(items)} post blocks found")

    posts: List[Dict] = []
    for li in items:
        try:
            post = _parse_post(li, now)
            if post:
                posts.append(post)
        except Exception as exc:
            logger.debug(f"Katakomben post parse error: {exc}")

    events: List[Dict] = []
    seen_ids: set = set()
    for post in posts:
        for when in post["datetimes"]:
            if not (window_start <= when < window_end):
                continue
            anchor = post["anchor"]
            is_primary = anchor is not None and when.date() == anchor.date()
            if not is_primary and _is_covered_by_other_post(post, when, posts):
                continue
            canonical = _make_canonical(post["title"], when, post["url"])
            if canonical in seen_ids:
                continue
            seen_ids.add(canonical)
            events.append(
                {
                    "canonical_id": canonical,
                    "title": post["title"][:500],
                    "short_description": post["description"],
                    "start_at": when,
                    "venue_name": VENUE_NAME,
                    "address_text": ADDRESS_TEXT,
                    "city": "Essen",
                    "lat": VENUE_LAT,
                    "lon": VENUE_LON,
                    "source_url": post["url"][:500],
                    "source_name": SOURCE_NAME,
                    "indoor_outdoor": "indoor",
                    "kids_suitable": post["kids"],
                    "price_text": post["price_text"],
                    "category": post["category"],
                    "image_url": post["image_url"][:500] if post["image_url"] else None,
                }
            )

    logger.info(f"Katakomben: {len(events)} events from {len(posts)} posts")
    return events


async def fetch_katakomben_events() -> List[Dict]:
    """Fetch Katakomben-Theater events from the homepage (never raises)."""
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        try:
            resp = await client.get(BASE_URL)
            resp.raise_for_status()
            return parse_katakomben_html(resp.text)
        except Exception as exc:
            logger.error(f"Katakomben fetch failed: {exc}")
            return []


async def sync_katakomben(db: Session) -> dict:
    """Sync Katakomben-Theater events to database."""
    events_data = await fetch_katakomben_events()
    return sync_events_to_db(db, events_data, SOURCE_NAME)
