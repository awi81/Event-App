"""Shared test fixtures for the Event-App backend."""
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

# Set test database URL BEFORE importing app modules
os.environ["DATABASE_URL"] = "sqlite://"

from app.models.base import Base, get_db
from app.main import app


@pytest.fixture
def db_engine():
    """Create an in-memory SQLite engine for testing."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(db_engine):
    """Create a database session for testing."""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_engine):
    """Create a FastAPI test client with test database."""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def sample_events(db_session):
    """Insert sample events into the test database."""
    from app.models.event import Event, KidsSuitable, IndoorOutdoor
    from datetime import datetime, timezone

    # Use far-future dates so the past-event filter doesn't hide the fixtures.
    events = [
        Event(
            canonical_id="test_001",
            title="Kinderführung Zollverein",
            short_description="Führung für Kinder durch das UNESCO-Welterbe",
            start_at=datetime(2099, 3, 21, 10, 0, tzinfo=timezone.utc),
            category="Führungen",
            venue_name="Zollverein",
            city="Essen",
            lat=51.4864,
            lon=7.0403,
            source_name="Zollverein",
            source_url="https://www.zollverein.de/event/1",
            indoor_outdoor=IndoorOutdoor.both,
            kids_suitable=KidsSuitable.yes,
            quality_score=0.8,
        ),
        Event(
            canonical_id="test_002",
            title="Jazz Konzert im Grillo",
            start_at=datetime(2099, 3, 22, 20, 0, tzinfo=timezone.utc),
            category="Musik",
            venue_name="Grillo-Theater",
            city="Essen",
            lat=51.4516,
            lon=7.0133,
            source_name="Rausgegangen",
            indoor_outdoor=IndoorOutdoor.indoor,
            kids_suitable=KidsSuitable.no,
            quality_score=0.7,
        ),
        Event(
            canonical_id="test_003",
            title="Grugapark Ostermarkt",
            start_at=datetime(2099, 3, 20, 11, 0, tzinfo=timezone.utc),
            category="Märkte",
            venue_name="Grugapark",
            city="Essen",
            lat=51.4293,
            lon=7.0561,
            source_name="Rausgegangen",
            indoor_outdoor=IndoorOutdoor.outdoor,
            kids_suitable=KidsSuitable.likely,
            is_permanent_offer=False,
            quality_score=0.9,
        ),
        Event(
            canonical_id="test_004",
            title="Dauerausstellung Ruhr Museum",
            short_description="Die Dauerausstellung des Ruhr Museums",
            category="Kultur",
            venue_name="Ruhr Museum",
            city="Essen",
            lat=51.4864,
            lon=7.0403,
            source_name="Zollverein",
            indoor_outdoor=IndoorOutdoor.indoor,
            kids_suitable=KidsSuitable.unknown,
            is_permanent_offer=True,
            quality_score=0.6,
        ),
        Event(
            canonical_id="test_005",
            title="Workshop ohne Koordinaten",
            start_at=datetime(2099, 3, 25, 14, 0, tzinfo=timezone.utc),
            category="Workshops",
            city="Essen",
            source_name="wasgehtapp.de",
            kids_suitable=KidsSuitable.unknown,
            quality_score=0.5,
        ),
    ]

    for event in events:
        db_session.add(event)
    db_session.commit()
    return events
