import httpx
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
import hashlib
import json
import logging
import re

from app.services.base_sync import sync_events_to_db, to_berlin_naive

logger = logging.getLogger(__name__)

RAUSGEGANGEN_BASE = "https://rausgegangen.de"

async def fetch_rausgegangen_events(city: str = "essen") -> List[Dict]:
    """Fetch events from Rausgegangen website using Playwright."""
    try:
        # Try Playwright first (for JavaScript-rendered content)
        events = await fetch_with_playwright(city)
        if events:
            logger.info(f"Found {len(events)} events with Playwright")
            return events
    except Exception as e:
        logger.warning(f"Playwright failed: {e}")

    # Fallback to HTTP
    return await fetch_with_http(city)

async def fetch_with_playwright(city: str) -> List[Dict]:
    """Fetch events using Playwright browser."""
    from playwright.async_api import async_playwright

    url = f"{RAUSGEGANGEN_BASE}/{city}/"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            # 'domcontentloaded' instead of 'networkidle' — rausgegangen.de
            # holds persistent background fetches that never settle.
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(4000)

            # Scroll down to load more events
            for _ in range(5):
                await page.keyboard.press("End")
                await page.wait_for_timeout(800)

            # Get full HTML for structured parsing (preserves venues)
            html = await page.content()
            text = await page.inner_text('body')
            await browser.close()

            # Try HTML parsing first (better venue extraction via JSON-LD / selectors)
            events = parse_rausgegangen_html(html, city)
            if events:
                logger.info(f"Playwright HTML parsing: {len(events)} events")
                return events

            # Fallback to text extraction
            events = extract_events_from_text(text, city)
            # Enrich each text-extracted event with an image_url from the HTML
            # by matching titles to <a> anchors that contain an <img>.
            try:
                _attach_images_from_html(events, html)
            except Exception as e:
                logger.debug(f"image enrichment failed: {e}")
            return events
        except Exception as e:
            logger.error(f"Playwright error: {e}")
            await browser.close()
            raise

def extract_events_from_text(text: str, city: str) -> List[Dict]:
    """Extract events from page text content."""
    events = []
    seen = set()
    lines = text.split('\n')

    months = {'Jan': 1, 'Feb': 2, 'Mär': 3, 'Apr': 4, 'Mai': 5, 'Jun': 6,
              'Jul': 7, 'Aug': 8, 'Sep': 9, 'Okt': 10, 'Nov': 11, 'Dez': 12}
    skip_words = ['eintritt', 'verlosung', '€', 'uhr', 'tagestipp', 'präsentiert',
                  'kostenlos', 'abgesagt']
    date_inline_re = re.compile(
        r'((?:Mo|Di|Mi|Do|Fr|Sa|So|Heute|Morgen),?\s*)?'
        r'(\d{1,2})\.\s*(\w+)\s*\|\s*(\d{1,2}):(\d{2})\s*(?:Uhr)?'
    )

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        match = date_inline_re.search(line)

        if match:
            day = int(match.group(2))
            month = months.get(match.group(3)[:3], 3)
            hour = int(match.group(4))
            minute = int(match.group(5))
            year = datetime.now().year
            try:
                start_at = datetime(year, month, day, hour, minute)
            except ValueError:
                i += 1
                continue

            # Rausgegangen sometimes glues the title directly behind the time
            # on the same line ("Sa, 30. Mai | 10:00Alexander Lackmann ..."),
            # sometimes puts it on the next line. Check the tail of the date
            # line first.
            tail = line[match.end():].strip(" |")
            tail = _clean_title(tail)
            title = tail if len(tail) >= 5 else None

            venue = None
            price_text = None

            for j in range(i + 1, min(i + 8, len(lines))):
                next_line = lines[j].strip()
                if not next_line or len(next_line) < 3:
                    continue
                low = next_line.lower()
                if _PRICE_RE.match(next_line):
                    price_text = next_line
                    continue
                if low.startswith('eintritt'):
                    price_text = next_line
                    continue
                if any(x in low for x in skip_words):
                    continue
                if re.match(r'^[\d,]+[\s€]*$', next_line):
                    continue

                if not title and 5 < len(next_line) < 150:
                    title = next_line
                elif title and not venue and len(next_line) < 80:
                    venue = next_line
                    break

            # Fallback: venue from "im/in der/bei <Name>" inside the title
            if title and not venue:
                venue_match = re.search(
                    r'\b(?:im|in der|in|bei|auf dem|auf der|am|@)\s+([A-ZÄÖÜ][a-zäöüß\s\-]+(?:[A-ZÄÖÜ][a-zäöüß\s\-]*)*)',
                    title,
                )
                if venue_match:
                    venue = venue_match.group(1).strip()

            if title:
                title = _clean_title(title)
            dedup_key = (title, start_at) if title else None
            if not title or len(title) < 5 or dedup_key in seen:
                i += 1
                continue

            seen.add(dedup_key)
            canonical_id = hashlib.md5(f"rausgegangen_{title}_{start_at}_{city}".encode()).hexdigest()[:16]
            events.append({
                "canonical_id": canonical_id,
                "title": title[:200],
                "start_at": start_at,
                "venue_name": venue,
                "city": city.capitalize(),
                "source_url": f"{RAUSGEGANGEN_BASE}/{city}/",
                "source_name": "Rausgegangen",
                "price_text": price_text,
            })

        i += 1

    logger.info(f"Extracted {len(events)} events from text")
    return events

