"""Integration tests for the recommendation read models (needs Postgres)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapters.outbound.persistence.recommend_repository import (
    PostgresCandidateSource,
    PostgresWeatherSnapshotStore,
)
from app.adapters.outbound.persistence.repository import PostgresCafeRepository
from app.adapters.outbound.persistence.taste_repository import PostgresTasteRepository
from app.application.taste import ComputeCafeTastes
from app.domain.models import (
    BusinessInfo,
    BusinessStatus,
    DayHours,
    GeoPoint,
    MenuItem,
    PlaceDetail,
    Review,
    SearchHit,
)

pytestmark = pytest.mark.integration
T0 = datetime(2026, 10, 9, 5, 0, tzinfo=UTC)
CENTER = GeoPoint(37.5006, 127.0364)


class FixedClock:
    def now(self) -> datetime:
        return T0


async def _seed(engine: AsyncEngine, place_id: str, name: str, lat: float, lng: float) -> None:
    repo = PostgresCafeRepository(engine)
    await repo.upsert_hits(
        [
            SearchHit(
                place_id,
                name,
                GeoPoint(lat, lng),
                "카페,디저트",
                "서울 강남구",
                None,
                50,
                1.0,
                False,
            )
        ],
        T0,
    )
    await repo.save_detail(
        PlaceDetail(
            place_id=place_id,
            name=name,
            phone=None,
            rating=4.6,
            review_count=50,
            micro_review=None,
            business=BusinessInfo(
                BusinessStatus.OPEN, "영업 중", (DayHours("금(10/9)", "09:00", "22:00"),)
            ),
            menus=(MenuItem("m1", "자몽에이드", 6000, None, "https://img.test/m1.jpg"),),
            menu_mentions=(("에이드", 12),),
            reviews=(
                Review("r1", 5, "상큼하고 시원한 자몽에이드가 정말 맛있어요", None, None, None),
            ),
            photo_urls=("https://img.test/p1.jpg",),
            cover_photo_url="https://img.test/cover.jpg",
        ),
        T0,
    )


async def test_candidates_near_filters_by_area_and_maps_everything(engine: AsyncEngine) -> None:
    await _seed(engine, "1", "가까운카페", 37.5010, 127.0370)
    await _seed(engine, "2", "먼카페", 37.6000, 127.2000)
    await ComputeCafeTastes(PostgresTasteRepository(engine), FixedClock()).run()

    found = await PostgresCandidateSource(engine).candidates_near(CENTER, 1000)
    assert [c.place_id for c in found] == ["1"]
    c = found[0]
    assert c.name == "가까운카페" and c.rating == 4.6 and c.road_address == "서울 강남구"
    assert c.menus[0].name == "자몽에이드" and c.menus[0].price == 6000
    assert c.menus[0].image_url == "https://img.test/m1.jpg"
    assert c.business.status is BusinessStatus.OPEN and c.business.hours[0].end == "22:00"
    assert c.status_checked_at == T0 and c.cover_photo_url == "https://img.test/cover.jpg"
    assert c.review_axis_counts.get("sour_fresh") == 1 and c.review_total == 1
    assert len(c.taste) == 10 and 0 < c.confidence <= 1

    wide = await PostgresCandidateSource(engine).candidates_near(CENTER, 20_000)
    assert {x.place_id for x in wide} == {"1", "2"}


async def test_cafes_without_taste_or_inactive_are_not_candidates(engine: AsyncEngine) -> None:
    await _seed(engine, "1", "맛벡터없음", 37.5010, 127.0370)
    assert await PostgresCandidateSource(engine).candidates_near(CENTER, 1000) == []
    await ComputeCafeTastes(PostgresTasteRepository(engine), FixedClock()).run()
    assert len(await PostgresCandidateSource(engine).candidates_near(CENTER, 1000)) == 1
    await PostgresCafeRepository(engine).mark_inactive("1", T0)
    assert await PostgresCandidateSource(engine).candidates_near(CENTER, 1000) == []


async def test_weather_snapshot_store_roundtrip_and_overwrite(engine: AsyncEngine) -> None:
    store = PostgresWeatherSnapshotStore(engine)
    assert await store.load("202610091400") is None
    rows = {"108": {"TM": "202610091400", "TA": "20.1"}}
    await store.save("202610091400", rows, T0)
    assert await store.load("202610091400") == rows
    rows2 = {"108": {"TM": "202610091400", "TA": "20.5"}, "112": {"TA": "19.0"}}
    await store.save("202610091400", rows2, T0)
    assert await store.load("202610091400") == rows2
