"""waddische.de (Werdener Nachrichten) - local Essen-Werden events.

The /termine/ page is the paper's weekly listing, one WordPress page:

    <div id="content"> <article> <div class="entry-content">
      <h3>Treffs, Kurse und Workshops</h3>      <- section
      <h4>Freitag, 18. September</h4>           <- day
      <p><strong>10 bis 12 Uhr:</strong> Tourist Information, Zentrum 60plus.</p>
      ...
      <h3>Adressen und Kontakte</h3>
      <p>Zentrum 60plus</p><p>Heckstraße 27 Infos und Anmeldungen: ...</p>

Only the dated sections become events; "Adressen und Kontakte" supplies the
street address for the venue names used in the entries (a bare "Zentrum
60plus, Essen" geocodes to a different house of that name in Überruhr).
Notdienste, Gottesdienste and the undated exhibition blurbs are skipped.
"""
import hashlib
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.services.base_sync import sync_events_to_db
from app.services.crawler_ua import CRAWLER_USER_AGENT

logger = logging.getLogger(__name__)

WADDISCHE_URL = "https://waddische.de/termine/"
SOURCE_NAME = "Werdener Nachrichten"

_BERLIN = ZoneInfo("Europe/Berlin")

GERMAN_MONTHS = {
    'januar': 1, 'februar': 2, 'märz': 3, 'april': 4,
    'mai': 5, 'juni': 6, 'juli': 7, 'august': 8,
    'september': 9, 'oktober': 10, 'november': 11, 'dezember': 12,
}

# h3 headings whose day blocks are events; everything else is skipped.
_EVENT_SECTION_WORDS = ("treff", "kurs", "workshop", "kinder", "jugend", "bühne", "musik")
_ADDRESS_SECTION_WORD = "adressen"

# "10 Uhr", "19:00 Uhr", "11.45 bis 13.45 Uhr" - one time slot.
_SLOT_RE = re.compile(
    r"(\d{1,2})(?:[.:](\d{2}))?\s*(?:Uhr\s*)?(?:bis\s*(\d{1,2})(?:[.:](\d{2}))?\s*)?Uhr"
)
# The whole leading time block, possibly several slots joined by "und" / ",".
_TIME_PREFIX_RE = re.compile(
    r"^\s*(?:\d{1,2}(?:[.:]\d{2})?\s*(?:Uhr\s*)?(?:bis\s*\d{1,2}(?:[.:]\d{2})?\s*)?Uhr"
    r"(?:\s*(?:und|,)\s*)?)+\s*:?\s*"
)
_DAY_RE = re.compile(r"(\d{1,2})\.\s*([A-Za-zÄÖÜäöüß]+)")
_NOTE_RE = re.compile(
    r"\s*\b(Bitte anmelden|Anmeldung erforderlich|Anmeldung unter [^.]*|Eintritt frei)\.?",
    re.IGNORECASE,
)
_PRICE_RE = re.compile(r"^\d+(?:,\d{2})?\s*(?:Euro|€)", re.IGNORECASE)
_STREET_RE = re.compile(
    r"(straße|str\.|weg|gasse|platz|allee|ring|werth|born|markt)\s+\d+\s*[a-z]?\b", re.IGNORECASE
)
_CONTACT_CUT_RE = re.compile(
    r"\s+(?:Tel\.|(?:Telefon|Infos|Internet|E-Mail|Kartenhotline|Konzerttickets|Öffnungszeiten)\b).*$"
)
_PLACE_IN_TEXT_RE = re.compile(r"\b(?:im|in der|in den|auf dem|am)\s+(.+)$")
_META_WORDS = ('impressum', 'datenschutz', 'kontakt', 'e-paper', 'abo', 'agb')
# Office hours of the senior centre etc. - listed like events, but nothing to go to.
_SERVICE_TITLE_RE = re.compile(r"(?i)tourist.?information|sprechstunde|^beratung")


async def fetch_waddische_events() -> List[Dict]:
    """Fetch events from waddische.de."""
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers={
        "User-Agent": CRAWLER_USER_AGENT
    }) as client:
        try:
            response = await client.get(WADDISCHE_URL)
            response.raise_for_status()
            return parse_waddische_html(response.text)
        except Exception as e:
            logger.error(f"Error fetching waddische.de: {e}")
            return []


