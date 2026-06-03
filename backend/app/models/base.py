from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import StaticPool
import logging
import os


logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


engine = None
SessionLocal = None


def get_database_url():
    return os.getenv("DATABASE_URL", "postgresql://eventapp:eventapp@localhost:5432/eventapp")


# Maps table -> {column_name: SQL type fragment} for additive columns that should
# be back-filled on existing databases. Only used when the column is missing.
_AUTO_MIGRATIONS: dict[str, dict[str, str]] = {
    "events": {
        "source_count": "INTEGER DEFAULT 1",
        "sources_list": "VARCHAR(500)",
    },
    "crawl_runs": {
        "items_created": "INTEGER DEFAULT 0",
        "items_updated": "INTEGER DEFAULT 0",
        "items_merged": "INTEGER DEFAULT 0",
    },
}


def _auto_migrate(eng):
    """Add columns that exist in the SQLAlchemy model but not yet in the DB.

    This is a pragmatic, additive-only migration that avoids the overhead of
    Alembic for a single-user app. Existing data is preserved.
    """
    inspector = inspect(eng)
    for table, columns in _AUTO_MIGRATIONS.items():
        if not inspector.has_table(table):
            continue
        existing = {col["name"] for col in inspector.get_columns(table)}
        for col_name, col_type in columns.items():
            if col_name in existing:
                continue
            try:
                with eng.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))
                logger.info(f"Auto-migrate: added {table}.{col_name}")
            except Exception as e:
                logger.warning(f"Auto-migrate failed for {table}.{col_name}: {e}")


def init_db():
    global engine, SessionLocal
    db_url = get_database_url()
    engine = create_engine(
        db_url,
        pool_pre_ping=True,
        poolclass=StaticPool if "sqlite" in db_url else None
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    # Import all models so metadata picks them up before create_all
    from app.models import event, crawl_run, source, event_source, cache  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _auto_migrate(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
