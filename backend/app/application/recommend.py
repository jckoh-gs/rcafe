"""Use case: coordinates -> weather -> wanted taste -> TOP 3 cafes with messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from app.application.errors import NotReadyError, WeatherUnavailableError
from app.application.taste import FindWeatherTaste, WeatherTaste
from app.domain.messages import Recommendation, recommendation_message, summary_message
from app.domain.models import GeoPoint
from app.domain.ports import AxisStatsPort, CandidateSource, ClockPort, WeatherPort
from app.domain.recommend import ScoredCafe, score_candidates, select_more, select_top
from app.domain.taste import AxisStats

KST = timezone(timedelta(hours=9))
__all__ = [
    "NotReadyError",
    "RecommendCafes",
    "RecommendationResult",
    "RecommendedCafe",
    "WeatherUnavailableError",
]

MIN_OPEN = 2
MORE_COUNT = 10  # extra cafes behind the "show more" button
MORE_MIN_OPEN = 5  # of those, as many open ones as exist (up to this) are preferred at night
# Search radius grows until enough cafes are open (late-night safety net).
RADIUS_STEPS_M = (1000.0, 2000.0, 3000.0, 5000.0)


@dataclass(frozen=True, slots=True)
class RecommendedCafe:
    rank: int
    scored: ScoredCafe
    text: Recommendation


@dataclass(frozen=True, slots=True)
class RecommendationResult:
    origin: GeoPoint
    radius_m: float
    weather: WeatherTaste
    observed_at: datetime
    today: date  # Korean calendar date the opening hours refer to
    station_id: str
    summary: str
    items: tuple[RecommendedCafe, ...]
    notices: tuple[str, ...] = field(default_factory=tuple)
    more_items: tuple[RecommendedCafe, ...] = field(default_factory=tuple)  # ranks after the podium


class RecommendCafes:
    def __init__(
        self,
        weather: WeatherPort,
        taste_finder: FindWeatherTaste,
        candidates: CandidateSource,
        tastes: AxisStatsPort,
        clock: ClockPort,
    ) -> None:
        self._weather = weather
        self._finder = taste_finder
        self._candidates = candidates
        self._tastes = tastes
        self._clock = clock

    async def run(self, origin: GeoPoint, radius_m: float = 1000.0) -> RecommendationResult:
        # Opening hours and weekdays are Korean local time; the clock may be UTC.
        now = self._clock.now().astimezone(KST)
        observation = await self._weather.observation_at(origin, now)
        if observation is None:
            raise WeatherUnavailableError("no weather observation for this location")
        wanted = await self._finder.run(observation)
        stats = await self._tastes.load_axis_stats()
        if stats is None:
            raise NotReadyError("cafe tastes have not been computed")

        chosen: list[ScoredCafe] = []
        more: list[ScoredCafe] = []
        used_radius = radius_m
        notices: list[str] = []
        for step in sorted({radius_m, *(r for r in RADIUS_STEPS_M if r > radius_m)}):
            used_radius = step
            chosen, more = await self._pick(origin, step, wanted, stats, now)
            if sum(1 for s in chosen if s.open_state.is_open) >= MIN_OPEN:
                break
        open_count = sum(1 for s in chosen if s.open_state.is_open)
        if used_radius > radius_m and chosen:
            notices.append(
                f"주변 {int(radius_m)}m 안에 열린 곳이 적어 {int(used_radius)}m까지 찾았어요."
            )
        if chosen and open_count < MIN_OPEN:
            notices.append("지금은 영업 중인 카페가 많지 않아요. 문 여는 시간을 함께 알려드려요.")

        day = observation.observed_at.astimezone(KST).date()
        items = self._with_texts(chosen, 1, wanted, day)
        more_items = self._with_texts(more, len(chosen) + 1, wanted, day)
        return RecommendationResult(
            origin=origin,
            radius_m=used_radius,
            weather=wanted,
            observed_at=observation.observed_at,
            today=now.date(),
            station_id=observation.station_id,
            summary=summary_message(wanted.conditions, wanted.taste, day),
            items=items,
            notices=tuple(notices),
            more_items=more_items,
        )

    @staticmethod
    def _with_texts(
        cafes: list[ScoredCafe], first_rank: int, wanted: WeatherTaste, day: date
    ) -> tuple[RecommendedCafe, ...]:
        return tuple(
            RecommendedCafe(rank, s, recommendation_message(rank, s, wanted.taste, day))
            for rank, s in enumerate(cafes, start=first_rank)
        )

    async def _pick(
        self,
        origin: GeoPoint,
        radius_m: float,
        wanted: WeatherTaste,
        stats: AxisStats,
        now: datetime,
    ) -> tuple[list[ScoredCafe], list[ScoredCafe]]:
        """The podium and the extra list that follows it."""
        candidates = await self._candidates.candidates_near(origin, radius_m)
        scored = score_candidates(candidates, wanted.taste, stats, origin, radius_m, now)
        podium = select_top(scored, count=3, min_open=MIN_OPEN)
        return podium, select_more(scored, podium, MORE_COUNT, MORE_MIN_OPEN)
