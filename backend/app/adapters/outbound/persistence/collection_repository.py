"""PostgreSQL implementation of CollectionRequestRepository (one row per ~1 km cell)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, delete, func, literal_column, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.adapters.outbound.persistence.tables import cafe, collection_request
from app.domain.models import CollectionRequest, CollectionStatus, GeoPoint
from app.domain.services import cell_for

M_PER_DEG_LAT = 111_320.0
REFRESH_AFTER = timedelta(days=30)  # a finished area may be collected again after this long


def _to_domain(row: Any) -> CollectionRequest:
    return CollectionRequest(
        id=row.id,
        cell_key=row.cell_key,
        center=GeoPoint(row.center_lat, row.center_lng),
        radius_m=row.radius_m,
        status=CollectionStatus(row.status),
        request_count=row.request_count,
        requested_at=row.requested_at,
        last_requested_at=row.last_requested_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        cafes_found=row.cafes_found,
        note=row.note,
    )


class PostgresCollectionRequestRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def submit(
        self, point: GeoPoint, at: datetime, radius_m: int
    ) -> tuple[CollectionRequest, bool]:
        key, center = cell_for(point)
        base = insert(collection_request).values(
            cell_key=key,
            center_lat=center.lat,
            center_lng=center.lng,
            radius_m=radius_m,
            status=CollectionStatus.PENDING.value,
            request_count=1,
            requested_at=at,
            last_requested_at=at,
        )
        # Repeated requests only raise the count; failed or stale finished areas are queued again.
        reopen = (collection_request.c.status == CollectionStatus.FAILED.value) | (
            (collection_request.c.status == CollectionStatus.DONE.value)
            & (collection_request.c.finished_at < at - REFRESH_AFTER)
        )
        upsert = base.on_conflict_do_update(
            index_elements=[collection_request.c.cell_key],
            set_={
                "request_count": collection_request.c.request_count + 1,
                "last_requested_at": at,
                "status": case(
                    (reopen, CollectionStatus.PENDING.value), else_=collection_request.c.status
                ),
            },
        ).returning(collection_request, literal_column("(xmax = 0)").label("created"))
        async with self._sessions.begin() as session:
            row = (await session.execute(upsert)).one()
        return _to_domain(row), bool(row.created)

    async def find(self, point: GeoPoint) -> CollectionRequest | None:
        key, _ = cell_for(point)
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(collection_request).where(collection_request.c.cell_key == key)
                )
            ).first()
        return None if row is None else _to_domain(row)

    async def next_pending(self, limit: int) -> list[CollectionRequest]:
        stmt = (
            select(collection_request)
            .where(collection_request.c.status == CollectionStatus.PENDING.value)
            .order_by(collection_request.c.request_count.desc(), collection_request.c.requested_at)
            .limit(limit)
        )
        async with self._sessions() as session:
            return [_to_domain(r) for r in await session.execute(stmt)]

    async def _set(self, request_id: int, **values: Any) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(collection_request)
                .where(collection_request.c.id == request_id)
                .values(**values)
            )

    async def mark_running(self, request_id: int, at: datetime) -> None:
        await self._set(request_id, status=CollectionStatus.RUNNING.value, started_at=at, note=None)

    async def mark_done(self, request_id: int, at: datetime, cafes_found: int) -> None:
        await self._set(
            request_id,
            status=CollectionStatus.DONE.value,
            finished_at=at,
            cafes_found=cafes_found,
            note=None,
        )

    async def mark_retry(self, request_id: int, at: datetime, note: str) -> None:
        await self._set(request_id, status=CollectionStatus.PENDING.value, note=note)

    async def mark_failed(self, request_id: int, at: datetime, note: str) -> None:
        await self._set(request_id, status=CollectionStatus.FAILED.value, finished_at=at, note=note)

    async def get(self, request_id: int) -> CollectionRequest | None:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(collection_request).where(collection_request.c.id == request_id)
                )
            ).first()
        return None if row is None else _to_domain(row)

    async def list_all(self, limit: int) -> list[CollectionRequest]:
        status = collection_request.c.status
        rank = case(
            (status == CollectionStatus.RUNNING.value, 0),
            (status == CollectionStatus.PENDING.value, 1),
            (status == CollectionStatus.FAILED.value, 2),
            else_=3,
        )
        waiting = status == CollectionStatus.PENDING.value
        stmt = (
            select(collection_request)
            .order_by(
                rank,
                case((waiting, collection_request.c.request_count), else_=0).desc(),
                case((waiting, collection_request.c.requested_at)).asc().nulls_last(),
                collection_request.c.last_requested_at.desc(),
            )
            .limit(limit)
        )
        async with self._sessions() as session:
            return [_to_domain(r) for r in await session.execute(stmt)]

    async def delete(self, request_id: int) -> bool:
        stmt = (
            delete(collection_request)
            .where(
                collection_request.c.id == request_id,
                collection_request.c.status != CollectionStatus.RUNNING.value,
            )
            .returning(collection_request.c.id)
        )
        async with self._sessions.begin() as session:
            return (await session.execute(stmt)).first() is not None

    async def requeue(self, request_id: int, note: str | None = None) -> bool:
        stmt = (
            update(collection_request)
            .where(
                collection_request.c.id == request_id,
                collection_request.c.status != CollectionStatus.RUNNING.value,
            )
            .values(status=CollectionStatus.PENDING.value, note=note)
            .returning(collection_request.c.id)
        )
        async with self._sessions.begin() as session:
            return (await session.execute(stmt)).first() is not None

    async def count_by_status(self) -> dict[CollectionStatus, int]:
        stmt = select(collection_request.c.status, func.count()).group_by(
            collection_request.c.status
        )
        async with self._sessions() as session:
            rows = (await session.execute(stmt)).all()
        return {CollectionStatus(status): int(count) for status, count in rows}

    async def reset_stale_running(self, started_before: datetime, note: str) -> int:
        stmt = (
            update(collection_request)
            .where(
                collection_request.c.status == CollectionStatus.RUNNING.value,
                collection_request.c.started_at < started_before,
            )
            .values(status=CollectionStatus.PENDING.value, note=note)
            .returning(collection_request.c.id)
        )
        async with self._sessions.begin() as session:
            return len((await session.execute(stmt)).all())

    async def count_pending(self) -> int:
        async with self._sessions() as session:
            return int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(collection_request)
                        .where(
                            collection_request.c.status.in_(
                                [CollectionStatus.PENDING.value, CollectionStatus.RUNNING.value]
                            )
                        )
                    )
                ).scalar_one()
            )

    async def count_created_since(self, since: datetime) -> int:
        async with self._sessions() as session:
            return int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(collection_request)
                        .where(collection_request.c.requested_at >= since)
                    )
                ).scalar_one()
            )

    async def count_cafes_near(self, center: GeoPoint, radius_m: float) -> int:
        dlat = radius_m / M_PER_DEG_LAT
        dlng = radius_m / (M_PER_DEG_LAT * max(0.1, math.cos(math.radians(center.lat))))
        async with self._sessions() as session:
            return int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(cafe)
                        .where(
                            cafe.c.is_active.is_(True),
                            cafe.c.lat.between(center.lat - dlat, center.lat + dlat),
                            cafe.c.lng.between(center.lng - dlng, center.lng + dlng),
                        )
                    )
                ).scalar_one()
            )
