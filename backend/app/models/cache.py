"""Persistent caches for geocoding and weather lookups."""
from sqlalchemy import Column, Integer, String, Float, DateTime, Date
from datetime import datetime, timezone
from app.models.base import Base


class GeocodeCache(Base):
    __tablename__ = "geocode_cache"

    id = Column(Integer, primary_key=True, index=True)
    query = Column(String(500), unique=True, nullable=False, index=True)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    fetched_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class WeatherCache(Base):
    __tablename__ = "weather_cache"

    id = Column(Integer, primary_key=True, index=True)
    target_date = Column(Date, unique=True, nullable=False, index=True)
    temp_max = Column(Float, nullable=True)
    temp_min = Column(Float, nullable=True)
    rain_probability = Column(Integer, nullable=True)
    weather_code = Column(Integer, nullable=True)
    hint = Column(String(255), nullable=True)
    fetched_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
