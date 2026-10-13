"""HTTP routes. Translation between the web layer and the recommendation use case."""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.adapters.inbound.http.schemas import (
    CafeOut,
    ErrorOut,
    HoursRowOut,
    ItemOut,
    MenuOut,
    OpenStateOut,
    RecommendationsOut,
    TasteChip,
    WeatherOut,
)
from app.application.recommend import (
    NotReadyError,
    RecommendationResult,
    RecommendCafes,
    RecommendedCafe,
    WeatherUnavailableError,
)
from app.domain.models import GeoPoint
from app.domain.recommend import hours_today, walking_minutes, weekly_hours
from app.domain.taste import AXES, AXIS_LABELS_KO, TasteVector
from app.domain.weather import describe

router = APIRouter(prefix="/api/v1")

# Service area guard: Korea only.
LatQuery = Annotated[float, Query(ge=33.0, le=39.0, description="위도")]
LngQuery = Annotated[float, Query(ge=124.0, le=132.0, description="경도")]


class TtlCache:
    """Small in-process cache so repeated requests for the same area do not hit the database."""

    def __init__(self, ttl_s: float, max_items: int = 512) -> None:
        self._ttl_s = ttl_s
        self._max_items = max_items
        self._items: dict[str, tuple[float, RecommendationResult]] = {}

    def get(self, key: str) -> RecommendationResult | None:
        entry = self._items.get(key)
        if entry is None or entry[0] < time.monotonic():
            self._items.pop(key, None)
            return None
        return entry[1]

    def put(self, key: str, value: RecommendationResult) -> None:
        if len(self._items) >= self._max_items:
            self._items.pop(next(iter(self._items)))
        self._items[key] = (time.monotonic() + self._ttl_s, value)


def get_use_case(request: Request) -> RecommendCafes:
    use_case: RecommendCafes = request.app.state.recommend
    return use_case


def get_cache(request: Request) -> TtlCache:
    cache: TtlCache = request.app.state.cache
    return cache


def _chips(vector: TasteVector, n: int, skip_temperature: bool = False) -> list[TasteChip]:
    ranked = sorted(zip(AXES, vector, strict=True), key=lambda p: p[1], reverse=True)
    chips = [
        TasteChip(axis=a, label=AXIS_LABELS_KO[a], value=round(v, 3))
        for a, v in ranked
        if not (skip_temperature and a in ("hot", "iced"))
    ]
    return chips[:n]


def _item(entry: RecommendedCafe, today: date) -> ItemOut:
    s = entry.scored
    c = s.candidate
    menu = s.menu
    image = (
        (menu.image_url if menu else None) or c.cover_photo_url or next(iter(c.photo_urls), None)
    )
    return ItemOut(
        rank=entry.rank,
        cafe=CafeOut(
            place_id=c.place_id,
            name=c.name,
            address=c.road_address,
            lat=c.point.lat,
            lng=c.point.lng,
            rating=c.rating,
            review_count=c.review_count,
            distance_m=round(s.distance_m),
            walking_minutes=walking_minutes(s.distance_m),
            naver_map_url=f"https://map.naver.com/p/entry/place/{c.place_id}",
            image_url=image,
            open_state=OpenStateOut(
                is_open=s.open_state.is_open,
                label=s.open_state.label,
                changes_at=s.open_state.changes_at,
                changes_tomorrow=s.open_state.changes_tomorrow,
            ),
            today_hours=hours_today(c.business.hours, today),
            weekly_hours=[
                HoursRowOut(days=r.days, text=r.text, is_today=r.is_today)
                for r in weekly_hours(c.business.hours, today)
            ],
        ),
        menu=MenuOut(
            name=menu.name if menu else "",
            price=menu.price if menu else None,
            image_url=menu.image_url if menu else None,
        ),
        message=entry.text.message,
        headline=entry.text.headline,
        reason=entry.text.reason,
        status_line=entry.text.status_line,
        score=round(s.score, 4),
        taste_chips=_chips(c.taste, 3, skip_temperature=True),
    )


def _weather(result: RecommendationResult) -> WeatherOut:
    w = result.weather
    return WeatherOut(
        station_id=result.station_id,
        observed_at=result.observed_at,
        description=describe(w.conditions),
        feels_like_c=round(w.conditions.feels_like, 1),
        raining=w.conditions.raining,
        humidity_pct=round(w.conditions.humidity * 100),
        wanted_taste=_chips(w.taste, 5),
        nearest_scenario=w.nearest.name_ko,
    )


def _to_response(result: RecommendationResult, generated_at: float) -> RecommendationsOut:
    return RecommendationsOut(
        origin_lat=result.origin.lat,
        origin_lng=result.origin.lng,
        radius_m=int(result.radius_m),
        weather=_weather(result),
        summary=result.summary,
        items=[_item(e, result.today) for e in result.items],
        more_items=[_item(e, result.today) for e in result.more_items],
        notices=list(result.notices),
        generated_at=datetime.fromtimestamp(generated_at, UTC),
    )


@router.get(
    "/recommendations",
    response_model=RecommendationsOut,
    responses={503: {"model": ErrorOut}},
)
async def recommendations(
    lat: LatQuery,
    lng: LngQuery,
    use_case: Annotated[RecommendCafes, Depends(get_use_case)],
    cache: Annotated[TtlCache, Depends(get_cache)],
    radius_m: Annotated[float, Query(ge=300, le=5000, description="검색 반경(m)")] = 1000.0,
) -> RecommendationsOut:
    # ~200 m cells: nearby requests share one answer (and the weather snapshot is hourly anyway)
    key = f"{round(lat / 0.002)}:{round(lng / 0.002)}:{int(radius_m)}"
    result = cache.get(key)
    if result is None:
        try:
            result = await use_case.run(GeoPoint(lat, lng), radius_m)
        except WeatherUnavailableError as exc:
            raise HTTPException(503, "이 지역의 날씨 정보를 아직 가져올 수 없어요.") from exc
        except NotReadyError as exc:
            raise HTTPException(
                503, "추천 데이터를 준비하고 있어요. 잠시 후 다시 시도해 주세요."
            ) from exc
        cache.put(key, result)
    return _to_response(result, time.time())


@router.get("/weather", response_model=WeatherOut, responses={503: {"model": ErrorOut}})
async def weather(
    lat: LatQuery,
    lng: LngQuery,
    use_case: Annotated[RecommendCafes, Depends(get_use_case)],
) -> WeatherOut:
    try:
        result = await use_case.run(GeoPoint(lat, lng), 300.0)
    except WeatherUnavailableError as exc:
        raise HTTPException(503, "이 지역의 날씨 정보를 아직 가져올 수 없어요.") from exc
    except NotReadyError as exc:
        raise HTTPException(503, "추천 데이터를 준비하고 있어요.") from exc
    return _weather(result)