def _infer_year(day: int, month: int, now: datetime) -> Optional[datetime]:
    """The listing has no year. Pick the one that puts the date closest to now
    (last Friday stays this year, "2. Januar" read in late December is next year)."""
    best = None
    for year in (now.year - 1, now.year, now.year + 1):
        try:
            candidate = datetime(year, month, day)
        except ValueError:
            continue
        if best is None or abs(candidate - now) < abs(best - now):
            best = candidate
    return best


def _split_outside_quotes(text: str) -> List[str]:
    """Split on ", " but not inside „…“ / "…" quotes."""
    parts, buf, depth = [], [], 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in "„«":
            depth += 1
        elif ch in "“”»" and depth:
            depth -= 1
        elif ch == '"':
            depth = 0 if depth else 1
        if ch == "," and depth == 0 and text[i + 1:i + 2] == " ":
            parts.append("".join(buf).strip())
            buf = []
            i += 2
            continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf).strip())
    return [p for p in parts if p]


def _first_sentence(text: str) -> str:
    """'Elternzeit-Konzerte: „…“. Memela Alija und …' -> up to the first
    sentence end, ignoring short abbreviations like 'Dr.' or 'St.'."""
    for m in re.finditer(r"\.\s+(?=[A-ZÄÖÜ])", text):
        word = re.search(r"(\S+)$", text[:m.start()])
        if word and len(word.group(1).strip("„“\"()")) >= 4:
            return text[:m.start() + 1].rstrip(".").strip()
    return text


def _looks_like_venue(segment: str) -> bool:
    words = segment.split()
    return (
        0 < len(words) <= 6
        and segment[:1].isupper()
        and not re.match(r"(?i)(mit|teil|ab|für|von|und|bis)\b", segment)
        # "…, Edvard Grieg, Alberto Ginastera und Fazıl Say." is a name list
        and not re.search(r"\s(und|&)\s", segment)
    )


def _parse_addresses(paragraphs: List[str]) -> Dict[str, str]:
    """'Zentrum 60plus' + 'Heckstraße 27 Infos und Anmeldungen: …' -> address map.
    Also keyed by a parenthesised short name: 'Jugend- und … (Jubb)' -> 'jubb'."""
    addresses: Dict[str, str] = {}
    name = None
    for text in paragraphs:
        is_detail = bool(
            re.search(r"\b(Tel\.|Internet|E-Mail|Öffnungszeiten)", text) or _STREET_RE.search(text)
        )
        if not is_detail:
            name = text.strip()
            continue
        if not name:
            continue
        address = _CONTACT_CUT_RE.sub("", text).strip(" ,")
        if address and not address.lower().startswith("öffnungszeiten"):
            keys = {name.lower()}
            short = re.search(r"\(([^)]+)\)", name)
            if short:
                keys.add(short.group(1).lower())
                keys.add(re.sub(r"\s*\([^)]*\)", "", name).strip().lower())
            for key in keys:
                addresses[key] = address
        name = None
    return addresses


def _split_entry(body: str, addresses: Dict[str, str]) -> Dict[str, Optional[str]]:
    """'Literaturcafé: „Im Schnee“ von …, Teil 1 von 2, Bürgermeisterhaus, 12 Euro.'
    -> title / venue / address / price / description."""
    notes = [m.group(1) for m in _NOTE_RE.finditer(body)]
    text = _NOTE_RE.sub("", body).strip().rstrip(".").strip()
    segments = _split_outside_quotes(text)
    price = next((s for s in segments if _PRICE_RE.match(s)), None)
    if price is None and any(n.lower() == "eintritt frei" for n in notes):
        price = "Eintritt frei"
    segments = [s for s in segments if not _PRICE_RE.match(s)]

    venue = address = None
    idx = len(segments) - 1
    if idx >= 1 and _STREET_RE.search(segments[idx]):
        address = segments[idx]
        idx -= 1
    if idx >= 1:
        candidate = segments[idx]
        in_list = sum(_looks_like_venue(x) for x in segments[1:idx]) >= 2
        if candidate.lower() in addresses or (_looks_like_venue(candidate) and not in_list):
            venue = candidate
        elif address:
            place = _PLACE_IN_TEXT_RE.search(candidate)
            if place and _looks_like_venue(place.group(1)):
                venue = place.group(1)
    if venue is None:
        # "Offener Treff der Awo Werden." - a known house named in the text
        lowered = text.lower()
        venue = next((k for k in addresses if len(k) > 3 and k in lowered), None)
        if venue:
            venue = text[lowered.index(venue):lowered.index(venue) + len(venue)]

    title = _first_sentence(segments[0] if segments else text)
    if address is None and venue:
        address = addresses.get(venue.lower())
    return {
        "title": title[:200],
        "venue_name": venue,
        "address_text": address,
        "price_text": price,
        "short_description": text if text != title else None,
    }


