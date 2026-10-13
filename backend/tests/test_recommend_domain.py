from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.domain.models import BusinessInfo, BusinessStatus, DayHours, GeoPoint
from app.domain.recommend import (
    Candidate,
    OpenState,
    ScoredCafe,
    brand_key,
    nearness_score,
    open_by_hours,
    open_state,
    quality_score,
    score_candidates,
    select_more,
    select_top,
)
from app.domain.taste import MenuEvidence, compute_axis_stats, menu_family, vec

KST = timezone(timedelta(hours=9))
ORIGIN = GeoPoint(37.5006, 127.0364)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """2026-10-{day} in KST (2026-10-09 is a Friday)."""
    return datetime(2026, 10, day, hour, minute, tzinfo=KST)


WEEK = (
    DayHours("금(10/9)", "11:00", "01:00"),  # overnight
    DayHours("토", "09:00", "18:00"),
    DayHours("일", None, None, "정기휴무"),
    DayHours("월", "09:00", "18:00"),
)


def test_open_by_hours_normal_overnight_and_closed_days() -> None:
    assert open_by_hours(WEEK, at(9, 12)) == OpenState(True, "영업 중", "01:00")
    assert open_by_hours(WEEK, at(9, 23, 30)) == OpenState(True, "영업 중", "01:00")
    after_midnight = open_by_hours(WEEK, at(10, 0, 30))  # Saturday 00:30, Friday's shift
    assert after_midnight is not None and after_midnight.is_open
    before = open_by_hours(WEEK, at(10, 8))
    assert before == OpenState(False, "영업 전", "09:00")
    after_close = open_by_hours(WEEK, at(10, 19))
    assert after_close is not None and not after_close.is_open and after_close.changes_tomorrow
    sunday = open_by_hours(WEEK, at(11, 12))
    assert sunday is not None and sunday.is_open is False
    assert open_by_hours((), at(9, 12)) is None


def test_fresh_crawl_status_beats_the_weekly_table() -> None:
    closed_now = BusinessInfo(BusinessStatus.CLOSED, "영업 종료", WEEK)
    fresh = open_state(closed_now, at(9, 11, 30), at(9, 12))
    assert fresh.is_open is False  # crawled 30 minutes ago: believe the crawl (break time etc.)
    stale = open_state(closed_now, at(9, 3), at(9, 12))
    assert stale.is_open is True  # crawled long ago: derive from the hours table
    unknown = open_state(BusinessInfo(BusinessStatus.UNKNOWN, None), None, at(9, 12))
    assert unknown.is_open is None


def test_quality_and_nearness_scores() -> None:
    assert quality_score(4.9, 1000) > quality_score(4.9, 3)  # few reviews are pulled to the prior
    assert quality_score(3.5, 1000) < quality_score(4.8, 1000)
    assert 0 <= quality_score(None, 0) <= 1
    assert nearness_score(0, 1000) == 1 > nearness_score(800, 1000) > nearness_score(2000, 1000)


def _candidate(
    name: str,
    taste: tuple[float, ...],
    dlat: float = 0.0,
    open_: bool = True,
    menus: tuple[str, ...] = ("아이스 아메리카노",),
) -> Candidate:
    status = BusinessStatus.OPEN if open_ else BusinessStatus.CLOSED
    return Candidate(
        place_id=name,
        name=name,
        point=GeoPoint(ORIGIN.lat + dlat, ORIGIN.lng),
        road_address=None,
        rating=4.6,
        review_count=100,
        taste=taste,
        confidence=1.0,
        menus=tuple(MenuEvidence(m) for m in menus),
        business=BusinessInfo(status, None),
        status_checked_at=at(9, 12),
        review_axis_counts={},
        review_total=0,
        cover_photo_url=None,
        photo_urls=(),
    )


def test_scoring_orders_by_taste_and_skips_far_or_menuless_cafes() -> None:
    stats = compute_axis_stats([vec(sweet=0.2, sour_fresh=0.2), vec(sweet=0.6, sour_fresh=0.1)])
    wanted = vec(hot=0.1, iced=0.9, sour_fresh=0.9, light=0.7)
    fruity = _candidate(
        "과일", vec(hot=0.2, iced=0.8, sour_fresh=0.9, light=0.6), menus=("자몽에이드",)
    )
    creamy = _candidate("크림", vec(hot=0.8, iced=0.1, rich_creamy=0.9, sweet=0.8), menus=("라떼",))
    far = _candidate("먼곳", vec(sour_fresh=0.9), dlat=0.05, menus=("자몽에이드",))
    no_menu = _candidate("메뉴없음", vec(sour_fresh=0.9), menus=("[패스오더전용] 100원 커피",))
    scored = score_candidates(
        [creamy, fruity, far, no_menu], wanted, stats, ORIGIN, 1000, at(9, 12)
    )
    assert [s.candidate.name for s in scored] == ["과일", "크림"]


