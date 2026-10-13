"""Score the keyword lexicon against the hand-labelled (made-up) review snippets.

    uv run python -m scripts.eval_taste

Prints precision / recall / F1 per set (an axis counts when the lexicon hits it at least once).
"""

import json
from pathlib import Path

from app.domain.taste import tag_text

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "taste_eval.json"


def score(items: list[dict[str, object]]) -> tuple[float, float, float, int]:
    tp = fp = fn = exact = 0
    for item in items:
        gold = set(item["labels"])  # type: ignore[call-overload]
        predicted = {axis for axis, hits in tag_text(str(item["text"])).items() if hits > 0}
        tp, fp, fn = (
            tp + len(gold & predicted),
            fp + len(predicted - gold),
            fn + len(gold - predicted),
        )
        exact += gold == predicted
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1, exact


def main() -> None:
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for name, items in doc["sets"].items():
        precision, recall, f1, exact = score(items)
        print(
            f"{name:12s} precision {precision:.2f}  recall {recall:.2f}  F1 {f1:.2f}  "
            f"exact {exact}/{len(items)}"
        )


if __name__ == "__main__":
    main()
