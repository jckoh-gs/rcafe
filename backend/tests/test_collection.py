"""Collection requests: taking them, and running them in the quiet-hours job."""

from datetime import UTC, datetime, timedelta, timezone

from app.application.collection import (
    MAX_NEW_PER_DAY,
    MAX_QUEUE,
    RequestCollection,
    RequestStatus,
    RunCollectionRequests,
    next_run_after,
)
from app.application.ingest import DiscoverCafes, FetchCafeDetails
from app.domain.models import CollectionStatus, GeoPoint, SearchHit
from app.domain.services import cell_for
from tests.fakes import FakeCollectionRepo
from tests.test_ingest import FakeDetails, FakeRepo, FakeSearch, _hit

KST = timezone(timedelta(hours=9))
NOON = datetime(2026, 10, 10, 12, 0, tzinfo=KST)
BUCHEON = GeoPoint(37.4878, 126.7886)  # the place in the user's screenshot (outside the data)


class Clock:
    def __init__(self, now: datetime = NOON, tick: timedelta = timedelta(0)) -> None:
        self._now, self._tick = now, tick

    def now(self) -> datetime:
        current = self._now
        self._now += self._tick  # every look at the clock moves time forward
        return current


def test_cells_merge_nearby_points_and_split_distant_ones() -> None:
    key, center = cell_for(BUCHEON)
    assert cell_for(GeoPoint(BUCHEON.lat + 0.001, BUCHEON.lng - 0.001))[0] == key
    assert cell_for(GeoPoint(BUCHEON.lat + 0.02, BUCHEON.lng))[0] != key
    assert abs(center.lat - BUCHEON.lat) < 0.006 and abs(center.lng - BUCHEON.lng) < 0.006


def test_next_run_is_the_coming_0330_korean_time() -> None:
    assert next_run_after(datetime(2026, 10, 10, 1, 0, tzinfo=KST)) == datetime(
        2026, 10, 10, 3, 30, tzinfo=KST
    )
    assert next_run_after(datetime(2026, 10, 10, 12, 0, tzinfo=KST)) == datetime(
        2026, 10, 11, 3, 30, tzinfo=KST
    )
    utc = datetime(2026, 10, 9, 18, 0, tzinfo=UTC)  # 03:00 KST the next morning
    assert next_run_after(utc) == datetime(2026, 10, 10, 3, 30, tzinfo=KST)


async def test_a_request_is_queued_once_and_counted_afterwards() -> None:
    service = RequestCollection(FakeCollectionRepo(), Clock())
    first = await service.submit(BUCHEON)
    assert first.status is RequestStatus.QUEUED and first.request_count == 1
    assert first.next_run == datetime(2026, 10, 11, 3, 30, tzinfo=KST)
    again = await service.submit(GeoPoint(BUCHEON.lat + 0.001, BUCHEON.lng))  # same cell
    assert again.status is RequestStatus.ALREADY_QUEUED and again.request_count == 2
    other = await service.submit(GeoPoint(35.18, 129.07))
    assert other.status is RequestStatus.QUEUED and other.request_count == 1


async def test_areas_that_already_have_data_are_not_queued() -> None:
    repo = FakeCollectionRepo(cafes_near=25)
    outcome = await RequestCollection(repo, Clock()).submit(GeoPoint(37.5006, 127.0364))
    assert outcome.status is RequestStatus.COVERED and repo.rows == {}


async def test_guards_against_floods() -> None:
    repo = FakeCollectionRepo()
    service = RequestCollection(repo, Clock())
    for i in range(MAX_NEW_PER_DAY):
        assert (
            await service.submit(GeoPoint(34.0 + i * 0.05, 126.0))
        ).status is RequestStatus.QUEUED
    assert (await service.submit(GeoPoint(38.9, 128.0))).status is RequestStatus.LIMIT
    # an area that is already queued can still be asked for again
    assert (await service.submit(GeoPoint(34.0, 126.0))).status is RequestStatus.ALREADY_QUEUED

    full = FakeCollectionRepo()
    for i in range(MAX_QUEUE):
        await full.submit(GeoPoint(33.5 + i * 0.05, 125.0), NOON - timedelta(days=3), 1500)
    assert (
        await RequestCollection(full, Clock()).submit(GeoPoint(37.0, 127.5))
    ).status is RequestStatus.BUSY


