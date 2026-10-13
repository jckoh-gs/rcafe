"""Naver map instant-search adapter (PlaceSearchPort)."""

from __future__ import annotations

import re
from typing import Any

from app.adapters.outbound.clients.throttled_http import ThrottledClient
from app.domain.models import GeoPoint, SearchHit

SEARCH_URL = "https://map.naver.com/p/api/search/instant-search"
_TAG_RE = re.compile(r"<[^>]+>")


def parse_search_response(payload: dict[str, Any]) -> list[SearchHit]:
    hits: list[SearchHit] = []
    for raw in payload.get("place") or []:
        try:
            review = raw.get("review") or {}
            hits.append(
                SearchHit(
                    place_id=str(raw["id"]),
                    name=_TAG_RE.sub("", str(raw["title"])).strip(),
                    point=GeoPoint(lat=float(raw["y"]), lng=float(raw["x"])),
                    category=str(raw.get("ctg") or ""),
                    road_address=raw.get("roadAddress") or None,
                    jibun_address=raw.get("jibunAddress") or None,
                    review_count=int(review.get("count") or 0),
                    rank_score=float(raw.get("totalScore") or 0.0),
                    has_booking=bool(raw.get("hasBooking")),
                )
            )
        except (KeyError, ValueError, TypeError):
            continue  # skip malformed entries instead of failing the whole crawl
    return hits


class NaverSearchClient:
    def __init__(self, http: ThrottledClient) -> None:
        self._http = http

    async def search(self, query: str, center: GeoPoint) -> list[SearchHit]:
        response = await self._http.get(
            SEARCH_URL, params={"query": query, "coords": f"{center.lat},{center.lng}"}
        )
        if response is None:
            return []
        payload = response.json()
        if not isinstance(payload, dict):
            return []
        return parse_search_response(payload)
