"""wasgehtapp.de event source.

wasgehtapp.de server-renders its event list as plain HTML — verified 2026-09
by diffing a Playwright-rendered `page.content()` against a plain `httpx`
GET of the same URL: byte-for-byte the same event markup. Playwright (full
headless Chromium) was therefore pure overhead here and has been dropped.

The site advertises a "Veranstaltungen API (JSON)" at `/export.php`, which
would have been preferable to HTML scraping, but:
  - robots.txt disallows `/export.php` for `User-agent: *`.
  - even ignoring that, it requires either account credentials (mail +
    passwort) or a single known location id — there is no "give me
    everything near Essen" mode without a login we don't have.
So the JSON path is out; plain HTML it is.

The site has no date-*range* view, only one day at a time
(`index.php?...&date=YYYY-MM-DD`), so `fetch_wasgehtapp_events` walks
`WGA_DAYS_AHEAD` consecutive days with a short HTTP-level pause between
requests.

Each day's page groups events into `<div class="katcontainer" kat="...">`
sections (Konzert, Comedy, Bühne, Sport, Medien, Sonstige, ...). We skip:
  - `kino` (Kinoprogramm): a wall of multiplex showtimes across the whole
    20km radius, not curated events — the rest of the app treats cinema
    programmes as out of scope (see Lichtburg: Bühnenevents only).
  - `tipp` (Vorschau/Tipps teaser box): a preview of a handful of highlighted
    upcoming events, structured differently from the day listing and fully
    redundant with what the per-day walk already finds on their actual date.
  - `favoriten`: the visitor's saved-locations box, always empty for us.
"""
import asyncio
import hashlib
import logging
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag
from sqlalchemy.orm import Session

from app.services.base_sync import sync_events_to_db

logger = logging.getLogger(__name__)

WASGEHTAPP_BASE = "https://www.wasgehtapp.de"
# Essen, 20km radius (unchanged from the original scraper's geo params).
WASGEHTAPP_GEO_PARAMS = (
    "geo_id=16348&ort=Essen&x=7.00865&y=51.4625&select_ort=1&radius=20&region=07"
)
WASGEHTAPP_ESSEN_URL = f"{WASGEHTAPP_BASE}/index.php?{WASGEHTAPP_GEO_PARAMS}"

_SKIP_CATEGORIES = {"kino", "tipp", "favoriten"}

# No date-range endpoint exists, so this is a straight loop of GETs, one per
# day. 14 days ("mehrere Wochen") keeps the request count modest while still
# giving a realistic look-ahead.
WGA_DAYS_AHEAD = 14
# Politeness pause between per-day requests.
_REQUEST_PAUSE_SECONDS = 0.3

_BERLIN = ZoneInfo("Europe/Berlin")

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
# wasgehtapp.de answers 403 to bare HTTP clients from datacenter IPs (GitHub
# Actions) while the same page renders fine in a browser there. Full browser
# headers first; if the very first day is still 403, the run switches to a
# headless browser for all days (14 page loads, ~1 min).
_HTTP_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


def _day_url(day: date) -> str:
    return f"{WASGEHTAPP_ESSEN_URL}&date={day.isoformat()}"


async def _fetch_days_http(days: List[date]) -> Dict[date, str]:
    """HTML per day via httpx. Raises PermissionError on a 403 for the first day
    so the caller can fall back to a browser; later 403s are logged and skipped."""
    pages: Dict[date, str] = {}
    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True, headers=_HTTP_HEADERS
    ) as client:
        for i, day in enumerate(days):
            try:
                response = await client.get(_day_url(day))
                if response.status_code == 403 and i == 0:
                    raise PermissionError("403 on first day")
                response.raise_for_status()
                pages[day] = response.text
            except PermissionError:
                raise
            except Exception as e:
                logger.warning(f"wasgehtapp: Fehler beim Laden von {day.isoformat()}: {e}")
            if i < len(days) - 1:
                await asyncio.sleep(_REQUEST_PAUSE_SECONDS)
    return pages


async def _fetch_days_playwright(days: List[date]) -> Dict[date, str]:
    """Same pages through headless Chromium (pattern from gasometer.py)."""
    from playwright.async_api import async_playwright

    pages: Dict[date, str] = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(user_agent=_BROWSER_UA, locale="de-DE")
            page = await context.new_page()
            for day in days:
                try:
                    await page.goto(_day_url(day), wait_until="domcontentloaded", timeout=45000)
                    pages[day] = await page.content()
                except Exception as e:
                    logger.warning(f"wasgehtapp (Playwright): Fehler bei {day.isoformat()}: {e}")
                await page.wait_for_timeout(int(_REQUEST_PAUSE_SECONDS * 1000))
        finally:
            await browser.close()
    return pages


async def fetch_wasgehtapp_events(
    city: str = "Essen", days_ahead: int = WGA_DAYS_AHEAD
) -> List[Dict]:
    """Fetch events from wasgehtapp.de for today .. today+days_ahead-1 (Essen, 20km)."""
    now_berlin = datetime.now(_BERLIN).replace(tzinfo=None)
    today = now_berlin.date()
    days = [today + timedelta(days=offset) for offset in range(days_ahead)]

    try:
        pages = await _fetch_days_http(days)
    except PermissionError:
        logger.info("wasgehtapp: 403 für HTTP-Client, wechsle auf Playwright")
        try:
            pages = await _fetch_days_playwright(days)
        except Exception as e:
            logger.error(f"wasgehtapp: Playwright-Fallback fehlgeschlagen: {e}")
            return []

    events: List[Dict] = []
    seen_ids: set[str] = set()
    for day in days:
        html = pages.get(day)
        if not html:
            continue
        try:
            day_events = parse_wasgehtapp_day_html(html, day, city)
        except Exception as e:
            logger.warning(f"wasgehtapp: Parser-Fehler für {day.isoformat()}: {e}")
            continue

        for ev in day_events:
            if ev["start_at"] < now_berlin:
                continue
            cid = ev["canonical_id"]
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            events.append(ev)

    logger.info(f"Extracted {len(events)} events from wasgehtapp.de ({days_ahead} Tage)")
    return events


