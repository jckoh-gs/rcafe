"""Routes for visitors to ask for an area to be collected (done later, in quiet hours)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.adapters.inbound.http.ratelimit import RateLimiter, client_ip
from app.application.collection import (
    KST,
    RequestCollection,
    RequestOutcome,
    RequestStatus,
)
from app.domain.models import GeoPoint

router = APIRouter(prefix="/api/v1")

PER_VISITOR_LIMIT = 5  # requests per hour from one address


class CollectionRequestIn(BaseModel):
    lat: float = Field(ge=33.0, le=39.0, description="위도")
    lng: float = Field(ge=124.0, le=132.0, description="경도")


class CollectionRequestOut(BaseModel):
    status: str  # one of RequestStatus, or "none" when nobody has asked yet
    request_count: int
    cafes_found: int | None
    message: str
    next_run_at: datetime | None


def get_service(request: Request) -> RequestCollection:
    service: RequestCollection = request.app.state.collection
    return service


def get_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.collection_limiter
    return limiter


def _when(next_run: datetime | None) -> str:
    if next_run is None:
        return "한가한 새벽"
    local = next_run.astimezone(KST)
    day = "오늘" if local.date() == datetime.now(KST).date() else "내일"
    return f"{day} 새벽 {local.hour}시 {local.minute:02d}분 무렵"


def _message(outcome: RequestOutcome) -> str:
    when = _when(outcome.next_run)
    match outcome.status:
        case RequestStatus.QUEUED:
            return f"요청을 받았어요! 서비스가 한가한 {when}에 수집하고, 끝나면 추천해 드려요."
        case RequestStatus.ALREADY_QUEUED:
            return (
                f"이미 수집 대기 중이에요 (지금까지 {outcome.request_count}번 요청됐어요). "
                f"{when}에 수집해요."
            )
        case RequestStatus.COLLECTING:
            return "지금 이 지역을 수집하고 있어요. 끝나면 새로고침해 보세요."
        case RequestStatus.DONE:
            if outcome.cafes_found == 0:
                return "이 지역을 확인해 봤지만 등록된 카페를 찾지 못했어요."
            return (
                f"수집이 끝났어요 (카페 {outcome.cafes_found}곳). 새로고침하면 추천을 볼 수 있어요."
            )
        case RequestStatus.COVERED:
            return "이 지역은 이미 카페 정보가 있어요. 지도에서 위치를 조금 옮겨 보세요."
        case RequestStatus.BUSY:
            return "지금은 요청이 많아 잠시 후에 다시 요청해 주세요."
        case RequestStatus.LIMIT:
            return "오늘 받을 수 있는 새 지역 요청이 모두 찼어요. 내일 다시 요청해 주세요."
    return ""


def _out(outcome: RequestOutcome) -> CollectionRequestOut:
    return CollectionRequestOut(
        status=outcome.status.value,
        request_count=outcome.request_count,
        cafes_found=outcome.cafes_found,
        message=_message(outcome),
        next_run_at=outcome.next_run,
    )


@router.post("/collection-requests", response_model=CollectionRequestOut)
async def request_collection(
    body: CollectionRequestIn,
    request: Request,
    service: Annotated[RequestCollection, Depends(get_service)],
    limiter: Annotated[RateLimiter, Depends(get_limiter)],
) -> CollectionRequestOut:
    if not limiter.allow(client_ip(request)):
        raise HTTPException(429, "요청이 너무 잦아요. 잠시 후에 다시 시도해 주세요.")
    outcome = await service.submit(GeoPoint(body.lat, body.lng))
    if outcome.status in (RequestStatus.BUSY, RequestStatus.LIMIT):
        raise HTTPException(429, _message(outcome))
    return _out(outcome)


@router.get("/collection-requests", response_model=CollectionRequestOut)
async def collection_status(
    service: Annotated[RequestCollection, Depends(get_service)],
    lat: Annotated[float, Query(ge=33.0, le=39.0)],
    lng: Annotated[float, Query(ge=124.0, le=132.0)],
) -> CollectionRequestOut:
    outcome = await service.status(GeoPoint(lat, lng))
    if outcome is None:
        return CollectionRequestOut(
            status="none", request_count=0, cafes_found=None, message="", next_run_at=None
        )
    return _out(outcome)