async def fetch_with_http(city: str) -> List[Dict]:
    """Fallback: Fetch events using HTTP (static HTML)."""
    url = f"{RAUSGEGANGEN_BASE}/{city}/"

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            logger.info(f"Fetched URL: {response.url}")
            return parse_rausgegangen_html(response.text, city)
        except Exception as e:
            logger.error(f"Error fetching Rausgegangen: {e}")
            return []

def parse_rausgegangen_html(html: str, city: str) -> List[Dict]:
    """Parse HTML to extract event data."""
    soup = BeautifulSoup(html, 'lxml')
    events = []

    # Strategy 1: Try JSON-LD structured data first
    json_ld_events = extract_json_ld(soup, city)
    if json_ld_events:
        logger.info(f"Found {len(json_ld_events)} events from JSON-LD")
        return json_ld_events

    # Strategy 2: Fallback to generic event selectors
    logger.info("No JSON-LD found, trying generic selectors")
    event_cards = soup.select('.event-card, .veranstaltung-item, article, [class*="event-item"]')

    for card in event_cards:
        try:
            event = extract_event_from_card(card, city)
            if event:
                events.append(event)
        except Exception as e:
            logger.warning(f"Error parsing event card: {e}")
            continue

    # Strategy 3: Look for any links that might be events
    if not events:
        events = extract_from_links(soup, city)

    return events

def extract_json_ld(soup, city: str) -> List[Dict]:
    """Extract events from JSON-LD structured data."""
    events = []
    scripts = soup.find_all('script', type='application/ld+json')

    for script in scripts:
        try:
            data = json.loads(script.string)
            # Handle array or single object
            items = data if isinstance(data, list) else [data]

            for item in items:
                if item.get('@type') == 'Event':
                    event = convert_json_ld_event(item, city)
                    if event:
                        events.append(event)
        except (json.JSONDecodeError, AttributeError) as e:
            logger.debug(f"JSON-LD parse error: {e}")
            continue

    return events

def _extract_image_url(image_field) -> Optional[str]:
    """Pull the first usable image URL out of a JSON-LD 'image' field.

    The Schema.org Event spec allows: string, ImageObject dict, list of either.
    """
    if not image_field:
        return None
    if isinstance(image_field, str):
        return image_field
    if isinstance(image_field, dict):
        url = image_field.get('url') or image_field.get('@id') or image_field.get('contentUrl')
        return url if isinstance(url, str) else None
    if isinstance(image_field, list) and image_field:
        return _extract_image_url(image_field[0])
    return None


