"""visitessen.de event source — Essen Marketing's official event calendar.

The public calendar at pages.visitessen.de is a thin frontend for the
destination.one / eT4 "Meta" API. Flow per sync:

1. GET the search page once to pick up the short-lived ``window.META_TOKEN``.
2. Page through ``meta.et4.de/rest.ashx/search/`` (JSON, 100 items per page).
3. Expand every item's ``timeIntervals`` into single occurrences (one event
   row per date, grouping into one card happens later in ``grouping.py``).

We request the full ``ET2014A.json`` template instead of ``ET2014A_LIGHT``:
same item structure and ordering, but LIGHT omits ``details`` and
``PRICE_INFO`` texts and leaves ~half of the teasers empty.
"""
import asyncio
import calendar
import hashlib
import html as html_lib
import logging
import re
import unicodedata
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.services.base_sync import sanitize_title, sync_events_to_db, to_berlin_naive

logger = logging.getLogger(__name__)

SOURCE_NAME = "visitessen.de"

# Search page: contains the META_TOKEN needed for the API. robots.txt of
# pages.visitessen.de only disallows unrelated magazine paths.
SEARCH_PAGE_URL = "https://pages.visitessen.de/de/visitessen/default/search/Event"
API_URL = "https://meta.et4.de/rest.ashx/search/"
DETAIL_URL_TEMPLATE = (
    "https://pages.visitessen.de/de/visitessen/default/detail/Event/{global_id}/{slug}"
)

API_EXPERIENCE = "visitessen"
API_TEMPLATE = "ET2014A.json"
API_QUERY = "all:all -systag:has_abnormal_interval"
API_PAGE_SIZE = 100
API_MAX_PAGES = 15

# Only occurrences from today up to this many days ahead are emitted.
HORIZON_DAYS = 120
# A daily exhibition would otherwise explode into hundreds of rows.
MAX_OCCURRENCES_PER_ITEM = 60
# Loop guard for open-ended recurrence rules.
_MAX_RULE_ITERATIONS = 5000

_BERLIN = ZoneInfo("Europe/Berlin")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# Token appears as `window.META_TOKEN = "t1...."` in the search page; the
# same value is also embedded as `"licensekey":"t1...."` in the page config.
_META_TOKEN_RE = re.compile(r'META_TOKEN\s*=\s*"([^"]+)"')
_LICENSEKEY_RE = re.compile(r'licensekey"\s*:\s*"([^"]+)"')

_KIDS_KEYWORDS = [
    "kind", "kinder", "famili", "jugend", "märchen", "maerchen",
    "puppentheater", "mitmach",
]

# Raw visitessen categories that imply an open-air / indoor setting.
_OUTDOOR_CATEGORIES = {
    "festival/open-air", "markt", "weihnachtsmarkt", "radtour", "wanderung",
    "ausflug/exkursion", "stadtfest/kirmes/jahrmarkt",
}
_INDOOR_CATEGORIES = {
    "schauspiel", "oper & operette", "musical & musiktheater", "kabarett & co.",
    "ausstellung", "vortrag/lesung", "klassisches konzert",
    "kinder- und jugendtheater", "filmkunst & kino", "party/nightlife", "messe",
    "kurs/seminar/hobby",
}

_WEEKDAY_IDX = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

# Plausibility box for coordinates (Essen and immediate surroundings).
_LAT_RANGE = (51.0, 51.8)
_LON_RANGE = (6.5, 7.6)


# ─────────────────────────────── helpers ─────────────────────────────────────


def extract_meta_token(page_html: str) -> Optional[str]:
    """Pull the short-lived API token out of the search page HTML."""
    if not page_html:
        return None
    m = _META_TOKEN_RE.search(page_html)
    if not m:
        m = _LICENSEKEY_RE.search(page_html)
    return m.group(1).strip() if m else None


