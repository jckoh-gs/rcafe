"""Use cases for collecting cafe data around a center point."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.domain.models import GeoPoint, SearchHit, UpsertResult
from app.domain.ports import (
    CafeRepository,
    ClockPort,
    PlaceDetailPort,
    PlaceFetchError,
    PlaceSearchPort,
)
from app.domain.services import filter_hits, grid_points

log = logging.getLogger(__name__)

DEFAULT_KEYWORDS = ("카페", "커피", "디저트", "베이커리")
MAX_UNEXPECTED_IN_A_ROW = 5
FLUSH_EVERY = 100  # requests between database flushes, so an interrupted crawl keeps its progress


@dataclass(frozen=True, slots=True)
class DiscoverParams:
    center: GeoPoint
    radius_m: float = 2000.0
    spacing_m: float = 300.0
    keywords: tuple[str, ...] = DEFAULT_KEYWORDS
    max_requests: int | None = None


@dataclass(slots=True)
class DiscoverReport:
    requests: int = 0
    hits_seen: int = 0
    failed_requests: int = 0
    stopped_early: bool = False  # the deadline passed before the whole grid was searched
    unique_places: int = 0
    upsert: UpsertResult = field(default_factory=UpsertResult)


class DiscoverCafes:
    """Sweep a grid x keyword matrix over the search API and upsert every cafe found."""

    def __init__(self, search: PlaceSearchPort, repo: CafeRepository, clock: ClockPort) -> None:
        self._search = search
        self._repo = repo
        self._clock = clock

    async def run(
        self,
        params: DiscoverParams,
        progress: Callable[[DiscoverReport], None] | None = None,
        deadline: datetime | None = None,
    ) -> DiscoverReport:
        """Sweep the area; stops early (keeping what it found) once `deadline` has passed."""
        report = DiscoverReport()
        buffer: dict[str, SearchHit] = {}
        all_ids: set[str] = set()
        try:
            for point in grid_points(params.center, params.radius_m, params.spacing_m):
                for keyword in params.keywords:
                    if params.max_requests is not None and report.requests >= params.max_requests:
                        return report
                    if deadline is not None and self._clock.now() >= deadline:
                        report.stopped_early = True
                        return report
                    report.requests += 1
                    try:
                        hits = await self._search.search(keyword, point)
                    except PlaceFetchError:
                        log.warning("search failed for %r at %s; skipping", keyword, point)
                        report.failed_requests += 1
                        continue
                    report.hits_seen += len(hits)
                    for hit in filter_hits(hits, params.center, params.radius_m):
                        buffer[hit.place_id] = hit
                        all_ids.add(hit.place_id)
                    report.unique_places = len(all_ids)
                    if report.requests % FLUSH_EVERY == 0:
                        await self._flush(buffer, report)
                    if progress and report.requests % 25 == 0:
                        progress(report)
            return report
        finally:
            # Persist what was found even when the upstream blocks us half-way through.
            await self._flush(buffer, report)

    async def _flush(self, buffer: dict[str, SearchHit], report: DiscoverReport) -> None:
        if buffer:
            report.upsert += await self._repo.upsert_hits(list(buffer.values()), self._clock.now())
            buffer.clear()


@dataclass(slots=True)
class DetailReport:
    attempted: int = 0
    saved: UpsertResult = field(default_factory=UpsertResult)
    missing: int = 0
    failed: int = 0
    stopped_early: bool = False


class FetchCafeDetails:
    """Fetch menus, reviews, photos, and business status for places that need it."""

    def __init__(self, details: PlaceDetailPort, repo: CafeRepository, clock: ClockPort) -> None:
        self._details = details
        self._repo = repo
        self._clock = clock

    async def run(
        self,
        limit: int = 100,
        max_age: timedelta = timedelta(days=7),
        progress: Callable[[DetailReport], None] | None = None,
        deadline: datetime | None = None,
        area: tuple[GeoPoint, float] | None = None,
    ) -> DetailReport:
        """Fetch details for places that need them (optionally only inside `area`)."""
        report = DetailReport()
        unexpected = 0
        ids = await self._repo.place_ids_needing_detail(self._clock.now() - max_age, limit, area)
        for place_id in ids:
            if deadline is not None and self._clock.now() >= deadline:
                report.stopped_early = True
                break
            report.attempted += 1
            try:
                detail = await self._details.fetch_detail(place_id)
                if detail is None:
                    report.missing += 1
                    await self._repo.mark_inactive(place_id, self._clock.now())
                else:
                    report.saved += await self._repo.save_detail(detail, self._clock.now())
                unexpected = 0
            except PlaceFetchError:
                log.warning("detail fetch failed for %s; will retry next run", place_id)
                report.failed += 1
                continue
            except Exception:
                # One odd place (bad data, a database constraint) must not stop the whole crawl,
                # but a systematic failure should: give up after a few in a row.
                log.exception("could not store %s; skipping it", place_id)
                report.failed += 1
                unexpected += 1
                if unexpected >= MAX_UNEXPECTED_IN_A_ROW:
                    raise
            if progress and report.attempted % 10 == 0:
                progress(report)
        return report