def convert_json_ld_event(item: dict, city: str) -> Optional[Dict]:
    """Convert JSON-LD Event to our format."""
    try:
        name = item.get('name')
        if not name:
            return None

        # Generate canonical ID
        canonical_id = hashlib.md5(f"rausgegangen_{name}_{city}".encode()).hexdigest()[:16]

        # Parse start date
        start_date = item.get('startDate')
        start_at = parse_iso_date(start_date) if start_date else None

        # Location
        location = item.get('location')
        venue_name = None
        address_text = None
        lat = None
        lon = None

        if isinstance(location, dict):
            venue_name = location.get('name')
            address = location.get('address')
            if address and isinstance(address, dict):
                address_text = address.get('streetAddress')
                if not address_text:
                    address_text = str(address)

            geo = location.get('geo')
            if geo and isinstance(geo, dict):
                lat = geo.get('latitude')
                lon = geo.get('longitude')

        # Description
        description = item.get('description', '')[:500]

        # URL
        url = item.get('url')

        # Image
        image_url = _extract_image_url(item.get('image'))

        return {
            "canonical_id": canonical_id,
            "title": name,
            "short_description": description,
            "start_at": start_at,
            "venue_name": venue_name,
            "address_text": address_text,
            "city": city.capitalize(),
            "lat": lat,
            "lon": lon,
            "source_url": url,
            "source_name": "Rausgegangen",
            "image_url": image_url,
        }
    except Exception as e:
        logger.warning(f"Error converting JSON-LD event: {e}")
        return None

def _attach_images_from_html(events: List[Dict], html: str) -> int:
    """For text-extracted events, scan all <a> anchors that contain an <img>,
    extract their visible title heuristically, and attach the image_url to
    matching events. Returns number of events enriched."""
    soup = BeautifulSoup(html, 'lxml')
    title_to_img: dict[str, str] = {}
    for link in soup.find_all('a'):
        img_url = _image_from_node(link)
        if not img_url:
            continue
        text = link.get_text(separator=' ', strip=True)
        if not text:
            continue
        # Keep all words >= 4 chars as a fuzzy signature, lowercase
        words = [w.lower() for w in re.findall(r'\b\w{4,}\b', text)]
        if not words:
            continue
        # Map every word individually so we can score matches
        for w in set(words):
            title_to_img.setdefault(w, img_url)

    enriched = 0
    for ev in events:
        if ev.get('image_url'):
            continue
        title = (ev.get('title') or '').lower()
        for w in re.findall(r'\b\w{5,}\b', title):
            if w in title_to_img:
                ev['image_url'] = title_to_img[w]
                enriched += 1
                break
    return enriched


def _image_from_node(node) -> Optional[str]:
    """Find the first usable image URL inside a BS4 node."""
    img_el = node.find('img') if node else None
    if not img_el:
        return None
    src = img_el.get('src') or img_el.get('data-src') or img_el.get('data-srcset')
    if not src or not isinstance(src, str):
        return None
    src = src.split(' ')[0]  # srcset → first url
    if src.startswith('//'):
        src = 'https:' + src
    elif src.startswith('/'):
        src = RAUSGEGANGEN_BASE + src
    return src if src.startswith('http') else None


def extract_event_from_card(card, city: str) -> Optional[Dict]:
    """Extract event data from a generic card element."""
    # Try to find title
    title_elem = card.select_one('h2, h3, h4, [class*="title"], [class*="name"]')
    if not title_elem:
        # Maybe it's a link with text
        link = card.find('a')
        if link and link.get_text(strip=True):
            title = link.get_text(strip=True)
        else:
            return None
    else:
        title = title_elem.get_text(strip=True)

    if not title or len(title) < 3:
        return None

    # Generate canonical ID
    canonical_id = hashlib.md5(f"rausgegangen_{title}_{city}".encode()).hexdigest()[:16]

    # Extract date
    date_elem = card.select_one('[class*="date"], time, [class*="datum"], [class*="zeit"]')
    start_at = parse_date(date_elem.get_text(strip=True) if date_elem else None)

    # Extract venue
    venue_elem = card.select_one('[class*="location"], [class*="ort"], [class*="venue"], [class*="place"]')
    venue_name = venue_elem.get_text(strip=True) if venue_elem else None

    # Extract URL
    link = card.find('a', href=True)
    source_url = link.get('href') if link else None
    if source_url and not source_url.startswith('http'):
        source_url = RAUSGEGANGEN_BASE + source_url

    # Extract description
    desc_elem = card.select_one('p, [class*="description"], [class*="beschreibung"], [class*="text"]')
    short_description = desc_elem.get_text(strip=True)[:500] if desc_elem else None

    return {
        "canonical_id": canonical_id,
        "title": title,
        "short_description": short_description,
        "start_at": start_at,
        "venue_name": venue_name,
        "city": city.capitalize(),
        "source_url": source_url,
        "source_name": "Rausgegangen",
        "image_url": _image_from_node(card),
    }

