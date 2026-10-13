"""Use cases for visitor-requested collection: taking requests and running them in quiet hours."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from enum import StrEnum
from typing import Protocol

from app.application.ingest import (
    DEFAULT_KEYWORDS,
    DiscoverCafes,
    DiscoverParams,
    FetchCafeDetails,
)
from app.domain.models import CollectionRequest, CollectionStatus, GeoPoint
from app.domain.ports import ClockPort, CollectionRequestRepository

log = logging.getLogger(__name__)


class TasteUpdater(Protocol):
    async def run(self, only_new: bool = False) -> object: ...


class ReviewTextPurger(Protocol):
    async def purge_raw_review_text(self) -> int: ...


KST = timezone(timedelta(hours=9))
RUN_AT = time(3, 30)  # quiet hours: the nightly CronJob starts at 03:30 Korean time

COVERED_MIN_CAFES = 10  # this many cafes within COVERED_RADIUS_M means the area is already served
COVERED_RADIUS_M = 1000.0
COLLECT_RADIUS_M = 1500
MAX_QUEUE = 100  # waiting + running requests
MAX_NEW_PER_DAY = 30  # new areas accepted per rolling 24 hours (a guard against abuse)
STALE_RUNNING_AFTER = timedelta(hours=4)  # a run never lasts this long; its request was orphaned


class RequestStatus(StrEnum):
    QUEUED = "queued"  # accepted just now
    ALREADY_QUEUED = "already_queued"  # someone asked before; the count went up
    COLLECTING = "collecting"  # running right now
    DONE = "done"  # collected earlier (maybe nothing was found)
    COVERED = "covered"  # the area already has data
    BUSY = "busy"  # the queue is full
    LIMIT = "limit"  # too many new areas today


@dataclass(frozen=True, slots=True)
class RequestOutcome:
    status: RequestStatus
    request_count: int = 0
    cafes_found: int | None = None
    next_run: datetime | None = None  # when the next quiet-hours run starts (KST)


def next_run_after(now: datetime) -> datetime:
    """The next 03:30 Korean time strictly after `now`."""
    local = now.astimezone(KST)
    candidate = datetime.combine(local.date(), RUN_AT, tzinfo=KST)
    return candidate if candidate > local else candidate + timedelta(days=1)


class RequestCollection:
    """Takes a visitor's request for an area without data and queues it for the night run."""

    def __init__(self, repo: CollectionRequestRepository, clock: ClockPort) -> None:
        self._repo = repo
        self._clock = clock

    async def submit(self, point: GeoPoint) -> RequestOutcome:
        now = self._clock.now()
        existing = await self._repo.find(point)
        if existing is None:
            if await self._repo.count_cafes_near(point, COVERED_RADIUS_M) >= COVERED_MIN_CAFES:
                return RequestOutcome(RequestStatus.COVERED)
            if await self._repo.count_created_since(now - timedelta(days=1)) >= MAX_NEW_PER_DAY:
                return RequestOutcome(RequestStatus.LIMIT)
            if await self._repo.count_pending() >= MAX_QUEUE:
                return RequestOutcome(RequestStatus.BUSY)
        request, created = await self._repo.submit(point, now, COLLECT_RADIUS_M)
        return self._outcome(request, created, now)

    async def status(self, point: GeoPoint) -> RequestOutcome | None:
        """What happened to an earlier request for this area (None if nobody asked)."""
        request = await self._repo.find(point)
        if request is None:
            return None
        return self._outcome(request, created=False, now=self._clock.now())

    @staticmethod
    def _outcome(request: CollectionRequest, created: bool, now: datetime) -> RequestOutcome:
        count = request.request_count
        if request.status is CollectionStatus.RUNNING:
            return RequestOutcome(RequestStatus.COLLECTING, count)
        if request.status is CollectionStatus.DONE:
            return RequestOutcome(RequestStatus.DONE, count, request.cafes_found)
        status = RequestStatus.QUEUED if created else RequestStatus.ALREADY_QUEUED
        return RequestOutcome(status, count, next_run=next_run_after(now))


