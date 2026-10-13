"""Integration tests: collection request persistence, area filters, incremental taste."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapters.outbound.persistence.collection_repository import (
    PostgresCollectionRequestRepository,
)
from app.adapters.outbound.persistence.repository import PostgresCafeRepository
from app.adapters.outbound.persistence.taste_repository import PostgresTasteRepository
from app.application.taste import ComputeCafeTastes
from app.domain.models import (
    BusinessInfo,
    BusinessStatus,
    CollectionStatus,
    GeoPoint,
    MenuItem,
    PlaceDetail,
    Review,
    SearchHit,
)

pytestmark = pytest.mark.integration
T0 = datetime(2026, 10, 10, 3, 0, tzinfo=UTC)
BUCHEON = GeoPoint(37.4878, 126.7886)
YEOKSAM = GeoPoint(37.5006, 127.0364)


class FixedClock:
    def now(self) -> datetime:
        return T0


async def test_requests_are_merged_per_cell_and_counted(engine: AsyncEngine) -> None:
    repo = PostgresCollectionRequestRepository(engine)
    first, created = await repo.submit(BUCHEON, T0, 1500)
    assert created and first.request_count == 1 and first.status is CollectionStatus.PENDING
    again, created_again = await repo.submit(
        GeoPoint(BUCHEON.lat + 0.001, BUCHEON.lng), T0 + timedelta(hours=1), 1500
    )
    assert not created_again and again.id == first.id and again.request_count == 2
    assert again.last_requested_at == T0 + timedelta(hours=1)
    other, created_other = await repo.submit(YEOKSAM, T0, 1500)
    assert created_other and other.id != first.id
    assert await repo.count_pending() == 2
    assert await repo.count_created_since(T0 - timedelta(days=1)) == 2
    assert await repo.count_created_since(T0 + timedelta(days=1)) == 0
    found = await repo.find(BUCHEON)
    assert (
        found is not None and found.request_count == 2 and found.center.lat == pytest.approx(37.49)
    )


async def test_status_transitions_queue_order_and_reopening(engine: AsyncEngine) -> None:
    repo = PostgresCollectionRequestRepository(engine)
    a, _ = await repo.submit(BUCHEON, T0, 1500)
    b, _ = await repo.submit(YEOKSAM, T0 + timedelta(minutes=1), 1500)
    await repo.submit(YEOKSAM, T0 + timedelta(minutes=2), 1500)  # b is now asked for twice
    queue = await repo.next_pending(10)
    assert [r.id for r in queue] == [b.id, a.id]  # most requested first

    await repo.mark_running(a.id, T0)
    assert [r.id for r in await repo.next_pending(10)] == [b.id]
    assert await repo.count_pending() == 2  # running still counts as waiting
    await repo.mark_retry(a.id, T0, "time budget used up")
    retried = await repo.find(BUCHEON)
    assert retried is not None and retried.status is CollectionStatus.PENDING and retried.note

    await repo.mark_done(a.id, T0 + timedelta(hours=1), 33)
    done = await repo.find(BUCHEON)
    assert done is not None and done.status is CollectionStatus.DONE and done.cafes_found == 33
    again, _ = await repo.submit(BUCHEON, T0 + timedelta(days=2), 1500)  # fresh: stays done
    assert again.status is CollectionStatus.DONE and again.request_count == 2
    stale, _ = await repo.submit(BUCHEON, T0 + timedelta(days=45), 1500)  # old: collect again
    assert stale.status is CollectionStatus.PENDING

    await repo.mark_failed(b.id, T0, "boom")
    reopened, _ = await repo.submit(YEOKSAM, T0 + timedelta(hours=1), 1500)
    assert reopened.status is CollectionStatus.PENDING


async def _cafe(engine: AsyncEngine, place_id: str, lat: float, lng: float, detailed: bool) -> None:
    repo = PostgresCafeRepository(engine)
    await repo.upsert_hits(
        [
            SearchHit(
                place_id,
                f"카페{place_id}",
                GeoPoint(lat, lng),
                "카페,디저트",
                None,
                None,
                5,
                1.0,
                False,
            )
        ],
        T0,
    )
    if detailed:
        await repo.save_detail(
            PlaceDetail(
                place_id=place_id,
                name=f"카페{place_id}",
                phone=None,
                rating=4.5,
                review_count=3,
                micro_review=None,
                business=BusinessInfo(BusinessStatus.OPEN, None),
                menus=(MenuItem("m", "자몽에이드", 6000, None, None),),
                menu_mentions=(),
                reviews=(
                    Review("r", 5, "상큼하고 시원한 에이드가 정말 맛있어요", None, None, None),
                ),
                photo_urls=(),
            ),
            T0,
        )


async def test_cafes_near_and_the_area_filter_for_details(engine: AsyncEngine) -> None:
    await _cafe(engine, "near1", BUCHEON.lat, BUCHEON.lng, detailed=False)
    await _cafe(engine, "near2", BUCHEON.lat + 0.004, BUCHEON.lng, detailed=False)
    await _cafe(engine, "far", YEOKSAM.lat, YEOKSAM.lng, detailed=False)
    requests = PostgresCollectionRequestRepository(engine)
    assert await requests.count_cafes_near(BUCHEON, 1000) == 2
    assert await requests.count_cafes_near(YEOKSAM, 1000) == 1
    assert await requests.count_cafes_near(GeoPoint(35.0, 129.0), 1000) == 0

    cafes = PostgresCafeRepository(engine)
    everywhere = await cafes.place_ids_needing_detail(T0, 10)
    nearby = await cafes.place_ids_needing_detail(T0, 10, (BUCHEON, 1500.0))
    assert set(everywhere) == {"near1", "near2", "far"}
    assert set(nearby) == {"near1", "near2"}


async def test_incremental_taste_leaves_existing_cafes_and_statistics_untouched(
    engine: AsyncEngine,
) -> None:
    await _cafe(engine, "old", YEOKSAM.lat, YEOKSAM.lng, detailed=True)
    tastes = PostgresTasteRepository(engine)
    await ComputeCafeTastes(tastes, FixedClock()).run()
    before = {p.place_id: p.taste for p in await tastes.list_profiles()}
    stats_before = await tastes.load_axis_stats()
    assert set(before) == {"old"} and stats_before is not None

    await _cafe(engine, "new", BUCHEON.lat, BUCHEON.lng, detailed=True)
    assert [e.place_id for e in await tastes.list_evidence(only_missing=True)] == ["new"]
    report = await ComputeCafeTastes(tastes, FixedClock()).run(only_new=True)
    assert report.cafes == 1

    after = {p.place_id: p.taste for p in await tastes.list_profiles()}
    assert set(after) == {"old", "new"} and after["old"] == before["old"]
    assert await tastes.load_axis_stats() == stats_before  # the dataset scale did not move
    assert await tastes.list_evidence(only_missing=True) == []


async def test_the_administrator_can_list_delete_requeue_and_recover_requests(
    engine: AsyncEngine,
) -> None:
    repo = PostgresCollectionRequestRepository(engine)
    busan, jeju, daegu, gwangju = (
        GeoPoint(35.18, 129.07),
        GeoPoint(33.50, 126.53),
        GeoPoint(35.87, 128.60),
        GeoPoint(35.16, 126.85),
    )
    popular, _ = await repo.submit(BUCHEON, T0, 1500)
    for _ in range(2):
        await repo.submit(BUCHEON, T0, 1500)  # three requests in all
    rare, _ = await repo.submit(busan, T0, 1500)
    failed, _ = await repo.submit(jeju, T0, 1500)
    finished, _ = await repo.submit(daegu, T0, 1500)
    running, _ = await repo.submit(gwangju, T0, 1500)
    await repo.mark_failed(failed.id, T0, "boom")
    await repo.mark_done(finished.id, T0, 12)
    await repo.mark_running(running.id, T0 - timedelta(hours=5))

    # running first, then waiting (most requested first), failed, finished
    assert [r.id for r in await repo.list_all(10)] == [
        running.id,
        popular.id,
        rare.id,
        failed.id,
        finished.id,
    ]
    assert len(await repo.list_all(2)) == 2
    counts = await repo.count_by_status()
    assert counts == {
        CollectionStatus.RUNNING: 1,
        CollectionStatus.PENDING: 2,
        CollectionStatus.FAILED: 1,
        CollectionStatus.DONE: 1,
    }
    got = await repo.get(popular.id)
    assert got is not None and got.request_count == 3
    assert await repo.get(99_999) is None

    # a running request is protected; the others can go or be queued again
    assert not await repo.delete(running.id)
    assert not await repo.requeue(running.id, "x")
    assert await repo.requeue(failed.id, "다시 대기열")
    again = await repo.get(failed.id)
    assert again is not None and again.status is CollectionStatus.PENDING
    assert again.note == "다시 대기열"
    assert await repo.delete(rare.id)
    assert not await repo.delete(rare.id)
    assert await repo.find(busan) is None  # a new request for it starts from scratch

    # a collector that died leaves `running` behind; only old ones are recovered
    assert await repo.reset_stale_running(T0 - timedelta(hours=6), "recovered") == 0
    assert await repo.reset_stale_running(T0 - timedelta(hours=4), "recovered") == 1
    recovered = await repo.get(running.id)
    assert recovered is not None and recovered.status is CollectionStatus.PENDING
    assert recovered.note == "recovered"