_DATE_LINE_RE = re.compile(
    r'((?:Mo|Di|Mi|Do|Fr|Sa|So|Heute|Morgen|Übermorgen),?\s*)?'
    r'\d{1,2}\.\s*(?:Jan|Feb|Mär|Apr|Mai|Jun|Jul|Aug|Sep|Okt|Nov|Dez)\w*'
    r'(?:\s*\d{4})?\s*\|\s*\d{1,2}:\d{2}(?:\s*Uhr)?'
)
# Same as DATE_LINE_RE but tolerating noise glued in front of the weekday:
#   * like-counters / tagestipp-counters: "5Di...", "211Sa..."
#   * sponsor / category labels: "TAGESTIPP22Mo...", "PRÄSENTIERT8Fr..."
_DATE_WITH_PREFIX_RE = re.compile(
    r'(?:TAGESTIPP|PRÄSENTIERT|VERLOSUNG)?\s*\d{0,4}\s*'
    r'((?:Mo|Di|Mi|Do|Fr|Sa|So|Heute|Morgen|Übermorgen),?\s*)?'
    r'\d{1,2}\.\s*(?:Jan|Feb|Mär|Apr|Mai|Jun|Jul|Aug|Sep|Okt|Nov|Dez)\w*'
    r'(?:\s*\d{4})?\s*\|\s*\d{1,2}:\d{2}(?:\s*Uhr)?',
    re.IGNORECASE,
)
_PRICE_RE = re.compile(r'^[\d.,]+\s*€')


def _clean_title(raw: str) -> str:
    """Strip leading date headers (incl. like-counter prefix), trailing
    venue/price tails, and anything after a second date header repeats."""
    if not raw:
        return ""
    text = raw

    # 1. Remove leading date headers (one or more), tolerating a like-counter
    #    prefix like "5Di, 12. Mai | 18:00..." or "211Sa, 17. Okt | 19:00...".
    for _ in range(3):
        stripped = text.strip()
        m = _DATE_WITH_PREFIX_RE.match(stripped)
        if not m:
            break
        text = stripped[m.end():].strip()

    # 2. If a SECOND date appears later in the string (e.g. the text repeats),
    #    cut everything from that point on.
    second = _DATE_WITH_PREFIX_RE.search(text)
    if second and second.start() > 0:
        text = text[:second.start()].strip()

    # 3. Strip trailing price segments / labels.
    text = re.sub(r'\d+[.,]\d+\s*(?:€|EUR)?\s*(?:bis\s*\d+[.,]\d+\s*(?:€|EUR)?)?\s*$', '', text).strip()
    text = re.sub(r'Eintritt\s+frei\s*$', '', text, flags=re.IGNORECASE).strip()
    text = re.sub(r'Tagestipp\s*$', '', text, flags=re.IGNORECASE).strip()
    text = re.sub(r'Verlosung\s*$', '', text, flags=re.IGNORECASE).strip()
    text = re.sub(r'PRÄSENTIERT\d*\s*', '', text).strip()

    # 4. If we still have a monster string (>180 chars), assume it's
    #    unparseable noise and return empty so the caller skips this event.
    if len(text) > 180:
        return ""
    return text


