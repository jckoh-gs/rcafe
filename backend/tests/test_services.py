from dataclasses import replace

from app.domain.models import (
    BusinessInfo,
    BusinessStatus,
    GeoPoint,
    PlaceDetail,
    SearchHit,
)
from app.domain.services import (
    detail_content_hash,
    filter_hits,
    grid_points,
    haversine_m,
    is_cafe_category,
    is_noise_review,
    snippet,
)

YEOKSAM = GeoPoint(37.5006431, 127.0363766)


def _hit(place_id: str, lat: float, lng: float, category: str = "카페,디저트") -> SearchHit:
    return SearchHit(place_id, "x", GeoPoint(lat, lng), category, None, None, 1, 1.0, False)


def _detail(**overrides: object) -> PlaceDetail:
    base = PlaceDetail(
        place_id="1",
        name="a",
        phone=None,
        rating=4.5,
        review_count=10,
        micro_review=None,
        business=BusinessInfo(BusinessStatus.OPEN, "영업 중"),
        menus=(),
        menu_mentions=(),
        reviews=(),
        photo_urls=(),
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def test_haversine_is_zero_for_same_point_and_about_111km_per_degree() -> None:
    assert haversine_m(YEOKSAM, YEOKSAM) == 0
    one_deg = haversine_m(GeoPoint(37.0, 127.0), GeoPoint(38.0, 127.0))
    assert 110_000 < one_deg < 112_500


def test_grid_points_cover_radius_nearest_first() -> None:
    points = grid_points(YEOKSAM, radius_m=2000, spacing_m=300)
    assert points[0] == YEOKSAM
    assert all(haversine_m(YEOKSAM, p) <= 2000 for p in points)
    assert 100 < len(points) < 200


def test_filter_hits_keeps_only_nearby_cafes() -> None:
    near = _hit("near", 37.5010, 127.0370)
    far = _hit("far", 37.60, 127.10)
    restaurant = _hit("rest", 37.5010, 127.0370, "한식")
    kept = list(filter_hits([near, far, restaurant], YEOKSAM, 2000))
    assert [h.place_id for h in kept] == ["near"]
    assert is_cafe_category("카페,디저트") and not is_cafe_category("한식")


def test_noise_reviews_are_flagged() -> None:
    assert is_noise_review("맛있어요")
    assert is_noise_review("물론! 너무 광고 같은 느낌 말고 두 가지 말투로 바꿔볼게요.")
    assert not is_noise_review("아이스 아메리카노가 시원하고 깔끔해서 더운 날 좋았어요.")


def test_snippet_is_single_line_and_limited() -> None:
    text = "가나다\n라마바 " * 100
    out = snippet(text, 50)
    assert len(out) == 50 and "\n" not in out and out.endswith("…")


def test_content_hash_is_stable_and_changes_with_content() -> None:
    assert detail_content_hash(_detail()) == detail_content_hash(_detail())
    assert detail_content_hash(_detail()) != detail_content_hash(_detail(rating=4.6))
