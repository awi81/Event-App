from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from datetime import datetime, timezone
from app.models.base import Base

class EventSource(Base):
    __tablename__ = "event_sources"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    source_url = Column(String(500), nullable=True)
    source_title = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