def extract_from_links(soup, city: str) -> List[Dict]:
    """Extract events from event links."""
    import re as _re

    events = []
    seen_titles = set()

    links = soup.select('a[class*="event"]')

    for link in links:
        try:
            href = link.get('href', '')
            if not href:
                continue

            # IMPORTANT: use a separator so text from sibling spans isn't glued
            # together (otherwise titles like "Sa, 30. Mai | 10:00ALEXANDER..."
            # collapse into one unreadable string).
            text = link.get_text(separator='\n', strip=True)
            if len(text) < 10 or len(text) > 500:
                continue

            lines = [l.strip() for l in text.split('\n') if l.strip()]
            date_str = None
            title_lines = []
            venue_name = None
            price_text = None
            seen_date = False

            for line in lines:
                if _DATE_LINE_RE.fullmatch(line) or _DATE_LINE_RE.match(line):
                    date_str = line
                    seen_date = True
                    continue
                low = line.lower()
                if _PRICE_RE.match(line) or low.startswith('eintritt'):
                    price_text = line
                    continue
                if low in ('tagestipp', 'verlosung', 'präsentiert', 'kostenlos', 'abgesagt'):
                    continue
                if not seen_date:
                    # Lines before the date are usually overlay labels - skip
                    continue
                if len(line) > 3:
                    title_lines.append(line)

            if not title_lines:
                continue

            # First line after date is title; remaining shortlines = venue
            title = _clean_title(title_lines[0])
            if not title or len(title) < 3:
                continue
            if len(title_lines) > 1:
                # Pick the shortest remaining line that doesn't look like a category
                candidates = [l for l in title_lines[1:] if 3 < len(l) < 60]
                if candidates:
                    venue_name = candidates[0]

            start_at = parse_german_date(date_str) if date_str else None
            dedup_key = (title, start_at)
            if dedup_key in seen_titles:
                continue
            seen_titles.add(dedup_key)

            canonical_id = hashlib.md5(f"rausgegangen_{title}_{start_at}_{city}".encode()).hexdigest()[:16]
            source_url = href if href.startswith('http') else RAUSGEGANGEN_BASE + href
            image_url = _image_from_node(link)

            events.append({
                "canonical_id": canonical_id,
                "title": title[:200],
                "start_at": start_at,
                "venue_name": venue_name,
                "city": city.capitalize(),
                "source_url": source_url,
                "source_name": "Rausgegangen",
                "price_text": price_text,
                "image_url": image_url,
            })
        except Exception as e:
            logger.debug(f"Error parsing link: {e}")
            continue

    return events

def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse German date formats."""
    if not date_str:
        return None

    # Clean the string
    date_str = date_str.strip()

    formats = [
        "%d.%m.%Y",
        "%d.%m.%Y %H:%M",
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%d. %B %Y",
        "%d. %b %Y",
    ]

    for fmt in formats:
        try:
            return to_berlin_naive(datetime.strptime(date_str, fmt))
        except ValueError:
            continue

    return None

def parse_german_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse German date format like 'Do, 19. Mär | 19:00' or 'Heute, 17. Mär | 20:00 Uhr'."""
    if not date_str:
        return None

    try:
        # Clean the string - extract date part
        date_str = date_str.strip()

        # Remove weekday prefix like "Do, " or "Heute, "
        import re
        date_str = re.sub(r'^(Heute|Morgen|Übermorgen|Mo|Di|Mi|Do|Fr|Sa|So),?\s*', '', date_str)

        # Extract time if present
        time_match = re.search(r'(\d{1,2}):(\d{2})(?:\s*Uhr)?', date_str)
        hour, minute = 0, 0
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))

        # Extract date
        date_match = re.search(r'(\d{1,2})\.\s*(\w+)(?:\s*(\d{4}))?', date_str)
        if date_match:
            day = int(date_match.group(1))
            month_str = date_match.group(2)
            year = date_match.group(3)
            if not year:
                year = datetime.now().year

            # German month names
            months = {
                'Jan': 1, 'Feb': 2, 'Mär': 3, 'Apr': 4, 'Mai': 5, 'Jun': 6,
                'Jul': 7, 'Aug': 8, 'Sep': 9, 'Okt': 10, 'Nov': 11, 'Dez': 12
            }

            month = months.get(month_str[:3], 1)

            return datetime(year, month, day, hour, minute)

        return None
    except Exception as e:
        logger.debug(f"Date parse error: {e}")
        return None