def _scored(name: str, score: float, open_: bool | None) -> ScoredCafe:
    return ScoredCafe(
        _candidate(name, vec(sweet=0.5)),
        score,
        0.5,
        0.5,
        0.5,
        0.5,
        MenuEvidence("메뉴"),
        OpenState(open_, "x"),
        100.0,
    )


def test_brand_key_groups_chain_branches() -> None:
    assert brand_key("투썸플레이스 논현역사거리점") == brand_key("투썸플레이스 역삼점")
    assert brand_key("블리스라운드 역삼점") != brand_key("트리오드")


def test_select_top_requires_two_open_and_keeps_score_order() -> None:
    ranked = [
        _scored("a", 0.9, False),
        _scored("b", 0.8, False),
        _scored("c", 0.7, True),
        _scored("d", 0.6, True),
        _scored("e", 0.5, True),
    ]
    top = select_top(ranked, count=3, min_open=2)
    assert [s.candidate.name for s in top] == ["a", "c", "d"]  # b (lowest closed) replaced by d
    assert sum(1 for s in top if s.open_state.is_open) == 2
    assert [s.score for s in top] == sorted((s.score for s in top), reverse=True)


def test_select_top_gives_what_it_has_when_nothing_is_open() -> None:
    ranked = [_scored(n, 1 - i / 10, False) for i, n in enumerate("abcd")]
    assert [s.candidate.name for s in select_top(ranked)] == ["a", "b", "c"]


def test_select_top_limits_one_cafe_per_brand() -> None:
    ranked = [
        replace(_scored("x1", 0.9, True), candidate=_candidate("투썸플레이스 A점", vec())),
        replace(_scored("x2", 0.8, True), candidate=_candidate("투썸플레이스 B점", vec())),
        _scored("other", 0.7, True),
    ]
    names = [s.candidate.name for s in select_top(ranked)]
    assert names == ["투썸플레이스 A점", "other"]


def _with_name(name: str, score: float, open_: bool | None = True) -> ScoredCafe:
    return replace(_scored(name, score, open_), candidate=_candidate(name, vec(sweet=0.5)))


def test_select_more_continues_after_the_podium_without_its_brands() -> None:
    ranked = [
        _with_name("투썸플레이스 A점", 0.9),
        _with_name("b", 0.85),
        _with_name("c", 0.8),
        _with_name("투썸플레이스 B점", 0.75),  # same chain as the podium's first pick
        _with_name("d", 0.7),
        _with_name("e", 0.6),
    ]
    podium = select_top(ranked, count=3, min_open=0)
    more = select_more(ranked, podium, count=10)
    assert [s.candidate.name for s in podium] == ["투썸플레이스 A점", "b", "c"]
    assert [s.candidate.name for s in more] == ["d", "e"]  # no second 투썸플레이스, no repeats


def test_select_more_is_capped_and_sorted_by_score() -> None:
    ranked = [_with_name(f"cafe{i}", 1 - i / 100) for i in range(30)]
    podium = select_top(ranked, count=3, min_open=0)
    more = select_more(ranked, podium, count=10)
    assert len(more) == 10
    assert [s.score for s in more] == sorted((s.score for s in more), reverse=True)
    assert not {s.candidate.place_id for s in more} & {s.candidate.place_id for s in podium}


def test_select_more_can_favour_open_cafes() -> None:
    ranked = [_with_name(f"closed{i}", 0.9 - i / 100, False) for i in range(6)]
    ranked += [_with_name(f"open{i}", 0.5 - i / 100, True) for i in range(4)]
    podium = select_top(ranked, count=3, min_open=0)
    plain = select_more(ranked, podium, count=3, min_open=0)
    wanted = select_more(ranked, podium, count=3, min_open=2)
    assert sum(1 for s in plain if s.open_state.is_open) == 0  # by score alone: all closed
    assert sum(1 for s in wanted if s.open_state.is_open) == 2  # two open ones pulled in


def test_day_labels_cover_daily_weekday_weekend_and_ranges() -> None:
    from app.domain.recommend import weekdays_in

    assert weekdays_in("매일") == set(range(7))
    assert weekdays_in("평일") == {0, 1, 2, 3, 4}
    assert weekdays_in("주말") == {5, 6}
    assert weekdays_in("월~금") == {0, 1, 2, 3, 4}
    assert weekdays_in("토,일") == {5, 6}
    assert weekdays_in("금(10/9)") == {4}
    assert weekdays_in("???") == set()


