"""Use cases for the administrator: look at the collection queue, delete, requeue, run now."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.application.collection import COVERED_RADIUS_M
from app.domain.models import CollectionRequest, CollectionStatus
from app.domain.ports import CollectionRequestRepository, CollectorLauncher

LIST_LIMIT = 300


class AdminResult(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    RUNNING = "running"  # the request itself is being collected right now
    COLLECTOR_BUSY = "collector_busy"  # another collector run is working


@dataclass(frozen=True, slots=True)
class AdminRequestView:
    request: CollectionRequest
    cafes_nearby: int  # active cafes within 1 km of the area's center


@dataclass(frozen=True, slots=True)
class AdminOverview:
    items: list[AdminRequestView]
    counts: dict[CollectionStatus, int]
    collector_running: bool


class ManageCollectionRequests:
    def __init__(self, repo: CollectionRequestRepository, launcher: CollectorLauncher) -> None:
        self._repo = repo
        self._launcher = launcher

    async def overview(self, limit: int = LIST_LIMIT) -> AdminOverview:
        items = [
            AdminRequestView(r, await self._repo.count_cafes_near(r.center, COVERED_RADIUS_M))
            for r in await self._repo.list_all(limit)
        ]
        counts = await self._repo.count_by_status()
        return AdminOverview(
            items=items,
            counts={status: counts.get(status, 0) for status in CollectionStatus},
            collector_running=await self._launcher.is_running(),
        )

    async def delete(self, request_id: int) -> AdminResult:
        if await self._repo.delete(request_id):
            return AdminResult.OK
        return await self._why_not(request_id)

    async def requeue(self, request_id: int) -> AdminResult:
        """Back into the queue for tonight's run (for a failed or finished request)."""
        if await self._repo.requeue(request_id, "관리자가 다시 대기열에 넣었어요"):
            return AdminResult.OK
        return await self._why_not(request_id)

    async def run_now(self, request_id: int) -> tuple[AdminResult, str | None]:
        """Start a collector for this request right away; returns the name of what was started.

        One collector at a time: two crawlers at once would double the load on Naver and get us
        blocked, so a running collector (nightly or manual) makes this wait.
        """
        request = await self._repo.get(request_id)
        if request is None:
            return AdminResult.NOT_FOUND, None
        if request.status is CollectionStatus.RUNNING:
            return AdminResult.RUNNING, None
        if await self._launcher.is_running():
            return AdminResult.COLLECTOR_BUSY, None
        return AdminResult.OK, await self._launcher.launch(
            request_id
        )  # may raise CollectorUnavailable

    async def _why_not(self, request_id: int) -> AdminResult:
        if await self._repo.get(request_id) is None:
            return AdminResult.NOT_FOUND
        return AdminResult.RUNNING
