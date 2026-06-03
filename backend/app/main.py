import asyncio
import logging
from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.models.base import init_db
from app.models import (  # noqa: F401 - ensures all tables are registered before create_all
    crawl_run, event, event_source, source, cache,
)
from app.api import events
from app.services.cleanup import archive_past_events, purge_old_archives
from app.services.sources_registry import seed_sources

logger = logging.getLogger(__name__)

# Run the full sync every 12h (matches Anforderungskatalog "2× täglich").
SCHEDULED_INTERVAL_SECONDS = int(os.getenv("SYNC_INTERVAL_SECONDS", str(12 * 60 * 60)))


async def _scheduled_sync_loop():
    """Run the full pipeline on a fixed interval."""
    from app.models import base as db_base
    from app.services.pipeline import run_full_sync

    while True:
        await asyncio.sleep(SCHEDULED_INTERVAL_SECONDS)
        logger.info("Scheduled sync starting...")
        if db_base.SessionLocal is None:
            logger.warning("DB not initialized, skipping scheduled sync")
            continue
        db = db_base.SessionLocal()
        try:
            try:
                seed_sources(db)
            except Exception as e:
                logger.warning(f"seed_sources failed: {e}")
            summary = await run_full_sync(db)
            logger.info(f"Scheduled sync complete: {summary['totals']}")
        except Exception as e:
            logger.error(f"Scheduled sync error: {e}")
        finally:
            db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Seed sources synchronously on startup so the admin page always has names.
    from app.models import base as db_base
    if db_base.SessionLocal is not None:
        db = db_base.SessionLocal()
        try:
            seed_sources(db)
        except Exception as e:
            logger.warning(f"Initial seed_sources failed: {e}")
        finally:
            db.close()

    archived = archive_past_events()
    if archived:
        logger.info(f"Startup: {archived} vergangene Events archiviert")
    purged = purge_old_archives()
    if purged:
        logger.info(f"Startup: {purged} alte Archiv-Eintraege geloescht")
    task = asyncio.create_task(_scheduled_sync_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(
    title="Event-App API",
    description="Backend API for Event Discovery App",
    version="0.2.0",
    lifespan=lifespan,
)

# Single-user app, LAN-only by design — wildcard origin is fine for this use case.
# allow_credentials=False so the wildcard is actually accepted by browsers.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(events.router, prefix="/api/v1", tags=["events"])


@app.get("/health")
def health_check():
    """Health check that also verifies DB connectivity."""
    from app.models import base as db_base
    from sqlalchemy import text

    db_ok = False
    if db_base.SessionLocal is not None:
        try:
            db = db_base.SessionLocal()
            db.execute(text("SELECT 1"))
            db.close()
            db_ok = True
        except Exception as e:
            logger.warning(f"Health check DB error: {e}")
    return {"status": "healthy" if db_ok else "degraded", "db": db_ok}