def test_daily_hours_and_date_specific_entries() -> None:
    daily = (DayHours("매일", "07:00", "23:00"),)
    assert open_by_hours(daily, at(10, 8, 30)) == OpenState(True, "영업 중", "23:00")
    holiday = (DayHours("금(10/9)", "09:00", "18:30"), DayHours("매일", "07:00", "23:00"))
    # the date-specific entry (holiday hours) wins over the generic one for that day
    friday_evening = open_by_hours(holiday, at(9, 20))
    assert friday_evening is not None and friday_evening.is_open is False
    saturday = open_by_hours(holiday, at(10, 20))
    assert saturday is not None and saturday.is_open is True


def test_cafes_without_any_drink_rank_below_equal_cafes_with_drinks() -> None:
    stats = compute_axis_stats([vec(sweet=0.2, sour_fresh=0.2), vec(sweet=0.6, sour_fresh=0.1)])
    wanted = vec(hot=0.1, iced=0.9, sour_fresh=0.9, light=0.7)
    taste = vec(hot=0.2, iced=0.8, sour_fresh=0.9, light=0.6)
    with_drink = _candidate("음료카페", taste, menus=("자몽에이드",))
    bakery = _candidate("빵집", taste, menus=("레몬 스콘",))  # same taste profile, pastry only
    scored = score_candidates([bakery, with_drink], wanted, stats, ORIGIN, 1000, at(9, 12))
    assert [s.candidate.name for s in scored] == ["음료카페", "빵집"]
    assert scored[1].score < scored[0].score * 0.9


def test_drink_share_and_its_effect_on_ranking() -> None:
    from app.domain.recommend import drink_share

    assert drink_share(()) == 0.5
    assert drink_share((("라떼", 300), ("커피", 100), ("소금빵", 100))) == 0.8
    assert drink_share((("소금빵", 200), ("케이크", 100))) == 0

    stats = compute_axis_stats([vec(sweet=0.2, sour_fresh=0.2), vec(sweet=0.6, sour_fresh=0.1)])
    wanted = vec(hot=0.1, iced=0.9, sour_fresh=0.9, light=0.7)
    taste = vec(hot=0.2, iced=0.8, sour_fresh=0.9, light=0.6)
    coffee_shop = replace(
        _candidate("커피집", taste, menus=("자몽에이드",)), menu_mentions=(("커피", 500),)
    )
    bakery = replace(
        _candidate("빵집", taste, menus=("자몽에이드",)), menu_mentions=(("소금빵", 500),)
    )
    scored = score_candidates([bakery, coffee_shop], wanted, stats, ORIGIN, 1000, at(9, 12))
    assert [s.candidate.name for s in scored] == ["커피집", "빵집"]


def test_podium_avoids_three_of_the_same_drink_when_scores_are_close() -> None:
    def item(name: str, menu: str, score: float) -> ScoredCafe:
        base = _scored(name, score, True)
        return replace(base, menu=MenuEvidence(menu))

    ranked = [
        item("가", "아이스 아메리카노", 0.80),
        item("나", "핫 아메리카노", 0.79),
        item("다", "카페 아메리카노", 0.78),
        item("라", "자몽에이드", 0.76),  # a different family, slightly lower
        item("마", "바닐라라떼", 0.72),  # far enough behind to stay out
    ]
    top = select_top(ranked)
    assert [s.candidate.name for s in top] == ["가", "나", "라"] or "라" in [
        s.candidate.name for s in top
    ]
    assert len({menu_family(s.menu.name) for s in top if s.menu}) >= 2
    far = select_top(
        [
            item("가", "아메리카노 A", 0.9),
            item("나", "아메리카노 B", 0.89),
            item("다", "아메리카노 C", 0.88),
            item("라", "자몽에이드", 0.6),
        ]
    )
    assert "라" not in [s.candidate.name for s in far]  # a big score gap still wins over variety


WEEKDAY_HOURS = (
    *(DayHours(d, "09:00", "22:00") for d in "월화수목금"),
    DayHours("토", "10:00", "18:00"),
    DayHours("일", None, None, "정기휴무 (매주 일요일)"),
)


