"""Compute a quality score per event.

Score is in [0, 1]. The score is a weighted sum of:
  - has start_at
  - has venue or address
  - has coordinates
  - has description
  - has category
  - has price
  - cross-source confirmation (source_count > 1)

It is intentionally simple — the goal is to surface well-described events first.
"""
from sqlalchemy.orm import Session
from app.models.event import Event


WEIGHTS = {
    "start_at": 0.20,
    "venue": 0.15,
    "coords": 0.20,
    "description": 0.10,
    "category": 0.10,
    "price": 0.05,
    "multi_source": 0.20,
}


def compute_quality_score(event: Event) -> float:
    score = 0.0
    if event.start_at is not None or event.is_permanent_offer:
        score += WEIGHTS["start_at"]
    if event.venue_name or event.address_text:
        score += WEIGHTS["venue"]
    if event.lat is not None and event.lon is not None:
        score += WEIGHTS["coords"]
    if event.short_description and len(event.short_description) >= 30:
        score += WEIGHTS["description"]
    if event.category:
        score += WEIGHTS["category"]
    if event.price_text:
        score += WEIGHTS["price"]
    if (event.source_count or 1) > 1:
        score += WEIGHTS["multi_source"]
    return round(min(1.0, score), 3)


def recompute_all_quality_scores(db: Session) -> int:
    events = db.query(Event).filter(Event.archived_at.is_(None)).all()
    for event in events:
        event.quality_score = compute_quality_score(event)
    db.commit()
    return len(events)
