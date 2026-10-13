"""PostgreSQL implementation of CafeRepository (keyed by Naver place_id, idempotent upserts)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime
from typing import Any

from sqlalchemy import delete, literal_column, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.sql.dml import ReturningInsert

from app.adapters.outbound.persistence.tables import cafe, cafe_menu, cafe_review
from app.domain.models import GeoPoint, PlaceDetail, SearchHit, UpsertResult
from app.domain.services import detail_content_hash, snippet

CHUNK = 500


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True)


class PostgresCafeRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def upsert_hits(self, hits: Sequence[SearchHit], seen_at: datetime) -> UpsertResult:
        unique = {h.place_id: h for h in hits}  # last one wins within a batch
        rows = [
            {
                "place_id": h.place_id,
                "name": h.name,
                "category": h.category,
                "lat": h.point.lat,
                "lng": h.point.lng,
                "road_address": h.road_address,
                "jibun_address": h.jibun_address,
                "review_count": h.review_count,
                "rank_score": h.rank_score,
                "has_booking": h.has_booking,
                "first_seen_at": seen_at,
                "last_seen_at": seen_at,
                "last_crawled_at": seen_at,
            }
            for h in unique.values()
        ]
        total = UpsertResult()
        async with self._sessions.begin() as session:
            for start in range(0, len(rows), CHUNK):
                chunk = rows[start : start + CHUNK]
                base = insert(cafe).values(chunk)
                changed = (
                    cafe.c.name.is_distinct_from(base.excluded.name)
                    | cafe.c.category.is_distinct_from(base.excluded.category)
                    | cafe.c.lat.is_distinct_from(base.excluded.lat)
                    | cafe.c.lng.is_distinct_from(base.excluded.lng)
                    | cafe.c.road_address.is_distinct_from(base.excluded.road_address)
                    | cafe.c.jibun_address.is_distinct_from(base.excluded.jibun_address)
                    | cafe.c.review_count.is_distinct_from(base.excluded.review_count)
                    | cafe.c.rank_score.is_distinct_from(base.excluded.rank_score)
                    | cafe.c.has_booking.is_distinct_from(base.excluded.has_booking)
                    | (cafe.c.is_active.is_(False))
                )
                stmt: ReturningInsert[Any] = base.on_conflict_do_update(
                    index_elements=[cafe.c.place_id],
                    set_={
                        "name": base.excluded.name,
                        "category": base.excluded.category,
                        "lat": base.excluded.lat,
                        "lng": base.excluded.lng,
                        "road_address": base.excluded.road_address,
                        "jibun_address": base.excluded.jibun_address,
                        "review_count": base.excluded.review_count,
                        "rank_score": base.excluded.rank_score,
                        "has_booking": base.excluded.has_booking,
                        "is_active": True,
                        "last_seen_at": base.excluded.last_seen_at,
                        "last_crawled_at": base.excluded.last_crawled_at,
                    },
                    where=changed,
                ).returning(literal_column("(xmax = 0)").label("inserted"))
                result = await session.execute(stmt)
                flags = [bool(r.inserted) for r in result]
                inserted = sum(flags)
                updated = len(flags) - inserted
                unchanged_ids = [r["place_id"] for r in chunk]
                # unchanged rows are skipped by the WHERE above; still record that we saw them
                await session.execute(
                    update(cafe)
                    .where(cafe.c.place_id.in_(unchanged_ids))
                    .values(last_seen_at=seen_at)
                )
                total += UpsertResult(inserted, updated, len(chunk) - len(flags))
        return total

    async def place_ids_needing_detail(
        self,
        older_than: datetime,
        limit: int,
        area: tuple[GeoPoint, float] | None = None,
    ) -> list[str]:
        conditions = [
            cafe.c.is_active.is_(True),
            or_(cafe.c.detail_fetched_at.is_(None), cafe.c.detail_fetched_at < older_than),
        ]
        if area is not None:
            center, radius_m = area
            dlat = radius_m / 111_320.0
            dlng = radius_m / (111_320.0 * max(0.1, math.cos(math.radians(center.lat))))
            conditions += [
                cafe.c.lat.between(center.lat - dlat, center.lat + dlat),
                cafe.c.lng.between(center.lng - dlng, center.lng + dlng),
            ]
        stmt = (
            select(cafe.c.place_id)
            .where(*conditions)
            .order_by(cafe.c.detail_fetched_at.asc().nullsfirst(), cafe.c.review_count.desc())
            .limit(limit)
        )
        async with self._sessions() as session:
            return [r.place_id for r in await session.execute(stmt)]

    async def save_detail(self, detail: PlaceDetail, fetched_at: datetime) -> UpsertResult:
        new_hash = detail_content_hash(detail)
        async with self._sessions.begin() as session:
            current = (
                await session.execute(
                    select(cafe.c.content_hash).where(cafe.c.place_id == detail.place_id)
                )
            ).first()
            if current is None:
                raise LookupError(f"unknown place_id {detail.place_id}")
            if current.content_hash == new_hash:
                await session.execute(
                    update(cafe)
                    .where(cafe.c.place_id == detail.place_id)
                    .values(detail_fetched_at=fetched_at, last_crawled_at=fetched_at)
                )
                return UpsertResult(unchanged=1)

            await session.execute(
                update(cafe)
                .where(cafe.c.place_id == detail.place_id)
                .values(
                    phone=detail.phone,
                    rating=detail.rating,
                    review_count=detail.review_count or 0,
                    micro_review=detail.micro_review,
                    business_status=detail.business.status.value,
                    business_status_text=detail.business.status_text,
                    business_hours=[asdict(h) for h in detail.business.hours],
                    cover_photo_url=detail.cover_photo_url,
                    photo_urls=list(detail.photo_urls),
                    conveniences=list(detail.conveniences),
                    menu_mentions=[[label, count] for label, count in detail.menu_mentions],
                    content_hash=new_hash,
                    detail_fetched_at=fetched_at,
                    last_crawled_at=fetched_at,
                )
            )
            await session.execute(delete(cafe_menu).where(cafe_menu.c.place_id == detail.place_id))
            await session.execute(
                delete(cafe_review).where(cafe_review.c.place_id == detail.place_id)
            )
            menu_rows: list[dict[str, Any]] = [
                {
                    "place_id": detail.place_id,
                    "menu_key": m.menu_key,
                    "position": position,
                    "name": m.name,
                    "price": m.price,
                    "description": m.description,
                    "image_url": m.image_url,
                    "mention_count": m.mention_count,
                }
                for position, m in enumerate({m.menu_key: m for m in detail.menus}.values())
            ]
            if menu_rows:
                await session.execute(insert(cafe_menu), menu_rows)
            review_rows: list[dict[str, Any]] = [
                {
                    "place_id": detail.place_id,
                    "review_key": r.review_key,
                    "rating": r.rating,
                    "text_snippet": snippet(r.text),
                    "raw_body": None if r.is_noise else r.text,
                    "visited_label": r.visited_label,
                    "ordered_item": r.ordered_item,
                    "photo_url": r.photo_url,
                    "voted_keywords": list(r.voted_keywords),
                    "is_noise": r.is_noise,
                }
                for r in {r.review_key: r for r in detail.reviews}.values()
            ]
            if review_rows:
                await session.execute(insert(cafe_review), review_rows)
            return UpsertResult(updated=1)

    async def mark_inactive(self, place_id: str, at: datetime) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(cafe)
                .where(cafe.c.place_id == place_id)
                .values(is_active=False, last_crawled_at=at)
            )


__all__ = ["PostgresCafeRepository", "make_engine"]
