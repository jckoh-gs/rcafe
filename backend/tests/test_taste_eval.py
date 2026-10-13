"""Regression guard for the keyword lexicon, plus the rules added to cut false positives.

The snippets are made up (see the note inside taste_eval.json), so these scores say whether the
lexicon got worse, not how accurate it is on real reviews.
"""

import json

import pytest

from app.domain.taste import tag_text
from tests.conftest import FIXTURES

EVAL_FILE = FIXTURES / "taste_eval.json"
# Floors are the measured scores minus a small margin: they catch regressions, they are not goals.
FLOORS = {"set1": 0.89, "set2": 0.85, "set3_blind": 0.82}


def _score(items: list[dict[str, object]]) -> tuple[float, float, float]:
    tp = fp = fn = 0
    for item in items:
        gold = set(item["labels"])  # type: ignore[call-overload]
        predicted = {a for a, hits in tag_text(str(item["text"])).items() if hits > 0}
        tp, fp, fn = (
            tp + len(gold & predicted),
            fp + len(predicted - gold),
            fn + len(gold - predicted),
        )
    precision, recall = tp / (tp + fp), tp / (tp + fn)
    return precision, recall, 2 * precision * recall / (precision + recall)


@pytest.mark.skipif(not EVAL_FILE.exists(), reason="evaluation snippets not available")
@pytest.mark.parametrize("name", sorted(FLOORS))
def test_lexicon_keeps_its_measured_quality(name: str) -> None:
    items = json.loads(EVAL_FILE.read_text(encoding="utf-8"))["sets"][name]
    precision, recall, f1 = _score(items)
    assert f1 >= FLOORS[name], (
        f"{name}: F1 {f1:.2f} (precision {precision:.2f}, recall {recall:.2f})"
    )
    assert precision >= 0.70 and recall >= 0.80


def test_shop_descriptions_are_not_taste() -> None:
    assert tag_text("따뜻한 우드 톤의 외관이 예뻐요")["hot"] == 0
    assert tag_text("분위기가 아늑한 공간이에요")["nutty_cozy"] == 0
    assert tag_text("매장도 깔끔해요")["light"] == 0
    assert tag_text("시원한 매장에서 쉬었어요")["iced"] == 0
    assert tag_text("커피가 깔끔하고 고소해요")["light"] == 1  # about the cup: still counted
    assert tag_text("따뜻한 라떼를 마셨어요")["hot"] == 1


def test_look_alike_words_and_food_names_are_ignored() -> None:
    assert tag_text("주차가 편해요")["iced"] == 0
    assert tag_text("강력 추천드립니다")["bitter_roast"] == 0
    assert tag_text("앙버터 빵이 맛있어요")["rich_creamy"] == 0
    assert tag_text("통곡물 빵을 샀어요")["nutty_cozy"] == 0
    assert tag_text("라떼위크 쿠폰으로 주문했어요")["rich_creamy"] == 0
    assert tag_text("허니 프로세스 원두예요")["sweet"] == 0
    assert tag_text("피칸 번과 초코바게트를 샀어요").total() == 0


def test_cold_desserts_and_reduced_tastes() -> None:
    assert tag_text("여름엔 빙수가 최고예요")["iced"] == 1
    assert tag_text("캬라멜 마끼아또가 좋아요")["sweet"] == 1
    assert tag_text("씁쓸함은 줄이고 부드러움만 남겼어요")["bitter_roast"] == 0
    assert (
        tag_text("디카페인 아이스 아메리카노")["iced"] == 1
    )  # '카페인' must not read as a place word
