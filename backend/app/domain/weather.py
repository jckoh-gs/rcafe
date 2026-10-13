"""Weather observation -> feature vector -> wanted taste.

The weather-to-taste rules are evidence-informed heuristics, not established facts (see
docs/evidence.md): the effects found in the literature are small and partly contradictory, so
every coefficient here is a tunable weight.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from app.domain.taste import TasteVector, clamp01, vec

FEATURE_DIM = 6
# Scaling applied to features so that L2 distance in the vector DB reflects importance.
FEATURE_WEIGHTS: tuple[float, ...] = (4.0, 0.8, 1.5, 0.8, 0.7, 0.7)
FEATURE_NAMES: tuple[str, ...] = (
    "feels_like",
    "humidity",
    "rain",
    "clarity",
    "hour_sin",
    "hour_cos",
)
RAIN_HUMIDITY_DEFAULT = 85.0


@dataclass(frozen=True, slots=True)
class WeatherObservation:
    station_id: str
    observed_at: datetime  # timezone-aware, local (KST)
    temp_c: float
    humidity_pct: float | None = None
    wind_ms: float | None = None
    rain_mm_h: float | None = None  # None: not observed
    cloud_tenths: float | None = None  # total cloud amount 0..10


def feels_like_c(temp_c: float, wind_ms: float | None, humidity_pct: float | None) -> float:
    """Wind chill when cold and windy, wet-bulb based summer formula when warm, else air temp."""
    wind_kmh = (wind_ms or 0.0) * 3.6
    if temp_c <= 10 and wind_kmh > 4.8:
        v = float(wind_kmh**0.16)
        return 13.12 + 0.6215 * temp_c - 11.37 * v + 0.3965 * temp_c * v
    if temp_c >= 20 and humidity_pct is not None and humidity_pct >= 10:
        # Summer formula based on the wet-bulb temperature (Stull), as used by KMA.
        rh = humidity_pct
        tw = (
            temp_c * math.atan(0.151977 * (rh + 8.313659) ** 0.5)
            + math.atan(temp_c + rh)
            - math.atan(rh - 1.676331)
            + 0.00391838 * rh**1.5 * math.atan(0.023101 * rh)
            - 4.686035
        )
        feel = (
            -0.2442
            + 0.55399 * tw
            + 0.45535 * temp_c
            - 0.0022 * tw * tw
            + 0.00278 * tw * temp_c
            + 3.0
        )
        return float(max(temp_c - 3.0, feel))
    return temp_c


def is_raining(rain_mm_h: float | None) -> bool:
    return rain_mm_h is not None and rain_mm_h > 0


def sky_clarity(cloud_tenths: float | None) -> float:
    """1 = clear sky, 0 = fully overcast; unknown -> 0.5."""
    if cloud_tenths is None or cloud_tenths < 0:
        return 0.5
    return clamp01(1 - cloud_tenths / 10)


@dataclass(frozen=True, slots=True)
class WeatherConditions:
    """Normalized inputs shared by observations and synthetic scenarios."""

    feels_like: float
    humidity: float  # 0..1
    raining: bool
    clarity: float  # 0..1
    hour: float  # 0..24 local


def conditions_from(obs: WeatherObservation) -> WeatherConditions:
    humidity = obs.humidity_pct if obs.humidity_pct is not None and obs.humidity_pct >= 0 else 60.0
    local = obs.observed_at
    return WeatherConditions(
        feels_like=feels_like_c(obs.temp_c, obs.wind_ms, obs.humidity_pct),
        humidity=clamp01(humidity / 100),
        raining=is_raining(obs.rain_mm_h),
        clarity=sky_clarity(obs.cloud_tenths),
        hour=local.hour + local.minute / 60,
    )


def feature_vector(c: WeatherConditions) -> tuple[float, ...]:
    angle = 2 * math.pi * c.hour / 24
    raw = (
        clamp01((c.feels_like + 15) / 50),
        c.humidity,
        1.0 if c.raining else 0.0,
        c.clarity,
        (math.sin(angle) + 1) / 2,
        (math.cos(angle) + 1) / 2,
    )
    return tuple(v * w for v, w in zip(raw, FEATURE_WEIGHTS, strict=True))


def taste_from_conditions(c: WeatherConditions) -> TasteVector:
    """Rule engine: which tastes fit these conditions (each coefficient is a tunable weight)."""
    hot_need = clamp01((c.feels_like - 22) / 10)  # 0 at <=22C, 1 at >=32C
    cold_need = clamp01((18 - c.feels_like) / 18)  # 0 at >=18C, 1 at <=0C
    rain = 1.0 if c.raining else 0.0
    cloudy = 1 - c.clarity
    morning = 1.0 if c.hour < 11 else 0.0
    caffeine = (
        0.25
        + 0.35 * math.exp(-(((c.hour - 8.5) / 2) ** 2))
        + 0.25 * math.exp(-(((c.hour - 14.5) / 1.5) ** 2))
        - (0.10 if c.hour >= 19 else 0.0)
    )

    def pref(value: float) -> float:
        return max(0.1, min(0.9, value))

    return vec(
        hot=pref(0.45 + 0.55 * cold_need - 0.45 * hot_need),
        iced=pref(0.45 + 0.55 * hot_need - 0.45 * cold_need),
        sweet=0.35 + 0.30 * cold_need + 0.15 * rain + 0.10 * cloudy - 0.10 * hot_need,
        sour_fresh=0.25 + 0.55 * hot_need + 0.10 * c.clarity - 0.10 * cold_need - 0.05 * rain,
        bitter_roast=0.40 + 0.15 * cold_need + 0.10 * morning - 0.10 * hot_need,
        rich_creamy=0.35 + 0.35 * cold_need + 0.15 * rain - 0.25 * hot_need,
        nutty_cozy=0.30 + 0.30 * cold_need + 0.30 * rain + 0.05 * cloudy - 0.10 * hot_need,
        aroma=0.30 + 0.20 * c.humidity + 0.15 * rain,
        light=0.30 + 0.45 * hot_need - 0.20 * cold_need - 0.05 * rain,
        caffeine_boost=caffeine,
    )


# --- scenario archetypes (seed data for the vector DB) ---------------------------------------


@dataclass(frozen=True, slots=True)
class Archetype:
    key: str
    name_ko: str
    feels_like: float
    raining: bool
    hour: int
    weather_vec: tuple[float, ...]
    taste_vec: TasteVector


def temperature_band(feels_like: float) -> str:
    for limit, name in (
        (-5, "한파"),
        (2, "추운"),
        (9, "쌀쌀한"),
        (16, "선선한"),
        (22, "포근한"),
        (27, "따뜻한"),
        (32, "무더운"),
    ):
        if feels_like <= limit:
            return name
    return "폭염"


def daypart(hour: float) -> str:
    if hour < 11:
        return "아침"
    if hour < 17:
        return "낮"
    if hour < 21:
        return "저녁"
    return "밤"


def describe(c: WeatherConditions) -> str:
    sky = "비 오는" if c.raining else ("맑은" if c.clarity >= 0.6 else "흐린")
    return f"{temperature_band(c.feels_like)} {sky} {daypart(c.hour)}"


def build_scenarios() -> list[Archetype]:
    """A grid of synthetic weather situations with the taste the rules want for each."""
    scenarios: list[Archetype] = []
    for feels in range(-12, 37, 3):
        for raining, humidity in ((False, 0.45), (False, 0.75), (True, 0.85)):
            for cloud_tenths in (2, 8):
                for hour in (8, 14, 20):
                    c = WeatherConditions(
                        feels_like=float(feels),
                        humidity=humidity,
                        raining=raining,
                        clarity=sky_clarity(cloud_tenths),
                        hour=float(hour),
                    )
                    key = (
                        f"fl{feels:+d}_{'rain' if raining else 'dry'}"
                        f"_h{int(humidity * 100)}_c{cloud_tenths}_t{hour}"
                    )
                    scenarios.append(
                        Archetype(
                            key=key,
                            name_ko=describe(c),
                            feels_like=float(feels),
                            raining=raining,
                            hour=hour,
                            weather_vec=feature_vector(c),
                            taste_vec=taste_from_conditions(c),
                        )
                    )
    return scenarios


def blend_neighbors(
    neighbors: list[tuple[TasteVector, float]], epsilon: float = 1e-3
) -> TasteVector:
    """Inverse-distance weighted mean of neighbor taste vectors."""
    if not neighbors:
        raise ValueError("no neighbors to blend")
    weights = [1.0 / (distance + epsilon) for _, distance in neighbors]
    total = sum(weights)
    dim = len(neighbors[0][0])
    return tuple(
        sum(w * vector[i] for (vector, _), w in zip(neighbors, weights, strict=True)) / total
        for i in range(dim)
    )
