"""Slot-based Korean recommendation messages (polite style, light emoji use).

Free-form LLM text is deliberately avoided: templates keep the output natural, fast, and
free of invented claims. Every fact in a message comes from stored data.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date

from app.domain.recommend import ScoredCafe, walking_minutes
from app.domain.taste import AXES, TasteVector, is_beverage, menu_vector
from app.domain.weather import WeatherConditions, temperature_band

MAX_MESSAGE_CHARS = 170
MAX_EMOJIS = 3
BANNED_PHRASES = ("우울", "슬프", "불행", "짜증", "기분이 나빠")

_BATCHIM_DIGITS = {
    "0": True,
    "1": True,
    "2": False,
    "3": True,
    "4": False,
    "5": False,
    "6": True,
    "7": True,
    "8": True,
    "9": False,
}
_BATCHIM_LETTERS = set("lmnrLMNR")


def _last_char(word: str) -> str:
    for ch in reversed(word):
        if "가" <= ch <= "힣" or ch.isalnum():
            return ch
    return ""


def has_batchim(word: str) -> bool:
    """Whether the last syllable of `word` ends with a consonant (for 을/를 style particles)."""
    ch = _last_char(word)
    if not ch:
        return False
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28 != 0
    if ch in _BATCHIM_DIGITS:
        return _BATCHIM_DIGITS[ch]
    return ch in _BATCHIM_LETTERS


def _rieul(word: str) -> bool:
    ch = _last_char(word)
    return "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 == 8


def josa(word: str, kind: str) -> str:
    """`word` followed by the right particle. kind: 을/를, 이/가, 은/는, 과/와, 으로/로."""
    batchim = has_batchim(word)
    if kind == "을/를":
        return word + ("을" if batchim else "를")
    if kind == "이/가":
        return word + ("이" if batchim else "가")
    if kind == "은/는":
        return word + ("은" if batchim else "는")
    if kind == "과/와":
        return word + ("과" if batchim else "와")
    if kind == "으로/로":
        return word + ("로" if (not batchim or _rieul(word)) else "으로")
    raise ValueError(f"unknown particle {kind!r}")


# --- weather sentence ----------------------------------------------------------------------------

_DRY_PHRASES: dict[str, tuple[str, ...]] = {
    "한파": ("꽁꽁 얼어붙는 날씨예요 🥶", "손끝이 시린 추운 날이에요 🧣"),
    "추운": ("바람이 매서운 추운 날이에요 🧣", "몸이 움츠러드는 날씨예요 ❄️"),
    "쌀쌀한": ("쌀쌀한 공기가 느껴지는 날이에요 🍂", "겉옷이 생각나는 쌀쌀한 날씨예요 🧥"),
    "선선한": ("선선한 바람이 부는 날이에요 🍃", "지내기 좋은 선선한 날씨예요 🍃"),
    "포근한": ("포근하고 부드러운 날씨예요 ☁️", "느긋하게 걷기 좋은 날씨예요 🌤️"),
    "따뜻한": ("따뜻한 햇살이 반가운 날이에요 ☀️", "기분 좋게 따뜻한 날씨예요 ☀️"),
    "무더운": ("후텁지근하게 무더운 날이에요 💦", "더위가 이어지는 날씨예요 🥵"),
    "폭염": ("한낮 더위가 대단한 날이에요 🥵", "더위를 식힐 한 잔이 간절한 날씨예요 🧊"),
}
_RAIN_PHRASES = {
    "cold": ("차가운 비가 내리는 날이에요 ☔", "비에 쌀쌀함이 더해진 날이에요 🌧️"),
    "mild": ("비가 부슬부슬 내리는 날이에요 🌧️", "빗소리가 잔잔하게 들리는 날이에요 ☔"),
    "hot": ("비가 와도 후텁지근한 날이에요 ☔", "습한 비가 내리는 날이에요 🌧️"),
}

# axis -> (connective form used before another adjective, final form)
_FLAVOR_WORDS: dict[str, tuple[str, str]] = {
    "sweet": ("달콤하고", "달콤한"),
    "sour_fresh": ("상큼하고", "상큼한"),
    "bitter_roast": ("쌉싸름하고", "쌉싸름한"),
    "rich_creamy": ("진하고", "크리미한"),
    "nutty_cozy": ("고소하고", "고소한"),
    "aroma": ("향긋하고", "향긋한"),
    "light": ("가볍고", "산뜻한"),
    "caffeine_boost": ("진하고", "진한"),
}
_EVIDENCE_NOUN: dict[str, str] = {
    "sweet": "달콤한 맛",
    "sour_fresh": "상큼한 맛",
    "bitter_roast": "깊은 커피 맛",
    "rich_creamy": "진하고 부드러운 맛",
    "nutty_cozy": "고소한 맛",
    "aroma": "향",
    "light": "깔끔한 맛",
}


def _pick(options: tuple[str, ...], seed: str) -> str:
    digest = hashlib.md5(seed.encode("utf-8"), usedforsecurity=False).digest()
    return options[digest[0] % len(options)]


def weather_phrase(conditions: WeatherConditions, day: date) -> str:
    seed = f"{day.isoformat()}:{round(conditions.feels_like)}"
    if conditions.raining:
        group = (
            "cold"
            if conditions.feels_like < 10
            else ("hot" if conditions.feels_like >= 26 else "mild")
        )
        return _pick(_RAIN_PHRASES[group], seed)
    return _pick(_DRY_PHRASES[temperature_band(conditions.feels_like)], seed)


def taste_phrase(wanted: TasteVector, temperature_cutoff: float = 0.65) -> str:
    """'시원하고 상큼한' style phrase from the strongest wanted traits."""
    index = {axis: i for i, axis in enumerate(AXES)}
    flavors = sorted(_FLAVOR_WORDS, key=lambda a: wanted[index[a]], reverse=True)[:2]
    chosen = [flavors[0]]
    if wanted[index[flavors[1]]] >= 0.55:
        chosen.append(flavors[1])
    connectives: list[str] = []
    if wanted[index["iced"]] >= temperature_cutoff:
        connectives.append("시원하고")
    elif wanted[index["hot"]] >= temperature_cutoff:
        connectives.append("따뜻하고")
    connectives += [_FLAVOR_WORDS[a][0] for a in chosen[:-1]]
    return " ".join([*connectives, _FLAVOR_WORDS[chosen[-1]][1]])


def serve_hint(wanted: TasteVector, menu_name: str, cutoff: float = 0.65) -> str:
    """'시원하게' / '따뜻하게' when the menu itself does not say how it is served."""
    index = {axis: i for i, axis in enumerate(AXES)}
    explicit = any(
        t in menu_name for t in ("아이스", "핫", "HOT", "Ice", "ICE", "Hot", "따뜻", "콜드")
    )
    if explicit:
        return ""
    if wanted[index["iced"]] >= cutoff:
        return "시원하게"
    if wanted[index["hot"]] >= cutoff:
        return "따뜻하게"
    return ""


# --- messages ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Recommendation:
    rank: int
    message: str  # headline + status line, for plain-text use
    headline: str  # opener + reason (no open/distance info; UIs show that separately)
    reason: str
    status_line: str


def summary_message(conditions: WeatherConditions, wanted: TasteVector, day: date) -> str:
    taste = josa(f"{taste_phrase(wanted)} 맛", "이/가")
    return f"{weather_phrase(conditions, day)} 오늘은 {taste} 어울려요."


MIN_POPULAR_MENTIONS = 20  # reviewers must have mentioned the item this often to call it popular
MIN_EVIDENCE_REVIEWS = 5  # taste evidence needs enough reviews to mean something ...
MIN_EVIDENCE_COUNT = 3  # ... and at least this many of them ...
MIN_EVIDENCE_SHARE = 0.3  # ... and at least this share of them
MIN_FLAVOR_FIT = 0.15
STRONG_TEMPERATURE = 0.65


def _popular_mention(item: ScoredCafe) -> tuple[str, int] | None:
    """The most-mentioned review label that is part of the recommended menu's name."""
    if item.menu is None:
        return None
    hits = [
        (label, count)
        for label, count in item.candidate.menu_mentions
        if len(label) >= 2 and label in item.menu.name
    ]
    best = max(hits, key=lambda pair: pair[1], default=None)
    return best if best and best[1] >= MIN_POPULAR_MENTIONS else None


