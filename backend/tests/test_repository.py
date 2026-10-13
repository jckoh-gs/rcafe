"""Integration tests against a real Postgres (the aicafe_test database)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapters.outbound.persistence.repository import PostgresCafeRepository
from app.adapters.outbound.persistence.tables import cafe, cafe_menu, cafe_review
from app.domain.models import (
    BusinessInfo,
    BusinessStatus,
    GeoPoint,
    MenuItem,
    PlaceDetail,
    Review,
    SearchHit,
)

pytestmark = pytest.mark.integration
T0 = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def _hit(place_id: str = "100", **kw: object) -> SearchHit:
    base = SearchHit(
        place_id, "카페A", GeoPoint(37.5, 127.03), "카페,디저트", "도로명", "지번", 10, 1.5, False
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def _detail(place_id: str = "100", **kw: object) -> PlaceDetail:
    base = PlaceDetail(
        place_id=place_id,
        name="카페A",
        phone="02-000-0000",
        rating=4.7,
        review_count=11,
        micro_review="한 줄",
        business=BusinessInfo(BusinessStatus.OPEN, "영업 중"),
        menus=(
            MenuItem("m1", "아메리카노", 4500, None, None),
            MenuItem("m2", "라떼", 5000, None, None),
        ),
        menu_mentions=(("커피", 3),),
        reviews=(
            Review(
                "r1",
                5,
                "시원하고 깔끔한 아이스 아메리카노였어요 " * 3,
                "9.11.금",
                "아메리카노",
                None,
            ),
            Review("r2", 5, "짧아요", None, None, None, is_noise=True),
        ),
        photo_urls=("https://example.com/a.jpg",),
        cover_photo_url="https://example.com/a.jpg",
    )
    return replace(base, **kw)  # type: ignore[arg-type]


async def _count(engine: AsyncEngine, table: object) -> int:
    async with engine.connect() as conn:
        return (await conn.execute(select(func.count()).select_from(table))).scalar_one()  # type: ignore[arg-type]


async def test_upsert_hits_is_idempotent_and_detects_changes(engine: AsyncEngine) -> None:
    repo = PostgresCafeRepository(engine)
    first = await repo.upsert_hits([_hit("1"), _hit("2"), _hit("1")], T0)  # duplicate in batch
    assert (first.inserted, first.updated, first.unchanged) == (2, 0, 0)

    again = await repo.upsert_hits([_hit("1"), _hit("2")], T0 + timedelta(hours=1))
    assert (again.inserted, again.updated, again.unchanged) == (0, 0, 2)
    assert await _count(engine, cafe) == 2

    changed = await repo.upsert_hits(
        [_hit("1", name="새 이름"), _hit("3")], T0 + timedelta(hours=2)
    )
    assert (changed.inserted, changed.updated) == (1, 1)
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                select(cafe.c.name, cafe.c.last_seen_at).where(cafe.c.place_id == "1")
            )
        ).one()
        unchanged_row = (
            await conn.execute(select(cafe.c.last_seen_at).where(cafe.c.place_id == "2"))
        ).one()
    assert row.name == "새 이름"
    assert unchanged_row.last_seen_at == T0 + timedelta(
        hours=1
    )  # unchanged rows still record "seen"
    assert await _count(engine, cafe) == 3


async def test_save_detail_replaces_children_and_skips_unchanged(engine: AsyncEngine) -> None:
    repo = PostgresCafeRepository(engine)
    await repo.upsert_hits([_hit("100")], T0)

    saved = await repo.save_detail(_detail(), T0)
    assert saved.updated == 1
    assert await _count(engine, cafe_menu) == 2 and await _count(engine, cafe_review) == 2

    again = await repo.save_detail(_detail(), T0 + timedelta(days=1))
    assert again.unchanged == 1
    async with engine.connect() as conn:
        fetched = (await conn.execute(select(cafe.c.detail_fetched_at))).scalar_one()
    assert fetched == T0 + timedelta(days=1)

    smaller = _detail(menus=(MenuItem("m1", "아메리카노", 4800, None, None),), reviews=())
    updated = await repo.save_detail(smaller, T0 + timedelta(days=2))
    assert updated.updated == 1
    assert await _count(engine, cafe_menu) == 1 and await _count(engine, cafe_review) == 0


async def test_review_text_policy_snippet_and_noise(engine: AsyncEngine) -> None:
    repo = PostgresCafeRepository(engine)
    await repo.upsert_hits([_hit("100")], T0)
    await repo.save_detail(_detail(), T0)
    async with engine.connect() as conn:
        rows = {r.review_key: r for r in await conn.execute(select(cafe_review))}
    assert len(rows["r1"].text_snippet) <= 200 and rows["r1"].raw_body
    assert rows["r2"].is_noise and rows["r2"].raw_body is None  # noise text is never kept


async def test_place_ids_needing_detail_and_inactive(engine: AsyncEngine) -> None:
    repo = PostgresCafeRepository(engine)
    await repo.upsert_hits([_hit("1", review_count=5), _hit("2", review_count=50), _hit("3")], T0)
    await repo.save_detail(_detail("3"), T0)
    ids = await repo.place_ids_needing_detail(T0 - timedelta(days=7), 10)
    assert ids == ["2", "1"]  # never-fetched first, most reviewed first; "3" is fresh
    stale = await repo.place_ids_needing_detail(T0 + timedelta(days=1), 10)
    assert set(stale) == {"1", "2", "3"}

    await repo.mark_inactive("2", T0)
    assert await repo.place_ids_needing_detail(T0 - timedelta(days=7), 10) == ["1"]
    await repo.upsert_hits([_hit("2", review_count=50)], T0 + timedelta(hours=1))  # seen again
    assert "2" in await repo.place_ids_needing_detail(T0 - timedelta(days=7), 10)
