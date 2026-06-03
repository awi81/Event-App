"""Group repeating events (same play/concert with multiple performances).

Theater Essen alone produces ~10 rows for the same opera at different show
times. Without grouping the user sees the same title over and over and loses
the overview. Grouping reduces "La Traviata × 10" to one card with a list of
occurrences.

Strategy:
- key = (normalised title, source_name) - same title from different sources
  still gets merged via the cross-source dedup in base_sync, so by the time
  we group, identical titles in the DB are intentional duplicates with
  different show times.
- representative row = the occurrence with the earliest future start_at
  (or the highest quality if none have a date).
- result list is sorted by next-occurrence ascending, then by quality.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable
import re
import unicodedata

from app.models.event import Event


_INVISIBLE_CHARS = re.compile(r"[­​‌‍⁠﻿]")
_TITLE_PUNCT = re.compile(r"[^\wäöüß ]+", re.UNICODE)
_TITLE_STOPWORDS = {
    "der", "die", "das", "den", "dem", "und", "oder", "mit", "im", "in",
    "ein", "eine", "einen", "einem", "auf", "an", "am", "von", "vom",
    "zur", "zum", "bei", "für", "fuer", "&", "-",
}


def normalise_title(title: str | None) -> str:
    if not title:
        return ""
    s = _INVISIBLE_CHARS.sub("", title)
    s = unicodedata.normalize("NFKC", s).lower()
    s = _TITLE_PUNCT.sub(" ", s)
    tokens = [t for t in s.split() if t and t not in _TITLE_STOPWORDS]
    return " ".join(tokens)


def _group_key(event: Event) -> tuple[str, str]:
    return (normalise_title(event.title), (event.source_name or "").lower())


def _occurrence_dict(event: Event) -> dict:
    return {
        "id": event.id,
        "start_at": event.start_at,
        "venue_name": event.venue_name,
        "source_url": event.source_url,
        "is_permanent_offer": event.is_permanent_offer,
    }


def _representative(events: list[Event], now: datetime) -> Event:
    """Pick the event that should drive title/category/score for the group.

    Prefer the occurrence whose start_at is the earliest one >= now; if none
    are future-dated (e.g. all permanent offers or all missing dates), prefer
    the highest quality_score.
    """
    future = [e for e in events if e.start_at and e.start_at >= now]
    if future:
        return min(future, key=lambda e: e.start_at)
    return max(events, key=lambda e: (e.quality_score or 0.0))


def group_events(events: Iterable[Event], now: datetime | None = None) -> list[dict]:
    """Group events with the same normalised (title, source).

    Returns a list of dicts that mirror EventResponse fields PLUS:
      - occurrences: sorted list of occurrence dicts
      - start_at: the next occurrence (or representative's start_at)

    The order is the group's natural sort key (next occurrence asc, then
    quality desc). Callers may re-sort.

    ``now`` selects the "next upcoming" occurrence that drives the headline
    fields. It defaults to the wall clock (live ``GET /events`` behaviour). The
    static-snapshot export passes a fixed past sentinel (``datetime.min``) so
    the headline becomes the earliest occurrence regardless of the wall clock —
    making the output deterministic across runs (the client recomputes the real
    next-upcoming from ``occurrences[]`` anyway).
    """
    if now is None:
        now = datetime.now()
    buckets: dict[tuple[str, str], list[Event]] = {}
    for e in events:
        key = _group_key(e)
        if not key[0]:
            # Title is unparseable - skip grouping (use Python's id() as
            # discriminator so each such row stays in its own bucket).
            key = (f"__unique_{id(e)}__", key[1])
        buckets.setdefault(key, []).append(e)

    result: list[dict] = []
    for group in buckets.values():
        rep = _representative(group, now)
        occurrences = sorted(
            (_occurrence_dict(e) for e in group),
            key=lambda o: (o["start_at"] is None, o["start_at"] or datetime.max),
        )
        # Use the earliest upcoming occurrence as the "headline" start_at so
        # the card always shows the soonest performance.
        next_start = next(
            (o["start_at"] for o in occurrences if o["start_at"] and o["start_at"] >= now),
            occurrences[0]["start_at"] if occurrences else None,
        )

        result.append({
            "id": rep.id,
            "canonical_id": rep.canonical_id,
            "title": rep.title,
            "short_description": rep.short_description,
            "start_at": next_start,
            "end_at": rep.end_at,
            "category": rep.category,
            "venue_name": rep.venue_name,
            "address_text": rep.address_text,
            "city": rep.city,
            "lat": rep.lat,
            "lon": rep.lon,
            "indoor_outdoor": rep.indoor_outdoor,
            "kids_suitable": rep.kids_suitable,
            "price_text": rep.price_text,
            "source_url": rep.source_url,
            "source_name": rep.source_name,
            "distance_km": rep.distance_km,
            "travel_time_minutes": rep.travel_time_minutes,
            "age_note": rep.age_note,
            "weather_note": rep.weather_note,
            "image_url": rep.image_url,
            "quality_score": rep.quality_score,
            "source_count": rep.source_count,
            "sources_list": rep.sources_list,
            "created_at": rep.created_at,
            "is_permanent_offer": rep.is_permanent_offer,
            "is_all_day": rep.is_all_day,
            "occurrences": occurrences,
        })

    # Default sort: next occurrence asc, then by quality desc.
    result.sort(
        key=lambda g: (
            g["start_at"] is None,
            g["start_at"] or datetime.max,
            -(g["quality_score"] or 0.0),
        )
    )
    return result
