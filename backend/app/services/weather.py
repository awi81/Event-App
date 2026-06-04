"""Weather service using Open-Meteo API (free, no API key).

Caches each daily forecast in the `weather_cache` table so we don't hammer the
API on every sync and the cache survives restarts. Cache TTL is short on the
day itself (forecast changes), longer for past dates.
"""
import httpx
from datetime import datetime, date, timezone, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
import logging

from app.models import base as db_base
from app.models.cache import WeatherCache

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
ESSEN_LAT = 51.4556
ESSEN_LON = 7.0116
BERLIN = ZoneInfo("Europe/Berlin")

# Re-fetch today's forecast every 3h; past/future days are stable for a day.
TODAY_TTL = timedelta(hours=3)
DEFAULT_TTL = timedelta(hours=24)


def _is_cache_fresh(row: WeatherCache, target: date) -> bool:
    if not row.fetched_at:
        return False
    fetched_at = row.fetched_at
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - fetched_at
    ttl = TODAY_TTL if target == datetime.now(BERLIN).date() else DEFAULT_TTL
    return age <= ttl


def _row_to_dict(row: WeatherCache) -> dict:
    return {
        "temp_max": row.temp_max,
        "temp_min": row.temp_min,
        "rain_probability": row.rain_probability,
        "weather_code": row.weather_code,
        "hint": row.hint,
    }


async def get_weather_for_date(target_date: date, db=None) -> Optional[dict]:
    """Return weather forecast for a date in Essen, cached in DB."""
    own_session = False
    if db is None:
        if db_base.SessionLocal is None:
            return None
        db = db_base.SessionLocal()
        own_session = True

    try:
        row = db.query(WeatherCache).filter(WeatherCache.target_date == target_date).first()
        if row and _is_cache_fresh(row, target_date):
            return _row_to_dict(row)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(OPEN_METEO_URL, params={
                    "latitude": ESSEN_LAT,
                    "longitude": ESSEN_LON,
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode",
                    "timezone": "Europe/Berlin",
                    "start_date": target_date.isoformat(),
                    "end_date": target_date.isoformat(),
                })
                if response.status_code != 200:
                    return _row_to_dict(row) if row else None

                data = response.json()
                daily = data.get("daily", {})
                if not daily.get("time"):
                    return _row_to_dict(row) if row else None

                temp_max = daily["temperature_2m_max"][0]
                temp_min = daily["temperature_2m_min"][0]
                rain_prob = daily["precipitation_probability_max"][0]
                weather_code = daily["weathercode"][0]
                hint = _generate_weather_hint(rain_prob or 0, weather_code or 0, temp_max or 0)

                now = datetime.now(timezone.utc)
                if row:
                    row.temp_max = temp_max
                    row.temp_min = temp_min
                    row.rain_probability = rain_prob
                    row.weather_code = weather_code
                    row.hint = hint
                    row.fetched_at = now
                else:
                    row = WeatherCache(
                        target_date=target_date,
                        temp_max=temp_max,
                        temp_min=temp_min,
                        rain_probability=rain_prob,
                        weather_code=weather_code,
                        hint=hint,
                        fetched_at=now,
                    )
                    db.add(row)
                db.commit()
                return _row_to_dict(row)
        except Exception as e:
            logger.error(f"Weather API error: {e!r}")
            return _row_to_dict(row) if row else None
    finally:
        if own_session:
            db.close()


def _generate_weather_hint(rain_prob: int, weather_code: int, temp_max: float) -> str:
    """Generate a human-readable weather hint in German."""
    # WMO Weather codes: 0=clear, 1-3=partly cloudy, 45-48=fog,
    # 51-57=drizzle, 61-67=rain, 71-77=snow, 80-82=showers, 95-99=thunderstorm
    if weather_code >= 95:
        return "Gewitter erwartet - Indoor sinnvoll"
    if weather_code >= 61 or rain_prob >= 70:
        return "Regen wahrscheinlich - Indoor sinnvoll"
    if weather_code >= 51 or rain_prob >= 40:
        return "Wetterabhängig - Regenschirm mitnehmen"
    if temp_max >= 28:
        return f"Warm ({temp_max:.0f}°C) - Sonnenschutz empfohlen"
    if temp_max <= 2:
        return f"Kalt ({temp_max:.0f}°C) - Warm anziehen"
    if weather_code <= 1:
        return f"Schönes Wetter ({temp_max:.0f}°C) - Gut für Outdoor"
    return f"{temp_max:.0f}°C - Gut bei jedem Wetter"


async def apply_weather_to_events(events, db) -> int:
    """Apply weather hints to events that have a start_at date within 7 days."""
    updated = 0
    today = datetime.now(BERLIN).date()

    for event in events:
        if not event.start_at:
            continue
        event_date = event.start_at.date()
        days_ahead = (event_date - today).days
        if days_ahead < 0 or days_ahead > 7:
            continue
        weather = await get_weather_for_date(event_date, db)
        if weather and weather.get("hint"):
            event.weather_note = weather["hint"]
            updated += 1

    if updated:
        db.commit()
        logger.info(f"Applied weather hints to {updated} events")
    return updated
