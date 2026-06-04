from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Float, Enum as SQLEnum
from datetime import datetime, timezone
import enum
from app.models.base import Base  # noqa: F401

class KidsSuitable(str, enum.Enum):
    yes = "yes"
    likely = "likely"
    unknown = "unknown"
    no = "no"

class IndoorOutdoor(str, enum.Enum):
    indoor = "indoor"
    outdoor = "outdoor"
    both = "both"
    unknown = "unknown"

class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    canonical_id = Column(String(100), unique=True, index=True)
    title = Column(String(500), nullable=False)
    short_description = Column(Text, nullable=True)
    start_at = Column(DateTime, nullable=True)
    end_at = Column(DateTime, nullable=True)
    is_all_day = Column(Boolean, default=False)
    is_recurring = Column(Boolean, default=False)
    is_permanent_offer = Column(Boolean, default=False)
    category = Column(String(100), nullable=True)
    source_name = Column(String(255), nullable=True)
    source_url = Column(String(500), nullable=True)
    venue_name = Column(String(255), nullable=True)
    address_text = Column(String(500), nullable=True)
    city = Column(String(100), nullable=True)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    distance_km = Column(Float, nullable=True)
    travel_time_minutes = Column(Integer, nullable=True)
    indoor_outdoor = Column(SQLEnum(IndoorOutdoor), default=IndoorOutdoor.unknown)
    kids_suitable = Column(SQLEnum(KidsSuitable), default=KidsSuitable.unknown)
    age_note = Column(String(255), nullable=True)
    price_text = Column(String(255), nullable=True)
    weather_note = Column(String(255), nullable=True)
    image_url = Column(String(500), nullable=True)
    quality_score = Column(Float, default=0.5)
    source_count = Column(Integer, default=1)
    sources_list = Column(String(500), nullable=True)  # comma-separated source names
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    archived_at = Column(DateTime, nullable=True)
