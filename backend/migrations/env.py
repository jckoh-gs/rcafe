"""Alembic environment (async engine, URL from settings)."""

import asyncio

from alembic import context
from sqlalchemy.engine import Connection

from app.adapters.outbound.persistence.repository import make_engine
from app.adapters.outbound.persistence.tables import metadata
from app.config import Settings

target_metadata = metadata


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = make_engine(Settings().database_url)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=Settings().database_url, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_online())
