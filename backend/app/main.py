"""Composition root: builds the adapters and wires them into the use cases."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.adapters.inbound.http.admin_auth import AdminAuth
from app.adapters.inbound.http.admin_routes import LOGIN_ATTEMPTS, LOGIN_WINDOW_S
from app.adapters.inbound.http.admin_routes import router as admin_router
from app.adapters.inbound.http.collection_routes import PER_VISITOR_LIMIT
from app.adapters.inbound.http.collection_routes import router as collection_router
from app.adapters.inbound.http.ratelimit import RateLimiter
from app.adapters.inbound.http.routes import TtlCache, router
from app.adapters.outbound.clients.k8s_collector import in_cluster_launcher
from app.adapters.outbound.clients.kma import KmaWeatherClient, load_stations
from app.adapters.outbound.clock import SystemClock
from app.adapters.outbound.persistence.collection_repository import (
    PostgresCollectionRequestRepository,
)
from app.adapters.outbound.persistence.recommend_repository import (
    PostgresCandidateSource,
    PostgresWeatherSnapshotStore,
)
from app.adapters.outbound.persistence.repository import make_engine
from app.adapters.outbound.persistence.taste_repository import (
    PostgresArchetypeRepository,
    PostgresTasteRepository,
)
from app.application.admin import ManageCollectionRequests
from app.application.collection import RequestCollection
from app.application.recommend import RecommendCafes
from app.application.taste import FindWeatherTaste
from app.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    # httpx logs every request URL at INFO, and the KMA URL carries the auth key.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings.database_url)
        async with httpx.AsyncClient() as http:
            stations_csv = Path(settings.kma_stations_csv)
            weather = KmaWeatherClient(
                http,
                settings.kma_auth_key,
                load_stations(stations_csv),
                PostgresWeatherSnapshotStore(engine),
            )
            tastes = PostgresTasteRepository(engine)
            app.state.recommend = RecommendCafes(
                weather,
                FindWeatherTaste(PostgresArchetypeRepository(engine)),
                PostgresCandidateSource(engine),
                tastes,
                SystemClock(),
            )
            app.state.cache = TtlCache(settings.recommendation_cache_ttl_s)
            requests = PostgresCollectionRequestRepository(engine)
            app.state.collection = RequestCollection(requests, SystemClock())
            app.state.collection_limiter = RateLimiter(PER_VISITOR_LIMIT, 3600.0)
            auth = AdminAuth(
                settings.admin_user,
                settings.admin_password,
                settings.admin_session_key,
                settings.admin_session_hours,
            )
            if not auth.enabled:
                logging.getLogger(__name__).info("admin page is off (admin settings are not set)")
            launcher = in_cluster_launcher(settings.collector_cronjob)
            app.state.admin_auth = auth
            app.state.admin = ManageCollectionRequests(requests, launcher)
            app.state.admin_login_limiter = RateLimiter(LOGIN_ATTEMPTS, LOGIN_WINDOW_S)
            yield
            await launcher.aclose()
        await engine.dispose()

    app = FastAPI(title="aicafe", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.include_router(collection_router)
    app.include_router(admin_router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
