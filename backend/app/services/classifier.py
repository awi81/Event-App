"""
Event Classification Service
Automatically categorizes events based on keywords and source
"""

from typing import Dict, Optional, List, Tuple
import re

# Canonical category taxonomy.
#
# Every event ends up in exactly one of these groups so the frontend chips stay
# stable and a group like "Theater & Bühne" can be excluded as a whole. Sources
# deliver wildly different raw labels ("Schauspiel", "Eigenproduktion", "Halle 8",
# "Tagesfahrten für Kinder", ...) — `normalize_category` maps them here.
#
# Order matters: the first matching group wins. Kids first (a "Kindertheater"
# is a family event), then the specific culture groups, then the broad ones.
# Patterns are regexes; short/ambiguous tokens carry word boundaries so "oper"
# does not fire on "Kooperation" and "fest" not on "Manifest".
CATEGORY_RULES: List[Tuple[str, List[str]]] = [
    ("Familie & Kinder", [
        r"kinder", r"\bkind\b", r"famili", r"jugend", r"\bkids\b", r"eltern",
        r"schüler", r"puppentheater", r"figurentheater", r"märchen", r"maerchen",
        r"ferien", r"mitmach", r"\bbaby", r"kindermusical", r"tagesfahrt",
        r"spiel und spaß", r"spielplatz",
    ]),
    ("Comedy & Kabarett", [
        r"comedy", r"kabarett", r"satire", r"lachnacht", r"stand-?up", r"impro\b",
        r"improtheater", r"humor",
    ]),
    ("Theater & Bühne", [
        r"theater", r"schauspiel", r"\boper\b", r"\bopern", r"operette", r"musical",
        r"ballett", r"\btanz", r"bühne", r"buehne", r"variet[ée]", r"eigenproduktion",
        r"gastspiel", r"inszenierung", r"\bdrama\b", r"boulevard", r"revue",
        r"zirkus", r"circus", r"performance", r"figuren",
    ]),
    ("Film & Kino", [r"\bfilm", r"\bkino", r"cinema", r"kurzfilm", r"filmkunst"]),
    ("Literatur & Vorträge", [
        r"lesung", r"literatur", r"vortrag", r"vorträge", r"\bbuch", r"poetry",
        r"\bslam\b", r"autor", r"diskussion", r"podium", r"\btalk\b", r"gespräch",
        r"seminar", r"kongress", r"tagung",
    ]),
    ("Museum & Ausstellung", [
        r"museum", r"ausstellung", r"vernissage", r"galerie", r"\bkunst", r"sammlung",
        r"exponat", r"red dot", r"design", r"historisch", r"denkmal", r"architektur",
        r"kunsthalle",
    ]),
    ("Führungen & Touren", [
        r"führung", r"fuehrung", r"rundgang", r"\btour\b", r"touren", r"besichtigung",
        r"exkursion", r"wanderung", r"radtour", r"rundfahrt", r"nachtwächter",
        r"spaziergang", r"stadtrundgang",
    ]),
    ("Märkte & Messen", [
        r"markt\b", r"märkte", r"maerkte", r"flohmarkt", r"weihnachtsmarkt", r"basar",
        r"trödel", r"troedel", r"bauernmarkt", r"\bmesse\b", r"messen\b",
    ]),
    ("Feste & Festivals", [
        r"\bfest\b", r"festival", r"feier", r"\bparty", r"open.?air", r"kirmes",
        r"volksfest", r"stadtfest", r"sommerfest", r"nightlife", r"karneval",
        r"halloween", r"silvester", r"jahrmarkt", r"brauchtum",
    ]),
    ("Food & Street-Food", [
        r"\bfood", r"street-?food", r"kulinar", r"genuss", r"gourmet", r"gastronomie",
        r"\bwein", r"\bbier", r"brunch", r"kochen", r"verkostung", r"tasting",
        r"restaurant", r"\bcaf[eé]\b", r"küche",
    ]),
    ("Workshops & Mitmachen", [
        r"workshop", r"\bkurs", r"kreativ", r"basteln", r"malen", r"handwerk",
        r"\bdiy\b", r"hobby", r"lerne", r"schnupper",
    ]),
    ("Musik & Konzerte", [
        r"konzert", r"musik", r"\bband\b", r"\blive\b", r"\bdj\b", r"jazz", r"\brock\b",
        r"\bpop\b", r"klassik", r"\bchor\b", r"orgel", r"sinfonie", r"symphon",
        r"philharmon", r"schlager", r"elektro", r"\bdance\b", r"\bsong", r"gesang",
        r"\bgig\b", r"unplugged", r"orchester", r"\bmetal\b", r"hip.?hop", r"punk",
    ]),
    ("Freizeitorte & Attraktionen", [
        r"freizeit", r"attraktion", r"\bpark\b", r"natur", r"\bwald", r"garten",
        r"\btier", r"\bzoo\b", r"gruga", r"schwimm", r"kletter", r"freizeitpark",
        r"\bsee\b", r"\brad\b", r"sport", r"\blauf", r"marathon", r"yoga",
        r"fußball", r"tennis", r"fitness", r"turnier", r"wellness", r"planetarium",
        r"outdoor", r"ausflug", r"erlebnis",
    ]),
]

