import json
from collections.abc import Mapping

from app.adapters.outbound.clients.naver_place import (
    extract_apollo_state,
    parse_home,
    parse_reviews,
)
from app.adapters.outbound.clients.naver_search import parse_search_response
from app.domain.models import BusinessStatus
from tests.conftest import load_fixture


def _html(state: Mapping[str, object]) -> str:
    return (
        f"<html><script>window.__APOLLO_STATE__={json.dumps(state, ensure_ascii=False)};</script>"
    )


def test_extract_apollo_state_handles_braces_inside_strings() -> None:
    state = {"a": "text with } and { braces", "b": {"c": 1}}
    assert extract_apollo_state(_html(state)) == state
    assert extract_apollo_state("<html>no state</html>") is None


def test_parse_search_response() -> None:
    hits = parse_search_response(load_fixture("instant_search.json"))
    assert len(hits) == 3
    first = hits[0]
    assert first.place_id and first.name and first.category
    assert 37 < first.point.lat < 38 and 126 < first.point.lng < 128
    assert first.review_count > 0


def test_parse_home_regular_menus_and_status() -> None:
    detail = parse_home(load_fixture("home_regular.json"), "1000000001")
    assert detail is not None
    assert detail.name == "샘플커피랩 역삼점"
    assert detail.business.status is BusinessStatus.OPEN
    assert detail.business.hours and detail.business.hours[0].start
    assert len(detail.menus) == 4
    assert detail.menus[0].name == "에스프레소" and detail.menus[0].price == 6500
    assert detail.menu_mentions and detail.menu_mentions[0][0] == "커피"
    assert detail.cover_photo_url and detail.photo_urls


def test_parse_home_delivery_menus_use_baemin_entries() -> None:
    detail = parse_home(load_fixture("home_delivery.json"), "1000000002")
    assert detail is not None
    assert detail.business.status is BusinessStatus.CLOSED
    assert [m.name for m in detail.menus][:1] == ["시그니처 라떼"]
    assert detail.menus[0].price == 5600 and detail.menus[0].image_url
    assert detail.menus[0].menu_key.startswith("bm:")
    # mention counts are per generic word ("라떼"), so they stay at cafe level, not per menu item
    assert detail.menus[0].mention_count is None
    assert ("라떼", 392) in detail.menu_mentions


def test_parse_home_returns_none_without_base() -> None:
    assert parse_home({"ROOT_QUERY": {}}, "1") is None


def test_parse_reviews_flags_noise_and_limits() -> None:
    reviews = parse_reviews(load_fixture("reviews.json"))
    assert len(reviews) == 4
    assert [r.is_noise for r in reviews] == [False, False, True, True]
    assert reviews[0].review_key and reviews[0].photo_url is None  # video-only review
    assert reviews[1].photo_url  # image review keeps its thumbnail
    assert (
        reviews[0].ordered_item == "아메리카노" and "커피가 맛있어요" in reviews[0].voted_keywords
    )
    assert len(parse_reviews(load_fixture("reviews.json"), limit=2)) == 2


def test_price_parsing_takes_the_first_number_and_rejects_absurd_values() -> None:
    from app.adapters.outbound.clients.naver_place import _price

    assert _price("6,500원") == 6500
    assert _price("2,850원 ~ 3,000원") == 2850  # ranges must not be glued into one huge number
    assert _price("5600") == 5600
    assert _price("가격 문의") is None
    assert _price("285,003,000원") is None
    assert _price(None) is None
