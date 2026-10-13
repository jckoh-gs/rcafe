"""In-memory fakes of the ports for use-case and API tests."""

import math
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from app.application.recommend import RecommendCafes
from app.application.taste import FindWeatherTaste
from app.domain.models import (
    BusinessInfo,
    BusinessStatus,
    CollectionRequest,
    CollectionStatus,
    DayHours,
    GeoPoint,
)
from app.domain.recommend import Candidate
from app.domain.services import cell_for, haversine_m
from app.domain.taste import AxisStats, MenuEvidence, compute_axis_stats, vec
from app.domain.weather import Archetype, WeatherObservation, build_scenarios

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 9, 14, 0, tzinfo=KST)  # Friday afternoon
YEOKSAM = GeoPoint(37.5006431, 127.0363766)


class FixedClock:
    def __init__(self, now: datetime = NOW) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class FakeWeather:
    def __init__(self, observation: WeatherObservation | None) -> None:
        self.observation = observation
        self.calls = 0

    async def observation_at(self, point: GeoPoint, now: datetime) -> WeatherObservation | None:
        self.calls += 1
        return self.observation


class FakeArchetypes:
    """Brute-force L2 search over the real scenario grid (what pgvector does in production)."""

    def __init__(self) -> None:
        self._archetypes = build_scenarios()

    async def upsert_archetypes(self, archetypes: Sequence[Archetype]) -> int:
        return len(archetypes)

    async def nearest_archetypes(
        self, weather_vec: Sequence[float], k: int
    ) -> list[tuple[Archetype, float]]:
        scored = [(a, math.dist(a.weather_vec, weather_vec)) for a in self._archetypes]
        return sorted(scored, key=lambda pair: pair[1])[:k]


class FakeTastes:
    def __init__(self, stats: AxisStats | None) -> None:
        self._stats = stats

    async def load_axis_stats(self) -> AxisStats | None:
        return self._stats


class FakeCandidates:
    def __init__(self, candidates: list[Candidate]) -> None:
        self._candidates = candidates
        self.radii: list[float] = []

    async def candidates_near(self, center: GeoPoint, radius_m: float) -> list[Candidate]:
        self.radii.append(radius_m)
        return [c for c in self._candidates if haversine_m(center, c.point) <= radius_m]


def hot_day() -> WeatherObservation:
    return WeatherObservation("108", NOW, 32.0, 70.0, 1.0, 0.0, 2.0)


def candidate(
    place_id: str,
    name: str,
    taste: tuple[float, ...],
    menus: tuple[str, ...],
    meters_north: float = 100.0,
    open_: bool = True,
    rating: float = 4.6,
) -> Candidate:
    point = GeoPoint(YEOKSAM.lat + meters_north / 111_320, YEOKSAM.lng)
    hours = (DayHours("금(10/9)", "08:00", "22:00"), DayHours("토", "08:00", "22:00"))
    closed_hours = (DayHours("금(10/9)", "17:00", "23:00"), DayHours("토", "17:00", "23:00"))
    return Candidate(
        place_id=place_id,
        name=name,
        point=point,
        road_address=f"서울 강남구 테헤란로 {place_id}",
        rating=rating,
        review_count=200,
        taste=taste,
        confidence=1.0,
        menus=tuple(MenuEvidence(m, None, 5500, f"https://img.test/{place_id}.jpg") for m in menus),
        business=BusinessInfo(
            BusinessStatus.OPEN if open_ else BusinessStatus.CLOSED,
            None,
            hours if open_ else closed_hours,
        ),
        status_checked_at=None,  # force the hours table to decide, relative to NOW
        review_axis_counts={"sour_fresh": 4} if "에이드" in menus[0] else {},
        review_total=10,
        cover_photo_url=f"https://img.test/{place_id}-cover.jpg",
        photo_urls=(),
    )


FRUITY = vec(hot=0.2, iced=0.8, sour_fresh=0.9, light=0.7)
CREAMY = vec(hot=0.7, iced=0.2, rich_creamy=0.9, sweet=0.8)
ROAST = vec(hot=0.5, iced=0.5, bitter_roast=0.9, caffeine_boost=0.8)
STATS = compute_axis_stats(
    [vec(sweet=0.3, sour_fresh=0.2, bitter_roast=0.3), FRUITY, CREAMY, ROAST]
)


