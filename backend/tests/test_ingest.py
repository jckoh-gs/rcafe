"""Use-case tests with in-memory fakes of the ports (no network, no DB)."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from app.application.ingest import DiscoverCafes, DiscoverParams, FetchCafeDetails
from app.domain.models import (
    BusinessInfo,
    BusinessStatus,
    GeoPoint,
    PlaceDetail,
    SearchHit,
    UpsertResult,
)
from app.domain.ports import PlaceFetchError

CENTER = GeoPoint(37.5006431, 127.0363766)
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeSearch:
    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits
        self.calls: list[tuple[str, GeoPoint]] = []

    async def search(self, query: str, center: GeoPoint) -> list[SearchHit]:
        self.calls.append((query, center))
        return self.hits


class FakeRepo:
    def __init__(self, pending: list[str] | None = None) -> None:
        self.hits: dict[str, SearchHit] = {}
        self.pending = pending or []
        self.saved: list[str] = []
        self.inactive: list[str] = []

    async def upsert_hits(self, hits: Sequence[SearchHit], seen_at: datetime) -> UpsertResult:
        new = [h for h in hits if h.place_id not in self.hits]
        self.hits.update({h.place_id: h for h in hits})
        return UpsertResult(inserted=len(new), updated=len(hits) - len(new))

    async def place_ids_needing_detail(
        self,
        older_than: datetime,
        limit: int,
        area: tuple[GeoPoint, float] | None = None,
    ) -> list[str]:
        return self.pending[:limit]

    async def save_detail(self, detail: PlaceDetail, fetched_at: datetime) -> UpsertResult:
        self.saved.append(detail.place_id)
        return UpsertResult(updated=1)

    async def mark_inactive(self, place_id: str, at: datetime) -> None:
        self.inactive.append(place_id)


class FakeDetails:
    def __init__(self, missing: set[str], failing: set[str]) -> None:
        self.missing, self.failing = missing, failing

    async def fetch_detail(self, place_id: str) -> PlaceDetail | None:
        if place_id in self.failing:
            raise PlaceFetchError("boom")
        if place_id in self.missing:
            return None
        return PlaceDetail(
            place_id,
            "n",
            None,
            4.0,
            1,
            None,
            BusinessInfo(BusinessStatus.OPEN, None),
            (),
            (),
            (),
            (),
        )


def _hit(place_id: str, lat: float = 37.5010, lng: float = 127.0370) -> SearchHit:
    return SearchHit(
        place_id, f"cafe-{place_id}", GeoPoint(lat, lng), "카페,디저트", None, None, 5, 1.0, False
    )


async def test_discover_dedupes_places_across_grid_points_and_keywords() -> None:
    search = FakeSearch([_hit("a"), _hit("b"), _hit("far", 37.7, 127.3)])
    repo = FakeRepo()
    params = DiscoverParams(CENTER, radius_m=600, spacing_m=300, keywords=("카페", "커피"))
    report = await DiscoverCafes(search, repo, FixedClock()).run(params)
    assert report.requests == len(search.calls) > 2
    assert (
        report.unique_places == 2
    )  # same two places returned on every call; "far" is filtered out
    assert set(repo.hits) == {"a", "b"}
    assert report.upsert.inserted == 2


async def test_discover_stops_at_max_requests_but_still_saves() -> None:
    search = FakeSearch([_hit("a")])
    repo = FakeRepo()
    params = DiscoverParams(CENTER, radius_m=2000, spacing_m=300, max_requests=3)
    report = await DiscoverCafes(search, repo, FixedClock()).run(params)
    assert report.requests == 3 and set(repo.hits) == {"a"}


async def test_fetch_details_handles_missing_and_failing_places() -> None:
    repo = FakeRepo(pending=["ok", "gone", "flaky"])
    uc = FetchCafeDetails(FakeDetails(missing={"gone"}, failing={"flaky"}), repo, FixedClock())
    report = await uc.run(limit=10, max_age=timedelta(days=7))
    assert (report.attempted, report.missing, report.failed) == (3, 1, 1)
    assert repo.saved == ["ok"] and repo.inactive == ["gone"]
    assert report.saved.updated == 1


class BlockingSearch(FakeSearch):
    """Succeeds twice, then the upstream refuses us."""

    async def search(self, query: str, center: GeoPoint) -> list[SearchHit]:
        if len(self.calls) >= 2:
            raise RuntimeError("blocked")
        return await super().search(query, center)


async def test_discover_saves_progress_when_the_crawl_is_interrupted() -> None:
    repo = FakeRepo()
    params = DiscoverParams(CENTER, radius_m=600, spacing_m=300, keywords=("카페",))
    uc = DiscoverCafes(BlockingSearch([_hit("a")]), repo, FixedClock())
    with pytest.raises(RuntimeError):
        await uc.run(params)
    assert set(repo.hits) == {"a"}


class FlakySearch(FakeSearch):
    """The first call fails transiently; later calls work."""

    async def search(self, query: str, center: GeoPoint) -> list[SearchHit]:
        if not self.calls:
            self.calls.append((query, center))
            raise PlaceFetchError("transient")
        return await super().search(query, center)


async def test_discover_skips_a_failed_request_and_continues() -> None:
    repo = FakeRepo()
    params = DiscoverParams(CENTER, radius_m=600, spacing_m=300, keywords=("카페",))
    report = await DiscoverCafes(FlakySearch([_hit("a")]), repo, FixedClock()).run(params)
    assert report.failed_requests == 1 and set(repo.hits) == {"a"}


class ExplodingRepo(FakeRepo):
    def __init__(self, pending: list[str], bad: set[str]) -> None:
        super().__init__(pending)
        self.bad = bad

    async def save_detail(self, detail: PlaceDetail, fetched_at: datetime) -> UpsertResult:
        if detail.place_id in self.bad:
            raise ValueError("integer out of range")
        return await super().save_detail(detail, fetched_at)


async def test_one_unsavable_place_does_not_stop_the_crawl() -> None:
    repo = ExplodingRepo(["a", "bad", "b"], {"bad"})
    report = await FetchCafeDetails(FakeDetails(set(), set()), repo, FixedClock()).run(10)
    assert report.attempted == 3 and report.failed == 1 and repo.saved == ["a", "b"]


async def test_a_systematic_storage_failure_stops_the_crawl() -> None:
    ids = [f"p{i}" for i in range(8)]
    repo = ExplodingRepo(ids, set(ids))
    with pytest.raises(ValueError, match="out of range"):
        await FetchCafeDetails(FakeDetails(set(), set()), repo, FixedClock()).run(10)