async def test_status_reports_progress_and_result() -> None:
    repo = FakeCollectionRepo()
    service = RequestCollection(repo, Clock())
    assert await service.status(BUCHEON) is None
    await service.submit(BUCHEON)
    queued = await service.status(BUCHEON)
    assert queued is not None and queued.status is RequestStatus.ALREADY_QUEUED
    request = await repo.find(BUCHEON)
    assert request is not None
    await repo.mark_running(request.id, NOON)
    running = await service.status(BUCHEON)
    assert running is not None and running.status is RequestStatus.COLLECTING
    await repo.mark_done(request.id, NOON, 37)
    done = await service.status(BUCHEON)
    assert done is not None and done.status is RequestStatus.DONE and done.cafes_found == 37


# --- the nightly runner ------------------------------------------------------------------------


class FakeTasteUpdater:
    def __init__(self) -> None:
        self.calls: list[bool] = []

    async def run(self, only_new: bool = False) -> object:
        self.calls.append(only_new)
        return None


class FakePurger:
    def __init__(self) -> None:
        self.purged = 0

    async def purge_raw_review_text(self) -> int:
        self.purged += 1
        return 0


class Blocked(RuntimeError):
    pass


class BlockingSearch(FakeSearch):
    async def search(self, query: str, center: GeoPoint) -> list[SearchHit]:
        raise Blocked("429")


class ExplodingSearch(FakeSearch):
    async def search(self, query: str, center: GeoPoint) -> list[SearchHit]:
        raise ValueError("boom")


def _runner(
    requests: FakeCollectionRepo,
    search: FakeSearch,
    cafe_repo: FakeRepo,
    clock: Clock,
    tastes: FakeTasteUpdater,
    purger: FakePurger,
) -> RunCollectionRequests:
    return RunCollectionRequests(
        requests,
        DiscoverCafes(search, cafe_repo, clock),
        FetchCafeDetails(FakeDetails(set(), set()), cafe_repo, clock),
        tastes,
        purger,
        clock,
        blocked_errors=(Blocked,),
    )


async def _queue(repo: FakeCollectionRepo, *points: tuple[GeoPoint, int]) -> None:
    for point, count in points:
        for _ in range(count):
            await repo.submit(point, NOON - timedelta(days=1), 1500)


def _search_near(point: GeoPoint, *ids: str) -> FakeSearch:
    return FakeSearch([_hit(i, point.lat + 0.0005, point.lng + 0.0005) for i in ids])


async def test_the_most_requested_area_is_collected_first_and_finished_requests_are_marked() -> (
    None
):
    requests = FakeCollectionRepo()
    rare, popular = GeoPoint(35.18, 129.07), GeoPoint(37.49, 126.79)
    await _queue(requests, (rare, 1), (popular, 3))
    cafes, tastes, purger = FakeRepo(), FakeTasteUpdater(), FakePurger()
    cafes.pending = ["p1"]  # a place of the area still lacks details
    report = await _runner(
        requests, _search_near(popular, "p1", "p2"), cafes, Clock(), tastes, purger
    ).run(timedelta(hours=1), max_requests=1)
    assert (report.started, report.done, report.new_cafes) == (1, 1, 2)
    done = await requests.find(popular)
    assert done is not None and done.status is CollectionStatus.DONE and done.cafes_found == 2
    waiting = await requests.find(rare)
    assert waiting is not None and waiting.status is CollectionStatus.PENDING  # not touched yet
    assert cafes.saved == ["p1"]
    assert tastes.calls == [True] and purger.purged == 1  # new cafes only, review text dropped


async def test_the_time_budget_stops_the_run_and_keeps_the_request_queued() -> None:
    requests = FakeCollectionRepo()
    point = GeoPoint(37.49, 126.79)
    await _queue(requests, (point, 1))
    cafes, tastes, purger = FakeRepo(), FakeTasteUpdater(), FakePurger()
    slow = Clock(tick=timedelta(minutes=10))  # each look at the clock costs ten minutes
    report = await _runner(requests, _search_near(point, "p1"), cafes, slow, tastes, purger).run(
        timedelta(minutes=45), max_requests=5
    )
    assert report.interrupted == 1 and report.done == 0
    request = await requests.find(point)
    assert request is not None and request.status is CollectionStatus.PENDING
    assert request.note is not None and "continues next run" in request.note
    assert tastes.calls == [] and purger.purged == 0  # nothing is finalized half-way


