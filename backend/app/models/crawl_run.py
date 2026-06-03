from sqlalchemy import Column, Integer, String, DateTime, Text
from app.models.base import Base


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id = Column(Integer, primary_key=True, index=True)
    source_name = Column(String(255), nullable=False)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String(50), nullable=False)  # running, success, error
    items_found = Column(Integer, default=0)
    items_created = Column(Integer, default=0)
    items_updated = Column(Integer, default=0)
    items_merged = Column(Integer, default=0)
    error_log = Column(Text, nullable=True)
