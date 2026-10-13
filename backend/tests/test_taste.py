from app.domain.taste import (
    AXES,
    CafeEvidence,
    MenuEvidence,
    ReviewEvidence,
    best_menu_for,
    compute_axis_stats,
    is_beverage,
    is_orderable_menu,
    menu_family,
    menu_vector,
    normalize_cafe_taste,
    raw_cafe_taste,
    tag_text,
    taste_similarity,
    top_axes,
    vec,
)

IDX = {a: i for i, a in enumerate(AXES)}


def test_lexicon_counts_mentions_but_not_negated_ones() -> None:
    assert tag_text("달콤하고 고소해요")["sweet"] == 1
    assert tag_text("달콤하고 고소해요")["nutty_cozy"] == 1
    assert tag_text("전혀 달지 않아서 좋아요")["sweet"] == 0
    assert tag_text("안 달고 깔끔해요")["sweet"] == 0
    assert tag_text("단맛이 없어요")["sweet"] == 0


def test_lexicon_ignores_look_alike_words() -> None:
    assert tag_text("아이스크림이 맛있어요")["iced"] == 0
    assert tag_text("요즘 핫한 카페예요")["hot"] == 0
    assert tag_text("핫초코 한 잔")["hot"] == 1
    decaf = tag_text("디카페인 가능해요")
    assert decaf["caffeine_boost"] == 0 and decaf["light"] == 0  # a product detail, not a taste
    assert tag_text("개인적인 취향은 아니에요")["aroma"] == 0
    assert tag_text("밤늦게 가기 좋아요")["nutty_cozy"] == 0
    assert tag_text("밀크티가 향긋해요")["aroma"] >= 2


def test_menu_vector_temperature_and_flavor() -> None:
    iced = menu_vector("아이스 아메리카노")
    assert iced[IDX["iced"]] == 1.0 and iced[IDX["hot"]] == 0.0
    latte = menu_vector("카페라떼")
    assert latte[IDX["hot"]] == latte[IDX["iced"]] == 0.5  # temperature is the customer's choice
    assert latte[IDX["rich_creamy"]] > 0.5
    ade = menu_vector("자몽에이드")
    assert ade[IDX["sour_fresh"]] >= 0.9 and ade[IDX["iced"]] == 1.0
    both = menu_vector("바닐라라떼 (Hot/Ice)")
    assert both[IDX["hot"]] == both[IDX["iced"]] == 0.5


def test_promo_and_option_lines_are_not_menus() -> None:
    assert not is_orderable_menu("[패스오더전용] 100원 아메리카노")
    assert not is_orderable_menu("샷 추가")
    assert not is_orderable_menu("딸기 생크림 케익(2호)")
    assert is_orderable_menu("아이스 아메리카노")


def _evidence(place_id: str, menus: list[str], reviews: list[str]) -> CafeEvidence:
    return CafeEvidence(
        place_id,
        tuple(MenuEvidence(m) for m in menus),
        (),
        tuple(ReviewEvidence(f"r{i}", text, 5) for i, text in enumerate(reviews)),
    )


def test_cafe_vector_reflects_its_menu_and_reviews() -> None:
    fruity = raw_cafe_taste(
        _evidence("a", ["자몽에이드", "레몬티"], ["상큼하고 시원해서 좋았어요"])
    )
    roaster = raw_cafe_taste(
        _evidence("b", ["에스프레소", "아메리카노"], ["진한 로스팅 향이 좋아요"])
    )
    assert fruity.raw[IDX["sour_fresh"]] > roaster.raw[IDX["sour_fresh"]]
    assert roaster.raw[IDX["bitter_roast"]] > fruity.raw[IDX["bitter_roast"]]
    assert fruity.review_tags["r0"]["sour_fresh"] >= 1


def test_normalization_shrinks_thin_evidence_toward_the_mean() -> None:
    rows = [
        raw_cafe_taste(
            _evidence(str(i), ["자몽에이드"] if i % 2 else ["아메리카노"], ["좋아요 맛있어요"])
        ).raw
        for i in range(10)
    ]
    stats = compute_axis_stats(rows)
    strong, conf_strong = normalize_cafe_taste(rows[1], stats, evidence_weight=40)
    weak, conf_weak = normalize_cafe_taste(rows[1], stats, evidence_weight=0.5)
    assert conf_strong > conf_weak
    i = IDX["sour_fresh"]
    mean_n = stats.mean[i] / stats.scale[i]
    assert abs(weak[i] - mean_n) < abs(strong[i] - mean_n)


