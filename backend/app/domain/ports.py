"""Ports (interfaces) the domain and application layers depend on."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from app.domain.models import (
    CollectionRequest,
    CollectionStatus,
    GeoPoint,
    PlaceDetail,
    SearchHit,
    UpsertResult,
)
from app.domain.recommend import Candidate
from app.domain.taste import AxisStats, CafeEvidence, CafeProfile, TasteVector
from app.domain.weather import Archetype, WeatherObservation


class PlaceFetchError(RuntimeError):
    """A single place could not be fetched (transient). The crawl may continue."""


class PlaceSearchPort(Protocol):
    async def search(self, query: str, center: GeoPoint) -> list[SearchHit]:
        """Return at most a handful of places near `center` matching `query`."""
        ...


class PlaceDetailPort(Protocol):
    async def fetch_detail(self, place_id: str) -> PlaceDetail | None:
        """Return detail data, or None if the place no longer exists."""
        ...


class CafeRepository(Protocol):
    async def upsert_hits(self, hits: Sequence[SearchHit], seen_at: datetime) -> UpsertResult:
        """Insert or update basic info keyed by place_id. Never creates duplicates."""
        ...

    async def place_ids_needing_detail(
        self,
        older_than: datetime,
        limit: int,
        area: tuple[GeoPoint, float] | None = None,
    ) -> list[str]:
        """Active places whose detail was never fetched or is older than `older_than`.

        `area` (center, radius in meters) restricts the answer to one neighborhood.
        """
        ...

    async def save_detail(self, detail: PlaceDetail, fetched_at: datetime) -> UpsertResult:
        """Store detail for an existing place. Unchanged content only refreshes the timestamp."""
        ...

    async def mark_inactive(self, place_id: str, at: datetime) -> None:
        """Flag a place that no longer exists upstream (rows are never deleted)."""
        ...


class ClockPort(Protocol):
    def now(self) -> datetime:
        """Timezone-aware current time."""
        ...


class AxisStatsPort(Protocol):
    async def load_axis_stats(self) -> AxisStats | None:
        """Dataset-wide axis statistics, or None before the first `taste` run."""
        ...


class TasteRepository(Protocol):
    async def list_evidence(self, only_missing: bool = False) -> list[CafeEvidence]:
        """Menus and non-noise reviews of active cafes whose detail has been fetched.

        `only_missing` keeps just the cafes that have no taste vector yet.
        """
        ...

    async def save_cafe_tastes(
        self, items: Sequence[tuple[str, TasteVector, float, float]], at: datetime
    ) -> None:
        """Upsert (place_id, taste vector, confidence, evidence weight) rows."""
        ...

    async def save_review_tags(self, tags: dict[str, dict[str, dict[str, int]]]) -> None:
        """Store lexicon hits per review: place_id -> review_key -> {axis: hits}."""
        ...

    async def save_axis_stats(self, stats: AxisStats, at: datetime) -> None: ...

    async def load_axis_stats(self) -> AxisStats | None: ...

    async def list_profiles(self) -> list[CafeProfile]:
        """Cafes that have a computed taste vector, with their menus."""
        ...

    async def purge_raw_review_text(self) -> int:
        """Delete the temporary full review text; tags and the short snippet stay."""
        ...


class ArchetypeRepository(Protocol):
    async def upsert_archetypes(self, archetypes: Sequence[Archetype]) -> int: ...

    async def nearest_archetypes(
        self, weather_vec: Sequence[float], k: int
    ) -> list[tuple[Archetype, float]]:
        """The k archetypes closest (L2) to the weather feature vector, with their distances."""
        ...


class WeatherPort(Protocol):
    async def observation_at(self, point: GeoPoint, now: datetime) -> WeatherObservation | None:
        """The latest observation from the nearest covered station, or None if unavailable."""
        ...


class CandidateSource(Protocol):
    async def candidates_near(self, center: GeoPoint, radius_m: float) -> list[Candidate]:
        """Active cafes with a taste vector inside the radius."""
        ...


class CollectionRequestRepository(Protocol):
    async def submit(
        self, point: GeoPoint, at: datetime, radius_m: int
    ) -> tuple[CollectionRequest, bool]:
        """Queue a request for the point's cell or bump the existing one: (request, created)."""
        ...

    async def find(self, point: GeoPoint) -> CollectionRequest | None:
        """The request of the point's cell, if any."""
        ...

    async def next_pending(self, limit: int) -> list[CollectionRequest]:
        """Pending requests, most requested first (oldest first among equals)."""
        ...

    async def mark_running(self, request_id: int, at: datetime) -> None: ...

    async def mark_done(self, request_id: int, at: datetime, cafes_found: int) -> None: ...

    async def mark_retry(self, request_id: int, at: datetime, note: str) -> None:
        """Put an interrupted request back in the queue (a block or the time budget ran out)."""
        ...

    async def mark_failed(self, request_id: int, at: datetime, note: str) -> None: ...

    async def count_pending(self) -> int: ...

    async def count_created_since(self, since: datetime) -> int: ...

    async def count_cafes_near(self, center: GeoPoint, radius_m: float) -> int:
        """Active cafes inside the radius (bounding-box accuracy is enough)."""
        ...

    async def get(self, request_id: int) -> CollectionRequest | None: ...

    async def list_all(self, limit: int) -> list[CollectionRequest]:
        """Running first, then waiting (most requested first), failed, and finished (newest)."""
        ...

    async def delete(self, request_id: int) -> bool:
        """Remove a request that is not running; False if it is gone or running."""
        ...

    async def requeue(self, request_id: int, note: str | None = None) -> bool:
        """Put a failed or finished request back in the queue; False if it is missing or running."""
        ...

    async def count_by_status(self) -> dict[CollectionStatus, int]: ...

    async def reset_stale_running(self, started_before: datetime, note: str) -> int:
        """Queue again what was left `running` by a collector that died; returns how many."""
        ...


class CollectorUnavailable(RuntimeError):
    """The collector cannot be started from here (not in the cluster, or the cluster refused)."""


class CollectorLauncher(Protocol):
    """Starts a collector run outside the API process (a Kubernetes Job in production)."""

    async def is_running(self) -> bool:
        """True while any collector (nightly or started by hand) is working."""
        ...

    async def launch(self, request_id: int) -> str:
        """Start a run for exactly this request and return the name of what was started."""
        ...
