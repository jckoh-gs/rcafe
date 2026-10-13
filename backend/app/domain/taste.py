"""Taste model: ten taste axes, a Korean keyword lexicon, and cafe/menu taste vectors.

All values are on a 0..1 scale. Tagging is a transparent keyword lexicon, measured against
hand-labelled reviews (see docs/taste-model.md).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

AXES: tuple[str, ...] = (
    "hot",
    "iced",
    "sweet",
    "sour_fresh",
    "bitter_roast",
    "rich_creamy",
    "nutty_cozy",
    "aroma",
    "light",
    "caffeine_boost",
)
AXIS_LABELS_KO: dict[str, str] = {
    "hot": "따뜻함",
    "iced": "시원함",
    "sweet": "달콤함",
    "sour_fresh": "상큼함",
    "bitter_roast": "깊은 로스팅",
    "rich_creamy": "진하고 크리미한",
    "nutty_cozy": "고소하고 포근한",
    "aroma": "향긋함",
    "light": "가볍고 산뜻한",
    "caffeine_boost": "각성",
}
DIM = len(AXES)
_IDX = {axis: i for i, axis in enumerate(AXES)}
TEMPERATURE_AXES = ("hot", "iced")

TasteVector = tuple[float, ...]


def vec(**values: float) -> TasteVector:
    """Build a vector from axis names; unspecified axes are 0."""
    unknown = set(values) - set(AXES)
    if unknown:
        raise KeyError(f"unknown taste axes: {sorted(unknown)}")
    return tuple(clamp01(values.get(axis, 0.0)) for axis in AXES)


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def top_axes(vector: Sequence[float], n: int = 3, skip_temperature: bool = False) -> list[str]:
    ranked = sorted(AXES, key=lambda axis: vector[_IDX[axis]], reverse=True)
    if skip_temperature:
        ranked = [a for a in ranked if a not in TEMPERATURE_AXES]
    return ranked[:n]


# --- keyword lexicon -------------------------------------------------------------------------


# axis -> keywords found in reviews / menu text. Order does not matter.
def _words(spec: str) -> tuple[str, ...]:
    """'a|b|c' -> ('a', 'b', 'c'); keeps the lexicon readable and formatter-stable."""
    return tuple(spec.split("|"))


LEXICON: dict[str, tuple[str, ...]] = {
    "hot": _words("따뜻|따듯|뜨끈|뜨거|핫|hot|HOT|온기|스팀"),
    "iced": _words("시원|아이스|차가|차갑|ice|ICE|얼음|콜드|아아|빙수|프라페|스무디|슬러시"),
    "sweet": _words(
        "달콤|달달|단맛|달아|달지|달고|당도|시럽|바닐라|카라멜|캐러멜|캬라멜|허니|벌꿀|연유|슈가|달다"
    ),
    "sour_fresh": _words(
        "상큼|새콤|시트러스|레몬|자몽|라임|오렌지|청량|에이드|산미|딸기|산뜻|톡 쏘"
    ),
    "bitter_roast": _words(
        "쓴맛|쓴 맛|씁쓸|로스팅|묵직|다크|에스프레소|싱글오리진|드립|블랙|탄 맛|탄맛|스모키"
    ),
    "rich_creamy": _words("크리미|크림|진한|꾸덕|부드러|라떼|버터|아인슈페너|밀크티|묵직"),
    "nutty_cozy": _words(
        "고소|꼬숩|견과|땅콩|헤이즐넛|흑임자|포근|아늑|피스타치오|밤식빵|군밤|밤라떼|마롱|구수|누룽지"
    ),
    "aroma": _words(
        "향긋|향이|향도|향과|향을|향기|아로마|플로럴|허브|꽃향|스파이스|시나몬|얼그레이|자스민|라벤더"
        "|캐모마일|홍차|밀크티|아이스티|허브티"
    ),
    "light": _words("가볍|깔끔|담백|부담 없는 맛|부담없는 맛|부담스럽지|부담이 덜|산뜻"),
    "caffeine_boost": _words("각성|카페인|샷 추가|샷추가|에스프레소|진한 커피|잠이 깨|잠 깨"),
}

# Longer words that contain a keyword but mean something else; a shorter keyword found inside one of
# them is ignored (the exclusion word itself may still be a keyword). Examples:
#   "아이스크림" is not an iced drink, "핫한" is "trendy", "디카페인" is the opposite of a caffeine
#   boost, "주차가" contains "차가", "추천드립니다" contains "드립", "앙버터" is a bread,
#   "라떼위크" is an event, and "가볍게 이용" is casual use rather than a light taste.
EXCLUSIONS: tuple[str, ...] = _words(
    "아이스크림|핫한|핫플|디카페인|취향|영향|주차가|드립니다|앙버터|라떼위크|허니 프로세스|통곡물"
    "|가볍게 이용|가볍게 방문|가볍게 들|가볍게 도전|가볍게 한|추가가볍"
)

# For these axes the same words often describe the shop, not the cup:
# "따뜻한 우드 톤", "아늑한 공간", "깔끔한 매장", "시원한 매장". A hit is ignored when a place
# word follows right after it or precedes it directly.
PLACE_SENSITIVE_AXES = frozenset({"hot", "iced", "nutty_cozy", "light"})
_PLACE_WORDS = _words(
    "분위기|공간|매장|가게|인테리어|조명|톤|우드|좌석|자리|외관|내부|화장실|직원|사장|서비스|응대"
    "|마음|미소|햇살|테이블"
)
_PLACE_AFTER = re.compile(r"^\S{0,2}\s?(" + "|".join(_PLACE_WORDS) + ")")
_PLACE_BEFORE = re.compile("(" + "|".join(_PLACE_WORDS) + r")\S{0,2}\s?$")

# Naver's own "voted keyword" labels on reviews, e.g. "커피가 맛있어요" -> small signals.
VOTED_KEYWORD_SIGNALS: dict[str, dict[str, float]] = {
    "커피가 맛있어요": {"bitter_roast": 0.6, "caffeine_boost": 0.3},
    "디저트가 맛있어요": {"sweet": 0.8},
    "음료가 맛있어요": {"sour_fresh": 0.3, "sweet": 0.3},
    "향이 좋아요": {"aroma": 0.8},
    "달지 않아요": {"light": 0.6},
}

_NEGATION_AFTER = re.compile(r"^.{0,3}(지\s?않|않|없|아니|별로|줄이|줄었|덜)")
_NEGATION_BEFORE = re.compile(r"(안|별로|전혀)\s?$")


def _excluded_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for word in EXCLUSIONS:
        start = 0
        while (pos := text.find(word, start)) >= 0:
            spans.append((pos, pos + len(word)))
            start = pos + len(word)
    return spans


def _describes_place(text: str, pos: int, end: int) -> bool:
    return bool(_PLACE_AFTER.match(text[end : end + 8])) or bool(
        _PLACE_BEFORE.search(text[max(0, pos - 6) : pos])
    )


def _count_keyword(
    text: str,
    keyword: str,
    spans: list[tuple[int, int]] | None = None,
    axis: str | None = None,
) -> int:
    spans = _excluded_spans(text) if spans is None else spans
    count = 0
    start = 0
    while (pos := text.find(keyword, start)) >= 0:
        end = pos + len(keyword)
        inside_excluded = any(s <= pos and end <= e and end - pos < e - s for s, e in spans)
        negated = bool(_NEGATION_AFTER.match(text[end : end + 5])) or bool(
            _NEGATION_BEFORE.search(text[max(0, pos - 3) : pos])
        )
        about_place = axis in PLACE_SENSITIVE_AXES and _describes_place(text, pos, end)
        if not (negated or inside_excluded or about_place):
            count += 1
        start = end
    return count


def tag_text(text: str) -> Counter[str]:
    """Count lexicon hits per axis (negated, look-alike, or shop-describing hits are skipped)."""
    hits: Counter[str] = Counter()
    spans = _excluded_spans(text)
    for axis, keywords in LEXICON.items():
        for keyword in keywords:
            n = _count_keyword(text, keyword, spans, axis)
            if n:
                hits[axis] += n
    return hits


def text_vector(text: str, saturation: float = 2.0) -> TasteVector:
    """One text -> 0..1 vector; repeated mentions saturate (1 - exp(-n/saturation))."""
    hits = tag_text(text)
    return tuple(1.0 - math.exp(-hits.get(axis, 0) / saturation) for axis in AXES)


# --- menu items ---------------------------------------------------------------------------------

# keyword in menu name/description -> contribution per axis
MENU_RULES: tuple[tuple[str, dict[str, float]], ...] = (
    ("아메리카노", {"bitter_roast": 0.8, "caffeine_boost": 0.6, "light": 0.4}),
    ("에스프레소", {"bitter_roast": 1.0, "caffeine_boost": 0.9}),
    ("드립", {"bitter_roast": 0.6, "aroma": 0.6, "light": 0.3}),
    ("필터", {"aroma": 0.6, "light": 0.4}),
    ("콜드브루", {"bitter_roast": 0.7, "iced": 1.0, "caffeine_boost": 0.5}),
    ("플랫화이트", {"rich_creamy": 0.7, "bitter_roast": 0.6}),
    ("카푸치노", {"rich_creamy": 0.6, "bitter_roast": 0.4}),
    ("라떼", {"rich_creamy": 0.8, "nutty_cozy": 0.3}),
    ("카페라떼", {"rich_creamy": 0.8}),
    ("아인슈페너", {"rich_creamy": 0.9, "sweet": 0.5, "bitter_roast": 0.4}),
    ("모카", {"sweet": 0.7, "bitter_roast": 0.4, "rich_creamy": 0.4}),
    ("돌체", {"sweet": 0.9, "rich_creamy": 0.6}),
    ("바닐라", {"sweet": 0.8}),
    ("카라멜", {"sweet": 0.8}),
    ("캐러멜", {"sweet": 0.8}),
    ("헤이즐넛", {"nutty_cozy": 0.9, "sweet": 0.4}),
    ("흑임자", {"nutty_cozy": 1.0, "rich_creamy": 0.4}),
    ("오트", {"nutty_cozy": 0.7}),
    ("에이드", {"sour_fresh": 1.0, "iced": 0.9, "light": 0.6}),
    ("주스", {"sour_fresh": 0.8, "iced": 0.6, "light": 0.5}),
    ("스무디", {"sour_fresh": 0.6, "iced": 1.0, "sweet": 0.6}),
    ("프라페", {"iced": 1.0, "sweet": 0.8, "rich_creamy": 0.5}),
    ("자몽", {"sour_fresh": 0.9}),
    ("레몬", {"sour_fresh": 0.9}),
    ("딸기", {"sour_fresh": 0.5, "sweet": 0.6}),
    ("티", {"aroma": 0.8, "light": 0.7, "hot": 0.4}),
    ("차", {"aroma": 0.6, "light": 0.6}),
    ("얼그레이", {"aroma": 0.9, "light": 0.5}),
    ("밀크티", {"rich_creamy": 0.7, "sweet": 0.6, "aroma": 0.5}),
    ("초코", {"sweet": 0.9, "rich_creamy": 0.6}),
    ("쿠키", {"sweet": 0.8, "nutty_cozy": 0.4}),
    ("케이크", {"sweet": 0.9, "rich_creamy": 0.5}),
    ("마들렌", {"sweet": 0.7, "nutty_cozy": 0.4}),
    ("휘낭시에", {"sweet": 0.7, "nutty_cozy": 0.6}),
    ("소금빵", {"nutty_cozy": 0.7, "rich_creamy": 0.4}),
    ("스콘", {"nutty_cozy": 0.6, "sweet": 0.4}),
    ("티라미수", {"sweet": 0.8, "rich_creamy": 0.8, "bitter_roast": 0.3}),
    ("크로플", {"sweet": 0.7, "rich_creamy": 0.4}),
    ("샌드위치", {"nutty_cozy": 0.4, "light": 0.3}),
    ("빙수", {"iced": 1.0, "sweet": 0.8}),
    ("아이스", {"iced": 1.0}),
    ("핫", {"hot": 1.0}),
)
_JUNK_MENU = re.compile(
    r"패스오더|쿠폰|증정|무료|옵션|추가|포장|배달|선택|사이즈|텀블러|원두\s?\d|[0-9]+\s?원|[0-9]+\s?호\)"
)


_DESSERT_WORDS = (
    "케이크",
    "케익",
    "쿠키",
    "빵",
    "바게트",
    "마들렌",
    "휘낭시에",
    "스콘",
    "샌드위치",
    "타르트",
    "크로플",
    "푸딩",
    "베이글",
    "티라미수",
    "와플",
    "도넛",
    "크루아상",
    "파이",
    "브라우니",
    "젤라또",
)
_BEVERAGE_WORDS = _words(
    "커피|아메리카노|라떼|에스프레소|에이드|주스|스무디|프라페|모카|마끼아또|마키아토|카푸치노"
    "|플랫화이트|콜드브루|드립|음료|쉐이크|슈페너|코코아|토닉|워터"
    # teas are listed by name: a bare "티" or "차" also sits inside "더티", "파티", "주차" ...
    "|밀크티|아이스티|허브티|블랙티|그린티|레몬티|유자티|자몽티|복숭아티|오렌지티|애플티|캐모마일"
    "|얼그레이|페퍼민트|루이보스|히비스커스|우롱|홍차|녹차|말차|보이차"
)
# Korean "..차" teas such as 유자차, 매실청차, 오미자차 (a word that ends in 차).
_KOREAN_TEA = re.compile(r"[가-힣]{2,5}차(?![가-힣])")


def is_beverage(name: str) -> bool:
    """A drink rather than food (the service recommends a cup first; desserts are still allowed)."""
    if name.strip() in ("티", "차"):
        return True
    if any(word in name for word in _DESSERT_WORDS):
        return False
    return any(word in name for word in _BEVERAGE_WORDS) or bool(_KOREAN_TEA.search(name))


def is_orderable_menu(name: str) -> bool:
    """False for promo/option lines such as '[패스오더전용] 100원 아메리카노' or '샷 추가'."""
    return not _JUNK_MENU.search(name)


_EXPLICIT_ICED = ("아이스", "콜드", "ICE", "ice", "빙수", "에이드", "스무디", "프라페", "I-")
_EXPLICIT_HOT = ("핫", "HOT", "hot", "따뜻", "H-")


def menu_vector(name: str, description: str | None = None) -> TasteVector:
    """Taste profile of one menu item. Temperature stays 0.5/0.5 unless the text says otherwise."""
    text = f"{name} {description or ''}"
    values = dict.fromkeys(AXES, 0.0)
    for keyword, contributions in MENU_RULES:
        if keyword in name:
            for axis, weight in contributions.items():
                values[axis] = max(values[axis], weight)
    for axis, hits in tag_text(text).items():  # description wording refines the profile
        values[axis] = max(values[axis], min(0.6, 0.3 * hits))
    iced = any(token in text for token in _EXPLICIT_ICED)
    hot = any(token in text for token in _EXPLICIT_HOT)
    if iced and not hot:
        values["iced"], values["hot"] = 1.0, 0.0
    elif hot and not iced:
        values["hot"], values["iced"] = 1.0, 0.0
    elif not iced and not hot:
        values["hot"], values["iced"] = 0.5, 0.5
    else:
        values["hot"], values["iced"] = 0.5, 0.5
    return tuple(clamp01(values[axis]) for axis in AXES)


# --- cafe aggregation --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MenuEvidence:
    name: str
    description: str | None = None
    price: int | None = None
    image_url: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewEvidence:
    review_key: str
    text: str
    rating: int | None = None
    ordered_item: str | None = None
    voted_keywords: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CafeEvidence:
    place_id: str
    menus: tuple[MenuEvidence, ...]
    menu_mentions: tuple[tuple[str, int], ...]
    reviews: tuple[ReviewEvidence, ...]


@dataclass(frozen=True, slots=True)
class CafeTaste:
    place_id: str
    raw: TasteVector
    evidence_weight: float
    review_tags: dict[str, dict[str, int]]  # review_key -> {axis: hits}


def review_vector(review: ReviewEvidence) -> tuple[TasteVector, Counter[str]]:
    hits = tag_text(f"{review.text} {review.ordered_item or ''}")
    values = [1.0 - math.exp(-hits.get(axis, 0) / 2.0) for axis in AXES]
    for keyword in review.voted_keywords:
        for axis, weight in VOTED_KEYWORD_SIGNALS.get(keyword, {}).items():
            values[_IDX[axis]] = max(values[_IDX[axis]], weight)
    if review.ordered_item:
        item = menu_vector(review.ordered_item)
        for i, axis in enumerate(AXES):
            if axis not in TEMPERATURE_AXES:
                values[i] = max(values[i], 0.5 * item[i])
    return tuple(values), hits


def raw_cafe_taste(evidence: CafeEvidence) -> CafeTaste:
    """Weighted mean of menu, menu-mention, and review vectors (not yet normalized)."""
    total = [0.0] * DIM
    weight_sum = 0.0

    def add(vector: Sequence[float], weight: float) -> None:
        nonlocal weight_sum
        for i, value in enumerate(vector):
            total[i] += weight * value
        weight_sum += weight

    for label, count in evidence.menu_mentions:
        add(menu_vector(label), math.log1p(count))
    menus = [m for m in evidence.menus if is_orderable_menu(m.name)]
    for position, menu in enumerate(menus[:12]):
        add(menu_vector(menu.name, menu.description), 1.0 if position >= 3 else 1.5)
    review_tags: dict[str, dict[str, int]] = {}
    for review in evidence.reviews:
        vector, hits = review_vector(review)
        rating_factor = (review.rating or 4) / 5
        add(vector, 2.0 * rating_factor)
        review_tags[review.review_key] = dict(hits)
    raw = tuple(v / weight_sum for v in total) if weight_sum else (0.0,) * DIM
    return CafeTaste(evidence.place_id, raw, weight_sum, review_tags)


@dataclass(frozen=True, slots=True)
class AxisStats:
    mean: tuple[float, ...]
    scale: tuple[float, ...]  # ~95th percentile per axis, used to stretch to 0..1


def compute_axis_stats(vectors: Iterable[Sequence[float]]) -> AxisStats:
    rows = list(vectors)
    if not rows:
        return AxisStats((0.0,) * DIM, (1.0,) * DIM)
    mean: list[float] = []
    scale: list[float] = []
    for i in range(DIM):
        column = sorted(row[i] for row in rows)
        mean.append(sum(column) / len(column))
        p95 = column[min(len(column) - 1, int(0.95 * len(column)))]
        scale.append(p95 if p95 > 1e-6 else 1.0)
    return AxisStats(tuple(mean), tuple(scale))


def normalize_cafe_taste(
    raw: Sequence[float], stats: AxisStats, evidence_weight: float, shrink_k: float = 4.0
) -> tuple[TasteVector, float]:
    """Stretch each axis by its dataset scale, shrink low-evidence cafes toward the dataset mean."""
    confidence = evidence_weight / (evidence_weight + shrink_k)
    out: list[float] = []
    for i, axis in enumerate(AXES):
        is_temperature = axis in TEMPERATURE_AXES
        stretched = raw[i] if is_temperature else clamp01(raw[i] / stats.scale[i])
        mean = 0.5 if is_temperature else clamp01(stats.mean[i] / stats.scale[i])
        out.append(clamp01(confidence * stretched + (1 - confidence) * mean))
    return tuple(out), confidence


def centered(vector: Sequence[float], stats: AxisStats) -> list[float]:
    """Vector minus the dataset mean (in normalized space), so only distinctive traits count."""
    return [
        v - (0.5 if AXES[i] in TEMPERATURE_AXES else clamp01(stats.mean[i] / stats.scale[i]))
        for i, v in enumerate(vector)
    ]


def taste_similarity(wanted: Sequence[float], cafe: Sequence[float], stats: AxisStats) -> float:
    """Cosine of mean-centered vectors, mapped to 0..1."""
    return (cosine(centered(wanted, stats), centered(cafe, stats)) + 1) / 2


_FAMILIES = _words(
    "아메리카노|라떼|에이드|티|주스|스무디|콜드브루|드립|모카|에스프레소|마끼아또|마키아토|슈페너"
    "|프라페|코코아|밀크티|커피"
)


def menu_family(name: str) -> str:
    """Coarse drink family ('아이스 아메리카노' -> '아메리카노') so a podium can avoid repeats."""
    return next((word for word in _FAMILIES if word in name), name)


def best_menu_for(
    wanted: Sequence[float], menus: Sequence[MenuEvidence], stats: AxisStats
) -> tuple[MenuEvidence, float] | None:
    """The menu item whose own profile fits the wanted taste best.

    A cafe recommendation is a cup first: when the cafe has any drink, only drinks compete.
    Flavor axes decide the ranking; an item that is explicitly hot or iced is penalized when it
    contradicts the temperature the weather calls for.
    """
    orderable = [m for m in menus if is_orderable_menu(m.name)]
    pool = [m for m in orderable if is_beverage(m.name)] or orderable
    best: tuple[MenuEvidence, float] | None = None
    keep = [i for i, axis in enumerate(AXES) if axis not in TEMPERATURE_AXES]
    want_hot, want_iced = wanted[_IDX["hot"]], wanted[_IDX["iced"]]
    for menu in pool:
        vector = menu_vector(menu.name, menu.description)
        if not any(vector[i] > 0 for i in keep):
            continue
        score = cosine([wanted[i] for i in keep], [vector[i] for i in keep])
        item_hot, item_iced = vector[_IDX["hot"]], vector[_IDX["iced"]]
        explicit = item_hot != item_iced
        if explicit and (
            (item_iced > item_hot and want_hot > want_iced + 0.2)
            or (item_hot > item_iced and want_iced > want_hot + 0.2)
        ):
            score *= 0.3
        if best is None or score > best[1]:
            best = (menu, score)
    return best


@dataclass(frozen=True, slots=True)
class CafeProfile:
    place_id: str
    name: str
    taste: TasteVector
    confidence: float
    menus: tuple[MenuEvidence, ...]
