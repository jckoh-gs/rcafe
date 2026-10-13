"""Administrator API: sign in, then manage the collection queue (delete, requeue, run now)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.adapters.inbound.http.admin_auth import COOKIE_NAME, AdminAuth
from app.adapters.inbound.http.ratelimit import RateLimiter, client_ip
from app.application.admin import (
    AdminOverview,
    AdminRequestView,
    AdminResult,
    ManageCollectionRequests,
)
from app.domain.ports import CollectorUnavailable

log = logging.getLogger(__name__)

# Sent by the admin page on every call. A browser will not add a custom header to a request from
# another site without a CORS preflight (which this API refuses), so forged requests stay out.
GUARD_HEADER = "x-admin-request"
LOGIN_ATTEMPTS = 10
LOGIN_WINDOW_S = 600.0
FAILED_LOGIN_DELAY_S = 0.5


def get_auth(request: Request) -> AdminAuth:
    auth: AdminAuth = request.app.state.admin_auth
    return auth


def get_admin(request: Request) -> ManageCollectionRequests:
    admin: ManageCollectionRequests = request.app.state.admin
    return admin


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex"


def guard(request: Request, auth: Annotated[AdminAuth, Depends(get_auth)]) -> None:
    if not auth.enabled:
        raise HTTPException(404)  # switched off: look like any other unknown path
    if request.headers.get(GUARD_HEADER) != "1":
        raise HTTPException(403, "허용되지 않은 요청이에요.")


def require_admin(
    request: Request,
    auth: Annotated[AdminAuth, Depends(get_auth)],
    _: Annotated[None, Depends(guard)],
) -> str:
    user = auth.user_for(request.cookies.get(COOKIE_NAME))
    if user is None:
        raise HTTPException(401, "로그인이 필요해요.")
    return user


router = APIRouter(prefix="/api/v1/admin", dependencies=[Depends(no_store)])
Admin = Annotated[str, Depends(require_admin)]
Service = Annotated[ManageCollectionRequests, Depends(get_admin)]


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class SessionOut(BaseModel):
    user: str


class AdminRequestOut(BaseModel):
    id: int
    cell_key: str
    lat: float
    lng: float
    radius_m: int
    status: str
    request_count: int
    requested_at: datetime
    last_requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cafes_found: int | None
    cafes_nearby: int
    note: str | None


class AdminOverviewOut(BaseModel):
    collector_running: bool
    counts: dict[str, int]
    items: list[AdminRequestOut]


class RunOut(BaseModel):
    job: str


def _item(view: AdminRequestView) -> AdminRequestOut:
    r = view.request
    return AdminRequestOut(
        id=r.id,
        cell_key=r.cell_key,
        lat=r.center.lat,
        lng=r.center.lng,
        radius_m=r.radius_m,
        status=r.status.value,
        request_count=r.request_count,
        requested_at=r.requested_at,
        last_requested_at=r.last_requested_at,
        started_at=r.started_at,
        finished_at=r.finished_at,
        cafes_found=r.cafes_found,
        cafes_nearby=view.cafes_nearby,
        note=r.note,
    )


def _overview(overview: AdminOverview) -> AdminOverviewOut:
    return AdminOverviewOut(
        collector_running=overview.collector_running,
        counts={status.value: n for status, n in overview.counts.items()},
        items=[_item(v) for v in overview.items],
    )


def _check(result: AdminResult) -> None:
    match result:
        case AdminResult.OK:
            return
        case AdminResult.NOT_FOUND:
            raise HTTPException(404, "이미 없는 요청이에요. 목록을 새로고침해 주세요.")
        case AdminResult.RUNNING:
            raise HTTPException(409, "수집 중인 요청이에요. 끝난 뒤에 처리해 주세요.")
        case AdminResult.COLLECTOR_BUSY:
            raise HTTPException(409, "다른 수집이 진행 중이에요. 끝난 뒤에 실행해 주세요.")


@router.post("/login", response_model=SessionOut)
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    auth: Annotated[AdminAuth, Depends(get_auth)],
    _: Annotated[None, Depends(guard)],
) -> SessionOut:
    limiter: RateLimiter = request.app.state.admin_login_limiter
    visitor = client_ip(request)
    if not limiter.allow(visitor):
        raise HTTPException(429, "로그인 시도가 너무 많아요. 잠시 후에 다시 시도해 주세요.")
    if not auth.credentials_ok(body.username, body.password):
        log.warning("admin sign-in failed from %s", visitor)
        await asyncio.sleep(FAILED_LOGIN_DELAY_S)  # slows down guessing
        raise HTTPException(401, "아이디 또는 비밀번호가 맞지 않아요.")
    forwarded = request.headers.get("x-forwarded-proto", "")
    response.set_cookie(
        COOKIE_NAME,
        auth.issue_token(),
        max_age=auth.session_seconds,
        path="/api/v1/admin",
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https" or "https" in forwarded,
    )
    return SessionOut(user=body.username)


@router.post("/logout", status_code=204)
async def logout(response: Response, _: Annotated[None, Depends(guard)]) -> None:
    response.delete_cookie(COOKIE_NAME, path="/api/v1/admin")


@router.get("/session", response_model=SessionOut)
async def session(user: Admin) -> SessionOut:
    return SessionOut(user=user)


@router.get("/collection-requests", response_model=AdminOverviewOut)
async def list_requests(_: Admin, service: Service) -> AdminOverviewOut:
    return _overview(await service.overview())


@router.delete("/collection-requests/{request_id}", status_code=204)
async def delete_request(request_id: int, _: Admin, service: Service) -> None:
    _check(await service.delete(request_id))


@router.post("/collection-requests/{request_id}/requeue", status_code=204)
async def requeue_request(request_id: int, _: Admin, service: Service) -> None:
    _check(await service.requeue(request_id))


@router.post("/collection-requests/{request_id}/run", response_model=RunOut, status_code=202)
async def run_request(request_id: int, _: Admin, service: Service) -> RunOut:
    try:
        result, job = await service.run_now(request_id)
    except CollectorUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    _check(result)
    return RunOut(job=job or "")
