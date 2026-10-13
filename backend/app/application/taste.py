"""Use cases for the taste model: cafe taste vectors and weather-wanted taste."""

from __future__ import annotations

from dataclasses import dataclass

from app.application.errors import NotReadyError
from app.domain.ports import ArchetypeRepository, ClockPort, TasteRepository
from app.domain.taste import (
    AxisStats,
    TasteVector,
    compute_axis_stats,
    normalize_cafe_taste,
    raw_cafe_taste,
)
from app.domain.weather import (
    Archetype,
    WeatherConditions,
    WeatherObservation,
    blend_neighbors,
    build_scenarios,
    conditions_from,
    feature_vector,
    taste_from_conditions,
)


@dataclass(frozen=True, slots=True)
class ComputeReport:
    cafes: int
    cafes_with_reviews: int
    reviews_tagged: int
    stats: AxisStats


class ComputeCafeTastes:
    """Build every cafe's taste vector from its menus and reviews (idempotent, safe to rerun)."""

    def __init__(self, repo: TasteRepository, clock: ClockPort) -> None:
        self._repo = repo
        self._clock = clock

    async def run(self, only_new: bool = False) -> ComputeReport:
        """Recompute every cafe, or (`only_new`) just the cafes that have no vector yet.

        The incremental mode keeps the stored dataset statistics so existing cafes are untouched;
        it is what the nightly collection uses (older cafes no longer have their review text).
        """
        evidence = await self._repo.list_evidence(only_missing=only_new)
        raw = [raw_cafe_taste(e) for e in evidence]
        stored = await self._repo.load_axis_stats() if only_new else None
        stats = stored or compute_axis_stats([t.raw for t in raw])
        now = self._clock.now()
        items: list[tuple[str, TasteVector, float, float]] = []
        for taste in raw:
            vector, confidence = normalize_cafe_taste(taste.raw, stats, taste.evidence_weight)
            items.append((taste.place_id, vector, confidence, taste.evidence_weight))
        if stored is None:
            await self._repo.save_axis_stats(stats, now)
        await self._repo.save_cafe_tastes(items, now)
        tags = {t.place_id: t.review_tags for t in raw if t.review_tags}
        await self._repo.save_review_tags(tags)
        return ComputeReport(
            cafes=len(raw),
            cafes_with_reviews=len(tags),
            reviews_tagged=sum(len(v) for v in tags.values()),
            stats=stats,
        )


class SeedArchetypes:
    """Fill the vector DB with synthetic weather situations and the taste each one calls for."""

    def __init__(self, repo: ArchetypeRepository) -> None:
        self._repo = repo

    async def run(self) -> int:
        return await self._repo.upsert_archetypes(build_scenarios())


@dataclass(frozen=True, slots=True)
class WeatherTaste:
    conditions: WeatherConditions
    taste: TasteVector
    nearest: Archetype
    nearest_distance: float
    neighbors: tuple[tuple[Archetype, float], ...]


class FindWeatherTaste:
    """Weather observation -> wanted taste, by similarity search over the archetypes."""

    def __init__(self, repo: ArchetypeRepository, neighbors: int = 5) -> None:
        self._repo = repo
        self._k = neighbors

    async def run(self, observation: WeatherObservation) -> WeatherTaste:
        conditions = conditions_from(observation)
        found = await self._repo.nearest_archetypes(feature_vector(conditions), self._k)
        if not found:
            raise NotReadyError("no archetypes stored; run `seed-archetypes` first")
        # The rule engine's answer for the exact conditions is blended with its neighbors, so
        # the result is smooth and still anchored in the stored (and tunable) archetypes.
        blended = blend_neighbors([(a.taste_vec, d) for a, d in found])
        exact = taste_from_conditions(conditions)
        taste = tuple(0.7 * b + 0.3 * e for b, e in zip(blended, exact, strict=True))
        nearest, distance = found[0]
        return WeatherTaste(conditions, taste, nearest, distance, tuple(found))
