"""PostgreSQL (pgvector) implementations of TasteRepository and ArchetypeRepository."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import and_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.adapters.outbound.persistence.tables import (
    cafe,
    cafe_menu,
    cafe_review,
    cafe_taste,
    taste_archetype,
    taste_axis_stats,
)
from app.domain.taste import (
    AXES,
    AxisStats,
    CafeEvidence,
    CafeProfile,
    MenuEvidence,
    ReviewEvidence,
    TasteVector,
)
from app.domain.weather import Archetype

MAX_MENUS_PER_CAFE = 40


class PostgresTasteRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def list_evidence(self, only_missing: bool = False) -> list[CafeEvidence]:
        async with self._sessions() as session:
            conditions = [cafe.c.is_active.is_(True), cafe.c.detail_fetched_at.is_not(None)]
            if only_missing:
                conditions.append(cafe.c.place_id.not_in(select(cafe_taste.c.place_id)))
            active = list(
                await session.execute(
                    select(cafe.c.place_id, cafe.c.menu_mentions).where(*conditions)
                )
            )
            ids = [r.place_id for r in active]
            mentions = {
                r.place_id: tuple((str(label), int(count)) for label, count in r.menu_mentions)
                for r in active
            }
            menus: dict[str, list[MenuEvidence]] = defaultdict(list)
            for r in await session.execute(
                select(cafe_menu.c.place_id, cafe_menu.c.name, cafe_menu.c.description).order_by(
                    cafe_menu.c.place_id, cafe_menu.c.position.asc().nullslast(), cafe_menu.c.name
                )
            ):
                if len(menus[r.place_id]) < MAX_MENUS_PER_CAFE:
                    menus[r.place_id].append(MenuEvidence(r.name, r.description))
            reviews: dict[str, list[ReviewEvidence]] = defaultdict(list)
            for rv in await session.execute(
                select(
                    cafe_review.c.place_id,
                    cafe_review.c.review_key,
                    cafe_review.c.rating,
                    cafe_review.c.text_snippet,
                    cafe_review.c.raw_body,
                    cafe_review.c.ordered_item,
                    cafe_review.c.voted_keywords,
                ).where(cafe_review.c.is_noise.is_(False))
            ):
                reviews[rv.place_id].append(
                    ReviewEvidence(
                        review_key=rv.review_key,
                        text=rv.raw_body or rv.text_snippet,
                        rating=rv.rating,
                        ordered_item=rv.ordered_item,
                        voted_keywords=tuple(rv.voted_keywords or ()),
                    )
                )
        return [
            CafeEvidence(
                place_id=pid,
                menus=tuple(menus.get(pid, ())),
                menu_mentions=mentions.get(pid, ()),
                reviews=tuple(reviews.get(pid, ())),
            )
            for pid in ids
        ]

    async def save_cafe_tastes(
        self, items: Sequence[tuple[str, TasteVector, float, float]], at: datetime
    ) -> None:
        if not items:
            return
        rows: list[dict[str, Any]] = [
            {
                "place_id": pid,
                "taste_vec": list(vector),
                "confidence": confidence,
                "evidence_weight": weight,
                "updated_at": at,
            }
            for pid, vector, confidence, weight in items
        ]
        async with self._sessions.begin() as session:
            stmt = insert(cafe_taste).values(rows)
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[cafe_taste.c.place_id],
                    set_={
                        "taste_vec": stmt.excluded.taste_vec,
                        "confidence": stmt.excluded.confidence,
                        "evidence_weight": stmt.excluded.evidence_weight,
                        "updated_at": stmt.excluded.updated_at,
                    },
                )
            )

    async def save_review_tags(self, tags: dict[str, dict[str, dict[str, int]]]) -> None:
        async with self._sessions.begin() as session:
            for place_id, per_review in tags.items():
                for review_key, hits in per_review.items():
                    await session.execute(
                        update(cafe_review)
                        .where(
                            and_(
                                cafe_review.c.place_id == place_id,
                                cafe_review.c.review_key == review_key,
                            )
                        )
                        .values(taste_tags=hits)
                    )

    async def save_axis_stats(self, stats: AxisStats, at: datetime) -> None:
        rows: list[dict[str, Any]] = [
            {"axis": axis, "mean": stats.mean[i], "scale": stats.scale[i], "updated_at": at}
            for i, axis in enumerate(AXES)
        ]
        async with self._sessions.begin() as session:
            stmt = insert(taste_axis_stats).values(rows)
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[taste_axis_stats.c.axis],
                    set_={
                        "mean": stmt.excluded.mean,
                        "scale": stmt.excluded.scale,
                        "updated_at": stmt.excluded.updated_at,
                    },
                )
            )

    async def load_axis_stats(self) -> AxisStats | None:
        async with self._sessions() as session:
            found = {r.axis: r for r in await session.execute(select(taste_axis_stats))}
        if len(found) != len(AXES):
            return None
        return AxisStats(
            mean=tuple(found[a].mean for a in AXES), scale=tuple(found[a].scale for a in AXES)
        )

    async def list_profiles(self) -> list[CafeProfile]:
        async with self._sessions() as session:
            rows = list(
                await session.execute(
                    select(
                        cafe.c.place_id,
                        cafe.c.name,
                        cafe_taste.c.taste_vec,
                        cafe_taste.c.confidence,
                    )
                    .join(cafe_taste, cafe_taste.c.place_id == cafe.c.place_id)
                    .where(cafe.c.is_active.is_(True))
                )
            )
            menus: dict[str, list[MenuEvidence]] = defaultdict(list)
            for m in await session.execute(
                select(cafe_menu.c.place_id, cafe_menu.c.name, cafe_menu.c.description).order_by(
                    cafe_menu.c.place_id, cafe_menu.c.position.asc().nullslast()
                )
            ):
                menus[m.place_id].append(MenuEvidence(m.name, m.description))
        return [
            CafeProfile(
                place_id=r.place_id,
                name=r.name,
                taste=tuple(float(x) for x in r.taste_vec),
                confidence=r.confidence,
                menus=tuple(menus.get(r.place_id, ())),
            )
            for r in rows
        ]

    async def purge_raw_review_text(self) -> int:
        async with self._sessions.begin() as session:
            result = await session.execute(
                update(cafe_review).where(cafe_review.c.raw_body.is_not(None)).values(raw_body=None)
            )
            return int(result.rowcount or 0)  # type: ignore[attr-defined]


class PostgresArchetypeRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def upsert_archetypes(self, archetypes: Sequence[Archetype]) -> int:
        rows: list[dict[str, Any]] = [
            {
                "key": a.key,
                "name_ko": a.name_ko,
                "feels_like": a.feels_like,
                "raining": a.raining,
                "hour": a.hour,
                "weather_vec": list(a.weather_vec),
                "taste_vec": list(a.taste_vec),
            }
            for a in archetypes
        ]
        async with self._sessions.begin() as session:
            for start in range(0, len(rows), 200):
                stmt = insert(taste_archetype).values(rows[start : start + 200])
                await session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=[taste_archetype.c.key],
                        set_={
                            "name_ko": stmt.excluded.name_ko,
                            "feels_like": stmt.excluded.feels_like,
                            "raining": stmt.excluded.raining,
                            "hour": stmt.excluded.hour,
                            "weather_vec": stmt.excluded.weather_vec,
                            "taste_vec": stmt.excluded.taste_vec,
                        },
                    )
                )
        return len(rows)

    async def nearest_archetypes(
        self, weather_vec: Sequence[float], k: int
    ) -> list[tuple[Archetype, float]]:
        distance = taste_archetype.c.weather_vec.l2_distance(list(weather_vec))
        stmt = select(taste_archetype, distance.label("distance")).order_by(distance).limit(k)
        async with self._sessions() as session:
            rows = list(await session.execute(stmt))
        return [
            (
                Archetype(
                    key=r.key,
                    name_ko=r.name_ko,
                    feels_like=r.feels_like,
                    raining=r.raining,
                    hour=r.hour,
                    weather_vec=tuple(float(x) for x in r.weather_vec),
                    taste_vec=tuple(float(x) for x in r.taste_vec),
                ),
                float(r.distance),
            )
            for r in rows
        ]
