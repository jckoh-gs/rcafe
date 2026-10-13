"""Scoring and selection of cafes for the taste the weather calls for."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.domain.models import BusinessInfo, BusinessStatus, DayHours, GeoPoint
from app.domain.services import haversine_m
from app.domain.taste import (
    AxisStats,
    MenuEvidence,
    TasteVector,
    best_menu_for,
    is_beverage,
    is_orderable_menu,
    menu_family,
    taste_similarity,
)

WEEKDAYS = "월화수목금토일"
FRESH_STATUS_MINUTES = 60
WALK_M_PER_MIN = 70.0

# Final score weights (PRD 5.4); tunable.
W_TASTE = 0.55
W_QUALITY = 0.20
W_DISTANCE = 0.15
W_MENU = 0.10
NO_DRINKS_FACTOR = 0.75  # bakeries and pastry shops without a single drink rank lower
# Cafes whose reviews are mostly about drinks rank above bakery-type shops with a coffee machine:
# score *= DRINK_SHARE_FLOOR + (1 - DRINK_SHARE_FLOOR) * share_of_drink_mentions
DRINK_SHARE_FLOOR = 0.8
DIVERSITY_PENALTY = 0.05  # per earlier pick of the same drink family on the podium


@dataclass(frozen=True, slots=True)
class Candidate:
    place_id: str
    name: str
    point: GeoPoint
    road_address: str | None
    rating: float | None
    review_count: int
    taste: TasteVector
    confidence: float
    menus: tuple[MenuEvidence, ...]
    business: BusinessInfo
    status_checked_at: datetime | None
    review_axis_counts: dict[str, int]
    review_total: int
    cover_photo_url: str | None
    photo_urls: tuple[str, ...]
    # (label, count) pairs of what reviewers mention most, e.g. ('라떼', 392)
    menu_mentions: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class OpenState:
    is_open: bool | None  # None: unknown
    label: str
    changes_at: str | None = None  # "HH:MM" of the next closing (if open) or opening (if closed)
    changes_tomorrow: bool = False


@dataclass(frozen=True, slots=True)
class ScoredCafe:
    candidate: Candidate
    score: float
    taste_fit: float
    quality: float
    nearness: float
    menu_fit: float
    menu: MenuEvidence | None
    open_state: OpenState
    distance_m: float


# --- opening hours -----------------------------------------------------------------------------


def _minutes(hhmm: str | None) -> int | None:
    if not hhmm or ":" not in hhmm:
        return None
    hours, minutes = hhmm.split(":", 1)
    try:
        return int(hours) * 60 + int(minutes)
    except ValueError:
        return None


_DAY_LABEL_NOISE = re.compile(r"\([^)]*\)")


def weekdays_in(label: str) -> set[int]:
    """Weekday numbers (Mon=0) a label like '금(10/9)', '매일', '평일', '월~금', '토,일' covers."""
    text = _DAY_LABEL_NOISE.sub("", label).strip()
    if "매일" in text:
        return set(range(7))
    if "평일" in text:
        return set(range(5))
    if "주말" in text:
        return {5, 6}
    days: set[int] = set()
    for a, b in re.findall(r"([월화수목금토일])\s*[~\-\u2013]\s*([월화수목금토일])", text):
        i, j = WEEKDAYS.index(a), WEEKDAYS.index(b)
        days |= set(range(i, j + 1)) if i <= j else set(range(i, 7)) | set(range(0, j + 1))
    text = re.sub(r"([월화수목금토일])\s*[~\-\u2013]\s*([월화수목금토일])", "", text)
    days |= {WEEKDAYS.index(ch) for ch in text if ch in WEEKDAYS}
    return days


_LABEL_DATE = re.compile(r"\((\d{1,2})/(\d{1,2})\)")


def _label_date(label: str) -> tuple[int, int] | None:
    """('금(10/9)' -> (10, 9)); None for plain weekday labels such as '금' or '매일'."""
    match = _LABEL_DATE.search(label)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _entries_on(hours: Sequence[DayHours], day: date) -> list[DayHours]:
    """Entries that apply on a calendar day.

    Naver lists either weekly rows ('월', '매일') or rows for the next seven dates ('토(10/10)').
    An entry for exactly that date wins, then a weekly row, then (stale) a dated row of the same
    weekday.
    """
    weekday = day.weekday()
    exact = [h for h in hours if _label_date(h.day) == (day.month, day.day)]
    if exact:
        return exact
    weekly = [h for h in hours if _label_date(h.day) is None and weekday in weekdays_in(h.day)]
    if weekly:
        return weekly
    return [h for h in hours if _label_date(h.day) is not None and weekday in weekdays_in(h.day)]


def open_by_hours(hours: Sequence[DayHours], now: datetime) -> OpenState | None:
    """Open/closed from the opening hours; None when there is nothing for today."""
    day = now.date()
    today = _entries_on(hours, day)
    if not today:
        return None
    minute = now.hour * 60 + now.minute
    # an overnight shift that started yesterday may still be running
    for entry in _entries_on(hours, day - timedelta(days=1)):
        start, end = _minutes(entry.start), _minutes(entry.end)
        if start is not None and end is not None and end <= start and minute < end:
            return OpenState(True, "영업 중", entry.end)
    for entry in today:
        start, end = _minutes(entry.start), _minutes(entry.end)
        if start is None or end is None:
            continue
        overnight = end <= start
        if minute >= start and (overnight or minute < end):
            return OpenState(True, "영업 중", entry.end)
        if minute < start:
            return OpenState(False, "영업 전", entry.start)
    nxt = _entries_on(hours, day + timedelta(days=1))
    opens = next((e.start for e in nxt if _minutes(e.start) is not None), None)
    return OpenState(False, "영업 종료", opens, changes_tomorrow=True)


# --- showing the hours ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HoursRow:
    days: str  # '월~금', '토·일', '매일', '금'
    text: str  # '09:00 ~ 22:00', '휴무', '11:00 ~ 익일 01:00'
    is_today: bool


def _entry_text(entry: DayHours) -> str:
    start, end = _minutes(entry.start), _minutes(entry.end)
    note = (entry.description or "").strip()
    if start is None or end is None:
        return "정기휴무" if note.startswith("정기휴무") else (note or "휴무")
    if start == 0 and end in (0, 24 * 60):
        return "24시간 영업"
    shown_end = f"익일 {entry.end}" if end <= start else str(entry.end)
    text = f"{entry.start} ~ {shown_end}"
    return f"{text} ({note})" if note and not note.startswith("정기휴무") else text


def _day_text(entries: Sequence[DayHours]) -> str | None:
    texts = list(dict.fromkeys(_entry_text(e) for e in entries))
    return ", ".join(texts) if texts else None


def hours_today(hours: Sequence[DayHours], today: date) -> str | None:
    """Today's opening hours as text, or None when the cafe has no hours on file."""
    return _day_text(_entries_on(hours, today))


