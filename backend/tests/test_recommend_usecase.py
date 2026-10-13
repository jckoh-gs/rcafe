from datetime import datetime

import pytest

from app.application.recommend import NotReadyError, RecommendCafes, WeatherUnavailableError
from app.application.taste import FindWeatherTaste
from app.domain.models import GeoPoint
from app.domain.recommend import Candidate
from tests.fakes import (
    CREAMY,
    FRUITY,
    NOW,
    ROAST,
    YEOKSAM,
    FakeArchetypes,
    FakeCandidates,
    FakeTastes,
    FakeWeather,
    FixedClock,
    build_use_case,
    candidate,
)


def _field() -> list[Candidate]:
    return [
        candidate("1", "과일창고", FRUITY, ("자몽에이드", "레몬티"), 150),
        candidate("2", "크림하우스", CREAMY, ("바닐라라떼", "카페라떼"), 200),
        candidate("3", "로스터리원", ROAST, ("에스프레소", "아메리카노"), 250),
        candidate("4", "에이드랩", FRUITY, ("딸기에이드", "아이스티"), 300),
    ]


async def test_hot_day_recommends_refreshing_cafes_first_with_complete_texts() -> None:
    use_case, _ = build_use_case(_field())
    result = await use_case.run(YEOKSAM, 1000)
    assert len(result.items) == 3
    assert [i.rank for i in result.items] == [1, 2, 3]
    names = [i.scored.candidate.name for i in result.items]
    assert names[0] in {"과일창고", "에이드랩"} and "크림하우스" not in names[:1]
    assert result.summary.endswith("어울려요.") and "시원하고" in result.summary
    first = result.items[0]
    assert first.scored.menu is not None and first.scored.menu.name in {
        "자몽에이드",
        "레몬티",
        "딸기에이드",
        "아이스티",
    }
    assert first.text.message.count("{") == 0 and first.scored.candidate.name in first.text.message
    assert result.notices == ()


def _crowd(n: int, **kwargs: object) -> list[Candidate]:
    return [
        candidate(str(i), f"카페{i}", FRUITY, ("자몽에이드",), 100 + i * 10, **kwargs)  # type: ignore[arg-type]
        for i in range(1, n + 1)
    ]


async def test_ten_more_cafes_follow_the_podium_with_their_own_texts() -> None:
    use_case, _ = build_use_case(_crowd(20))
    result = await use_case.run(YEOKSAM, 1000)
    assert len(result.items) == 3 and len(result.more_items) == 10
    assert [i.rank for i in result.more_items] == list(range(4, 14))
    ids = [i.scored.candidate.place_id for i in (*result.items, *result.more_items)]
    assert len(set(ids)) == 13  # nobody twice
    for entry in result.more_items:
        assert entry.text.message.count("{") == 0
        assert entry.scored.candidate.name in entry.text.message
        assert entry.text.headline and entry.text.status_line


async def test_the_extra_list_is_shorter_when_the_area_has_fewer_cafes() -> None:
    use_case, _ = build_use_case(_crowd(7))
    assert (len((await use_case.run(YEOKSAM, 1000)).more_items)) == 4
    use_case, _ = build_use_case(_crowd(3))
    assert (await use_case.run(YEOKSAM, 1000)).more_items == ()


async def test_more_cafes_do_not_repeat_a_chain_from_the_podium() -> None:
    chain = [
        candidate(str(i), f"스타벅스 {i}호점", FRUITY, ("자몽에이드",), 100 + i * 10)
        for i in range(1, 6)
    ]
    others = [
        candidate(str(20 + i), f"동네카페{i}", FRUITY, ("레몬에이드",), 300 + i * 10)
        for i in range(1, 6)
    ]
    use_case, _ = build_use_case(chain + others)
    result = await use_case.run(YEOKSAM, 1000)
    chains = [
        i
        for i in (*result.items, *result.more_items)
        if i.scored.candidate.name.startswith("스타벅스")
    ]
    assert len(chains) == 1  # one branch of the chain in all 13 places, not five


