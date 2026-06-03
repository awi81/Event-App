"""Schatzkammer St. Ludgerus Werden — event source via WordPress post scraping.

The site is a small WordPress installation with no dedicated event plugin.
Events are published as regular posts on the homepage (typically 2–5 visible).
The homepage shows the 3 most recent posts; each post usually names an upcoming
event date in its title or body text.

robots.txt only disallows /wp-admin/ — all post pages are fully crawlable.
Volume is low (<5/month) but location-relevance for Essen-Werden is maximal.
"""
import hashlib
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.services.base_sync import sync_events_to_db

logger = logging.getLogger(__name__)

HOME_URL = "https://www.schatzkammer-werden.de/"

# Venue coordinates (Nominatim verified: 51.3878809, 7.0051599)
VENUE_LAT = 51.3878809
VENUE_LON = 7.0051599

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

_MONTH_MAP = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4,
    "mai": 5, "juni": 6, "juli": 7, "august": 8, "september": 9,
    "oktober": 10, "november": 11, "dezember": 12,
}

# Patterns for German dates: "28. Juni 2026", "28.6.2026"
_GERMAN_DATE_RE = re.compile(
    r"(\d{1,2})\.\s*(Januar|Februar|März|Maerz|April|Mai|Juni|Juli|August|"
    r"September|Oktober|November|Dezember)\s+(\d{4})",
    re.IGNORECASE,
)
_NUMERIC_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")

# Time pattern: "15.30 Uhr", "15:30 Uhr", "15.30 Uhr"
_TIME_RE = re.compile(r"(\d{1,2})[.:](\d{2})\s*Uhr")

# Skip non-event posts
_SKIP_KEYWORDS = [
    "impressum", "datenschutz", "hausordnung", "öffnungszeit", "oeffnungszeit",
    "sitemap", "newsletter", "restaurierung abgeschlossen", "verst",
]

_KIDS_KEYWORDS = ["kind", "kinder", "familie", "jugend", "schule"]


def _parse_german_date(text: str) -> Optional[datetime]:
    """Extract the first date from German text."""
    # Try full German date: "28. Juni 2026"
    m = _GERMAN_DATE_RE.search(text)
    if m:
        day = int(m.group(1))
        month = _MONTH_MAP.get(m.group(2).lower(), 0)
        year = int(m.group(3))
        if month:
            # Look for time near the date match
            hour, minute = 0, 0
            vicinity = text[max(0, m.start() - 50): m.end() + 100]
            t_match = _TIME_RE.search(vicinity)
            if t_match:
                hour = int(t_match.group(1))
                minute = int(t_match.group(2))
            try:
                return datetime(year, month, day, hour, minute)
            except ValueError:
                pass

    # Try numeric: "28.6.2026"
    m2 = _NUMERIC_DATE_RE.search(text)
    if m2:
        day, month, year = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
        try:
            return datetime(year, month, day)
        except ValueError:
            pass

    return None


_EVENT_TITLE_KEYWORDS = [
    "führung", "fuehrung", "veranstaltung", "vortrag", "workshop",
    "fest", "tag", "konzert", "lesung", "ausstellung", "öffnet", "oeffnet",
    "sonntagsführung", "museumstag", "ludgerusfest",
]

_NON_EVENT_TITLE_KEYWORDS = [
    "fragen", "antworten", "impressum", "sitemap", "newsletter",
    "hausordnung", "datenschutz",
]


def _is_event_post(title: str, body: str) -> bool:
    """Return True if this post looks like an actual event announcement."""
    title_lower = title.lower()
    if any(kw in title_lower for kw in _SKIP_KEYWORDS):
        return False
    if any(kw in title_lower for kw in _NON_EVENT_TITLE_KEYWORDS):
        return False
    # Must either match an event keyword or have an explicit date in the title
    has_event_keyword = any(kw in title_lower for kw in _EVENT_TITLE_KEYWORDS)
    has_date_in_title = bool(_GERMAN_DATE_RE.search(title) or _NUMERIC_DATE_RE.search(title))
    return has_event_keyword or has_date_in_title


def _detect_kids(title: str, body: str) -> str:
    combined = (title + " " + body).lower()
    if any(kw in combined for kw in _KIDS_KEYWORDS):
        return "likely"
    return "unknown"


def _make_canonical(title: str, url: str) -> str:
    return hashlib.md5(f"schatzkammer_{title}_{url}".encode()).hexdigest()[:16]


