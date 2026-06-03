"""Ferienspatz Essen – Kinder-Ferienprogramm der Stadt Essen.

Quelle: https://ferienspatz.essen.de/Event
Technologie: ASP.NET Core / Blazor-Server, aber die Listenansicht (/Event)
wird server-seitig als vollständiges HTML ausgeliefert (kein JS nötig).
Paginierung via ?pageIndex=N (je 10 Karten, derzeit bis pageIndex~38).

Datenschutz-Hinweis: Es werden ausschließlich öffentliche Angebotsseiten
abgerufen. Anmelde-/Registrierungs-Endpunkte (/Identity/…) werden nicht
aufgerufen (DSGVO Art. 5 Abs. 1 lit. c – Datensparsamkeit).

Fix A – Detailadressen (2025-06):
  Jede Detailseite enthält ein Feld „Adresse" (label[for=Event_FullAdresse])
  mit der echten Veranstaltungsadresse (Straße + PLZ + Ort).  Diese wird als
  ``address_text`` übernommen, sodass der nachgelagerte Geocoder
  (known_venues → Nominatim) sie auflösen kann.

Fix B – Nicht-Essen-Filter (2025-06):
  Events, deren Veranstaltungsadresse eine PLZ außerhalb Essens trägt, werden
  verworfen.  Damit fallen Angebote in Ratingen, Herne, Hattingen, Mülheim,
  Gelsenkirchen usw. heraus (~9 von ~144 Angeboten).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.services.base_sync import sync_events_to_db

logger = logging.getLogger(__name__)

BASE_URL = "https://ferienspatz.essen.de"
LIST_URL = f"{BASE_URL}/Event"

# Wie viele Seiten maximal laden (Sicherheitsbremse; 10 Karten/Seite)
MAX_PAGES = 40

# Maximale Anzahl Detailabrufe pro Sync-Lauf (Sicherheitsbremse).
# Bei 144 Angeboten und ~1 s Pause → ca. 2,5 Min für Details; passt in 30-Min-Limit.
MAX_DETAIL_FETCHES = 160

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
}

# Datum-Formate auf der Listenseite: 05.06.26 oder 05.06.2026
_DATE_FMTS = ["%d.%m.%y", "%d.%m.%Y"]

# ---------------------------------------------------------------------------
# Essener PLZ (vollständige offizielle Liste, Stand 2024)
# Quelle: Stadtgebiet Essen, Postleitzahlenverzeichnis Bundesnetzagentur
# ---------------------------------------------------------------------------
_ESSEN_PLZ: frozenset[str] = frozenset(
    {
        "45127", "45128", "45130", "45131", "45133", "45134", "45136",
        "45138", "45139", "45141", "45143", "45144", "45145", "45147",
        "45149", "45219", "45239", "45257", "45259", "45276", "45277",
        "45279", "45289", "45307", "45309", "45326", "45327", "45329",
        "45355", "45356", "45357", "45359",
    }
)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _parse_date(raw: str) -> Optional[datetime]:
    """Parse a German short or long date string.

    Handles the following formats from ferienspatz.essen.de:
    - Simple date:      "05.06.26" / "05.06.2026"
    - Date + time:      "18.07.26, 15:30 - 17:30"   → uses date + start time
    - Date range:       "10.07.26 - 11.07.26"        → uses first date
    - Date range+time:  "18.07.26 - 28.07.26"        → uses first date
    """
    raw = raw.strip()
    # Extract time if present before the date part gets modified:  "18.07.26, 15:30 - …"
    time_match = re.search(r",\s*(\d{1,2}:\d{2})", raw)
    start_time: Optional[Tuple[int, int]] = None
    if time_match:
        h, m = time_match.group(1).split(":")
        start_time = (int(h), int(m))
        # Remove everything from the comma onward so the date parser sees only the date
        raw = raw[: time_match.start()].strip()

    # If it's a date range "DD.MM.YY - DD.MM.YY", keep only the first date
    range_match = re.match(r"(\d{2}\.\d{2}\.\d{2,4})\s*-\s*\d{2}\.", raw)
    if range_match:
        raw = range_match.group(1)

    for fmt in _DATE_FMTS:
        try:
            dt = datetime.strptime(raw, fmt)
            if start_time is not None:
                dt = dt.replace(hour=start_time[0], minute=start_time[1])
            return dt
        except ValueError:
            continue
    return None


def _find_date_col_index(table) -> int:
    """Return the column index that contains 'Beginn/Ende' dates.

    Most tables have headers [Beginn/Ende, Altersgruppe, Hinweis] → index 0.
    Some have [Titel, Beginn/Ende, Altersgruppe, Hinweis]          → index 1.
    Fall back to 0 when the header row is absent or unclear.
    """
    header_cells = table.select("thead th")
    for idx, th in enumerate(header_cells):
        if "Beginn" in th.get_text():
            return idx
    return 0


def _is_free(card) -> bool:
    """Return True if the card shows the kostenlos-icon."""
    img = card.select_one('img[src*="kostenlos"]')
    return img is not None


def _extract_address_from_detail(detail_html: str) -> Optional[str]:
    """Extract the event address from a Ferienspatz detail page.

    The detail page contains a row::

        <label class="col-md-4 fw-bold" for="Event_FullAdresse">Adresse</label>
        <div class="col-md-8">
          <p class="card-text">Gustav-Heinemann-Platz 1 , 45309 Essen</p>
        </div>

    Returns the address string or None if the field is absent.
    """
    soup = BeautifulSoup(detail_html, "lxml")
    label = soup.find("label", attrs={"for": "Event_FullAdresse"})
    if not label:
        return None
    row = label.find_parent("div", class_="row")
    if not row:
        return None
    col = row.select_one("div.col-md-8")
    if not col:
        return None
    text = col.get_text(strip=True)
    return text if text else None


def _is_essen_address(address: str) -> bool:
    """Return True iff the address belongs to Essen.

    Logic (conservative – prefer false-negative over false-positive):
    1. Extract 5-digit postal code.
    2. If the PLZ is in the known Essen PLZ set → True.
    3. If the PLZ starts with "45" but is NOT in the set, and the word "Essen"
       appears in the address → True  (handles rare edge-case PLZ).
    4. Any other PLZ → False (not Essen).
    5. No PLZ found: fall back to checking whether ", Essen" or " Essen" ends
       the address string → True; otherwise unknown → True (conservative).
    """
    plz_match = re.search(r"\b(\d{5})\b", address)
    if plz_match:
        plz = plz_match.group(1)
        if plz in _ESSEN_PLZ:
            return True
        # 45xxx PLZ that's not in our set: accept only if "Essen" is explicit
        if plz.startswith("45") and re.search(r"\bEssen\b", address, re.IGNORECASE):
            return True
        # Any other PLZ → clearly not Essen
        return False
    # No PLZ: check city name
    if re.search(r",\s*Essen\b", address, re.IGNORECASE):
        return True
    if re.search(r"\bEssen\s*$", address.strip(), re.IGNORECASE):
        return True
    # No information → conservative: keep the event
    return True


# ---------------------------------------------------------------------------
# List-page parser
# ---------------------------------------------------------------------------


def _parse_card(card) -> List[Dict]:
    """Extract one or more event-dicts from a single Bootstrap card.

    The card covers one *Angebot* (title + description + venue) but may
    contain multiple appointment rows in the embedded table.  We emit one
    dict per appointment so the app's grouping logic can collapse them.
    """
    # --- Title ---
    title_tag = card.select_one(".card-header h2")
    if not title_tag:
        return []
    title = title_tag.get_text(strip=True)
    if not title or len(title) < 4:
        return []

    # --- Detail URL ---
    link = card.select_one(".card-header a[href]")
    detail_url = BASE_URL + link["href"] if link else LIST_URL

    # --- Venue (Veranstalter shown as text-muted under title) ---
    venue_tag = card.select_one(".card-header.pt-0 .text-muted")
    venue_name = venue_tag.get_text(strip=True) if venue_tag else None

    # --- Category badge ---
    badge = card.select_one(".badge.bg-primary")
    category = badge.get_text(strip=True) if badge else None

    # --- Description ---
    desc_tag = card.select_one(".card-text")
    description = desc_tag.get_text(strip=True)[:500] if desc_tag else None

    # --- Price ---
    price_text = "kostenlos" if _is_free(card) else None

    # --- Appointments table ---
    table = card.select_one("table.card-table")
    rows = table.select("tbody tr") if table else []
    # Filter rows that have a "weitere Termine" link (not real date rows)
    date_rows = [r for r in rows if not r.select_one("a")]

    # Determine which column contains "Beginn/Ende" dates.
    # Most tables: col 0 = Beginn/Ende; some: col 0 = Titel, col 1 = Beginn/Ende
    date_col = _find_date_col_index(table) if table else 0

    events: List[Dict] = []
    for row in date_rows:
        cells = row.find_all("td")
        if len(cells) <= date_col:
            continue
        raw_date = cells[date_col].get_text(strip=True)
        start_at = _parse_date(raw_date)
        if not start_at:
            continue

        # Altersgruppe aus der Spalte nach date_col in die Beschreibung aufnehmen
        age_col = date_col + 1
        age_info = cells[age_col].get_text(strip=True) if len(cells) > age_col else ""
        full_desc = description or ""
        if age_info and age_info not in ("&nbsp;", "\xa0", ""):
            full_desc = f"Altersgruppe: {age_info}. {full_desc}".strip()

        # canonical_id: md5 aus quelle + titel + ISO-Datum
        id_src = f"ferienspatz_{title}_{start_at.date().isoformat()}"
        canonical_id = hashlib.md5(id_src.encode("utf-8")).hexdigest()[:16]

        events.append(
            {
                "canonical_id": canonical_id,
                "title": title[:200],
                "short_description": full_desc[:500] if full_desc else None,
                "start_at": start_at,
                "venue_name": venue_name,
                "city": "Essen",
                "lat": None,
                "lon": None,
                "address_text": None,  # wird in fetch_ferienspatz_events befüllt
                "source_url": detail_url,
                "source_name": "Ferienspatz",
                "indoor_outdoor": "unknown",
                "kids_suitable": "yes",
                "category": category,
                "price_text": price_text,
                "is_permanent_offer": False,
            }
        )

    # If the card has appointments but all were un-parseable,
    # or there are no rows at all: emit one placeholder entry.
    if not events:
        # At least keep the offer visible without a concrete date
        id_src = f"ferienspatz_{title}"
        canonical_id = hashlib.md5(id_src.encode("utf-8")).hexdigest()[:16]
        events.append(
            {
                "canonical_id": canonical_id,
                "title": title[:200],
                "short_description": description[:500] if description else None,
                "start_at": None,
                "venue_name": venue_name,
                "city": "Essen",
                "lat": None,
                "lon": None,
                "address_text": None,  # wird in fetch_ferienspatz_events befüllt
                "source_url": detail_url,
                "source_name": "Ferienspatz",
                "indoor_outdoor": "unknown",
                "kids_suitable": "yes",
                "category": category,
                "price_text": price_text,
                "is_permanent_offer": True,  # undatiert = Dauerangebot
            }
        )

    return events


def parse_ferienspatz_html(html: str) -> List[Dict]:
    """Parse Ferienspatz list-page HTML and return event dicts."""
    soup = BeautifulSoup(html, "lxml")
    events: List[Dict] = []

    for card in soup.select("div.card.mb-3"):
        try:
            events.extend(_parse_card(card))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Ferienspatz: Fehler beim Parsen einer Karte: %s", exc)
            continue

    return events


# ---------------------------------------------------------------------------
# Detail-Enrichment (Fix A) + Essen-Filter (Fix B)
# ---------------------------------------------------------------------------


async def _enrich_with_detail_address(
    client: httpx.AsyncClient,
    events: List[Dict],
) -> Tuple[List[Dict], int, int]:
    """Fetch detail pages and fill address_text; filter non-Essen events.

    Args:
        client: Shared httpx client (already configured with headers/timeout).
        events: Raw event dicts from parse_ferienspatz_html (all pages).

    Returns:
        (enriched_events, n_with_address, n_filtered_out)
    """
    # Baue ein Mapping detail_url → List[event] auf, damit jede URL nur einmal
    # abgerufen wird (mehrere Termine desselben Angebots teilen sich eine URL).
    url_to_events: Dict[str, List[Dict]] = {}
    for ev in events:
        url = ev["source_url"]
        url_to_events.setdefault(url, []).append(ev)

    unique_urls = list(url_to_events.keys())
    if len(unique_urls) > MAX_DETAIL_FETCHES:
        logger.warning(
            "Ferienspatz: %d unique Detail-URLs, begrenze auf %d",
            len(unique_urls),
            MAX_DETAIL_FETCHES,
        )
        unique_urls = unique_urls[:MAX_DETAIL_FETCHES]

    n_with_address = 0
    filtered_urls: set[str] = set()

    for url in unique_urls:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            address = _extract_address_from_detail(resp.text)
        except Exception as exc:
            logger.debug("Ferienspatz: Detail-Abruf fehlgeschlagen %s: %s", url, exc)
            address = None

        if address:
            n_with_address += 1
            # Fix B: Essen-Check
            if not _is_essen_address(address):
                logger.debug(
                    "Ferienspatz: Event gefiltert (nicht Essen): %r @ %r",
                    url_to_events[url][0].get("title"),
                    address,
                )
                filtered_urls.add(url)
                continue
            # Adresse in alle Events dieser URL eintragen
            for ev in url_to_events[url]:
                ev["address_text"] = address
                # city korrekt setzen wenn PLZ/Ort eindeutig bekannt
                city_match = re.search(r",\s*(\d{5})\s+(\S+.*)", address)
                if city_match:
                    ev["city"] = city_match.group(2).split(",")[0].strip()
        # else: kein address_text → bleibt None, Geocoder nutzt venue_name

        # Kleiner Delay um den Server zu schonen
        await asyncio.sleep(0.5)

    n_filtered = sum(
        len(url_to_events[u]) for u in filtered_urls
    )

    enriched = [ev for ev in events if ev["source_url"] not in filtered_urls]
    return enriched, n_with_address, n_filtered


# ---------------------------------------------------------------------------
# Fetch-Funktion (öffentlicher Einstiegspunkt)
# ---------------------------------------------------------------------------


async def fetch_ferienspatz_events() -> List[Dict]:
    """Fetch all paginated event pages from ferienspatz.essen.de.

    Ablauf:
    1. Alle Listenseiten paginiert abrufen und parsen (parse_ferienspatz_html).
    2. Pro Angebot (unique source_url) die Detailseite laden und address_text
       befüllen (Fix A).
    3. Events mit Adressen außerhalb Essens verwerfen (Fix B).
    """
    all_events: List[Dict] = []

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        page = 1  # pageIndex=1 is the first real page (0 redirects to /angebote/)
        while page <= MAX_PAGES:
            url = f"{LIST_URL}?pageIndex={page}"
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except Exception as exc:
                logger.error("Ferienspatz: Fehler beim Abrufen von %s: %s", url, exc)
                break

            page_events = parse_ferienspatz_html(resp.text)
            if not page_events:
                # Empty page → we've gone past the last real page
                break

            all_events.extend(page_events)

            # Check whether there is a next-page link (stop early if not)
            soup = BeautifulSoup(resp.text, "lxml")
            next_link = soup.select_one(f'a[href*="pageIndex={page + 1}"]')
            if not next_link:
                break

            page += 1

        logger.info(
            "Ferienspatz: %d Events von %d Listenseiten geladen", len(all_events), page
        )

        # Fix A + B: Detail-Abruf für Adressen + Essen-Filter
        all_events, n_addr, n_filtered = await _enrich_with_detail_address(
            client, all_events
        )
        logger.info(
            "Ferienspatz: %d Events mit Adresse befüllt, %d Nicht-Essen-Events gefiltert "
            "→ %d Events verbleiben",
            n_addr,
            n_filtered,
            len(all_events),
        )

    return all_events


async def sync_ferienspatz(db: Session):
    """Sync Ferienspatz events into the database."""
    events_data = await fetch_ferienspatz_events()
    return sync_events_to_db(db, events_data, "Ferienspatz")