def build_use_case(
    candidates: list[Candidate],
    observation: WeatherObservation | None = None,
    stats: AxisStats | None = STATS,
    now: datetime = NOW,
    weather: FakeWeather | None = None,
) -> tuple[RecommendCafes, FakeCandidates]:
    source = FakeCandidates(candidates)
    weather = weather or FakeWeather(observation if observation is not None else hot_day())
    use_case = RecommendCafes(
        weather,
        FindWeatherTaste(FakeArchetypes()),
        source,
        FakeTastes(stats),
        FixedClock(now),
    )
    return use_case, source


class FakeCollectionRepo:
    """In-memory CollectionRequestRepository (same rules as the Postgres one)."""

    def __init__(self, cafes_near: int = 0) -> None:
        self.rows: dict[str, CollectionRequest] = {}
        self._next_id = 1
        self.cafes_near = cafes_near

    async def submit(
        self, point: GeoPoint, at: datetime, radius_m: int
    ) -> tuple[CollectionRequest, bool]:
        key, center = cell_for(point)
        existing = self.rows.get(key)
        if existing is not None:
            status = (
                CollectionStatus.PENDING
                if existing.status is CollectionStatus.FAILED
                else existing.status
            )
            updated = replace(
                existing,
                request_count=existing.request_count + 1,
                last_requested_at=at,
                status=status,
            )
            self.rows[key] = updated
            return updated, False
        row = CollectionRequest(
            self._next_id, key, center, radius_m, CollectionStatus.PENDING, 1, at, at
        )
        self._next_id += 1
        self.rows[key] = row
        return row, True

    async def find(self, point: GeoPoint) -> CollectionRequest | None:
        return self.rows.get(cell_for(point)[0])

    async def next_pending(self, limit: int) -> list[CollectionRequest]:
        pending = [r for r in self.rows.values() if r.status is CollectionStatus.PENDING]
        pending.sort(key=lambda r: (-r.request_count, r.requested_at))
        return pending[:limit]

    def _update(self, request_id: int, **changes: Any) -> None:
        for key, row in self.rows.items():
            if row.id == request_id:
                self.rows[key] = replace(row, **changes)

    async def mark_running(self, request_id: int, at: datetime) -> None:
        self._update(request_id, status=CollectionStatus.RUNNING, started_at=at)

    async def mark_done(self, request_id: int, at: datetime, cafes_found: int) -> None:
        self._update(
            request_id, status=CollectionStatus.DONE, finished_at=at, cafes_found=cafes_found
        )

    async def mark_retry(self, request_id: int, at: datetime, note: str) -> None:
        self._update(request_id, status=CollectionStatus.PENDING, note=note)

    async def mark_failed(self, request_id: int, at: datetime, note: str) -> None:
        self._update(request_id, status=CollectionStatus.FAILED, finished_at=at, note=note)

    async def count_pending(self) -> int:
        active = (CollectionStatus.PENDING, CollectionStatus.RUNNING)
        return sum(1 for r in self.rows.values() if r.status in active)

    async def count_created_since(self, since: datetime) -> int:
        return sum(1 for r in self.rows.values() if r.requested_at >= since)

    async def count_cafes_near(self, center: GeoPoint, radius_m: float) -> int:
        return self.cafes_near

    async def get(self, request_id: int) -> CollectionRequest | None:
        return next((r for r in self.rows.values() if r.id == request_id), None)

    async def list_all(self, limit: int) -> list[CollectionRequest]:
        order = {
            CollectionStatus.RUNNING: 0,
            CollectionStatus.PENDING: 1,
            CollectionStatus.FAILED: 2,
            CollectionStatus.DONE: 3,
        }
        rows = sorted(self.rows.values(), key=lambda r: (order[r.status], -r.request_count))
        return rows[:limit]

    async def delete(self, request_id: int) -> bool:
        row = await self.get(request_id)
        if row is None or row.status is CollectionStatus.RUNNING:
            return False
        del self.rows[row.cell_key]
        return True

    async def requeue(self, request_id: int, note: str | None = None) -> bool:
        row = await self.get(request_id)
        if row is None or row.status is CollectionStatus.RUNNING:
            return False
        self._update(request_id, status=CollectionStatus.PENDING, note=note)
        return True

    async def count_by_status(self) -> dict[CollectionStatus, int]:
        counts: dict[CollectionStatus, int] = {}
        for row in self.rows.values():
            counts[row.status] = counts.get(row.status, 0) + 1
        return counts

    async def reset_stale_running(self, started_before: datetime, note: str) -> int:
        stale = [
            r
            for r in self.rows.values()
            if r.status is CollectionStatus.RUNNING
            and r.started_at is not None
            and r.started_at < started_before
        ]
        for row in stale:
            self._update(row.id, status=CollectionStatus.PENDING, note=note)
        return len(stale)
