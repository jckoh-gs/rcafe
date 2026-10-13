"""HTTP tests for collection requests (real routes over an in-memory repository)."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI, Request

from app.adapters.inbound.http.collection_routes import router
from app.adapters.inbound.http.ratelimit import RateLimiter, client_ip
from app.application.collection import RequestCollection
from tests.fakes import FakeCollectionRepo

KST = timezone(timedelta(hours=9))


class Clock:
    def now(self) -> datetime:
        return datetime.now(KST)


def _app(repo: FakeCollectionRepo, per_hour: int = 5) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.collection = RequestCollection(repo, Clock())
    app.state.collection_limiter = RateLimiter(per_hour, 3600.0)
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


BUCHEON = {"lat": 37.4878, "lng": 126.7886}


async def test_requesting_an_empty_area_queues_it_and_tells_when_it_will_run() -> None:
    repo = FakeCollectionRepo()
    async with _client(_app(repo)) as client:
        response = await client.post("/api/v1/collection-requests", json=BUCHEON)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued" and body["request_count"] == 1
    assert "한가한" in body["message"] and "새벽 3시 30분" in body["message"]
    assert body["next_run_at"] is not None
    assert len(repo.rows) == 1


async def test_asking_again_only_raises_the_count_and_status_follows_progress() -> None:
    repo = FakeCollectionRepo()
    async with _client(_app(repo)) as client:
        await client.post("/api/v1/collection-requests", json=BUCHEON)
        again = (await client.post("/api/v1/collection-requests", json=BUCHEON)).json()
        assert again["status"] == "already_queued" and again["request_count"] == 2
        assert "2번 요청" in again["message"]
        assert len(repo.rows) == 1

        status = (await client.get("/api/v1/collection-requests", params=BUCHEON)).json()
        assert status["status"] == "already_queued"

        row = next(iter(repo.rows.values()))
        await repo.mark_done(row.id, datetime.now(KST), 41)
        done = (await client.get("/api/v1/collection-requests", params=BUCHEON)).json()
        assert done["status"] == "done" and done["cafes_found"] == 41
        assert "41곳" in done["message"]


async def test_status_is_none_for_an_area_nobody_asked_about() -> None:
    async with _client(_app(FakeCollectionRepo())) as client:
        body = (await client.get("/api/v1/collection-requests", params=BUCHEON)).json()
    assert body["status"] == "none" and body["message"] == ""


async def test_covered_areas_are_told_so_and_not_queued() -> None:
    repo = FakeCollectionRepo(cafes_near=30)
    async with _client(_app(repo)) as client:
        body = (await client.post("/api/v1/collection-requests", json=BUCHEON)).json()
    assert body["status"] == "covered" and "이미 카페 정보가 있어요" in body["message"]
    assert repo.rows == {}


@pytest.mark.parametrize(
    "payload",
    [{"lat": 10, "lng": 127}, {"lat": 37.5, "lng": 200}, {"lat": "x", "lng": 127}, {"lat": 37.5}],
)
async def test_invalid_coordinates_are_rejected(payload: dict[str, object]) -> None:
    repo = FakeCollectionRepo()
    async with _client(_app(repo)) as client:
        response = await client.post("/api/v1/collection-requests", json=payload)
    assert response.status_code == 422 and repo.rows == {}


async def test_one_visitor_cannot_flood_the_queue() -> None:
    repo = FakeCollectionRepo()
    async with _client(_app(repo, per_hour=3)) as client:
        codes = []
        for i in range(5):
            r = await client.post(
                "/api/v1/collection-requests", json={"lat": 34.0 + i * 0.1, "lng": 126.0}
            )
            codes.append(r.status_code)
        other = await client.post(
            "/api/v1/collection-requests",
            json={"lat": 36.0, "lng": 127.0},
            headers={"x-forwarded-for": "9.9.9.9, 10.0.0.1"},  # a different visitor
        )
    assert codes == [200, 200, 200, 429, 429]
    assert other.status_code == 200
    assert len(repo.rows) == 4  # three from the flooding visitor, one from the other


def test_rate_limiter_window_and_visitor_address() -> None:
    limiter = RateLimiter(2, 3600.0)
    assert limiter.allow("a") and limiter.allow("a") and not limiter.allow("a")
    assert limiter.allow("b")
    expiring = RateLimiter(1, 0.01)
    assert expiring.allow("x")
    import time

    time.sleep(0.02)
    assert expiring.allow("x")  # the window has passed

    def request(header: str | None) -> Request:
        headers = [(b"x-forwarded-for", header.encode())] if header else []
        return Request({"type": "http", "headers": headers, "client": ("1.2.3.4", 1)})

    assert client_ip(request("5.6.7.8, 10.0.0.1")) == "5.6.7.8"  # visitor, then the proxy
    assert client_ip(request("spoofed, 5.6.7.8, 10.0.0.1")) == "5.6.7.8"  # spoofing is ignored
    assert client_ip(request("5.6.7.8")) == "5.6.7.8"
    assert client_ip(request(None)) == "1.2.3.4"
