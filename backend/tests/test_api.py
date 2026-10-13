"""HTTP layer tests: the real router and schemas over in-memory fakes."""

from collections.abc import Sequence

import httpx
import pytest
from fastapi import FastAPI

from app.adapters.inbound.http.routes import TtlCache, router
from app.application.recommend import RecommendCafes
from app.application.taste import FindWeatherTaste
from app.domain.recommend import Candidate
from app.domain.weather import Archetype
from tests.fakes import (
    CREAMY,
    FRUITY,
    ROAST,
    STATS,
    FakeArchetypes,
    FakeCandidates,
    FakeTastes,
    FakeWeather,
    FixedClock,
    build_use_case,
    candidate,
    hot_day,
)


def _app(use_case: RecommendCafes) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.recommend = use_case
    app.state.cache = TtlCache(60)
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _field() -> list[Candidate]:
    return [
        candidate("1", "과일창고", FRUITY, ("자몽에이드", "레몬티"), 150),
        candidate("2", "크림하우스", CREAMY, ("바닐라라떼",), 200),
        candidate("3", "로스터리원", ROAST, ("아메리카노",), 250),
    ]


async def test_recommendations_response_shape() -> None:
    use_case, _ = build_use_case(_field())
    async with _client(_app(use_case)) as client:
        response = await client.get(
            "/api/v1/recommendations", params={"lat": 37.5006, "lng": 127.0364}
        )
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 3
    first = body["items"][0]
    assert first["rank"] == 1 and first["cafe"]["name"] == "과일창고"
    assert first["menu"]["name"] and first["message"] and first["reason"]
    assert first["cafe"]["naver_map_url"] == "https://map.naver.com/p/entry/place/1"
    assert first["cafe"]["open_state"]["is_open"] is True
    assert first["cafe"]["image_url"] == "https://img.test/1.jpg"  # menu photo wins over cover
    assert body["weather"]["description"] and body["weather"]["wanted_taste"][0]["label"]
    assert body["summary"].endswith("어울려요.")
    assert body["radius_m"] == 1000 and body["notices"] == []


async def test_more_items_follow_the_podium_in_the_response() -> None:
    crowd = [
        candidate(str(i), f"카페{i}", FRUITY, ("자몽에이드",), 100 + i * 10) for i in range(1, 16)
    ]
    use_case, _ = build_use_case(crowd)
    async with _client(_app(use_case)) as client:
        body = (
            await client.get("/api/v1/recommendations", params={"lat": 37.5006, "lng": 127.0364})
        ).json()
    assert [i["rank"] for i in body["items"]] == [1, 2, 3]
    assert [i["rank"] for i in body["more_items"]] == list(range(4, 14))
    extra = body["more_items"][0]
    assert extra["cafe"]["name"] and extra["menu"]["name"] and extra["headline"]
    assert extra["cafe"]["open_state"]["label"] and "weekly_hours" in extra["cafe"]
    shown = [i["cafe"]["place_id"] for i in body["items"] + body["more_items"]]
    assert len(set(shown)) == 13


async def test_nearby_requests_share_a_cached_result() -> None:
    weather = FakeWeather(hot_day())
    use_case, _ = build_use_case(_field(), weather=weather)
    async with _client(_app(use_case)) as client:
        a = await client.get("/api/v1/recommendations", params={"lat": 37.5006, "lng": 127.0364})
        b = await client.get("/api/v1/recommendations", params={"lat": 37.5007, "lng": 127.0365})
        far = await client.get("/api/v1/recommendations", params={"lat": 37.52, "lng": 127.06})
    assert a.status_code == b.status_code == far.status_code == 200
    assert weather.calls == 2  # the second, nearby request was served from the cache


@pytest.mark.parametrize(
    "params",
    [
        {"lat": 10, "lng": 127},  # outside Korea
        {"lat": 37.5, "lng": 127, "radius_m": 50},
        {"lat": 37.5, "lng": 127, "radius_m": 99999},
        {"lat": "abc", "lng": 127},
    ],
)
async def test_invalid_input_is_rejected(params: dict[str, float | str]) -> None:
    use_case, _ = build_use_case(_field())
    async with _client(_app(use_case)) as client:
        response = await client.get("/api/v1/recommendations", params=params)
    assert response.status_code == 422


async def test_weather_unavailable_is_a_friendly_503() -> None:
    use_case, _ = build_use_case(_field())
    use_case._weather = FakeWeather(None)
    async with _client(_app(use_case)) as client:
        response = await client.get("/api/v1/recommendations", params={"lat": 35.18, "lng": 129.07})
    assert response.status_code == 503
    assert "날씨" in response.json()["detail"]


async def test_not_ready_and_weather_endpoint() -> None:
    use_case, _ = build_use_case(_field(), stats=None)
    async with _client(_app(use_case)) as client:
        not_ready = await client.get("/api/v1/recommendations", params={"lat": 37.5, "lng": 127.03})
    assert not_ready.status_code == 503 and "준비" in not_ready.json()["detail"]

    ready, _ = build_use_case(_field())
    async with _client(_app(ready)) as client:
        weather = await client.get("/api/v1/weather", params={"lat": 37.5, "lng": 127.03})
    assert weather.status_code == 200
    assert weather.json()["raining"] is False and weather.json()["feels_like_c"] > 30


class EmptyArchetypes(FakeArchetypes):
    async def nearest_archetypes(
        self, weather_vec: Sequence[float], k: int
    ) -> list[tuple[Archetype, float]]:
        return []


async def test_unseeded_scenarios_are_a_friendly_503_not_a_crash() -> None:
    use_case = RecommendCafes(
        FakeWeather(hot_day()),
        FindWeatherTaste(EmptyArchetypes()),
        FakeCandidates([]),
        FakeTastes(STATS),
        FixedClock(),
    )
    async with _client(_app(use_case)) as client:
        response = await client.get("/api/v1/recommendations", params={"lat": 37.5, "lng": 127.03})
    assert response.status_code == 503 and "준비" in response.json()["detail"]


async def test_opening_hours_are_exposed_next_to_the_open_state() -> None:
    use_case, _ = build_use_case(_field())
    async with _client(_app(use_case)) as client:
        response = await client.get(
            "/api/v1/recommendations", params={"lat": 37.5006, "lng": 127.0364}
        )
    cafe = response.json()["items"][0]["cafe"]
    assert cafe["open_state"]["is_open"] is True
    assert cafe["today_hours"] == "08:00 ~ 22:00"
    assert cafe["weekly_hours"] == [{"days": "금·토", "text": "08:00 ~ 22:00", "is_today": True}]