async def test_a_block_by_the_source_stops_everything_and_requeues() -> None:
    requests = FakeCollectionRepo()
    first, second = GeoPoint(37.49, 126.79), GeoPoint(35.18, 129.07)
    await _queue(requests, (first, 2), (second, 1))
    report = await _runner(
        requests, BlockingSearch([]), FakeRepo(), Clock(), FakeTasteUpdater(), FakePurger()
    ).run(timedelta(hours=1))
    assert report.stopped_by_block and report.interrupted == 1 and report.started == 1
    blocked = await requests.find(first)
    assert (
        blocked is not None
        and blocked.status is CollectionStatus.PENDING
        and "blocked" in str(blocked.note)
    )
    untouched = await requests.find(second)
    assert (
        untouched is not None
        and untouched.status is CollectionStatus.PENDING
        and untouched.note is None
    )


async def test_one_failing_area_does_not_stop_the_others() -> None:
    requests = FakeCollectionRepo()
    bad, good = GeoPoint(37.49, 126.79), GeoPoint(35.18, 129.07)
    await _queue(requests, (bad, 2), (good, 1))

    class Mixed(FakeSearch):
        async def search(self, query: str, center: GeoPoint) -> list[SearchHit]:
            if abs(center.lat - bad.lat) < 0.05:
                raise ValueError("boom")
            return [_hit("g1", good.lat, good.lng)]

    report = await _runner(
        requests, Mixed([]), FakeRepo(), Clock(), FakeTasteUpdater(), FakePurger()
    ).run(timedelta(hours=1))
    assert (report.failed, report.done) == (1, 1)
    failed = await requests.find(bad)
    assert (
        failed is not None
        and failed.status is CollectionStatus.FAILED
        and "boom" in str(failed.note)
    )
    # asking again re-opens a failed area
    again = await requests.submit(bad, NOON, 1500)
    assert again[0].status is CollectionStatus.PENDING


async def test_run_now_collects_only_the_named_request_even_if_it_was_finished() -> None:
    requests = FakeCollectionRepo()
    popular, other = GeoPoint(37.49, 126.79), GeoPoint(35.18, 129.07)
    await _queue(requests, (popular, 3), (other, 1))
    other_row = await requests.find(other)
    assert other_row is not None
    await requests.mark_done(other_row.id, NOON, 5)  # finished before; the administrator reruns it
    report = await _runner(
        requests, _search_near(other, "o1"), FakeRepo(), Clock(), FakeTasteUpdater(), FakePurger()
    ).run(timedelta(hours=1), request_id=other_row.id)
    assert (report.started, report.done) == (1, 1)
    rerun = await requests.find(other)
    assert rerun is not None and rerun.status is CollectionStatus.DONE and rerun.cafes_found == 1
    waiting = await requests.find(popular)
    assert waiting is not None and waiting.status is CollectionStatus.PENDING  # left alone


async def test_run_now_does_nothing_for_a_request_that_is_running_or_gone() -> None:
    requests = FakeCollectionRepo()
    point = GeoPoint(37.49, 126.79)
    await _queue(requests, (point, 1))
    row = await requests.find(point)
    assert row is not None
    await requests.mark_running(row.id, NOON)
    runner = _runner(
        requests, _search_near(point, "p1"), FakeRepo(), Clock(), FakeTasteUpdater(), FakePurger()
    )
    busy = await runner.run(timedelta(hours=1), request_id=row.id)
    missing = await runner.run(timedelta(hours=1), request_id=999)
    assert busy.started == 0 and missing.started == 0
    assert "does not exist or is already running" in busy.notes[0]
    still = await requests.find(point)
    assert still is not None and still.status is CollectionStatus.RUNNING


async def test_requests_orphaned_by_a_dead_collector_are_queued_again() -> None:
    requests = FakeCollectionRepo()
    old, fresh = GeoPoint(37.49, 126.79), GeoPoint(35.18, 129.07)
    await _queue(requests, (old, 1), (fresh, 1))
    old_row, fresh_row = await requests.find(old), await requests.find(fresh)
    assert old_row is not None and fresh_row is not None
    await requests.mark_running(old_row.id, NOON - timedelta(hours=5))  # its pod was killed
    await requests.mark_running(fresh_row.id, NOON - timedelta(hours=1))  # still working
    report = await _runner(
        requests, FakeSearch([]), FakeRepo(), Clock(), FakeTasteUpdater(), FakePurger()
    ).run(timedelta(hours=1), max_requests=0)
    assert "1 orphaned" in report.notes[0]
    back = await requests.find(old)
    assert back is not None and back.status is CollectionStatus.PENDING
    assert back.note is not None and "stopped unexpectedly" in back.note
    working = await requests.find(fresh)
    assert working is not None and working.status is CollectionStatus.RUNNING
