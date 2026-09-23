"""Folkwang Universität der Künste event source — TYPO3 "calendarize" HTML scraping.

Not to be confused with ``folkwang.py`` (Museum Folkwang) — this module covers
the university's public concerts, theatre/dance performances and lectures.
Main campus is Essen-Werden (Klemensborn 39), further venues: Campus Welterbe
Zollverein (SANAA building), Duisburg and Bochum.
"""
import asyncio
import hashlib
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.services.base_sync import sync_events_to_db
from app.services.crawler_ua import CRAWLER_USER_AGENT

logger = logging.getLogger(__name__)

SOURCE_NAME = "Folkwang Universität"
BASE_URL = "https://www.folkwang-uni.de"
# Landing page = current month (plus a few upcoming entries).
LIST_URL = f"{BASE_URL}/home/hochschule/veranstaltungen/"
# Month pages use an UNPADDED month ("2026/9") — "2026/09" returns 404.
MONTH_URL = f"{BASE_URL}/home/hochschule/veranstaltungen/monat/{{year}}/{{month}}"

# robots.txt: "Allow: /" with "Crawl-delay: 1" → one request per second.
REQUEST_DELAY = 1.0
MONTHS_AHEAD = 3
MAX_DETAIL_REQUESTS = 25
MAX_DAYS_AHEAD = 120
MAX_OCCURRENCES_PER_TITLE = 60

# Fixed campus coordinates (Nominatim verified).
# Campus Essen-Werden, Klemensborn 39: 51.3874951, 7.0045260
# SANAA-Gebäude, Gelsenkirchener Str. 209 (Zollverein): 51.4882207, 7.0476214
CAMPUS_WERDEN_LAT = 51.3874951
CAMPUS_WERDEN_LON = 7.0045260
CAMPUS_ZOLLVEREIN_LAT = 51.4882207
CAMPUS_ZOLLVEREIN_LON = 7.0476214
CAMPUS_WERDEN_ADDRESS = "Klemensborn 39, 45239 Essen"
CAMPUS_ZOLLVEREIN_ADDRESS = "Gelsenkirchener Str. 209, 45309 Essen"

_HEADERS = {
    "User-Agent": CRAWLER_USER_AGENT
}

# German month abbreviations as rendered by calendarize ("Sep", "Mär", ...),
# plus full names and ASCII fallbacks for robustness.
_MONTH_MAP = {
    "jan": 1, "januar": 1,
    "feb": 2, "februar": 2,
    "mär": 3, "maer": 3, "mrz": 3, "märz": 3, "maerz": 3,
    "apr": 4, "april": 4,
    "mai": 5,
    "jun": 6, "juni": 6,
    "jul": 7, "juli": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "okt": 10, "oktober": 10,
    "nov": 11, "november": 11,
    "dez": 12, "dezember": 12,
}

_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*Uhr", re.IGNORECASE)
_LINK_DATE_SUFFIX_RE = re.compile(r"-(\d{4})(\d{2})(\d{2})/?$")
_MONTH_URL_RE = re.compile(r"/monat/(\d{4})/(\d{1,2})")
_PRICE_RE = re.compile(r"eintritt|€|euro|kostenlos|frei", re.IGNORECASE)
_ADDRESS_RE = re.compile(
    r"\d.*(str\.|straße|strasse|platz|weg|allee|ring)|(str\.|straße|strasse|platz|weg|allee|ring).*\d",
    re.IGNORECASE,
)
# Bare city segments ("Essen", "Essen-Werden", "Bochum") are not room names.
_CITY_TOKEN_RE = re.compile(r"^(essen|bochum|duisburg)(-[\wäöüß]+)?$")
_OUTDOOR_RE = re.compile(r"innenhof|garten|open\s*air|\bpark\b|freilicht", re.IGNORECASE)
_KIDS_RE = re.compile(
    r"\b(kinder|kind|familie|familien|jugend|jugendliche|kids|schüler|schueler)",
    re.IGNORECASE,
)