def _slots(prefix: str) -> List[tuple]:
    """'11.45 bis 13.45 Uhr und 14 bis 16 Uhr' -> [(11,45,13,45), (14,0,16,0)]."""
    out = []
    for m in _SLOT_RE.finditer(prefix):
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        eh = int(m.group(3)) if m.group(3) else None
        em = int(m.group(4) or 0) if m.group(3) else None
        if h < 24 and mi < 60 and (eh is None or (eh < 24 and em < 60)):
            out.append((h, mi, eh, em))
    return out


def parse_waddische_html(html: str, now: Optional[datetime] = None) -> List[Dict]:
    """Parse the waddische.de weekly listing into event dicts."""
    now = now or datetime.now(_BERLIN).replace(tzinfo=None)
    soup = BeautifulSoup(html, 'lxml')
    # '.entry-content' first: in the live markup '#content' is the outer
    # wrapper, whose children are <article>/<div> - matching it yields nothing.
    content = (
        soup.select_one('.entry-content')
        or soup.select_one('article')
        or soup.select_one('#content')
        or soup
    )

    # Pass 1: address list (it comes after the events on the page).
    addresses: Dict[str, str] = {}
    section = None
    address_paragraphs: List[str] = []
    for el in content.find_all(['h3', 'p']):
        if el.name == 'h3':
            section = el.get_text(" ", strip=True).lower()
        elif section and _ADDRESS_SECTION_WORD in section:
            address_paragraphs.append(el.get_text(" ", strip=True))
    addresses = _parse_addresses(address_paragraphs)

    # Pass 2: dated entries.
    events: List[Dict] = []
    seen = set()
    learned_addresses: Dict[str, str] = {}
    section = None
    in_event_section = False
    day = None
    for el in content.find_all(['h3', 'h4', 'p']):
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        if el.name == 'h3':
            section = text
            in_event_section = any(w in text.lower() for w in _EVENT_SECTION_WORDS)
            day = None
            continue
        if not in_event_section:
            continue
        if el.name == 'h4':
            m = _DAY_RE.search(text)
            month = GERMAN_MONTHS.get(m.group(2).lower()) if m else None
            day = _infer_year(int(m.group(1)), month, now) if month else None
            continue
        if day is None or len(text) < 10:
            continue
        if any(w in text.lower() for w in _META_WORDS):
            continue

        prefix_match = _TIME_PREFIX_RE.match(text)
        slots = _slots(prefix_match.group(0)) if prefix_match else []
        body = text[prefix_match.end():] if prefix_match else text
        entry = _split_entry(body, addresses)
        if not entry["title"] or len(entry["title"]) < 4 or _SERVICE_TITLE_RE.search(entry["title"]):
            continue

        venue_key = (entry["venue_name"] or "").lower()
        if entry["address_text"] and venue_key:
            learned_addresses.setdefault(venue_key, entry["address_text"])
        elif venue_key in learned_addresses:
            entry["address_text"] = learned_addresses[venue_key]

        kids = "yes" if re.search(r"(?i)kinder|jugend", section or "") else None
        for h, mi, eh, em in slots or [(0, 0, None, None)]:
            start_at = day.replace(hour=h, minute=mi)
            end_at = day.replace(hour=eh, minute=em) if eh is not None else None
            if end_at is not None and end_at <= start_at:
                end_at = None
            key = (entry["title"], start_at)
            if key in seen:
                continue
            seen.add(key)
            events.append({
                "canonical_id": hashlib.md5(
                    f"waddische_{entry['title']}_{start_at.isoformat()}".encode()
                ).hexdigest()[:16],
                "title": entry["title"],
                "start_at": start_at,
                "end_at": end_at,
                "is_all_day": not slots,
                "venue_name": entry["venue_name"],
                "address_text": entry["address_text"],
                "city": "Essen",
                "category": section,
                "price_text": entry["price_text"],
                "short_description": entry["short_description"],
                "source_url": WADDISCHE_URL,
                "source_name": SOURCE_NAME,
                "kids_suitable": kids,
            })

    logger.info(f"Found {len(events)} events from waddische.de")
    return events


async def sync_waddische(db: Session):
    """Sync events from waddische.de to database."""
    events_data = await fetch_waddische_events()
    return sync_events_to_db(db, events_data, SOURCE_NAME)