def slugify(title: str) -> str:
    """Simple slug as used in visitessen deep links (umlauts → ae/oe/ue/ss)."""
    s = (title or "").lower()
    for src, dst in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(src, dst)
    # Drop remaining accents (é → e) so they don't become dashes.
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def build_detail_url(global_id: str, title: str) -> str:
    slug = slugify(title) or "event"
    return DETAIL_URL_TEMPLATE.format(global_id=global_id, slug=slug)


def _make_canonical(global_id: str, start_at: datetime) -> str:
    return hashlib.md5(
        f"visitessen_{global_id}_{start_at.isoformat()}".encode()
    ).hexdigest()[:16]


def _parse_iso(value) -> Optional[datetime]:
    """Parse an ISO timestamp ('2026-08-11T12:00:00+02:00') to naive Berlin time."""
    if not value or not isinstance(value, str):
        return None
    raw = value.strip()
    # Python 3.10 fromisoformat needs a colon in the offset ("+0200" → "+02:00").
    raw = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", raw)
    try:
        return to_berlin_naive(datetime.fromisoformat(raw))
    except ValueError:
        return None


def _strip_html(value: str) -> str:
    text = BeautifulSoup(value or "", "lxml").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", html_lib.unescape(text)).strip()


def _text_by_rel(texts: List[Dict], rel: str, mime: str) -> Optional[str]:
    for t in texts or []:
        if not isinstance(t, dict):
            continue
        if t.get("rel") == rel and t.get("type") == mime:
            value = (t.get("value") or "").strip()
            if value:
                return value
    return None


def _extract_description(texts: List[Dict]) -> Optional[str]:
    """Teaser (plain) → details (plain) → details (html, stripped)."""
    value = _text_by_rel(texts, "teaser", "text/plain")
    if not value:
        value = _text_by_rel(texts, "details", "text/plain")
    if not value:
        raw_html = _text_by_rel(texts, "details", "text/html")
        value = _strip_html(raw_html) if raw_html else None
    if not value:
        return None
    return re.sub(r"\s+", " ", value).strip()[:500] or None


def _extract_price(texts: List[Dict], attributes: Dict[str, str]) -> Optional[str]:
    price = _text_by_rel(texts, "PRICE_INFO", "text/plain")
    if price:
        # Multi-line price blocks ("VVK 12€\nAK 14€") → single line.
        price = " | ".join(p.strip() for p in price.splitlines() if p.strip())
        price = re.sub(r"[ \t]+", " ", price)
    if attributes.get("DETAILS_AUSGEBUCHT", "").lower() == "true":
        price = f"Ausverkauft ({price})" if price else "Ausverkauft"
    return price[:255] if price else None


def _extract_image(media_objects: List[Dict]) -> Optional[str]:
    """First image-typed media object, preferring rel='default'."""
    images = [
        m for m in media_objects or []
        if isinstance(m, dict)
        and str(m.get("type") or "").lower().startswith("image/")
        and m.get("url")
    ]
    if not images:
        return None
    default = next((m for m in images if m.get("rel") == "default"), images[0])
    url = str(default["url"]).strip()
    return url[:500] if url.startswith("http") else None


def _extract_coords(geo) -> Tuple[Optional[float], Optional[float]]:
    main = (geo or {}).get("main") if isinstance(geo, dict) else None
    if not isinstance(main, dict):
        return None, None
    try:
        lat = float(main.get("latitude"))
        lon = float(main.get("longitude"))
    except (TypeError, ValueError):
        return None, None
    if _LAT_RANGE[0] <= lat <= _LAT_RANGE[1] and _LON_RANGE[0] <= lon <= _LON_RANGE[1]:
        return lat, lon
    return None, None


def _detect_kids(title: str, categories: List[str]) -> str:
    cats = " ".join(categories).lower()
    if "kinder" in cats or "famili" in cats:
        return "yes"
    lowered = (title or "").lower()
    if any(kw in lowered for kw in _KIDS_KEYWORDS):
        return "likely"
    return "unknown"


