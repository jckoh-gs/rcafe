"""Pure domain logic: geometry, filtering, review noise detection, content hashing."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Iterator
from dataclasses import asdict

from app.domain.models import GeoPoint, PlaceDetail, SearchHit

EARTH_RADIUS_M = 6_371_000.0
CAFE_CATEGORY_HINTS = ("카페", "커피", "디저트", "베이커리", "제과", "브런치", "다방", "찻집", "차")
NOISE_PHRASES = (
    "물론!",
    "바꿔볼게요",
    "말투로",
    "다음과 같이",
    "리뷰를 작성",
    "AI",
    "챗GPT",
    "ChatGPT",
)
MIN_REVIEW_CHARS = 10
MAX_SNIPPET_CHARS = 200


def haversine_m(a: GeoPoint, b: GeoPoint) -> float:
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlng = math.radians(b.lng - a.lng)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def grid_points(center: GeoPoint, radius_m: float, spacing_m: float) -> list[GeoPoint]:
    """Square grid covering the circle around `center`, nearest points first."""
    if radius_m <= 0 or spacing_m <= 0:
        raise ValueError("radius_m and spacing_m must be positive")
    m_per_deg_lat = math.pi * EARTH_RADIUS_M / 180
    m_per_deg_lng = m_per_deg_lat * math.cos(math.radians(center.lat))
    steps = int(radius_m // spacing_m)
    points: list[GeoPoint] = []
    for i in range(-steps, steps + 1):
        for j in range(-steps, steps + 1):
            p = GeoPoint(
                lat=center.lat + (i * spacing_m) / m_per_deg_lat,
                lng=center.lng + (j * spacing_m) / m_per_deg_lng,
            )
            if haversine_m(center, p) <= radius_m:
                points.append(p)
    points.sort(key=lambda p: haversine_m(center, p))
    return points


CELL_DEG = 0.01  # about 1.1 km north-south and 0.9 km east-west in Korea


def cell_for(point: GeoPoint) -> tuple[str, GeoPoint]:
    """The collection cell a point belongs to: (stable key, cell center)."""
    row, col = round(point.lat / CELL_DEG), round(point.lng / CELL_DEG)
    return f"{row}:{col}", GeoPoint(round(row * CELL_DEG, 5), round(col * CELL_DEG, 5))


def is_cafe_category(category: str) -> bool:
    return any(hint in category for hint in CAFE_CATEGORY_HINTS)


def filter_hits(
    hits: Iterable[SearchHit], center: GeoPoint, radius_m: float
) -> Iterator[SearchHit]:
    """Keep cafe-like places inside the radius."""
    for hit in hits:
        if is_cafe_category(hit.category) and haversine_m(center, hit.point) <= radius_m:
            yield hit


def is_noise_review(text: str) -> bool:
    """True for empty, tiny, or chatbot/meta-text reviews that should not feed taste analysis."""
    stripped = text.strip()
    if len(stripped) < MIN_REVIEW_CHARS:
        return True
    return any(phrase in stripped for phrase in NOISE_PHRASES)


def snippet(text: str, limit: int = MAX_SNIPPET_CHARS) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= limit else one_line[: limit - 1] + "…"


def detail_content_hash(detail: PlaceDetail) -> str:
    """Stable hash of the stored detail content (volatile timestamps excluded)."""
    payload = json.dumps(asdict(detail), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