# Raw category by title keyword; default is "Konzert" (music university).
_CATEGORY_KEYWORDS = [
    ("theater", "Theater"),
    ("schauspiel", "Schauspiel"),
    ("tanz", "Tanz"),
    ("vortrag", "Vortrag"),
    ("ausstellung", "Ausstellung"),
    ("festival", "Festival"),
    ("workshop", "Workshop"),
]
_DEFAULT_CATEGORY = "Konzert"


def _parse_month(month_str: str) -> int:
    """Map 'Sep', 'Mär', 'Okt' … to 1–12 (0 if unknown)."""
    key = month_str.strip().strip(".").lower()
    return _MONTH_MAP.get(key, 0)


def _resolve_year(month: int, page_year: int, page_month: int) -> int:
    """Pick the year for a day/month pair shown on a month page.

    A month page may list events that started in a neighbouring month
    (e.g. an exhibition from Oct on the Nov page, or a Dec event on the
    Jan page). Anything more than 6 months away wraps into the previous /
    next year.
    """
    diff = month - page_month
    if diff > 6:
        return page_year - 1
    if diff < -6:
        return page_year + 1
    return page_year


def derive_page_context(soup, now: Optional[datetime] = None) -> Tuple[int, int]:
    """Derive (year, month) of the calendar page from its prev/next links.

    The landing page has no year in its URL; the calendar navigation links
    (".cp-calendar-next a" → /monat/2026/10) reveal the displayed month.
    Falls back to the current date.
    """
    now = now or datetime.now()
    nxt = soup.select_one(".cp-calendar-next a[href]")
    if nxt:
        m = _MONTH_URL_RE.search(nxt.get("href", ""))
        if m:
            year, month = int(m.group(1)), int(m.group(2)) - 1
            if month == 0:
                year, month = year - 1, 12
            return year, month
    prev = soup.select_one(".cp-calendar-prev a[href]")
    if prev:
        m = _MONTH_URL_RE.search(prev.get("href", ""))
        if m:
            year, month = int(m.group(1)), int(m.group(2)) + 1
            if month == 13:
                year, month = year + 1, 1
            return year, month
    return now.year, now.month


def _parse_time(text: str) -> Tuple[int, int, bool]:
    """Return (hour, minute, is_all_day) from '19:30 Uhr' / '00:00 Uhr'.

    The paragraph only ever contains a time, but the regex requires a colon
    so a date like '24.06.' can never be mistaken for 24:06.
    """
    clean = text.replace("\xa0", " ")
    m = _TIME_RE.search(clean)
    if not m:
        return 0, 0, True
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return 0, 0, True
    return hour, minute, (hour == 0 and minute == 0)


def _parse_location(text: str) -> Dict:
    """Split 'Raum | Straße Nr | Campus X' into venue/campus/address/city/coords.

    Fixed coordinates are only used for the two known campuses ("Campus
    Essen-Werden", "Campus Welterbe Zollverein"); other venues (churches,
    Museum Folkwang, Bürgermeisterhaus …) are left to the geocoder.
    """
    clean = re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
    segments = [s.strip() for s in clean.split("|") if s.strip()]

    campus: Optional[str] = None
    raw_address: Optional[str] = None
    room_parts: List[str] = []
    city_tokens: List[str] = []
    is_online = False
    for seg in segments:
        low = seg.lower()
        if low.startswith("campus"):
            campus = seg
        elif low == "online":
            is_online = True
        elif _CITY_TOKEN_RE.match(low):
            city_tokens.append(low)
        elif _ADDRESS_RE.search(seg):
            raw_address = seg
        else:
            room_parts.append(seg)
    room = ", ".join(room_parts) if room_parts else None

    city_hint = " ".join(city_tokens + [campus.lower() if campus else ""])
    city = "Essen"
    if "bochum" in city_hint:
        city = "Bochum"
    elif "duisburg" in city_hint:
        city = "Duisburg"

    lat = lon = None
    address: Optional[str] = None
    campus_low = (campus or "").lower()
    if "werden" in campus_low:
        lat, lon = CAMPUS_WERDEN_LAT, CAMPUS_WERDEN_LON
        address = CAMPUS_WERDEN_ADDRESS
    elif "zollverein" in campus_low:
        lat, lon = CAMPUS_ZOLLVEREIN_LAT, CAMPUS_ZOLLVEREIN_LON
        address = CAMPUS_ZOLLVEREIN_ADDRESS
    elif raw_address:
        # Street from the page has no postcode — append the city for the geocoder.
        address = raw_address if city.lower() in raw_address.lower() else f"{raw_address}, {city}"

    if room and campus:
        venue = f"{room}, {campus}"
    elif campus:
        venue = campus
    elif room:
        venue = room
    elif raw_address:
        venue = raw_address
    elif is_online:
        venue = "Online"
    else:
        venue = "Folkwang Universität der Künste"

    indoor_outdoor = "outdoor" if _OUTDOOR_RE.search(clean) else "indoor"

    return {
        "venue_name": venue,
        "campus": campus,
        "address_text": address,
        "city": city,
        "lat": lat,
        "lon": lon,
        "indoor_outdoor": indoor_outdoor,
        "is_online": is_online,
    }