def test_hours_today_formats_normal_overnight_and_closed_days() -> None:
    from datetime import date

    from app.domain.recommend import hours_today

    assert hours_today(WEEKDAY_HOURS, date(2026, 10, 9)) == "09:00 ~ 22:00"
    assert hours_today(WEEKDAY_HOURS, date(2026, 10, 11)) == "정기휴무"
    assert (
        hours_today((DayHours("금", "11:00", "01:00"),), date(2026, 10, 9)) == "11:00 ~ 익일 01:00"
    )
    assert hours_today((DayHours("토", None, None),), date(2026, 10, 10)) == "휴무"
    assert hours_today((), date(2026, 10, 9)) is None
    assert hours_today((DayHours("매일", "00:00", "24:00"),), date(2026, 10, 9)) == "24시간 영업"
    assert hours_today((DayHours("매일", "00:00", "00:00"),), date(2026, 10, 9)) == "24시간 영업"
    split = (DayHours("금", "11:00", "15:00"), DayHours("금", "17:00", "22:00"))
    assert hours_today(split, date(2026, 10, 9)) == "11:00 ~ 15:00, 17:00 ~ 22:00"


def test_weekly_hours_merges_days_and_marks_today() -> None:
    from datetime import date

    from app.domain.recommend import HoursRow, weekly_hours

    rows = weekly_hours(WEEKDAY_HOURS, date(2026, 10, 10))  # a Saturday
    assert rows == [
        HoursRow("월~금", "09:00 ~ 22:00", False),
        HoursRow("토", "10:00 ~ 18:00", True),
        HoursRow("일", "정기휴무", False),
    ]
    assert weekly_hours((DayHours("매일", "07:00", "23:00"),), date(2026, 10, 9)) == [
        HoursRow("매일", "07:00 ~ 23:00", True)
    ]
    assert weekly_hours((), date(2026, 10, 9)) == []


def test_date_specific_rows_apply_to_their_own_date_only() -> None:
    from datetime import date

    from app.domain.recommend import hours_today, weekly_hours

    holiday = (DayHours("금(10/9)", "09:00", "18:30", "한글날"), DayHours("매일", "07:00", "23:00"))
    assert hours_today(holiday, date(2026, 10, 9)) == "09:00 ~ 18:30 (한글날)"
    assert (
        hours_today(holiday, date(2026, 10, 10)) == "07:00 ~ 23:00"
    )  # the holiday row is not reused
    rows = weekly_hours(holiday, date(2026, 10, 9))
    assert [(r.days, r.text, r.is_today) for r in rows] == [
        ("월~목", "07:00 ~ 23:00", False),
        ("금", "09:00 ~ 18:30 (한글날)", True),
        ("토·일", "07:00 ~ 23:00", False),
    ]
    # a cafe that lists only the next seven dates: each date gets its own row
    dated = tuple(
        DayHours(f"{d}({10}/{n})", "10:00", "20:00" if d != "일" else "18:00")
        for d, n in zip("토일월화수목금", range(10, 17), strict=True)
    )
    assert hours_today(dated, date(2026, 10, 11)) == "10:00 ~ 18:00"
    assert hours_today(dated, date(2026, 10, 16)) == "10:00 ~ 20:00"
    # stale data (a week later) still answers with the same weekday's row instead of nothing
    assert (
        hours_today((DayHours("금(10/9)", "09:00", "18:00"),), date(2026, 10, 16))
        == "09:00 ~ 18:00"
    )


def test_open_state_uses_the_date_specific_row_on_a_holiday() -> None:
    holiday = (DayHours("금(10/9)", "09:00", "18:30", "한글날"), DayHours("매일", "07:00", "23:00"))
    evening = open_by_hours(holiday, at(9, 20))  # closed early on the holiday
    assert evening is not None and evening.is_open is False
    normal_day = open_by_hours(holiday, at(10, 20))  # Saturday: normal hours
    assert normal_day is not None and normal_day.is_open is True


def test_cafes_closed_for_the_whole_week_are_not_recommended() -> None:
    from app.domain.recommend import closed_all_week

    shut = (DayHours("토(10/10)", None, None, "휴무"), DayHours("일(10/11)", None, None, "휴무"))
    assert closed_all_week(shut)
    assert not closed_all_week((*shut, DayHours("월(10/12)", "10:00", "20:00")))
    assert not closed_all_week(())  # no hours on file is "unknown", not "closed"

    stats = compute_axis_stats([vec(sweet=0.2, sour_fresh=0.2), vec(sweet=0.6, sour_fresh=0.1)])
    wanted = vec(hot=0.1, iced=0.9, sour_fresh=0.9, light=0.7)
    taste = vec(hot=0.2, iced=0.8, sour_fresh=0.9, light=0.6)
    open_cafe = _candidate("영업카페", taste, menus=("자몽에이드",))
    closed_cafe = replace(
        _candidate("문닫은카페", taste, menus=("자몽에이드",)),
        business=BusinessInfo(BusinessStatus.CLOSED, "오늘 휴무", shut),
    )
    scored = score_candidates([closed_cafe, open_cafe], wanted, stats, ORIGIN, 1000, at(10, 12))
    assert [s.candidate.name for s in scored] == ["영업카페"]