async def test_the_extra_list_leans_on_cafes_that_are_open_now() -> None:
    # twelve cafes close by that have not opened yet, six open ones a bit farther away
    closed = _crowd(12, open_=False)
    open_ones = [
        candidate(str(50 + i), f"열린카페{i}", FRUITY, ("자몽에이드",), 900 + i * 10)
        for i in range(6)
    ]
    use_case, _ = build_use_case(closed + open_ones)
    result = await use_case.run(YEOKSAM, 1000)
    shown = (*result.items, *result.more_items)
    open_shown = sum(1 for i in shown if i.scored.open_state.is_open)
    assert open_shown == 6  # every open cafe made it onto the page, ahead of closed ones by score
    assert sum(1 for i in result.more_items if i.scored.open_state.is_open) >= 4


async def test_cold_day_flips_the_podium() -> None:
    from app.domain.weather import WeatherObservation

    cold = WeatherObservation("108", NOW, 2.0, 60.0, 3.0, 0.0, 8.0)
    use_case, _ = build_use_case(_field(), cold)
    result = await use_case.run(YEOKSAM, 1000)
    assert result.items[0].scored.candidate.name == "크림하우스"
    assert "따뜻하" in result.summary


async def test_radius_grows_until_two_cafes_are_open() -> None:
    far_open = [
        candidate("5", "먼카페A", FRUITY, ("자몽에이드",), 1500),
        candidate("6", "먼카페B", FRUITY, ("레몬에이드",), 1700),
    ]
    near_closed = [
        candidate("1", "닫힘A", FRUITY, ("자몽에이드",), 100, open_=False),
        candidate("2", "닫힘B", FRUITY, ("레몬에이드",), 150, open_=False),
        candidate("3", "닫힘C", FRUITY, ("딸기에이드",), 200, open_=False),
    ]
    use_case, source = build_use_case(near_closed + far_open)
    result = await use_case.run(YEOKSAM, 1000)
    assert source.radii == [1000.0, 2000.0]
    open_names = {i.scored.candidate.name for i in result.items if i.scored.open_state.is_open}
    assert open_names == {"먼카페A", "먼카페B"}
    assert any("2000m까지" in n for n in result.notices)


async def test_late_night_with_nothing_open_still_answers_with_a_notice() -> None:
    night = datetime(2026, 10, 9, 23, 30, tzinfo=NOW.tzinfo)
    closed = [
        candidate(str(i), f"카페{i}", FRUITY, ("자몽에이드",), 100 * i, open_=False)
        for i in range(1, 4)
    ]
    use_case, source = build_use_case(closed, now=night)
    result = await use_case.run(YEOKSAM, 1000)
    assert len(result.items) == 3 and source.radii[-1] == 5000.0
    assert any("영업 중인 카페가 많지 않아요" in n for n in result.notices)
    assert all("문을 닫았어요" in i.text.status_line for i in result.items)


async def test_empty_area_returns_no_items() -> None:
    use_case, _ = build_use_case([])
    result = await use_case.run(YEOKSAM, 1000)
    assert result.items == () and result.notices == ()


async def test_missing_weather_or_taste_data_are_distinct_errors() -> None:
    no_weather = RecommendCafes(
        FakeWeather(None),
        FindWeatherTaste(FakeArchetypes()),
        FakeCandidates([]),
        FakeTastes(None),
        FixedClock(),
    )
    with pytest.raises(WeatherUnavailableError):
        await no_weather.run(GeoPoint(35.18, 129.07))
    use_case, _ = build_use_case(_field(), stats=None)
    with pytest.raises(NotReadyError):
        await use_case.run(YEOKSAM)


async def test_utc_clock_gives_the_same_open_states_as_korean_time() -> None:
    from datetime import UTC

    # Friday 14:00 KST == Friday 05:00 UTC; Saturday 08:30 KST == Friday 23:30 UTC
    saturday_morning_kst = datetime(2026, 10, 10, 8, 30, tzinfo=NOW.tzinfo)
    field = [candidate("1", "아침카페", FRUITY, ("자몽에이드",), 100)]  # open every day 08:00-22:00
    for instant in (NOW, saturday_morning_kst):
        kst_case, _ = build_use_case(field, now=instant)
        utc_case, _ = build_use_case(field, now=instant.astimezone(UTC))
        kst = await kst_case.run(YEOKSAM, 1000)
        utc = await utc_case.run(YEOKSAM, 1000)
        assert [i.scored.open_state for i in kst.items] == [i.scored.open_state for i in utc.items]
        assert kst.items[0].scored.open_state.is_open is True