@dataclass(slots=True)
class CollectionRunReport:
    started: int = 0
    done: int = 0
    interrupted: int = 0
    failed: int = 0
    new_cafes: int = 0
    stopped_by_block: bool = False
    notes: list[str] = field(default_factory=list)


class RunCollectionRequests:
    """Works through the queue inside a time budget; safe to interrupt and rerun.

    Each request: search the area, fetch menus/reviews of the places that have none, compute tastes
    for the new cafes only, then drop the temporary review text. Everything upserts by place id, so
    an interrupted request is simply put back in the queue and continues where it left off.
    """

    def __init__(
        self,
        requests: CollectionRequestRepository,
        discover: DiscoverCafes,
        details: FetchCafeDetails,
        tastes: TasteUpdater,
        taste_repo: ReviewTextPurger,
        clock: ClockPort,
        blocked_errors: tuple[type[BaseException], ...] = (),
    ) -> None:
        self._requests = requests
        self._discover = discover
        self._details = details
        self._tastes = tastes
        self._taste_repo = taste_repo
        self._clock = clock
        self._blocked = blocked_errors

    async def run(
        self,
        budget: timedelta,
        max_requests: int = 10,
        progress: Callable[[str], None] | None = None,
        request_id: int | None = None,
    ) -> CollectionRunReport:
        """Run the queue, or only the request `request_id` (an administrator's "run now")."""
        report = CollectionRunReport()
        now = self._clock.now()
        deadline = now + budget
        recovered = await self._requests.reset_stale_running(
            now - STALE_RUNNING_AFTER, "the previous run stopped unexpectedly; queued again"
        )
        if recovered:
            report.notes.append(f"{recovered} orphaned request(s) put back in the queue")
        queue = await self._queue(request_id, max_requests)
        if request_id is not None and not queue:
            report.notes.append(f"request {request_id} does not exist or is already running")
        for request in queue:
            if self._clock.now() >= deadline:
                break
            report.started += 1
            await self._requests.mark_running(request.id, self._clock.now())
            if progress:
                progress(f"collecting {request.cell_key} ({request.request_count} requests)")
            try:
                found, finished = await self._collect(request, deadline)
            except self._blocked as exc:
                await self._requests.mark_retry(request.id, self._clock.now(), f"blocked: {exc}")
                report.interrupted += 1
                report.stopped_by_block = True
                report.notes.append(f"{request.cell_key}: upstream blocked, stopping the run")
                break
            except Exception as exc:  # one bad area must not stop the others
                log.exception("collection request %s failed", request.id)
                await self._requests.mark_failed(request.id, self._clock.now(), str(exc)[:200])
                report.failed += 1
                continue
            if finished:
                await self._requests.mark_done(request.id, self._clock.now(), found)
                report.done += 1
                report.new_cafes += found
            else:
                await self._requests.mark_retry(
                    request.id, self._clock.now(), "time budget used up; continues next run"
                )
                report.interrupted += 1
                break
        return report

    async def _queue(self, request_id: int | None, max_requests: int) -> list[CollectionRequest]:
        if request_id is None:
            return await self._requests.next_pending(max_requests)
        request = await self._requests.get(request_id)
        if request is None or request.status is CollectionStatus.RUNNING:
            return []
        return [request]

    async def _collect(self, request: CollectionRequest, deadline: datetime) -> tuple[int, bool]:
        area = (request.center, float(request.radius_m))
        sweep = await self._discover.run(
            DiscoverParams(
                center=request.center,
                radius_m=float(request.radius_m),
                spacing_m=400.0,
                keywords=DEFAULT_KEYWORDS,
            ),
            deadline=deadline,
        )
        if sweep.stopped_early:
            return sweep.unique_places, False
        detail = await self._details.run(
            limit=2000, max_age=timedelta(days=36500), deadline=deadline, area=area
        )
        if detail.stopped_early:
            return sweep.unique_places, False
        # taste vectors for the new cafes only, then the temporary review text goes away
        await self._tastes.run(only_new=True)
        await self._taste_repo.purge_raw_review_text()
        return sweep.unique_places, True
