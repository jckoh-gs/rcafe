"""Pydantic response/request models of the public API (domain objects never leave as-is)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class OpenStateOut(BaseModel):
    is_open: bool | None
    label: str
    changes_at: str | None = None
    changes_tomorrow: bool = False


class HoursRowOut(BaseModel):
    days: str
    text: str
    is_today: bool


class MenuOut(BaseModel):
    name: str
    price: int | None = None
    image_url: str | None = None


class CafeOut(BaseModel):
    place_id: str
    name: str
    address: str | None
    lat: float
    lng: float
    rating: float | None
    review_count: int
    distance_m: int
    walking_minutes: int
    naver_map_url: str
    image_url: str | None
    open_state: OpenStateOut
    today_hours: str | None
    weekly_hours: list[HoursRowOut]


class TasteChip(BaseModel):
    axis: str
    label: str
    value: float


class ItemOut(BaseModel):
    rank: int
    cafe: CafeOut
    menu: MenuOut
    message: str
    headline: str
    reason: str
    status_line: str
    score: float
    taste_chips: list[TasteChip]


class WeatherOut(BaseModel):
    station_id: str
    observed_at: datetime
    description: str
    feels_like_c: float
    raining: bool
    humidity_pct: float
    wanted_taste: list[TasteChip]
    nearest_scenario: str


class RecommendationsOut(BaseModel):
    origin_lat: float
    origin_lng: float
    radius_m: int
    weather: WeatherOut
    summary: str
    items: list[ItemOut]
    more_items: list[ItemOut]  # ranks after the podium, shown behind "show more"
    notices: list[str]
    generated_at: datetime


class ErrorOut(BaseModel):
    detail: str
