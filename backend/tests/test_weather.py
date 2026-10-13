from datetime import datetime, timedelta, timezone

from app.domain.taste import AXES, vec
from app.domain.weather import (
    FEATURE_DIM,
    WeatherConditions,
    WeatherObservation,
    blend_neighbors,
    build_scenarios,
    conditions_from,
    describe,
    feature_vector,
    feels_like_c,
    taste_from_conditions,
)

KST = timezone(timedelta(hours=9))
IDX = {a: i for i, a in enumerate(AXES)}


def _cond(
    feels: float, rain: bool = False, clarity: float = 0.8, hour: float = 14
) -> WeatherConditions:
    return WeatherConditions(feels, 0.6, rain, clarity, hour)


def test_feels_like_wind_chill_and_summer_formula() -> None:
    assert feels_like_c(3, 4.0, 60) < 3 - 3
    assert feels_like_c(15, 1.0, 60) == 15
    summer = feels_like_c(33, 1.0, 75)
    assert 33 <= summer < 40  # humid heat feels hotter, but not absurdly so
    assert feels_like_c(33, None, None) == 33


def test_conditions_from_observation() -> None:
    obs = WeatherObservation(
        "108", datetime(2026, 10, 9, 14, 30, tzinfo=KST), 20.0, 70, 2.0, 1.5, 8
    )
    c = conditions_from(obs)
    assert c.raining and c.hour == 14.5 and abs(c.clarity - 0.2) < 1e-9
    dry = conditions_from(
        WeatherObservation("108", datetime(2026, 10, 9, 14, tzinfo=KST), 20.0, rain_mm_h=None)
    )
    assert not dry.raining and dry.clarity == 0.5


def test_hot_day_wants_cold_fresh_light() -> None:
    taste = taste_from_conditions(_cond(33))
    assert taste[IDX["iced"]] > taste[IDX["hot"]]
    assert taste[IDX["sour_fresh"]] > 0.6 and taste[IDX["light"]] > 0.5
    assert taste[IDX["rich_creamy"]] < 0.3


def test_cold_rainy_day_wants_warm_sweet_cozy() -> None:
    taste = taste_from_conditions(_cond(2, rain=True, clarity=0.1))
    dry_cold = taste_from_conditions(_cond(2))
    assert taste[IDX["hot"]] > taste[IDX["iced"]]
    assert taste[IDX["nutty_cozy"]] > dry_cold[IDX["nutty_cozy"]]
    assert taste[IDX["sweet"]] > 0.6 and taste[IDX["sour_fresh"]] < 0.3


def test_all_taste_values_stay_in_unit_range() -> None:
    for feels in (-15, 0, 10, 20, 30, 45):
        for rain in (True, False):
            for hour in (3, 9, 15, 22):
                assert all(
                    0 <= v <= 1 for v in taste_from_conditions(_cond(feels, rain, 0.5, hour))
                )


def test_feature_vector_shape_and_ordering() -> None:
    cold, hot = feature_vector(_cond(-5)), feature_vector(_cond(30))
    assert len(cold) == len(hot) == FEATURE_DIM
    assert hot[0] > cold[0]  # feels-like dominates the first dimension


def test_scenarios_are_unique_and_described() -> None:
    scenarios = build_scenarios()
    assert len(scenarios) == len({s.key for s in scenarios}) == 306
    assert all(
        len(s.weather_vec) == FEATURE_DIM and len(s.taste_vec) == len(AXES) for s in scenarios
    )
    assert describe(_cond(33)) == "폭염 맑은 낮"
    assert describe(_cond(14, rain=True, hour=19)) == "선선한 비 오는 저녁"


def test_blend_neighbors_weights_by_inverse_distance() -> None:
    near, far = vec(sweet=1.0), vec(sweet=0.0)
    blended = blend_neighbors([(near, 0.1), (far, 1.0)])
    assert blended[IDX["sweet"]] > 0.8