def _detect_kids(*texts: str) -> str:
    combined = " ".join(t for t in texts if t)
    return "likely" if _KIDS_RE.search(combined) else "unknown"


def _detect_category(title: str) -> str:
    low = title.lower()
    for keyword, cat in _CATEGORY_KEYWORDS:
        if keyword in low:
            return cat
    return _DEFAULT_CATEGORY


def _make_canonical(title: str, start_at: datetime, url: str) -> str:
    return hashlib.md5(
        f"folkwanguni_{title}_{start_at.isoformat()}_{url}".encode()
    ).hexdigest()[:16]


def _base_detail_url(url: str) -> str:
    """Strip the '-YYYYMMDD' occurrence suffix so series share one detail page."""
    return _LINK_DATE_SUFFIX_RE.sub("", url)


def _parse_event_block(block, page_year: int, page_month: int) -> Optional[Dict]:
    """Extract one event from a div.cp-module-event block."""
    day_el = block.select_one(".cp-date .day")
    month_el = block.select_one(".cp-date .month")
    content = block.select_one(".cp-event-content")
    if not (day_el and month_el and content):
        return None

    title_el = content.find("h4")
    title = title_el.get_text(" ", strip=True) if title_el else ""
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        return None

    link_el = content.find("a", class_="cp-module-partial-link", href=True)
    href = link_el.get("href", "") if link_el else ""
    source_url = href if href.startswith("http") else f"{BASE_URL}{href}" if href else LIST_URL

    # Date: day + abbreviated month; year from link suffix or page context.
    try:
        day = int(day_el.get_text(strip=True).strip("."))
    except ValueError:
        return None
    month = _parse_month(month_el.get_text(strip=True))
    if not month or not 1 <= day <= 31:
        return None
    year = None
    m = _LINK_DATE_SUFFIX_RE.search(href)
    if m and int(m.group(2)) == month and int(m.group(3)) == day:
        year = int(m.group(1))
    if year is None:
        year = _resolve_year(month, page_year, page_month)

    # Paragraphs before the <h4> hold time + location, those after it hold
    # subtitle and (optionally) price info. Identify by content, not position.
    before: List[str] = []
    after: List[str] = []
    seen_title = False
    for child in content.children:
        if getattr(child, "name", None) == "h4":
            seen_title = True
            continue
        if getattr(child, "name", None) != "p":
            continue
        txt = re.sub(r"\s+", " ", child.get_text(" ", strip=True).replace("\xa0", " ")).strip()
        if not txt:
            continue
        # TYPO3 editors prefix some paragraphs with "_" (formatting artefact).
        (after if seen_title else before).append(txt.lstrip("_").strip())

    time_text = next((t for t in before if _TIME_RE.search(t)), "")
    location_text = next((t for t in before if not _TIME_RE.search(t)), "")
    hour, minute, is_all_day = _parse_time(time_text)
    try:
        start_at = datetime(year, month, day, hour, minute)
    except ValueError:
        return None

    location = _parse_location(location_text)
    if location["is_online"]:
        # Online lectures/streams are not outings — skip them.
        return None

    price_text: Optional[str] = None
    subtitle: Optional[str] = None
    for txt in after:
        if price_text is None and _PRICE_RE.search(txt) and len(txt) <= 80:
            price_text = txt
        elif subtitle is None:
            subtitle = txt

    event = {
        "canonical_id": _make_canonical(title, start_at, source_url),
        "title": title[:500],
        "short_description": subtitle[:500] if subtitle else None,
        "start_at": start_at,
        "is_all_day": is_all_day,
        "venue_name": location["venue_name"],
        "address_text": location["address_text"],
        "city": location["city"],
        "source_url": source_url[:500],
        "source_name": SOURCE_NAME,
        "indoor_outdoor": location["indoor_outdoor"],
        "kids_suitable": _detect_kids(title, subtitle or ""),
        "price_text": price_text[:255] if price_text else None,
        "category": _detect_category(title),
    }
    if location["lat"] is not None:
        event["lat"] = location["lat"]
        event["lon"] = location["lon"]
    return event


