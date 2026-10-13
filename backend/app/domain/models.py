"""Domain models for cafe discovery. Pure Python: no framework, DB, or HTTP imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class GeoPoint:
    lat: float
    lng: float


class BusinessStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One result of the Naver map search (basic info only)."""

    place_id: str
    name: str
    point: GeoPoint
    category: str
    road_address: str | None
    jibun_address: str | None
    review_count: int
    rank_score: float
    has_booking: bool


@dataclass(frozen=True, slots=True)
class DayHours:
    day: str
    start: str | None
    end: str | None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class BusinessInfo:
    status: BusinessStatus
    status_text: str | None
    hours: tuple[DayHours, ...] = ()


@dataclass(frozen=True, slots=True)
class MenuItem:
    menu_key: str
    name: str
    price: int | None
    description: str | None
    image_url: str | None
    mention_count: int | None = None


@dataclass(frozen=True, slots=True)
class Review:
    review_key: str
    rating: int | None
    text: str
    visited_label: str | None
    ordered_item: str | None
    photo_url: str | None
    voted_keywords: tuple[str, ...] = ()
    is_noise: bool = False


@dataclass(frozen=True, slots=True)
class PlaceDetail:
    """Detail page data. `reviews` holds at most the configured number of reviews."""

    place_id: str
    name: str
    phone: str | None
    rating: float | None
    review_count: int | None
    micro_review: str | None
    business: BusinessInfo
    menus: tuple[MenuItem, ...]
    menu_mentions: tuple[tuple[str, int], ...]
    reviews: tuple[Review, ...]
    photo_urls: tuple[str, ...]
    cover_photo_url: str | None = None
    conveniences: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class UpsertResult:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0

    def __add__(self, other: UpsertResult) -> UpsertResult:
        return UpsertResult(
            self.inserted + other.inserted,
            self.updated + other.updated,
            self.unchanged + other.unchanged,
        )


@dataclass(frozen=True, slots=True)
class Station:
    station_id: str
    name: str
    point: GeoPoint


class CollectionStatus(StrEnum):
    PENDING = "pending"  # waiting for the next quiet-hours run
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CollectionRequest:
    """A visitor's request to collect cafes around a place that has no data yet."""

    id: int
    cell_key: str  # requests inside the same ~1 km cell are merged into one
    center: GeoPoint
    radius_m: int
    status: CollectionStatus
    request_count: int
    requested_at: datetime
    last_requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cafes_found: int | None = None
    note: str | None = None