async def _fetch_post(client: httpx.AsyncClient, url: str) -> Optional[Dict]:
    """Fetch and parse a single post page, return event dict or None."""
    try:
        resp = await client.get(url)
        resp.raise_for_status()
    except Exception as exc:
        logger.debug(f"Schatzkammer post fetch failed {url}: {exc}")
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    # Title: find the article container first, then the heading inside it
    article = soup.find("article") or soup.find("main")
    h_el = None
    if article:
        h_el = article.find(["h1", "h2", "h3"])
    if not h_el:
        # Fallback: second h2 on the page (first is usually site title)
        all_h2 = soup.find_all("h2")
        h_el = all_h2[1] if len(all_h2) > 1 else (all_h2[0] if all_h2 else None)
    title = h_el.get_text(strip=True) if h_el else ""
    if not title:
        return None
    body_text = article.get_text(" ", strip=True) if article else soup.get_text(" ", strip=True)

    if not _is_event_post(title, body_text):
        return None

    start_at = _parse_german_date(title + " " + body_text)

    # Short description: first meaningful paragraph after the heading
    desc_paras = []
    if article:
        for p in article.find_all("p"):
            txt = p.get_text(strip=True)
            if txt and len(txt) > 30:
                desc_paras.append(txt)
    description = " ".join(desc_paras)[:500] if desc_paras else None

    # Price
    price_text: Optional[str] = None
    price_match = re.search(
        r"(Eintritt|Kostenbeitrag|Erwachsene|Preis)[:\s]+([^\n]{3,80})",
        body_text, re.IGNORECASE
    )
    if price_match:
        price_text = price_match.group(0).strip()[:100]

    kids = _detect_kids(title, body_text)
    canonical = _make_canonical(title, url)

    return {
        "canonical_id": canonical,
        "title": title,
        "short_description": description,
        "start_at": start_at,
        "venue_name": "Schatzkammer St. Ludgerus",
        "city": "Essen",
        "lat": VENUE_LAT,
        "lon": VENUE_LON,
        "source_url": url,
        "source_name": "Schatzkammer Werden",
        "indoor_outdoor": "indoor",
        "kids_suitable": kids,
        "price_text": price_text,
        "category": "ausstellung",
    }


def _extract_post_links(html: str) -> List[str]:
    """Extract post URLs from the Schatzkammer homepage."""
    soup = BeautifulSoup(html, "lxml")

    # The homepage shows recent posts as h2 links (thumbnail + title).
    # We look for internal links that aren't navigation/utility pages.
    skip_patterns = {
        "/impressum", "/datenschutz", "/sitemap", "/shop", "/restaurierung",
        "/oeffnungszeiten", "/hausordnung",
    }
    skip_prefixes = ("/category/", "/tag/", "/author/")

    seen: set = set()
    links: List[str] = []

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if not href.startswith("https://www.schatzkammer-werden.de/"):
            continue
        path = href.replace("https://www.schatzkammer-werden.de", "")
        if any(skip in path for skip in skip_patterns):
            continue
        if path.startswith(skip_prefixes):
            continue
        # Must look like a post slug (no query params, not root)
        if path in ("/", "") or "?" in path or "#" in path:
            continue
        if href not in seen:
            seen.add(href)
            links.append(href)

    # Also include /oeffentliche-fuehrung-… if present (the recurring event page)
    return links


def parse_schatzkammer_homepage_links(html: str) -> List[str]:
    """Public helper for testing."""
    return _extract_post_links(html)


async def fetch_schatzkammer_events() -> List[Dict]:
    """Fetch Schatzkammer events by crawling homepage post links."""
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        try:
            resp = await client.get(HOME_URL)
            resp.raise_for_status()
        except Exception as exc:
            logger.error(f"Schatzkammer homepage fetch failed: {exc}")
            return []

        post_links = _extract_post_links(resp.text)
        logger.info(f"Schatzkammer: {len(post_links)} post links found")

        events: List[Dict] = []
        for url in post_links[:10]:  # low volume site, capped at 10
            import asyncio
            await asyncio.sleep(0.5)
            event = await _fetch_post(client, url)
            if event:
                events.append(event)

        logger.info(f"Schatzkammer: {len(events)} events extracted")
        return events


async def sync_schatzkammer_werden(db: Session):
    """Sync Schatzkammer Werden events to database."""
    events_data = await fetch_schatzkammer_events()
    return sync_events_to_db(db, events_data, "Schatzkammer Werden")
