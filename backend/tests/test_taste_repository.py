"""Integration tests: pgvector similarity search and taste persistence (needs Postgres)."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapters.outbound.persistence.repository import PostgresCafeRepository
from app.adapters.outbound.persistence.tables import cafe_review
from app.adapters.outbound.persistence.taste_repository import (
    PostgresArchetypeRepository,
    PostgresTasteRepository,
)
from app.application.errors import NotReadyError
from app.application.taste import ComputeCafeTastes, FindWeatherTaste, SeedArchetypes
from app.domain.models import (
    BusinessInfo,
    BusinessStatus,
    GeoPoint,
    MenuItem,
    PlaceDetail,
    Review,
    SearchHit,
)
from app.domain.taste import AXES
from app.domain.weather import WeatherObservation, build_scenarios

pytestmark = pytest.mark.integration
T0 = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
KST = timezone(timedelta(hours=9))
IDX = {a: i for i, a in enumerate(AXES)}


class FixedClock:
    def now(self) -> datetime:
        return T0


async def _cafe(
    engine: AsyncEngine, place_id: str, name: str, menus: list[str], reviews: list[str]
) -> None:
    repo = PostgresCafeRepository(engine)
    await repo.upsert_hits(
        [
            SearchHit(
                place_id, name, GeoPoint(37.5, 127.03), "카페,디저트", None, None, 10, 1.0, False
            )
        ],
        T0,
    )
    detail = PlaceDetail(
        place_id=place_id,
        name=name,
        phone=None,
        rating=4.5,
        review_count=10,
        micro_review=None,
        business=BusinessInfo(BusinessStatus.OPEN, "영업 중"),
        menus=tuple(MenuItem(f"m{i}", m, 5000, None, None) for i, m in enumerate(menus)),
        menu_mentions=(),
        reviews=tuple(Review(f"r{i}", 5, text, None, None, None) for i, text in enumerate(reviews)),
        photo_urls=(),
    )
    await repo.save_detail(detail, T0)


async def test_seed_is_idempotent_and_nearest_neighbor_matches_the_weather(
    engine: AsyncEngine,
) -> None:
    archetypes = PostgresArchetypeRepository(engine)
    assert await SeedArchetypes(archetypes).run() == len(build_scenarios())
    assert await SeedArchetypes(archetypes).run() == len(build_scenarios())  # no duplicates

    hot = WeatherObservation("108", datetime(2026, 8, 1, 14, tzinfo=KST), 33, 75, 1, 0, 2)
    cold_rain = WeatherObservation("108", datetime(2026, 12, 1, 20, tzinfo=KST), 2, 85, 2, 1.0, 9)
    hot_taste = await FindWeatherTaste(archetypes).run(hot)
    cold_taste = await FindWeatherTaste(archetypes).run(cold_rain)

    assert "폭염" in hot_taste.nearest.name_ko or "무더운" in hot_taste.nearest.name_ko
    assert "비 오는" in cold_taste.nearest.name_ko
    assert hot_taste.taste[IDX["iced"]] > hot_taste.taste[IDX["hot"]]
    assert cold_taste.taste[IDX["hot"]] > cold_taste.taste[IDX["iced"]]
    assert len(hot_taste.neighbors) == 5
    distances = [d for _, d in hot_taste.neighbors]
    assert distances == sorted(distances)


async def test_find_weather_taste_requires_seeded_archetypes(engine: AsyncEngine) -> None:
    obs = WeatherObservation("108", datetime(2026, 8, 1, 14, tzinfo=KST), 30)
    with pytest.raises(NotReadyError):
        await FindWeatherTaste(PostgresArchetypeRepository(engine)).run(obs)


async def test_compute_tastes_tags_reviews_and_purges_raw_text(engine: AsyncEngine) -> None:
    await _cafe(
        engine,
        "1",
        "과일카페",
        ["자몽에이드", "레몬티"],
        ["상큼하고 시원한 에이드가 최고예요 정말"],
    )
    await _cafe(
        engine, "2", "로스터리", ["에스프레소", "아메리카노"], ["진한 로스팅 원두 향이 좋아요 최고"]
    )
    tastes = PostgresTasteRepository(engine)

    report = await ComputeCafeTastes(tastes, FixedClock()).run()
    assert report.cafes == 2 and report.reviews_tagged == 2

    profiles = {p.place_id: p for p in await tastes.list_profiles()}
    assert profiles["1"].taste[IDX["sour_fresh"]] > profiles["2"].taste[IDX["sour_fresh"]]
    assert profiles["2"].taste[IDX["bitter_roast"]] > profiles["1"].taste[IDX["bitter_roast"]]
    assert profiles["1"].menus[0].name == "자몽에이드"  # menu order is kept
    assert await tastes.load_axis_stats() is not None

    async with engine.connect() as conn:
        tags = (
            await conn.execute(
                select(cafe_review.c.taste_tags).where(cafe_review.c.place_id == "1")
            )
        ).scalar_one()
    assert tags and tags.get("sour_fresh", 0) >= 1

    again = await ComputeCafeTastes(tastes, FixedClock()).run()  # idempotent
    assert again.cafes == 2 and len(await tastes.list_profiles()) == 2

    assert await tastes.purge_raw_review_text() == 2
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                select(cafe_review.c.raw_body, cafe_review.c.text_snippet, cafe_review.c.taste_tags)
            )
        ).all()
    assert all(r.raw_body is None and r.text_snippet and r.taste_tags for r in rows)
