from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
from enum import Enum


class KidsSuitable(str, Enum):
    yes = "yes"
    likely = "likely"
    unknown = "unknown"
    no = "no"


class IndoorOutdoor(str, Enum):
    indoor = "indoor"
    outdoor = "outdoor"
    both = "both"
    unknown = "unknown"


class EventBase(BaseModel):
    title: str
    short_description: Optional[str] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    category: Optional[str] = None
    venue_name: Optional[str] = None
    address_text: Optional[str] = None
    city: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    indoor_outdoor: Optional[IndoorOutdoor] = None
    kids_suitable: Optional[KidsSuitable] = None
    price_text: Optional[str] = None
    source_url: Optional[str] = None
    source_name: Optional[str] = None


class EventCreate(EventBase):
    canonical_id: str


class Occurrence(BaseModel):
    """One performance / time slot of a (potentially recurring) event."""
    id: int
    start_at: Optional[datetime] = None
    venue_name: Optional[str] = None
    source_url: Optional[str] = None
    is_permanent_offer: Optional[bool] = None


class EventResponse(EventBase):
    id: int
    canonical_id: str
    distance_km: Optional[float] = None
    travel_time_minutes: Optional[int] = None
    age_note: Optional[str] = None
    weather_note: Optional[str] = None
    image_url: Optional[str] = None
    quality_score: Optional[float] = None
    source_count: Optional[int] = None
    sources_list: Optional[str] = None
    created_at: Optional[datetime] = None
    is_permanent_offer: Optional[bool] = None
    is_all_day: Optional[bool] = None
    # All performances of this event (≥1, sorted by start_at).
    occurrences: List[Occurrence] = []

    model_config = {"from_attributes": True}
