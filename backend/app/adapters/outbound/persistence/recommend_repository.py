"""Read models for recommendations: candidate cafes near a point, and the weather snapshot store."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.adapters.outbound.persistence.tables import (
    cafe,
    cafe_menu,
    cafe_review,
    cafe_taste,
    weather_snapshot,
)
from app.domain.models import BusinessInfo, BusinessStatus, DayHours, GeoPoint
from app.domain.recommend import Candidate
from app.domain.taste import AXES, MenuEvidence

M_PER_DEG_LAT = 111_320.0


def _bbox(center: GeoPoint, radius_m: float) -> tuple[float, float, float, float]:
    dlat = radius_m / M_PER_DEG_LAT
    dlng = radius_m / (M_PER_DEG_LAT * max(0.1, math.cos(math.radians(center.lat))))
    return center.lat - dlat, center.lat + dlat, center.lng - dlng, center.lng + dlng


def _business(status: str, text: str | None, hours: list[dict[str, Any]]) -> BusinessInfo:
    try:
        parsed = BusinessStatus(status)
    except ValueError:
        parsed = BusinessStatus.UNKNOWN
    return BusinessInfo(
        parsed,
        text,
        tuple(
            DayHours(h.get("day") or "", h.get("start"), h.get("end"), h.get("description"))
            for h in hours
        ),
    )


class PostgresCandidateSource:
    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def candidates_near(self, center: GeoPoint, radius_m: float) -> list[Candidate]:
        lat_min, lat_max, lng_min, lng_max = _bbox(center, radius_m)
        async with self._sessions() as session:
            rows = list(
                await session.execute(
                    select(cafe, cafe_taste.c.taste_vec, cafe_taste.c.confidence)
                    .join(cafe_taste, cafe_taste.c.place_id == cafe.c.place_id)
                    .where(
                        cafe.c.is_active.is_(True),
                        cafe.c.lat.between(lat_min, lat_max),
                        cafe.c.lng.between(lng_min, lng_max),
                    )
                )
            )
            ids = [r.place_id for r in rows]
            menus: dict[str, list[MenuEvidence]] = defaultdict(list)
            tags: dict[str, list[dict[str, int]]] = defaultdict(list)
            if ids:
                for m in await session.execute(
                    select(
                        cafe_menu.c.place_id,
                        cafe_menu.c.name,
                        cafe_menu.c.description,
                        cafe_menu.c.price,
                        cafe_menu.c.image_url,
                    )
                    .where(cafe_menu.c.place_id.in_(ids))
                    .order_by(cafe_menu.c.place_id, cafe_menu.c.position.asc().nullslast())
                ):
                    menus[m.place_id].append(
                        MenuEvidence(m.name, m.description, m.price, m.image_url)
                    )
                for t in await session.execute(
                    select(cafe_review.c.place_id, cafe_review.c.taste_tags).where(
                        cafe_review.c.place_id.in_(ids), cafe_review.c.is_noise.is_(False)
                    )
                ):
                    tags[t.place_id].append(t.taste_tags or {})
        candidates: list[Candidate] = []
        for r in rows:
            review_tags = tags.get(r.place_id, [])
            axis_counts = {a: sum(1 for t in review_tags if t.get(a, 0) > 0) for a in AXES}
            candidates.append(
                Candidate(
                    place_id=r.place_id,
                    name=r.name,
                    point=GeoPoint(r.lat, r.lng),
                    road_address=r.road_address,
                    rating=r.rating,
                    review_count=r.review_count,
                    taste=tuple(float(x) for x in r.taste_vec),
                    confidence=r.confidence,
                    menus=tuple(menus.get(r.place_id, ())),
                    business=_business(
                        r.business_status, r.business_status_text, r.business_hours or []
                    ),
                    status_checked_at=r.detail_fetched_at,
                    review_axis_counts={a: n for a, n in axis_counts.items() if n},
                    review_total=len(review_tags),
                    cover_photo_url=r.cover_photo_url,
                    photo_urls=tuple(r.photo_urls or ()),
                    menu_mentions=tuple(
                        (str(label), int(count)) for label, count in r.menu_mentions or ()
                    ),
                )
            )
        return candidates


class PostgresWeatherSnapshotStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def load(self, tm: str) -> dict[str, dict[str, str]] | None:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(weather_snapshot.c.stations).where(weather_snapshot.c.tm == tm)
                )
            ).first()
        return None if row is None else dict(row.stations)

    async def save(self, tm: str, rows: dict[str, dict[str, str]], fetched_at: datetime) -> None:
        async with self._sessions.begin() as session:
            stmt = insert(weather_snapshot).values(tm=tm, fetched_at=fetched_at, stations=rows)
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[weather_snapshot.c.tm],
                    set_={
                        "fetched_at": stmt.excluded.fetched_at,
                        "stations": stmt.excluded.stations,
                    },
                )
            )
