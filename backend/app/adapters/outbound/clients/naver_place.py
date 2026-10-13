"""Naver place detail adapter (PlaceDetailPort).

The detail pages are server-rendered and embed an Apollo cache as
`window.__APOLLO_STATE__ = {...}`. We parse that JSON; no login or cookies are needed.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any

from app.adapters.outbound.clients.throttled_http import ThrottledClient
from app.domain.models import (
    BusinessInfo,
    BusinessStatus,
    DayHours,
    MenuItem,
    PlaceDetail,
    Review,
)
from app.domain.services import is_noise_review

HOME_URL = "https://pcmap.place.naver.com/place/{place_id}/home"
# Cafes use the "restaurant" business type; /place/ would redirect there (one extra request).
REVIEW_URL = "https://pcmap.place.naver.com/restaurant/{place_id}/review/visitor"
REVIEW_FALLBACK_URL = "https://pcmap.place.naver.com/place/{place_id}/review/visitor"
APOLLO_MARKER = "window.__APOLLO_STATE__"
MAX_REVIEWS = 10
MAX_PHOTOS = 12
MAX_MENU_MENTIONS = 10

State = dict[str, Any]


def extract_apollo_state(html: str) -> State | None:
    marker = html.find(APOLLO_MARKER)
    if marker < 0:
        return None
    brace = html.find("{", marker)
    if brace < 0:
        return None
    try:
        state, _ = json.JSONDecoder().raw_decode(html, brace)
    except json.JSONDecodeError:
        return None
    return state if isinstance(state, dict) else None


def _deref(state: State, value: Any) -> Any:
    if isinstance(value, dict) and "__ref" in value:
        return state.get(value["__ref"])
    return value


def _place_detail_root(state: State) -> State:
    root = state.get("ROOT_QUERY") or {}
    for key, value in root.items():
        if key.startswith("placeDetail(") and isinstance(value, dict):
            return value
    return {}


_FIRST_NUMBER = re.compile(r"\d[\d,]*")
MAX_PRICE = 1_000_000


def _price(text: Any) -> int | None:
    """First number in the text ('2,850원 ~ 3,000원' -> 2850); None if absent or absurd."""
    match = _FIRST_NUMBER.search(str(text or ""))
    if match is None:
        return None
    value = int(match.group().replace(",", ""))
    return value if 0 < value <= MAX_PRICE else None


def _status(text: str | None) -> BusinessStatus:
    if not text:
        return BusinessStatus.UNKNOWN
    if "영업 중" in text or "라스트오더" in text:
        return BusinessStatus.OPEN
    return BusinessStatus.CLOSED


def _parse_business(root: State) -> BusinessInfo:
    blocks = root.get("newBusinessHours") or []
    if not blocks:
        return BusinessInfo(BusinessStatus.UNKNOWN, None)
    block = blocks[0]
    desc = block.get("businessStatusDescription") or {}
    status_text = desc.get("status")
    detail = desc.get("description")
    hours = tuple(
        DayHours(
            day=str(h.get("day") or ""),
            start=(h.get("businessHours") or {}).get("start"),
            end=(h.get("businessHours") or {}).get("end"),
            description=h.get("description"),
        )
        for h in block.get("businessHours") or []
    )
    text = f"{status_text} · {detail}" if status_text and detail else status_text
    return BusinessInfo(_status(status_text), text, hours)


def _parse_menus(state: State, root: State, mentions: dict[str, int]) -> tuple[MenuItem, ...]:
    menus: dict[str, MenuItem] = {}
    place_menus = _deref(state, root.get("placeMenus")) or {}
    for ref in place_menus.get("items") or []:
        item = _deref(state, ref)
        if not item or not item.get("name"):
            continue
        images = item.get("images") or []
        menus[item["name"]] = MenuItem(
            menu_key=str(item.get("id") or item["name"]),
            name=item["name"],
            price=_price((item.get("price") or {}).get("displayText")),
            description=item.get("description"),
            image_url=item.get("thumbnailUrl") or (images[0] if images else None),
            mention_count=mentions.get(item["name"]),
        )
    for key, value in state.items():  # delivery-linked stores expose their menu this way
        if not key.startswith("PlaceDetail_BaeminMenu:") or not value.get("name"):
            continue
        name = value["name"]
        if name in menus:
            continue
        images = value.get("images") or []
        menus[name] = MenuItem(
            menu_key=f"bm:{value.get('id') or name}",
            name=name,
            price=_price(value.get("price")),
            description=value.get("desc"),
            image_url=images[0] if images else None,
            mention_count=mentions.get(name),
        )
    return tuple(menus.values())


def _parse_mentions(state: State, root: State) -> tuple[tuple[str, int], ...]:
    stats = _deref(state, root.get("visitorReviewStats")) or {}
    menus = (stats.get("analysis") or {}).get("menus") or []
    pairs = [(str(m["label"]), int(m["count"])) for m in menus if m.get("label")]
    return tuple(pairs[:MAX_MENU_MENTIONS])


def _parse_photos(state: State, root: State) -> tuple[tuple[str, ...], str | None]:
    urls: list[str] = []
    cover: str | None = None
    top = _deref(state, root.get("topPhotos")) or {}
    for ref in top.get("items") or []:
        photo = _deref(state, ref) or {}
        url = photo.get("originalUrl")
        if url and not photo.get("video"):
            urls.append(url)
            cover = cover or url
    for image in root.get("menuImages") or []:
        if image.get("imageUrl"):
            urls.append(image["imageUrl"])
    return tuple(dict.fromkeys(urls))[:MAX_PHOTOS], cover


def parse_home(state: State, place_id: str) -> PlaceDetail | None:
    root = _place_detail_root(state)
    base = state.get(f"PlaceDetailBase:{place_id}") or _deref(state, root.get("base"))
    if not base or not base.get("name"):
        return None
    mentions = dict(_parse_mentions(state, root))
    photos, cover = _parse_photos(state, root)
    micro = base.get("microReviews") or []
    score = base.get("visitorReviewsScore")
    return PlaceDetail(
        place_id=place_id,
        name=base["name"],
        phone=base.get("phone"),
        rating=float(score) if score is not None else None,
        review_count=base.get("visitorReviewsTotal"),
        micro_review=micro[0] if micro else None,
        business=_parse_business(root),
        menus=_parse_menus(state, root, mentions),
        menu_mentions=tuple(mentions.items()),
        reviews=(),
        photo_urls=photos,
        cover_photo_url=cover,
        conveniences=tuple(base.get("conveniences") or ()),
    )


def parse_reviews(state: State, limit: int = MAX_REVIEWS) -> tuple[Review, ...]:
    """Parse the review list that was requested with `includeContent: true`."""
    root = state.get("ROOT_QUERY") or {}
    for key, value in root.items():
        if not (key.startswith("visitorReviews(") and '"includeContent":true' in key):
            continue
        reviews: list[Review] = []
        for ref in (value or {}).get("items") or []:
            item = _deref(state, ref) or {}
            body = str(item.get("body") or "").strip()
            if not body:
                continue
            media = item.get("media") or []
            photo = next((m.get("thumbnail") for m in media if m.get("type") == "image"), None)
            reviews.append(
                Review(
                    review_key=str(item.get("reviewId") or item.get("id")),
                    rating=item.get("rating"),
                    text=body,
                    visited_label=item.get("visited"),
                    ordered_item=(item.get("item") or {}).get("name"),
                    photo_url=photo or item.get("thumbnail"),
                    voted_keywords=tuple(
                        k["name"] for k in item.get("votedKeywords") or [] if k.get("name")
                    ),
                    is_noise=is_noise_review(body),
                )
            )
            if len(reviews) >= limit:
                break
        return tuple(reviews)
    return ()


class NaverPlaceClient:
    def __init__(self, http: ThrottledClient, review_limit: int = MAX_REVIEWS) -> None:
        self._http = http
        self._review_limit = review_limit

    async def fetch_detail(self, place_id: str) -> PlaceDetail | None:
        home = await self._http.get(HOME_URL.format(place_id=place_id))
        if home is None:
            return None
        home_state = extract_apollo_state(home.text)
        detail = parse_home(home_state, place_id) if home_state else None
        if detail is None:
            return None
        review_page = await self._http.get(REVIEW_URL.format(place_id=place_id))
        if review_page is None:
            review_page = await self._http.get(REVIEW_FALLBACK_URL.format(place_id=place_id))
        reviews: tuple[Review, ...] = ()
        if review_page is not None:
            review_state = extract_apollo_state(review_page.text)
            if review_state:
                reviews = parse_reviews(review_state, self._review_limit)
        review_photos = tuple(r.photo_url for r in reviews if r.photo_url and not r.is_noise)
        photos = tuple(dict.fromkeys((*detail.photo_urls, *review_photos)))[:MAX_PHOTOS]
        return replace(detail, reviews=reviews, photo_urls=photos)