def _taste_evidence(item: ScoredCafe, wanted: TasteVector, profile: TasteVector) -> str | None:
    """'리뷰 N건 중 M건에서 …' only when the reviews really back this menu and this weather."""
    index = {axis: i for i, axis in enumerate(AXES)}
    total = item.candidate.review_total
    if total < MIN_EVIDENCE_REVIEWS:
        return None
    candidates = [
        (wanted[index[axis]] * item.candidate.review_axis_counts.get(axis, 0) / total, axis)
        for axis in _EVIDENCE_NOUN
        if wanted[index[axis]] >= 0.4
        and profile[index[axis]] >= 0.2  # the evidence has to be about what this menu is
        and item.candidate.review_axis_counts.get(axis, 0) >= MIN_EVIDENCE_COUNT
        and item.candidate.review_axis_counts.get(axis, 0) / total >= MIN_EVIDENCE_SHARE
    ]
    if not candidates:
        return None
    axis = max(candidates)[1]
    count = item.candidate.review_axis_counts[axis]
    return f"리뷰 {total}건 중 {count}건에서 {josa(_EVIDENCE_NOUN[axis], '이/가')} 언급돼요."


def _reason(item: ScoredCafe, wanted: TasteVector) -> str:
    """One honest sentence for why this cup: popularity, review evidence, flavor, or temperature."""
    index = {axis: i for i, axis in enumerate(AXES)}
    if popular := _popular_mention(item):
        label, count = popular
        return f"리뷰에서 {josa(label, '이/가')} {count:,}번 언급된 인기 메뉴예요."
    if item.menu is None:
        return "오늘 날씨에 잘 어울리는 메뉴예요."
    profile = menu_vector(item.menu.name, item.menu.description)
    if evidence := _taste_evidence(item, wanted, profile):
        return evidence
    flavor = max(_FLAVOR_WORDS, key=lambda a: profile[index[a]] * wanted[index[a]])
    if profile[index[flavor]] * wanted[index[flavor]] >= MIN_FLAVOR_FIT:
        return f"{_FLAVOR_WORDS[flavor][1]} 맛이라 오늘 날씨에 잘 어울려요."
    explicit_hot = profile[index["hot"]] > profile[index["iced"]]
    explicit_iced = profile[index["iced"]] > profile[index["hot"]]
    if wanted[index["iced"]] >= STRONG_TEMPERATURE and not explicit_hot:
        return "오늘 같은 날씨엔 시원하게 즐기기 좋은 메뉴예요."
    if wanted[index["hot"]] >= STRONG_TEMPERATURE and not explicit_iced:
        return "오늘 같은 날씨엔 따뜻하게 즐기기 좋은 메뉴예요."
    return "오늘 날씨에 잘 어울리는 메뉴예요."