def parse_folkwang_uni_html(
    html: str,
    page_year: Optional[int] = None,
    page_month: Optional[int] = None,
    now: Optional[datetime] = None,
) -> List[Dict]:
    """Parse one calendar page (landing or month page) into event dicts.

    ``page_year``/``page_month`` describe the month the page shows; when
    omitted they are derived from the calendar navigation links. Past events
    and events beyond MAX_DAYS_AHEAD are dropped.
    """
    now = now or datetime.now()
    soup = BeautifulSoup(html, "lxml")
    if page_year is None or page_month is None:
        page_year, page_month = derive_page_context(soup, now)

    blocks = soup.find_all("div", class_="cp-module-event")
    logger.debug(f"Folkwang Uni: {len(blocks)} event blocks on page {page_year}/{page_month}")

    events: List[Dict] = []
    seen: set = set()
    for block in blocks:
        try:
            event = _parse_event_block(block, page_year, page_month)
        except Exception as exc:
            logger.debug(f"Folkwang Uni block parse error: {exc}")
            continue
        if not event:
            continue
        key = (event["source_url"], event["start_at"].date())
        if key in seen:
            continue
        seen.add(key)
        events.append(event)

    return filter_time_window(events, now)


def filter_time_window(events: List[Dict], now: Optional[datetime] = None) -> List[Dict]:
    """Keep events from today (Berlin local) up to MAX_DAYS_AHEAD days ahead."""
    now = now or datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    horizon = today + timedelta(days=MAX_DAYS_AHEAD)
    return [
        e for e in events
        if e.get("start_at") is not None and today <= e["start_at"] <= horizon
    ]


def _cap_occurrences(events: List[Dict]) -> List[Dict]:
    """Limit daily series (e.g. exhibitions) to MAX_OCCURRENCES_PER_TITLE."""
    counts: Dict[str, int] = {}
    result: List[Dict] = []
    for event in sorted(events, key=lambda e: e["start_at"]):
        key = event["title"].lower()
        counts[key] = counts.get(key, 0) + 1
        if counts[key] <= MAX_OCCURRENCES_PER_TITLE:
            result.append(event)
    return result


def parse_folkwang_uni_detail_html(html: str) -> Dict:
    """Extract description/price from a calendarize detail page.

    Returns a dict with optional keys ``short_description`` and ``price_text``.
    The article's first paragraphs repeat date and venue; the first longer
    paragraph is the actual description.
    """
    result: Dict = {}
    soup = BeautifulSoup(html, "lxml")
    article = soup.select_one("div.calendarize article") or soup.select_one("div.calendarize")
    if not article:
        return result

    paragraphs = [
        re.sub(r"\s+", " ", p.get_text(" ", strip=True).replace("\xa0", " ")).strip()
        for p in article.find_all("p")
    ]
    paragraphs = [p for p in paragraphs if p]

    for txt in paragraphs:
        # Skip the date/time line and the venue line at the top.
        if _TIME_RE.search(txt) or re.match(r"^\d{1,2}\.\s*\w+\s*\d{4}", txt):
            continue
        if txt.lower().startswith("campus") or len(txt) < 40:
            continue
        result["short_description"] = txt.lstrip("_").strip()[:500]
        break

    full_text = " ".join(paragraphs)
    price_match = re.search(
        r"(Eintritt\s*frei|Eintritt\s*:?\s*[^.|]{2,60}?\d+[,.]?\d*\s*(?:€|Euro)|Karten\s*:?\s*[^.|]{0,40}?\d+[,.]?\d*\s*(?:€|Euro))",
        full_text,
        re.IGNORECASE,
    )
    if price_match:
        result["price_text"] = price_match.group(1).strip()[:255]

    return result


