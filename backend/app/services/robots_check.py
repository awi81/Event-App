"""Check robots.txt for every registered source.

Uses stdlib `urllib.robotparser`. Result is cached in-process for an hour to
avoid hammering each domain on repeated admin-page reloads.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx

from app.services.geocoder import NOMINATIM_USER_AGENT  # reuse identifying UA
from app.services.sources_registry import SOURCES, SourceEntry

logger = logging.getLogger(__name__)


@dataclass
class RobotsResult:
    source: str
    base_url: str
    robots_url: Optional[str]
    fetched: bool
    allowed: Optional[bool]  # None if robots.txt unreachable
    crawl_delay: Optional[float]
    raw_excerpt: Optional[str]
    error: Optional[str]


_CACHE: dict[str, tuple[float, RobotsResult]] = {}
_CACHE_TTL = 60 * 60  # 1 hour


def _robots_url_for(base_url: str) -> str:
    p = urlparse(base_url)
    return urlunparse((p.scheme, p.netloc, "/robots.txt", "", "", ""))


def check_source(entry: SourceEntry) -> RobotsResult:
    """Fetch and evaluate robots.txt for one source. Cached for an hour."""
    cached = _CACHE.get(entry.name)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL:
        return cached[1]

    robots_url = _robots_url_for(entry.base_url)
    result = RobotsResult(
        source=entry.name,
        base_url=entry.base_url,
        robots_url=robots_url,
        fetched=False,
        allowed=None,
        crawl_delay=None,
        raw_excerpt=None,
        error=None,
    )

    try:
        response = httpx.get(
            robots_url,
            timeout=10.0,
            headers={"User-Agent": NOMINATIM_USER_AGENT},
            follow_redirects=True,
        )
        if response.status_code == 200:
            body = response.text
            parser = RobotFileParser()
            parser.parse(body.splitlines())
            allowed = parser.can_fetch(NOMINATIM_USER_AGENT, entry.base_url)
            crawl_delay = parser.crawl_delay(NOMINATIM_USER_AGENT)
            result.fetched = True
            result.allowed = allowed
            result.crawl_delay = float(crawl_delay) if crawl_delay else None
            result.raw_excerpt = body[:600]
        elif response.status_code == 404:
            # Per RFC 9309 / RFC 8615: missing robots.txt means "allowed".
            result.fetched = True
            result.allowed = True
            result.raw_excerpt = "(no robots.txt found - access allowed by default)"
        else:
            result.error = f"HTTP {response.status_code}"
    except Exception as e:
        result.error = str(e)
        logger.warning(f"robots.txt fetch failed for {entry.name}: {e}")

    _CACHE[entry.name] = (time.monotonic(), result)
    return result


def check_all_sources() -> list[RobotsResult]:
    """Check robots.txt for every source. Sequential, ~10s for 12 sources."""
    return [check_source(entry) for entry in SOURCES]