def _detect_indoor_outdoor(categories: List[str]) -> str:
    cats = {c.strip().lower() for c in categories}
    outdoor = bool(cats & _OUTDOOR_CATEGORIES)
    indoor = bool(cats & _INDOOR_CATEGORIES)
    if outdoor and indoor:
        return "both"
    if outdoor:
        return "outdoor"
    if indoor:
        return "indoor"
    return "unknown"


# ────────────────────────── recurrence expansion ─────────────────────────────


def _nth_weekday_of_month(year: int, month: int, weekday: int, ordinal: int) -> Optional[date]:
    """E.g. ordinal=2, weekday=4 → second Friday. Negative ordinal counts from the end."""
    if ordinal > 0:
        first = date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        d = first + timedelta(days=offset + 7 * (ordinal - 1))
    elif ordinal < 0:
        last = date(year, month, calendar.monthrange(year, month)[1])
        offset = (last.weekday() - weekday) % 7
        d = last - timedelta(days=offset + 7 * (-ordinal - 1))
    else:
        return None
    return d if d.month == month else None


def _expand_interval(interval: Dict, horizon_end: datetime) -> List[Tuple[datetime, Optional[datetime]]]:
    """Expand one timeInterval into (start, end) pairs in naive Berlin time.

    Most intervals are already single dates. Some carry a recurrence rule
    (``freq`` Daily/Weekly/Monthly/Yearly + ``interval`` + ``repeatUntil``,
    ``weekdays`` for weekly, ``dayOrdinal``+``weekday`` for monthly).
    Expansion stops at ``repeatUntil`` or ``horizon_end``, whichever is first.
    """
    start = _parse_iso(interval.get("start"))
    if start is None:
        return []
    end = None if interval.get("hideEnd") else _parse_iso(interval.get("end"))
    duration = (end - start) if end is not None and end >= start else None

    freq = str(interval.get("freq") or "").strip().lower()
    if not freq:
        return [(start, end)]

    until = _parse_iso(interval.get("repeatUntil"))
    if until is None or until > horizon_end:
        until = horizon_end
    until_date = until.date()
    try:
        step = max(1, int(interval.get("interval") or 1))
    except (TypeError, ValueError):
        step = 1
    try:
        max_count = int(interval.get("repeatCount")) if interval.get("repeatCount") else None
    except (TypeError, ValueError):
        max_count = None

    dates: List[date] = []
    iterations = 0

    if freq == "daily":
        d = start.date()
        while d <= until_date and iterations < _MAX_RULE_ITERATIONS:
            dates.append(d)
            d += timedelta(days=step)
            iterations += 1

    elif freq == "weekly":
        weekdays = {
            _WEEKDAY_IDX[w.lower()]
            for w in interval.get("weekdays") or []
            if isinstance(w, str) and w.lower() in _WEEKDAY_IDX
        } or {start.weekday()}
        week_zero = start.date() - timedelta(days=start.weekday())
        d = start.date()
        while d <= until_date and iterations < _MAX_RULE_ITERATIONS:
            weeks_since = (d - week_zero).days // 7
            if d.weekday() in weekdays and weeks_since % step == 0:
                dates.append(d)
            d += timedelta(days=1)
            iterations += 1

    elif freq == "monthly":
        ordinal = interval.get("dayOrdinal")
        weekday_name = str(interval.get("weekday") or "").lower()
        year, month = start.year, start.month
        while iterations < _MAX_RULE_ITERATIONS:
            if date(year, month, 1) > until_date:
                break
            d: Optional[date]
            if ordinal and weekday_name in _WEEKDAY_IDX:
                try:
                    d = _nth_weekday_of_month(year, month, _WEEKDAY_IDX[weekday_name], int(ordinal))
                except (TypeError, ValueError):
                    d = None
            else:
                try:
                    d = date(year, month, start.day)
                except ValueError:
                    d = None  # e.g. 31st in a short month
            if d is not None and start.date() <= d <= until_date:
                dates.append(d)
            month += step
            year, month = year + (month - 1) // 12, (month - 1) % 12 + 1
            iterations += 1

    elif freq == "yearly":
        try:
            month = int(interval.get("month") or start.month)
            day = int(interval.get("dayOfMonth") or start.day)
        except (TypeError, ValueError):
            month, day = start.month, start.day
        year = start.year
        while year <= until_date.year and iterations < _MAX_RULE_ITERATIONS:
            try:
                d = date(year, month, day)
                if start.date() <= d <= until_date:
                    dates.append(d)
            except ValueError:
                pass
            year += step
            iterations += 1

    else:
        logger.debug(f"visitessen: unknown freq '{freq}', using start only")
        return [(start, end)]

    if max_count is not None:
        dates = dates[:max_count]

    out: List[Tuple[datetime, Optional[datetime]]] = []
    for d in dates:
        occ_start = datetime.combine(d, start.time())
        occ_end = occ_start + duration if duration is not None else None
        out.append((occ_start, occ_end))
    return out


