from dataclasses import replace
from datetime import date

from app.domain.messages import (
    has_batchim,
    is_valid_message,
    josa,
    recommendation_message,
    serve_hint,
    summary_message,
    taste_phrase,
    weather_phrase,
)
from app.domain.models import BusinessInfo, BusinessStatus, GeoPoint
from app.domain.recommend import Candidate, OpenState, ScoredCafe
from app.domain.taste import MenuEvidence, vec
from app.domain.weather import WeatherConditions

DAY = date(2026, 10, 9)


def test_batchim_and_particles() -> None:
    assert has_batchim("라떼") is False and has_batchim("커피") is False
    assert has_batchim("딸기") is False and has_batchim("에이드") is False
    assert has_batchim("쿠키") is False and has_batchim("크림치즈") is False
    assert has_batchim("흑임자라떼") is False and has_batchim("밀크티") is False
    assert has_batchim("케이크") is False and has_batchim("망고빙수") is False
    assert has_batchim("딸기스무디") is False and has_batchim("달고나라떼") is False
    assert has_batchim("아메리카노") is False and has_batchim("자몽에이드") is False
    assert has_batchim("바닐라빈") is True and has_batchim("크로플") is True
    assert josa("아메리카노", "을/를") == "아메리카노를"
    assert josa("바닐라빈", "을/를") == "바닐라빈을"
    assert josa("크로플", "이/가") == "크로플이"
    assert josa("라떼", "은/는") == "라떼는"
    assert josa("서울", "으로/로") == "서울로"  # ㄹ batchim takes 로
    assert josa("집", "으로/로") == "집으로"
    assert josa("커피", "과/와") == "커피와"
    assert josa("아이스 아메리카노(L)", "을/를") == "아이스 아메리카노(L)을"  # 'L' reads 엘
    assert josa("메뉴 3", "이/가") == "메뉴 3이"  # 삼


def test_weather_phrases_cover_every_band_and_are_deterministic() -> None:
    for feels in (-10, 0, 5, 12, 20, 25, 30, 38):
        c = WeatherConditions(float(feels), 0.5, False, 0.5, 14)
        assert weather_phrase(c, DAY) == weather_phrase(c, DAY)
        assert is_valid_message(weather_phrase(c, DAY))
    rainy = WeatherConditions(8.0, 0.9, True, 0.1, 19)
    assert "비" in weather_phrase(rainy, DAY)


def test_taste_phrase_reads_naturally() -> None:
    hot_day = vec(hot=0.1, iced=0.9, sour_fresh=0.9, light=0.75, sweet=0.3)
    assert taste_phrase(hot_day) == "시원하고 상큼하고 산뜻한"
    cold_day = vec(hot=0.9, iced=0.1, sweet=0.7, rich_creamy=0.4)
    assert taste_phrase(cold_day) == "따뜻하고 달콤한"
    mild = vec(hot=0.45, iced=0.45, nutty_cozy=0.7, sweet=0.3)
    assert taste_phrase(mild) == "고소한"


def test_serve_hint_only_when_menu_has_no_temperature() -> None:
    cold = vec(hot=0.9, iced=0.1)
    hot = vec(hot=0.1, iced=0.9)
    assert serve_hint(cold, "카페라떼") == "따뜻하게"
    assert serve_hint(hot, "카페라떼") == "시원하게"
    assert serve_hint(hot, "아이스 아메리카노") == ""
    assert serve_hint(vec(hot=0.4, iced=0.4), "카페라떼") == ""


def _scored(open_state: OpenState, counts: dict[str, int], total: int, menu: str) -> ScoredCafe:
    cand = Candidate(
        "1",
        "레자미오네뜨",
        GeoPoint(37.5, 127.0),
        None,
        4.7,
        300,
        vec(sweet=0.8),
        1.0,
        (MenuEvidence(menu),),
        BusinessInfo(BusinessStatus.OPEN, None),
        None,
        counts,
        total,
        None,
        (),
    )
    return ScoredCafe(cand, 0.8, 0.8, 0.8, 0.8, 0.8, MenuEvidence(menu), open_state, 280.0)


def test_messages_are_complete_polite_and_valid_for_every_rank() -> None:
    wanted = vec(hot=0.1, iced=0.9, sour_fresh=0.9, light=0.75)
    open_item = _scored(OpenState(True, "영업 중", "22:00"), {"sour_fresh": 4}, 10, "자몽에이드")
    for rank in (1, 2, 3):
        rec = recommendation_message(rank, open_item, wanted, DAY)
        assert is_valid_message(rec.message), rec.message
        assert rec.message == f"{rec.headline} {rec.status_line}" and "도보" not in rec.headline
        assert "레자미오네뜨" in rec.message and "자몽에이드" in rec.message
        assert "10건 중 4건" in rec.reason and "상큼한 맛이" in rec.reason
        assert (
            "도보 약 4분" in rec.status_line
            and "영업 중" in rec.status_line
            and "22:00까지" in rec.status_line
        )