def parse_iso_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO 8601 date format."""
    if not date_str:
        return None

    try:
        # Try various ISO formats
        for fmt in ["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
            try:
                return to_berlin_naive(datetime.strptime(date_str, fmt))
            except ValueError:
                continue

        # Handle timezone manually
        if '+' in date_str:
            date_str = date_str.split('+')[0]
        elif 'Z' in date_str:
            date_str = date_str.replace('Z', '')

        return to_berlin_naive(datetime.fromisoformat(date_str))
    except Exception:
        return None

async def enrich_events_from_detail_pages(events: List[Dict], max_fetches: int = 30) -> List[Dict]:
    """Fetch detail pages to extract venue/location for events missing venue_name."""
    import asyncio

    enriched = 0
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }) as client:
        for event in events:
            if enriched >= max_fetches:
                break

            # Skip events that already have venue or coordinates
            if event.get("venue_name") and event.get("lat"):
                continue

            url = event.get("source_url")
            if not url or url.endswith(f"/{event.get('city', 'essen').lower()}/"):
                continue  # Skip listing URLs, only fetch detail pages

            try:
                response = await client.get(url)
                if response.status_code != 200:
                    continue

                soup = BeautifulSoup(response.text, 'lxml')

                # Strategy 1: JSON-LD on detail page
                for script in soup.find_all('script', type='application/ld+json'):
                    try:
                        data = json.loads(script.string)
                        items = data if isinstance(data, list) else [data]
                        for item in items:
                            if item.get('@type') == 'Event':
                                loc = item.get('location', {})
                                if isinstance(loc, dict):
                                    if not event.get("venue_name") and loc.get('name'):
                                        event["venue_name"] = loc['name']
                                    addr = loc.get('address', {})
                                    if isinstance(addr, dict) and addr.get('streetAddress'):
                                        event["address_text"] = addr['streetAddress']
                                    geo = loc.get('geo', {})
                                    if isinstance(geo, dict):
                                        if geo.get('latitude') and geo.get('longitude'):
                                            event["lat"] = float(geo['latitude'])
                                            event["lon"] = float(geo['longitude'])
                                if not event.get("short_description") and item.get('description'):
                                    event["short_description"] = item['description'][:500]
                                if not event.get("image_url"):
                                    img = _extract_image_url(item.get('image'))
                                    if img:
                                        event["image_url"] = img
                    except (json.JSONDecodeError, ValueError):
                        continue

                # Strategy 2: Look for venue in meta tags or common HTML patterns
                if not event.get("venue_name"):
                    venue_elem = soup.select_one('[class*="location"] [class*="name"], [class*="venue"], [itemprop="location"] [itemprop="name"]')
                    if venue_elem:
                        event["venue_name"] = venue_elem.get_text(strip=True)

                if not event.get("venue_name"):
                    # Try address/location text
                    addr_elem = soup.select_one('[class*="address"], [itemprop="address"], [class*="location-name"]')
                    if addr_elem:
                        text = addr_elem.get_text(strip=True)
                        if len(text) < 100:
                            event["venue_name"] = text

                enriched += 1
                # Rate limiting
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.debug(f"Detail page fetch error for {url}: {e}")
                continue

    logger.info(f"Enriched {enriched} events from detail pages")
    return events


async def sync_rausgegangen(db: Session):
    """Sync events from Rausgegangen to database."""
    events_data = await fetch_rausgegangen_events("essen")

    # Enrich events missing venue data from detail pages
    events_data = await enrich_events_from_detail_pages(events_data)

    return sync_events_to_db(db, events_data, "Rausgegangen")
