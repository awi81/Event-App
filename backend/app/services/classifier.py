"""
Event Classification Service
Automatically categorizes events based on keywords and source
"""

from typing import Dict, Optional, List, Tuple
import re

# Category keywords mapping
CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "Familie & Kinder": [
        "kind", "kinder", "famili", "eltern", "kids", "jugend", "schüler",
        "geburtstag", "spiel", "spielplatz", "tochter", "sohn", "baby",
        "mitmach", "puppentheater"
    ],
    "Museum & Ausstellung": [
        "museum", "ausstellung", "kunst", "galerie", "historisch",
        "denkmal", "architektur", "sammlung", "exponat"
    ],
    "Märkte": [
        "markt", "flohmarkt", "weihnachtsmarkt", "basar", "trödelmarkt",
        "bauernmarkt", "streetfood-markt"
    ],
    "Food & Street-Food": [
        "food", "street-food", "streetfood", "essen", "trinken",
        "restaurant", "cafe", "küche", "kochen", "verkostung", "wein",
        "bier", "brunch", "kulinarisch"
    ],
    "Feste & Festivals": [
        "fest", "festival", "feier", "party", "open air", "openair",
        "stadtfest", "sommerfest", "kirmes", "volksfest"
    ],
    "Workshops & Mitmachen": [
        "workshop", "kurs", "seminar", "kreativ", "basteln", "malen",
        "handwerk", "lerne", "mitmach", "diy"
    ],
    "Freizeitorte & Attraktionen": [
        "park", "natur", "wald", "garten", "tier", "zoo", "gruga",
        "schwimmbad", "kletterhalle", "freizeitpark", "see", "rad",
        "sport", "lauf", "marathon", "yoga", "fußball", "tennis"
    ],
    "Kultur & Sonstiges": [
        "kultur", "konzert", "musik", "band", "live", "dj", "jazz",
        "rock", "pop", "klassik", "chor", "theater", "bühne", "show",
        "kabarett", "comedy", "film", "kino", "vorstellung", "drama",
        "lesung", "literatur", "führung", "rundgang", "tour",
        "besichtigung", "kulturerbe"
    ],
}

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

    # 2. Category classification based on keywords
    category = None
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in all_text:
                category = cat
                break
        if category:
            break

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
    Only sets values if not already present.
    """
    category, indoor_outdoor, kids_suitable = classify_event(event_data)

    # Only set if not already present
    if category and not event_data.get("category"):
        event_data["category"] = category

    if indoor_outdoor and not event_data.get("indoor_outdoor"):
        event_data["indoor_outdoor"] = indoor_outdoor

    if kids_suitable and not event_data.get("kids_suitable"):
        event_data["kids_suitable"] = kids_suitable

    return event_data