def _status_line(item: ScoredCafe) -> str:
    walk = f"도보 약 {walking_minutes(item.distance_m)}분"
    state = item.open_state
    if state.is_open:
        until = f" ({state.changes_at}까지)" if state.changes_at else ""
        return f"{walk}, 지금 영업 중이에요{until}."
    if state.is_open is False:
        when = (
            f"{'내일 ' if state.changes_tomorrow else ''}{state.changes_at}"
            if state.changes_at
            else ""
        )
        return f"{walk}, 지금은 문을 닫았어요 🌙{(' ' + when + '에 열어요.') if when else ''}"
    return f"{walk} 거리예요."


def recommendation_message(
    rank: int, item: ScoredCafe, wanted: TasteVector, day: date
) -> Recommendation:
    cafe = item.candidate.name
    menu = item.menu.name if item.menu else "추천 메뉴"
    serve = serve_hint(wanted, menu)
    serve_part = f"{serve} " if serve else ""
    seed = f"{item.candidate.place_id}:{day.isoformat()}:{rank}"
    face = "☕" if is_beverage(menu) else "🍰"
    menu_obj = josa(menu, "을/를")
    menu_subj = josa(menu, "이/가")
    cafe_topic = josa(cafe, "은/는")
    openers = {
        1: (
            f"가장 먼저 추천드려요! {cafe_topic} {menu_obj} {serve_part}드셔 보세요 {face}",
            f"{cafe}의 {menu_obj} {serve_part}추천드려요 ✨",
        ),
        2: (
            f"{cafe}의 {menu_subj} {serve_part}좋은 선택이에요 🙂",
            f"{cafe_topic} {menu_obj} {serve_part}즐기기 좋아요 🍃",
        ),
        3: (
            f"{cafe}의 {menu_obj} {serve_part}골라 보셔도 좋아요 😊",
            f"{cafe}에서 {menu_obj} {serve_part}만나 보세요 {face}",
        ),
    }
    opener = _pick(openers[min(rank, 3)], seed)
    reason = _reason(item, wanted)
    status = _status_line(item)
    headline = " ".join(part for part in (opener, reason) if part)
    message = " ".join(part for part in (headline, status) if part)
    if not is_valid_message(message):
        headline = f"{cafe}의 {menu_obj} 추천드려요."
        message = f"{headline} {status}"
    return Recommendation(
        rank=rank, message=message, headline=headline, reason=reason, status_line=status
    )


def _emoji_count(text: str) -> int:
    """Pictographs only (misc symbols/dingbats and the emoji planes); Hangul does not count."""
    return sum(1 for ch in text if 0x2600 <= ord(ch) <= 0x27BF or 0x1F000 <= ord(ch) <= 0x1FAFF)


def is_valid_message(text: str) -> bool:
    """Guard rails: no unfilled slots, no mood claims, reasonable length and emoji count."""
    if "{" in text or "}" in text or "None" in text:
        return False
    if any(phrase in text for phrase in BANNED_PHRASES):
        return False
    return len(text) <= MAX_MESSAGE_CHARS and _emoji_count(text) <= MAX_EMOJIS