def _collect_occurrences(
    intervals: List[Dict], window_start: datetime, horizon_end: datetime
) -> List[Tuple[datetime, Optional[datetime]]]:
    """All occurrences inside the window, chronological, unique by start, capped."""
    seen: set = set()
    occurrences: List[Tuple[datetime, Optional[datetime]]] = []
    for interval in intervals or []:
        if not isinstance(interval, dict):
            continue
        try:
            expanded = _expand_interval(interval, horizon_end)
        except Exception as exc:
            logger.debug(f"visitessen interval expansion failed: {exc}")
            continue
        for occ_start, occ_end in expanded:
            if occ_start < window_start or occ_start > horizon_end:
                continue
            if occ_start in seen:
                continue
            seen.add(occ_start)
            occurrences.append((occ_start, occ_end))
    occurrences.sort(key=lambda pair: pair[0])
    return occurrences[:MAX_OCCURRENCES_PER_ITEM]


# ──────────────────────────────── parsing ────────────────────────────────────


def parse_visitessen_items(items: List[Dict], now: Optional[datetime] = None) -> List[Dict]:
    """Turn raw API items into event dicts (one per occurrence). Pure, no network.

    ``now`` is a naive Berlin datetime; defaults to the current Berlin time.
    """
    if now is None:
        now = datetime.now(_BERLIN).replace(tzinfo=None)
    window_start = datetime.combine(now.date(), time.min)
    horizon_end = datetime.combine(now.date() + timedelta(days=HORIZON_DAYS), time.max)

    events: List[Dict] = []
    seen_ids: set = set()
    skipped = 0

    for item in items or []:
        try:
            item_events = _parse_item(item, window_start, horizon_end)
        except Exception as exc:
            logger.debug(f"visitessen item parse error: {exc}")
            skipped += 1
            continue
        if not item_events:
            skipped += 1
            continue
        for event in item_events:
            if event["canonical_id"] not in seen_ids:
                seen_ids.add(event["canonical_id"])
                events.append(event)

    logger.info(
        f"visitessen: {len(events)} occurrences from {len(items or [])} items "
        f"({skipped} items without usable dates skipped)"
    )
    return events