def test_similarity_prefers_matching_distinctive_traits() -> None:
    stats = compute_axis_stats([vec(sweet=0.2, sour_fresh=0.2), vec(sweet=0.6, sour_fresh=0.1)])
    wanted = vec(hot=0.1, iced=0.9, sour_fresh=0.9, light=0.7)
    fruity = vec(hot=0.2, iced=0.8, sour_fresh=0.9, light=0.6)
    creamy = vec(hot=0.8, iced=0.1, rich_creamy=0.9, sweet=0.8)
    assert taste_similarity(wanted, fruity, stats) > taste_similarity(wanted, creamy, stats)


def test_best_menu_respects_weather_temperature() -> None:
    stats = compute_axis_stats([vec(sweet=0.3)])
    menus = (MenuEvidence("아이스 바닐라라떼"), MenuEvidence("핫 헤이즐넛라떼"))
    cold_day = vec(hot=0.9, iced=0.1, sweet=0.7, nutty_cozy=0.7, rich_creamy=0.6)
    hot_day = vec(hot=0.1, iced=0.9, sweet=0.7, nutty_cozy=0.2, rich_creamy=0.6)
    best_cold = best_menu_for(cold_day, menus, stats)
    best_hot = best_menu_for(hot_day, menus, stats)
    assert best_cold is not None and best_cold[0].name == "핫 헤이즐넛라떼"
    assert best_hot is not None and best_hot[0].name == "아이스 바닐라라떼"


def test_top_axes_can_skip_temperature() -> None:
    v = vec(hot=0.9, sweet=0.8, rich_creamy=0.7)
    assert top_axes(v, 2) == ["hot", "sweet"]
    assert top_axes(v, 2, skip_temperature=True) == ["sweet", "rich_creamy"]


def test_beverage_detection_and_preference() -> None:
    assert is_beverage("아이스 아메리카노") and is_beverage("자몽에이드") and is_beverage("밀크티")
    assert (
        not is_beverage("말제르브바게트")
        and not is_beverage("티라미수")
        and not is_beverage("딸기 크로플")
    )
    stats = compute_axis_stats([vec(sweet=0.3)])
    wanted = vec(hot=0.5, iced=0.5, sweet=0.8)
    # two equally sweet picks: the drink wins over the pastry
    menus = (MenuEvidence("초코 쿠키"), MenuEvidence("바닐라라떼"))
    best = best_menu_for(wanted, menus, stats)
    assert best is not None and best[0].name == "바닐라라떼"


def test_beverage_detection_is_not_fooled_by_look_alike_syllables() -> None:
    for drink in (
        "유자차",
        "매실청차",
        "오미자차",
        "얼그레이티라떼",
        "제로 자몽허니아이스티",
        "티",
    ):
        assert is_beverage(drink), drink
    for food in ("더티 초코 롤", "파티세리 케이크", "주차 쿠폰", "차돌 샌드위치", "티라미수"):
        assert not is_beverage(food), food


def test_a_cafe_with_drinks_is_recommended_a_drink_even_if_a_pastry_fits_better() -> None:
    stats = compute_axis_stats([vec(sweet=0.3)])
    wanted = vec(hot=0.5, iced=0.5, sweet=0.9, rich_creamy=0.8)
    menus = (MenuEvidence("초코 케이크"), MenuEvidence("아메리카노"))
    best = best_menu_for(wanted, menus, stats)
    assert best is not None and best[0].name == "아메리카노"
    only_pastry = best_menu_for(wanted, (MenuEvidence("초코 케이크"),), stats)
    assert only_pastry is not None and only_pastry[0].name == "초코 케이크"  # nothing else to offer


def test_menu_family_groups_the_same_kind_of_drink() -> None:
    assert menu_family("아이스 아메리카노") == menu_family("카페 아메리카노(핫)") == "아메리카노"
    assert menu_family("바닐라라떼") == "라떼"
    assert menu_family("정체불명 음료수") == "정체불명 음료수"  # unknown names stand for themselves
