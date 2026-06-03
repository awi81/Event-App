from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from datetime import datetime, timezone
from app.models.base import Base

class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    base_url = Column(String(500), nullable=False)
    source_type = Column(String(50), nullable=False)  # api, rss, html
    extraction_mode = Column(String(50), nullable=False)  # json, xml, scrape
    active = Column(Boolean, default=True)
    legal_note = Column(Text, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