def _parse_item(item: Dict, window_start: datetime, horizon_end: datetime) -> List[Dict]:
    """Build one event dict per occurrence of a single API item."""
    if not isinstance(item, dict):
        return []

    global_id = str(item.get("global_id") or "").strip()
    title = sanitize_title(str(item.get("title") or ""))
    if not global_id or not title:
        return []
    title = title[:500]

    attributes = {
        str(a.get("key")): str(a.get("value") or "")
        for a in item.get("attributes") or []
        if isinstance(a, dict) and a.get("key")
    }
    if attributes.get("DETAILS_ABGESAGT", "").lower() == "true":
        logger.debug(f"visitessen: skipping cancelled event {global_id} '{title[:40]}'")
        return []

    occurrences = _collect_occurrences(item.get("timeIntervals"), window_start, horizon_end)
    if not occurrences:
        return []

    categories = [str(c).strip() for c in item.get("categories") or [] if str(c).strip()]
    texts = item.get("texts") or []

    # Venue / address
    venue_name = sanitize_title(
        str(item.get("name") or item.get("company") or item.get("street") or "").strip()
    ) or None
    street = str(item.get("street") or "").strip()
    zip_code = str(item.get("zip") or "").strip()
    city = str(item.get("city") or "").strip() or "Essen"
    locality = " ".join(part for part in (zip_code, city) if part)
    address_text = ", ".join(part for part in (street, locality) if part) or None

    lat, lon = _extract_coords(item.get("geo"))
    image_url = _extract_image(item.get("media_objects"))
    description = _extract_description(texts)
    price_text = _extract_price(texts, attributes)
    kids = _detect_kids(title, categories)
    indoor_outdoor = _detect_indoor_outdoor(categories)
    category = categories[0][:100] if categories else None
    source_url = build_detail_url(global_id, title)

    events: List[Dict] = []
    for start_at, end_at in occurrences:
        event: Dict = {
            "canonical_id": _make_canonical(global_id, start_at),
            "title": title,
            "short_description": description,
            "start_at": start_at,
            "end_at": end_at,
            "venue_name": venue_name,
            "address_text": address_text,
            "city": city,
            "source_url": source_url,
            "source_name": SOURCE_NAME,
            "indoor_outdoor": indoor_outdoor,
            "kids_suitable": kids,
            "price_text": price_text,
            "category": category,
            "image_url": image_url,
            "is_permanent_offer": False,
        }
        if lat is not None and lon is not None:
            event["lat"] = lat
            event["lon"] = lon
        events.append(event)
    return events


# ──────────────────────────────── fetching ───────────────────────────────────


async def _fetch_token(client: httpx.AsyncClient) -> Optional[str]:
    resp = await client.get(SEARCH_PAGE_URL)
    resp.raise_for_status()
    return extract_meta_token(resp.text)


async def _fetch_all_items(client: httpx.AsyncClient, token: str, today: date) -> List[Dict]:
    """Page through the Meta API. Raises on any non-200 page."""
    base_params = {
        "experience": API_EXPERIENCE,
        "type": "Event",
        "startdate": today.strftime("%d.%m.%Y"),
        "enddate": (today + timedelta(days=HORIZON_DAYS)).strftime("%d.%m.%Y"),
        "q": API_QUERY,
        "template": API_TEMPLATE,
        "licensekey": token,
        "limit": API_PAGE_SIZE,
    }
    items: List[Dict] = []
    for page in range(API_MAX_PAGES):
        offset = page * API_PAGE_SIZE
        resp = await client.get(API_URL, params={**base_params, "offset": offset})
        resp.raise_for_status()
        data = resp.json()
        page_items = data.get("items") or []
        items.extend(page_items)
        count = int(data.get("count") or len(page_items))
        overall = int(data.get("overallcount") or 0)
        logger.debug(f"visitessen: page {page} offset={offset} count={count} overall={overall}")
        if count < API_PAGE_SIZE or offset + count >= overall:
            break
        await asyncio.sleep(0.3)
    return items


async def fetch_visitessen_events() -> List[Dict]:
    """Fetch all upcoming visitessen events (token + paged API). Never raises."""
    now = datetime.now(_BERLIN).replace(tzinfo=None)
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        try:
            token = await _fetch_token(client)
        except Exception as exc:
            logger.error(f"visitessen token fetch failed: {exc}")
            return []
        if not token:
            logger.error("visitessen: META_TOKEN not found in search page")
            return []

        try:
            items = await _fetch_all_items(client, token, now.date())
        except Exception as exc:
            logger.error(f"visitessen API fetch failed: {exc}")
            return []

    logger.info(f"visitessen: {len(items)} raw items fetched")
    return parse_visitessen_items(items, now=now)


async def sync_visitessen(db: Session):
    """Sync visitessen.de events to database."""
    events_data = await fetch_visitessen_events()
    return sync_events_to_db(db, events_data, SOURCE_NAME)