def _run_label(weekdays: Sequence[int]) -> str:
    if len(weekdays) == 7:
        return "매일"
    names = [WEEKDAYS[d] for d in weekdays]
    if len(names) == 1:
        return names[0]
    return "·".join(names) if len(names) == 2 else f"{names[0]}~{names[-1]}"


def weekly_hours(hours: Sequence[DayHours], today: date) -> list[HoursRow]:
    """The week at a glance, Monday first; consecutive days with the same hours are merged."""
    texts: dict[int, str] = {}
    for offset in range(7):  # the next seven calendar days cover every weekday exactly once
        day = today + timedelta(days=offset)
        text = _day_text(_entries_on(hours, day))
        if text is not None:
            texts[day.weekday()] = text
    rows: list[HoursRow] = []
    run: list[int] = []
    for weekday in range(7):
        same_as_run = run and weekday in texts and texts.get(run[-1]) == texts[weekday]
        if run and not same_as_run:
            rows.append(HoursRow(_run_label(run), texts[run[0]], today.weekday() in run))
            run = []
        if weekday in texts:
            run.append(weekday)
    if run:
        rows.append(HoursRow(_run_label(run), texts[run[0]], today.weekday() in run))
    return rows


def closed_all_week(hours: Sequence[DayHours]) -> bool:
    """True when every listed day is a closed day (temporary closure or a shop that shut down)."""
    return bool(hours) and all(_minutes(h.start) is None or _minutes(h.end) is None for h in hours)


def open_state(business: BusinessInfo, checked_at: datetime | None, now: datetime) -> OpenState:
    """Prefer the freshly crawled status; otherwise derive it from the weekly hours."""
    fresh = checked_at is not None and now - checked_at <= timedelta(minutes=FRESH_STATUS_MINUTES)
    if fresh and business.status is not BusinessStatus.UNKNOWN:
        is_open = business.status is BusinessStatus.OPEN
        return OpenState(is_open, "영업 중" if is_open else "영업 종료")
    derived = open_by_hours(business.hours, now)
    if derived is not None:
        return derived
    return OpenState(None, "영업 정보 없음")


# --- scoring -------------------------------------------------------------------------------------


def drink_share(mentions: Sequence[tuple[str, int]]) -> float:
    """Share of review mentions that are about drinks (0.5 when nothing is known)."""
    total = sum(count for _, count in mentions)
    if total <= 0:
        return 0.5
    return sum(count for label, count in mentions if is_beverage(label)) / total