# Bucket for events whose source did label them, but with something no rule
# understands ("Stiftung Zollverein", "Halle 8"). Keeps raw labels off the chips
# while still letting the user hide the leftovers.
FALLBACK_CATEGORY = "Sonstiges"

CANONICAL_CATEGORIES: List[str] = [name for name, _ in CATEGORY_RULES] + [FALLBACK_CATEGORY]

_COMPILED_RULES: List[Tuple[str, "re.Pattern[str]"]] = [
    (name, re.compile("|".join(patterns), re.IGNORECASE)) for name, patterns in CATEGORY_RULES
]

# Kept for backwards compatibility with older imports/tests: plain keyword lists.
CATEGORY_KEYWORDS: Dict[str, List[str]] = {name: patterns for name, patterns in CATEGORY_RULES}


def _match_category(text: str) -> Optional[str]:
    """First canonical group whose pattern fires on `text`, else None."""
    if not text:
        return None
    for name, pattern in _COMPILED_RULES:
        if pattern.search(text):
            return name
    return None


def normalize_category(
    raw_category: Optional[str],
    title: str = "",
    description: str = "",
    venue: str = "",
) -> Optional[str]:
    """Map whatever a source calls its category onto the canonical taxonomy.

    Signal order: the raw label (strongest), then the title, then description
    and venue. A raw label that fits nothing becomes "Sonstiges"; with no raw
    label at all the result is None — better no chip than a wrong one.
    """
    raw = (raw_category or "").strip()
    if raw in CANONICAL_CATEGORIES:
        return raw
    # Kids first, across label + title: "Schauspiel" + "Kindertheater: ..." is a
    # family event, and families are who this app is for.
    kids_name, kids_pattern = _COMPILED_RULES[0]
    if kids_pattern.search(f"{raw} {title}".lower()):
        return kids_name
    for text in (raw, title, f"{description} {venue}"):
        match = _match_category(text.lower() if text else "")
        if match:
            return match
    return FALLBACK_CATEGORY if raw else None


# Indoor/Outdoor keywords
INDOOR_KEYWORDS = [
    "museum", "theater", "kino", "konzert", "halle", "indoor", "innen",
    "galerie", "ausstellung", "restaurant", "cafe", "kultur", "rade"
]

OUTDOOR_KEYWORDS = [
    "park", "frei", "outdoor", " draußen", "garten", "wald", "wiese",
    "platz", "straße", "lauf", "radweg", "see", "teich"
]


def classify_event(event_data: Dict) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Classify an event based on its data.
    Returns: (category, indoor_outdoor, kids_suitable)
    """
    title = event_data.get("title", "").lower()
    description = event_data.get("short_description", "").lower()
    source_name = event_data.get("source_name", "").lower()
    venue = event_data.get("venue_name", "").lower()

    # Combine all text for keyword matching
    all_text = f"{title} {description} {venue}"

    # 1. Source-based classification
    if "ruhrpott" in source_name:
        kids_suitable = "yes"
    else:
        kids_suitable = None

    # 2. Category classification: canonical group from title, then description/venue
    category = normalize_category(event_data.get("category"), title, description, venue)

    # 3. Indoor/Outdoor classification
    indoor_outdoor = None
    indoor_count = sum(1 for kw in INDOOR_KEYWORDS if kw in all_text)
    outdoor_count = sum(1 for kw in OUTDOOR_KEYWORDS if kw in all_text)

    if indoor_count > 0 and outdoor_count > 0:
        indoor_outdoor = "both"
    elif outdoor_count > 0:
        indoor_outdoor = "outdoor"
    elif indoor_count > 0:
        indoor_outdoor = "indoor"

    # 4. Override: specific venues
    if "grugapark" in venue:
        indoor_outdoor = "outdoor"
    if "zollverein" in venue or "museum" in all_text:
        indoor_outdoor = "indoor"

    return category, indoor_outdoor, kids_suitable


def apply_classification(event_data: Dict) -> Dict:
    """
    Apply classification to an event and return updated data.
    Category is normalised onto the canonical taxonomy; indoor/outdoor and
    kids_suitable are only set if not already present.
    """
    category, indoor_outdoor, kids_suitable = classify_event(event_data)

    # Category is always normalised onto the canonical taxonomy — a raw source
    # label ("Schauspiel", "Halle 8") must never reach the frontend chips.
    if category:
        event_data["category"] = category

    if indoor_outdoor and not event_data.get("indoor_outdoor"):
        event_data["indoor_outdoor"] = indoor_outdoor

    if kids_suitable and not event_data.get("kids_suitable"):
        event_data["kids_suitable"] = kids_suitable

    return event_data