def test_closed_cafe_message_mentions_opening_time() -> None:
    wanted = vec(hot=0.9, iced=0.1, sweet=0.7, rich_creamy=0.6)
    closed = _scored(OpenState(False, "영업 종료", "09:00", True), {}, 10, "카페라떼")
    rec = recommendation_message(2, closed, wanted, DAY)
    assert "문을 닫았어요" in rec.status_line and "내일 09:00에 열어요" in rec.status_line
    assert "따뜻하게" in rec.message  # neutral menu gets a serving hint from the weather
    assert rec.reason.endswith(
        "맛이라 오늘 날씨에 잘 어울려요."
    )  # no review evidence -> menu-based
    assert "카페라떼" not in rec.reason  # the menu name is not repeated


def test_summary_message_and_validation_guards() -> None:
    c = WeatherConditions(33.0, 0.75, False, 0.8, 14)
    text = summary_message(c, vec(hot=0.1, iced=0.9, sour_fresh=0.9, light=0.75), DAY)
    assert text.endswith("어울려요.") and "시원하고 상큼하고 산뜻한 맛이" in text
    assert not is_valid_message("안녕하세요 {cafe}")
    assert not is_valid_message("비가 오면 우울해요")
    assert not is_valid_message("가" * 300)
    assert not is_valid_message("☕☕☕☕ 너무 많아요")


def test_emoji_matches_the_kind_of_menu() -> None:
    wanted = vec(hot=0.1, iced=0.9, sour_fresh=0.9)
    drinks: list[str] = []
    pastries: list[str] = []
    for place in range(1, 25):  # place ids/ranks select different opener variants
        for rank in (1, 2, 3):
            for menu, bucket in (("자몽에이드", drinks), ("딸기 크로플", pastries)):
                item = _scored(OpenState(True, "영업 중", "22:00"), {}, 10, menu)
                item = replace(item, candidate=replace(item.candidate, place_id=str(place)))
                bucket.append(recommendation_message(rank, item, wanted, DAY).headline)
    assert not any("🍰" in h for h in drinks) and not any("☕" in h for h in pastries)
    assert any("☕" in h for h in drinks) and any("🍰" in h for h in pastries)


def _item(
    menu: str, counts: dict[str, int], total: int, mentions: tuple[tuple[str, int], ...] = ()
) -> ScoredCafe:
    base = _scored(OpenState(True, "영업 중", "22:00"), counts, total, menu)
    return replace(base, candidate=replace(base.candidate, menu_mentions=mentions))


def test_reason_prefers_real_popularity_over_everything_else() -> None:
    wanted = vec(hot=0.1, iced=0.9, sour_fresh=0.9)
    item = _item(
        "시그니처 라떼", {"sour_fresh": 6}, 10, (("라떼", 392), ("커피", 100), ("쿠키", 5))
    )
    assert (
        recommendation_message(1, item, wanted, DAY).reason
        == "리뷰에서 라떼가 392번 언급된 인기 메뉴예요."
    )
    few = _item("시그니처 라떼", {}, 10, (("라떼", 12),))  # too few mentions to call it popular
    assert "언급된 인기" not in recommendation_message(1, few, wanted, DAY).reason


def test_review_evidence_must_be_strong_and_about_the_menu() -> None:
    wanted = vec(hot=0.1, iced=0.9, sour_fresh=0.9, aroma=0.7)
    good = _item("자몽에이드", {"sour_fresh": 4}, 10)
    assert (
        recommendation_message(1, good, wanted, DAY).reason
        == "리뷰 10건 중 4건에서 상큼한 맛이 언급돼요."
    )
    thin = _item("자몽에이드", {"sour_fresh": 2}, 10)  # 2 of 10 is not evidence
    assert "10건 중" not in recommendation_message(1, thin, wanted, DAY).reason
    few_reviews = _item("자몽에이드", {"sour_fresh": 3}, 4)
    assert "건 중" not in recommendation_message(1, few_reviews, wanted, DAY).reason
    off_topic = _item(
        "아메리카노", {"sour_fresh": 6}, 10
    )  # sour reviews do not back a plain americano
    assert "건 중" not in recommendation_message(1, off_topic, wanted, DAY).reason


def test_reason_falls_back_to_flavor_then_temperature() -> None:
    cold_day = vec(hot=0.9, iced=0.1)
    plain = _item("카페라떼", {}, 0)  # no flavor wish at all, only a temperature
    assert (
        recommendation_message(1, plain, cold_day, DAY).reason
        == "오늘 같은 날씨엔 따뜻하게 즐기기 좋은 메뉴예요."
    )
    hot_day = vec(hot=0.1, iced=0.9)
    assert recommendation_message(1, _item("카페라떼", {}, 0), hot_day, DAY).reason == (
        "오늘 같은 날씨엔 시원하게 즐기기 좋은 메뉴예요."
    )
    iced_on_cold = _item("아이스 아메리카노", {}, 0)  # an iced drink must not be sold as warming
    assert "따뜻하게" not in recommendation_message(1, iced_on_cold, cold_day, DAY).reason