def quality_score(
    rating: float | None, review_count: int, prior: float = 4.3, m: int = 20
) -> float:
    """Bayesian-smoothed rating (0..1) blended with log popularity."""
    r = rating if rating is not None else prior
    smoothed = (r * review_count + prior * m) / (review_count + m)
    rating_part = max(0.0, min(1.0, (smoothed - 3.5) / 1.5))
    popularity = max(0.0, min(1.0, math.log10(1 + review_count) / 3.5))
    return 0.7 * rating_part + 0.3 * popularity


def nearness_score(distance_m: float, radius_m: float) -> float:
    return math.exp(-distance_m / max(1.0, 0.6 * radius_m))


def score_candidates(
    candidates: Sequence[Candidate],
    wanted: TasteVector,
    stats: AxisStats,
    origin: GeoPoint,
    radius_m: float,
    now: datetime,
) -> list[ScoredCafe]:
    scored: list[ScoredCafe] = []
    for c in candidates:
        distance = haversine_m(origin, c.point)
        if distance > radius_m:
            continue
        if closed_all_week(c.business.hours):
            continue  # listed as closed for the whole week: not something to recommend
        taste_fit = taste_similarity(wanted, c.taste, stats) * (0.6 + 0.4 * c.confidence)
        best = best_menu_for(wanted, c.menus, stats)
        menu, menu_fit = (best[0], max(0.0, min(1.0, best[1]))) if best else (None, 0.0)
        if menu is None:
            continue  # a cafe without an orderable menu cannot be recommended
        quality = quality_score(c.rating, c.review_count)
        nearness = nearness_score(distance, radius_m)
        total = (
            W_TASTE * taste_fit + W_QUALITY * quality + W_DISTANCE * nearness + W_MENU * menu_fit
        )
        if not any(is_beverage(m.name) for m in c.menus if is_orderable_menu(m.name)):
            total *= NO_DRINKS_FACTOR
        total *= DRINK_SHARE_FLOOR + (1 - DRINK_SHARE_FLOOR) * drink_share(c.menu_mentions)
        scored.append(
            ScoredCafe(
                c,
                total,
                taste_fit,
                quality,
                nearness,
                menu_fit,
                menu,
                open_state(c.business, c.status_checked_at, now),
                distance,
            )
        )
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored


def brand_key(name: str) -> str:
    """'투썸플레이스 논현역사거리점' -> '투썸플레이스' (chains must not fill the whole podium)."""
    return name.split()[0] if name.split() else name


def _family(item: ScoredCafe) -> str:
    return menu_family(item.menu.name) if item.menu else ""


def select_top(scored: Sequence[ScoredCafe], count: int = 3, min_open: int = 2) -> list[ScoredCafe]:
    """Best `count` cafes: one per brand, a varied podium, and at least `min_open` open right now.

    Each pick is the best remaining score minus a small penalty per earlier pick of the same
    drink family (three americanos in a row is a poor answer). If the picks are mostly closed,
    the best open cafes replace the lowest-scored closed picks. Display order stays by score.
    """
    unique: list[ScoredCafe] = []
    seen_brands: set[str] = set()
    for s in scored:
        brand = brand_key(s.candidate.name)
        if brand in seen_brands:
            continue
        seen_brands.add(brand)
        unique.append(s)

    chosen: list[ScoredCafe] = []
    remaining = list(unique)
    while remaining and len(chosen) < count:
        used = Counter(_family(s) for s in chosen)
        best = max(remaining, key=lambda s: s.score - DIVERSITY_PENALTY * used[_family(s)])
        chosen.append(best)
        remaining.remove(best)

    open_needed = min(min_open, count)
    for replacement in (s for s in remaining if s.open_state.is_open):
        if sum(1 for s in chosen if s.open_state.is_open) >= open_needed:
            break
        closed = [s for s in chosen if not s.open_state.is_open]
        if not closed:
            break
        chosen.remove(min(closed, key=lambda s: s.score))
        chosen.append(replacement)
    chosen.sort(key=lambda s: s.score, reverse=True)
    return chosen


def select_more(
    scored: Sequence[ScoredCafe], chosen: Sequence[ScoredCafe], count: int = 10, min_open: int = 0
) -> list[ScoredCafe]:
    """The next `count` cafes after the podium, for the "show more" list.

    Same rules as the podium (one per brand, a varied mix, score order) but never a brand that is
    already on it, so the extra list adds new places instead of more branches of the same chain.
    """
    taken = {brand_key(s.candidate.name) for s in chosen}
    rest = [s for s in scored if brand_key(s.candidate.name) not in taken]
    return select_top(rest, count=count, min_open=min_open)


def walking_minutes(distance_m: float) -> int:
    return max(1, round(distance_m / WALK_M_PER_MIN))
