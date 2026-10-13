"""Measure the quality of the recommendation podium over many weather x location scenarios.

    uv run python -m scripts.eval_reco

Uses the real cafe data in the database (AICAFE_DATABASE_URL) and the production scoring/selection/
message code. Reports how often the picks are drinks, how varied the podium is, how much of it comes
from bakery-type shops, and what kind of reason sentence is shown.
"""

import asyncio
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from app.adapters.outbound.persistence.recommend_repository import PostgresCandidateSource
from app.adapters.outbound.persistence.repository import make_engine
from app.adapters.outbound.persistence.taste_repository import PostgresTasteRepository
from app.config import Settings
from app.domain.messages import recommendation_message
from app.domain.models import GeoPoint
from app.domain.recommend import score_candidates, select_top
from app.domain.taste import is_beverage
from app.domain.weather import WeatherConditions, taste_from_conditions

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 10, 14, 0, tzinfo=KST)  # a Saturday afternoon: most cafes are open
CENTER = GeoPoint(37.5006431, 127.0363766)
SCENARIOS = {
    "hot noon": WeatherConditions(33, 0.7, False, 0.9, 13),
    "hot rain": WeatherConditions(28, 0.9, True, 0.1, 16),
    "mild afternoon": WeatherConditions(20, 0.5, False, 0.6, 15),
    "cool morning": WeatherConditions(12, 0.6, False, 0.5, 9),
    "cold evening": WeatherConditions(2, 0.5, False, 0.4, 19),
    "cold rain": WeatherConditions(5, 0.9, True, 0.1, 20),
}
SPOTS = [
    (0, 0),
    (500, 0),
    (-500, 0),
    (0, 500),
    (0, -500),
    (900, 700),
    (-900, 700),
    (900, -700),
    (-900, -700),
    (1400, 0),
    (-1400, 0),
    (0, 1400),
    (0, -1400),
]
FAMILIES = (
    "아메리카노",
    "라떼",
    "에이드",
    "티",
    "주스",
    "스무디",
    "콜드브루",
    "드립",
    "모카",
    "에스프레소",
    "마끼아또",
    "슈페너",
    "프라페",
    "초코",
    "밀크티",
    "커피",
)


def family(name: str) -> str:
    for word in FAMILIES:
        if word in name:
            return word
    return name


def at(point: GeoPoint, east_m: float, north_m: float) -> GeoPoint:
    return GeoPoint(point.lat + north_m / 111_320, point.lng + east_m / (111_320 * 0.793))


async def main() -> None:
    engine = make_engine(Settings().database_url)
    candidates = await PostgresCandidateSource(engine).candidates_near(CENTER, 3000)
    stats = await PostgresTasteRepository(engine).load_axis_stats()
    await engine.dispose()
    assert stats is not None, "run `taste` first"

    picks = drinks = podiums = all_drinks = 0
    distinct = Counter()
    reasons: Counter[str] = Counter()
    desserts: Counter[str] = Counter()
    for conditions in SCENARIOS.values():
        wanted = taste_from_conditions(conditions)
        for east, north in SPOTS:
            origin = at(CENTER, east, north)
            scored = score_candidates(candidates, wanted, stats, origin, 1000, NOW)
            top = select_top(scored)
            if len(top) < 3:
                continue
            podiums += 1
            names = [s.menu.name for s in top if s.menu]
            kinds = [is_beverage(n) for n in names]
            picks += len(names)
            drinks += sum(kinds)
            all_drinks += all(kinds)
            distinct[len({family(n) for n in names})] += 1
            for rank, s in enumerate(top, start=1):
                text = recommendation_message(rank, s, wanted, NOW.date())
                if re.search(r"리뷰 \d+건 중 \d+건", text.reason):
                    reasons["reviews mention taste"] += 1
                elif "번 언급" in text.reason or "인기" in text.reason:
                    reasons["popular item"] += 1
                elif "맛이라" in text.reason:
                    reasons["menu flavor"] += 1
                elif "즐기기 좋은 메뉴" in text.reason:
                    reasons["temperature"] += 1
                else:
                    reasons["generic"] += 1
                if s.menu and not is_beverage(s.menu.name):
                    desserts[f"{s.candidate.name} / {s.menu.name}"] += 1
    print(f"podiums evaluated: {podiums}")
    print(f"picks that are drinks:      {drinks}/{picks} = {drinks / picks:.0%}")
    print(f"podiums with 3 drinks:      {all_drinks}/{podiums} = {all_drinks / podiums:.0%}")
    print("distinct menu families in a podium (of 3):", dict(sorted(distinct.items())))
    print("reason sentences:", dict(reasons))
    print("most frequent non-drink picks:", desserts.most_common(5))


if __name__ == "__main__":
    asyncio.run(main())
