import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapters.outbound.persistence.repository import make_engine
from app.adapters.outbound.persistence.tables import metadata

FIXTURES = Path(__file__).parent / "fixtures"
TEST_DB_URL = os.environ.get(
    "AICAFE_TEST_DATABASE_URL",
    "postgresql+asyncpg://aicafe:aicafe@localhost:55432/aicafe_test",
)


def load_fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """Fresh tables in the dedicated test database; skipped when Postgres is unreachable."""
    eng = make_engine(TEST_DB_URL)
    try:
        async with eng.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(metadata.drop_all)
            await conn.run_sync(metadata.create_all)
    except OSError:
        await eng.dispose()
        pytest.skip("Postgres test database is not reachable")
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(metadata.drop_all)
    await eng.dispose()