def _apply_detail(events: List[Dict], detail: Dict) -> None:
    """Merge detail-page description/price into all occurrences of a series."""
    for event in events:
        desc = detail.get("short_description")
        if desc:
            subtitle = event.get("short_description")
            if subtitle and subtitle.lower() not in desc.lower():
                event["short_description"] = f"{subtitle} – {desc}"[:500]
            else:
                event["short_description"] = desc[:500]
        if detail.get("price_text") and not event.get("price_text"):
            event["price_text"] = detail["price_text"]


async def fetch_folkwang_uni_events(now: Optional[datetime] = None) -> List[Dict]:
    """Fetch current month + MONTHS_AHEAD month pages, then enrich details."""
    now = now or datetime.now()
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        # Step 1: landing page (current month) + the following months.
        page_urls: List[Tuple[str, Optional[int], Optional[int]]] = [(LIST_URL, None, None)]
        year, month = now.year, now.month
        for _ in range(MONTHS_AHEAD):
            month += 1
            if month > 12:
                month, year = 1, year + 1
            page_urls.append((MONTH_URL.format(year=year, month=month), year, month))

        events: List[Dict] = []
        seen: set = set()
        for idx, (url, page_year, page_month) in enumerate(page_urls):
            if idx:
                await asyncio.sleep(REQUEST_DELAY)
            try:
                resp = await client.get(url)
                if resp.status_code == 404:
                    logger.debug(f"Folkwang Uni: no calendar page at {url}")
                    continue
                resp.raise_for_status()
            except Exception as exc:
                logger.error(f"Folkwang Uni fetch failed for {url}: {exc}")
                continue
            try:
                page_events = parse_folkwang_uni_html(
                    resp.text, page_year=page_year, page_month=page_month, now=now
                )
            except Exception as exc:
                logger.error(f"Folkwang Uni parse failed for {url}: {exc}")
                continue
            for event in page_events:
                key = (event["source_url"], event["start_at"].date())
                if key in seen:
                    continue
                seen.add(key)
                events.append(event)

        events = _cap_occurrences(events)
        logger.info(f"Folkwang Uni: {len(events)} events from {len(page_urls)} pages")

        # Step 2: detail enrichment — one request per series (base URL),
        # capped to stay polite (Crawl-delay 1).
        by_base: Dict[str, List[Dict]] = {}
        for event in events:
            by_base.setdefault(_base_detail_url(event["source_url"]), []).append(event)
        for base_url in list(by_base.keys())[:MAX_DETAIL_REQUESTS]:
            if base_url == LIST_URL:
                continue
            try:
                await asyncio.sleep(REQUEST_DELAY)
                resp = await client.get(base_url)
                resp.raise_for_status()
                detail = parse_folkwang_uni_detail_html(resp.text)
                if detail:
                    _apply_detail(by_base[base_url], detail)
            except Exception as exc:
                logger.debug(f"Folkwang Uni detail fetch failed for {base_url}: {exc}")

        return events


async def sync_folkwang_uni(db: Session) -> dict:
    """Sync Folkwang Universität events to database."""
    try:
        events_data = await fetch_folkwang_uni_events()
    except Exception as exc:
        logger.error(f"Folkwang Uni fetch failed: {exc}")
        events_data = []
    return sync_events_to_db(db, events_data, SOURCE_NAME)
