"""Central registry of all event source sync functions.

Single source of truth used by the manual sync endpoint, the scheduled sync,
and any future tooling. Adding a new source means appending one entry here.
"""
from typing import Awaitable, Callable, NamedTuple
from sqlalchemy.orm import Session

from app.services.rausgegangen import sync_rausgegangen
from app.services.zollverein import sync_zollverein
from app.services.ruhrpott_kids import sync_ruhrpott_kids
from app.services.wasgehtapp import sync_wasgehtapp
from app.services.grugapark import sync_grugapark
from app.services.borbeck import sync_borbeck
from app.services.gasometer import sync_gasometer
from app.services.unperfekthaus import sync_unperfekthaus
from app.services.theater_essen import sync_theater_essen
from app.services.folkwang import sync_folkwang
from app.services.waddische import sync_waddische
from app.services.seaside_beach import sync_seaside_beach
from app.services.ferienspatz import sync_ferienspatz
from app.services.artistical import sync_artistical
from app.services.villa_huegel import sync_villa_huegel
from app.services.zeche_carl import sync_zeche_carl
from app.services.grend import sync_grend
from app.services.lichtburg import sync_lichtburg
from app.services.schatzkammer_werden import sync_schatzkammer_werden


SyncFn = Callable[[Session], Awaitable[int]]


class SourceEntry(NamedTuple):
    name: str
    sync_fn: SyncFn
    base_url: str
    source_type: str  # api | rss | html | playwright


SOURCES: list[SourceEntry] = [
    SourceEntry("Zollverein", sync_zollverein, "https://www.zollverein.de/", "api"),
    SourceEntry("Rausgegangen", sync_rausgegangen, "https://www.rausgegangen.de/", "playwright"),
    SourceEntry("Ruhrpott-Kids", sync_ruhrpott_kids, "https://ruhrpottkids.com/", "rss"),
    SourceEntry("wasgehtapp", sync_wasgehtapp, "https://www.wasgehtapp.de/", "playwright"),
    SourceEntry("Grugapark", sync_grugapark, "https://www.grugapark.de/", "html"),
    SourceEntry("borbeck.de", sync_borbeck, "https://www.borbeck.de/", "rss"),
    SourceEntry("Gasometer", sync_gasometer, "https://www.gasometer.de/", "playwright"),
    SourceEntry("Unperfekthaus", sync_unperfekthaus, "https://www.unperfekthaus.de/", "playwright"),
    SourceEntry("Theater Essen", sync_theater_essen, "https://www.theater-essen.de/", "playwright"),
    SourceEntry("Museum Folkwang", sync_folkwang, "https://www.museum-folkwang.de/", "playwright"),
    SourceEntry("Werdener Nachrichten", sync_waddische, "https://waddische.de/", "html"),
    SourceEntry("Seaside Beach", sync_seaside_beach, "https://www.seaside-beach.de/", "html"),
    SourceEntry("Ferienspatz", sync_ferienspatz, "https://ferienspatz.essen.de/", "html"),
    SourceEntry("GOP Varieté", sync_artistical, "https://artistical.de/", "html"),
    SourceEntry("Villa Hügel", sync_villa_huegel, "https://www.krupp-stiftung.de/", "html"),
    SourceEntry("Zeche Carl", sync_zeche_carl, "https://www.zechecarl.de/", "html"),
    SourceEntry("GREND", sync_grend, "https://grend.de/", "html"),
    SourceEntry("Lichtburg", sync_lichtburg, "https://filmspiegel-essen.de/buehne/", "html"),
    SourceEntry("Schatzkammer Werden", sync_schatzkammer_werden, "https://www.schatzkammer-werden.de/", "html"),
]


def seed_sources(db: Session) -> int:
    """Insert/update entries in the `sources` table so the DB knows about
    all configured crawlers. Returns the number of rows inserted."""
    from app.models.source import Source

    inserted = 0
    for entry in SOURCES:
        existing = db.query(Source).filter(Source.name == entry.name).first()
        if existing:
            existing.base_url = entry.base_url
            existing.source_type = entry.source_type
            existing.extraction_mode = entry.source_type
            existing.active = True
        else:
            db.add(Source(
                name=entry.name,
                base_url=entry.base_url,
                source_type=entry.source_type,
                extraction_mode=entry.source_type,
                active=True,
            ))
            inserted += 1
    db.commit()
    return inserted