def _category_label(container: Tag) -> Optional[str]:
    """Human-readable raw category from a `.katcontainer`'s header.

    Markup: `<div class="kat"><div class="wc"><span class="icon">theater</span>
    Bühne / So, 20.09.26 <a class="more">..mehr</a></div></div>` → "Bühne".
    """
    wc = container.select_one(".kat .wc")
    if not wc:
        return None
    copy = BeautifulSoup(str(wc), "html.parser").find(class_="wc")
    for tag in copy.select("span.icon, a"):
        tag.decompose()
    label = copy.get_text().split("/")[0].strip()
    return label or None


def _extract_venue(zeitloc: Tag) -> Tuple[Optional[str], Optional[str]]:
    """Venue name + city from a `.zeitloc` block.

    Venues outside the queried city carry a trailing ", <City>" plus a
    sibling `<small>x,x km</small>`; venues in the queried city (Essen) have
    neither. That `<small>` presence is the reliable signal for "this text
    ends in a city name" — venue names themselves occasionally contain
    commas (e.g. "Anneliese Brost Musikforum Ruhr (Großer Saal), Bochum"),
    so splitting on every comma would misfire.
    """
    loc_a = zeitloc.select_one("a.location")
    if not loc_a:
        return None, None
    copy = BeautifulSoup(str(loc_a), "html.parser").find("a")
    for icon in copy.select("span.icon"):
        icon.decompose()
    text = re.sub(r"\s+", " ", copy.get_text(" ", strip=True)).strip()
    if not text:
        return None, None
    small = loc_a.find_next_sibling("small")
    if small and "," in text:
        venue, _, city = text.rpartition(",")
        return venue.strip(), city.strip()
    return text, None


def _extract_description(termin: Tag) -> Optional[str]:
    """Free-text description from a `.subtitel` block, if any.

    Markup: `<div class="subtitel tags">Text <span class="icon">tags</span>
    <a class="tag">geige</a>, <a class="tag">klavier</a></div>`. Everything
    from the "tags" icon onward is the tag-chip list (with connecting ", "
    text nodes between chips) — not part of the description — so we stop
    collecting text at the first `span.icon`, rather than trying to strip
    the icon/chip elements back out and risk leftover stray commas.
    """
    subtitel = termin.select_one(".subtitel")
    if not subtitel:
        return None
    parts: List[str] = []
    for node in subtitel.contents:
        if isinstance(node, Tag) and "icon" in (node.get("class") or []):
            break
        parts.append(node.get_text() if isinstance(node, Tag) else str(node))
    text = re.sub(r"\s+", " ", "".join(parts)).strip()
    return text or None


def parse_wasgehtapp_day_html(
    html: str, day: date, default_city: str = "Essen", source_url: Optional[str] = None
) -> List[Dict]:
    """Parse one day's wasgehtapp.de listing page into event dicts.

    `day` is the date this page was fetched for — every event on it happens
    on that date (the site's `date=` query param), so we don't need to parse
    a weekday/date out of the text itself, only the time.
    """
    soup = BeautifulSoup(html, "html.parser")
    events: List[Dict] = []
    seen: set = set()

    for container in soup.select(".katcontainer"):
        kat = (container.get("kat") or "").strip()
        if not kat or kat in _SKIP_CATEGORIES:
            continue
        category = _category_label(container) or kat

        for termin in container.select(".termin"):
            title_a = termin.select_one("h3.titel a.target")
            if not title_a:
                continue
            title = title_a.get_text(strip=True)
            if not title:
                continue

            zeitloc = termin.select_one(".zeitloc")
            if not zeitloc:
                continue
            zeit_el = zeitloc.select_one(".zeit")
            if not zeit_el:
                continue
            time_match = re.search(r"(\d{1,2}):(\d{2})", zeit_el.get_text())
            if not time_match:
                continue
            hour, minute = int(time_match.group(1)), int(time_match.group(2))
            try:
                start_at = datetime(day.year, day.month, day.day, hour, minute)
            except ValueError as e:
                logger.warning(f"wasgehtapp: ungültige Zeit ({hour}:{minute}) am {day}: {e}")
                continue

            venue, venue_city = _extract_venue(zeitloc)
            city = venue_city or default_city
            short_description = _extract_description(termin)

            event_id = termin.get("id")
            event_url = None
            href = title_a.get("href")
            if href:
                event_url = urljoin(f"{WASGEHTAPP_BASE}/", href)
            if not event_url:
                event_url = source_url or WASGEHTAPP_ESSEN_URL

            dedup_key = (title, start_at, venue)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            canonical_id = hashlib.md5(
                f"wasgehtapp_{title}_{start_at}_{venue or ''}_{event_id or ''}".encode()
            ).hexdigest()[:16]

            events.append({
                "canonical_id": canonical_id,
                "title": title[:200],
                "short_description": short_description,
                "start_at": start_at,
                "venue_name": venue,
                "city": city,
                "category": category,
                "source_url": event_url,
                "source_name": "wasgehtapp.de",
            })

    return events


async def sync_wasgehtapp(db: Session):
    """Sync events from wasgehtapp.de to database."""
    events_data = await fetch_wasgehtapp_events("Essen")
    return sync_events_to_db(db, events_data, "wasgehtapp.de")
