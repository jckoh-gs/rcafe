"""Administrator: sign-in, the queue API, and starting a run in the cluster."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.adapters.inbound.http.admin_auth import COOKIE_NAME, AdminAuth
from app.adapters.inbound.http.admin_routes import router
from app.adapters.inbound.http.ratelimit import RateLimiter
from app.adapters.outbound.clients.k8s_collector import (
    KubernetesCollectorLauncher,
    UnavailableCollectorLauncher,
    in_cluster_launcher,
)
from app.application.admin import AdminResult, ManageCollectionRequests
from app.domain.models import CollectionStatus, GeoPoint
from app.domain.ports import CollectorUnavailable
from tests.fakes import FakeCollectionRepo

KST = timezone(timedelta(hours=9))
NOON = datetime(2026, 10, 10, 12, 0, tzinfo=KST)
PASSWORD = "correct horse battery"
KEY = "k" * 32
POINT = GeoPoint(37.4878, 126.7886)
GUARD = {"x-admin-request": "1"}


class FakeLauncher:
    def __init__(self, running: bool = False, unavailable: bool = False) -> None:
        self.running = running
        self.unavailable = unavailable
        self.launched: list[int] = []

    async def is_running(self) -> bool:
        return self.running

    async def launch(self, request_id: int) -> str:
        if self.unavailable:
            raise CollectorUnavailable("클러스터 안에서만 즉시 실행을 쓸 수 있어요.")
        self.launched.append(request_id)
        return f"job-{request_id}"


async def _queued(repo: FakeCollectionRepo, point: GeoPoint = POINT, count: int = 1) -> int:
    for _ in range(count):
        request, _ = await repo.submit(point, NOON, 1500)
    return request.id


# --- sign-in -----------------------------------------------------------------------------------


def test_the_session_cookie_is_signed_and_expires() -> None:
    now = [1_000_000.0]
    auth = AdminAuth("admin", PASSWORD, KEY, session_hours=1, now=lambda: now[0])
    token = auth.issue_token()
    assert auth.user_for(token) == "admin"
    assert auth.user_for(None) is None and auth.user_for("") is None
    assert auth.user_for(token[:-1] + ("0" if token[-1] != "0" else "1")) is None  # tampered
    expires, _, signature = token.partition(".")
    assert auth.user_for(f"{int(expires) + 999}.{signature}") is None  # extended expiry
    other = AdminAuth("admin", PASSWORD, "z" * 32, now=lambda: now[0])
    assert other.user_for(token) is None  # signed with another key
    now[0] += 3601
    assert auth.user_for(token) is None  # expired


def test_weak_or_missing_settings_keep_the_admin_off() -> None:
    assert AdminAuth("admin", PASSWORD, KEY).enabled
    assert not AdminAuth("", PASSWORD, KEY).enabled
    assert not AdminAuth("admin", "short", KEY).enabled
    assert not AdminAuth("admin", PASSWORD, "tiny").enabled
    assert not AdminAuth("admin", "short", KEY).credentials_ok("admin", "short")


def test_only_the_exact_credentials_are_accepted() -> None:
    auth = AdminAuth("admin", PASSWORD, KEY)
    assert auth.credentials_ok("admin", PASSWORD)
    assert not auth.credentials_ok("admin", PASSWORD + "x")
    assert not auth.credentials_ok("root", PASSWORD)
    assert not auth.credentials_ok("", "")


# --- the queue use case ------------------------------------------------------------------------


async def test_overview_lists_requests_with_cafes_nearby_and_collector_state() -> None:
    repo = FakeCollectionRepo(cafes_near=7)
    await _queued(repo)
    manage = ManageCollectionRequests(repo, FakeLauncher(running=True))
    overview = await manage.overview()
    assert [v.cafes_nearby for v in overview.items] == [7]
    assert overview.counts[CollectionStatus.PENDING] == 1
    assert overview.counts[CollectionStatus.FAILED] == 0
    assert overview.collector_running


async def test_delete_removes_waiting_requests_but_not_a_running_one() -> None:
    repo = FakeCollectionRepo()
    waiting = await _queued(repo)
    running = await _queued(repo, GeoPoint(35.18, 129.07))
    await repo.mark_running(running, NOON)
    manage = ManageCollectionRequests(repo, FakeLauncher())
    assert await manage.delete(waiting) is AdminResult.OK
    assert await manage.delete(waiting) is AdminResult.NOT_FOUND
    assert await manage.delete(running) is AdminResult.RUNNING
    assert len(repo.rows) == 1


async def test_requeue_puts_a_failed_request_back_in_line() -> None:
    repo = FakeCollectionRepo()
    request = await _queued(repo)
    await repo.mark_failed(request, NOON, "boom")
    manage = ManageCollectionRequests(repo, FakeLauncher())
    assert await manage.requeue(request) is AdminResult.OK
    row = await repo.get(request)
    assert row is not None and row.status is CollectionStatus.PENDING
    assert row.note is not None and "다시 대기열" in row.note
    assert await manage.requeue(999) is AdminResult.NOT_FOUND


async def test_run_now_starts_one_collector_unless_one_is_already_working() -> None:
    repo = FakeCollectionRepo()
    request = await _queued(repo)
    launcher = FakeLauncher()
    manage = ManageCollectionRequests(repo, launcher)
    assert await manage.run_now(request) == (AdminResult.OK, f"job-{request}")
    assert launcher.launched == [request]
    launcher.running = True
    assert await manage.run_now(request) == (AdminResult.COLLECTOR_BUSY, None)
    launcher.running = False
    await repo.mark_running(request, NOON)
    assert await manage.run_now(request) == (AdminResult.RUNNING, None)
    assert await manage.run_now(999) == (AdminResult.NOT_FOUND, None)
    assert launcher.launched == [request]  # only the first call started anything


# --- the HTTP API ------------------------------------------------------------------------------


def _app(
    repo: FakeCollectionRepo, launcher: FakeLauncher | None = None, enabled: bool = True
) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.admin_auth = AdminAuth("admin" if enabled else "", PASSWORD, KEY)
    app.state.admin = ManageCollectionRequests(repo, launcher or FakeLauncher())
    app.state.admin_login_limiter = RateLimiter(3, 600.0)
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers=GUARD
    )


async def _sign_in(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/admin/login", json={"username": "admin", "password": PASSWORD}
    )
    assert response.status_code == 200


async def test_the_admin_api_does_not_exist_while_it_is_switched_off() -> None:
    async with _client(_app(FakeCollectionRepo(), enabled=False)) as client:
        assert (await client.get("/api/v1/admin/session")).status_code == 404
        login = await client.post("/api/v1/admin/login", json={"username": "a", "password": "b"})
    assert login.status_code == 404


async def test_nothing_is_shown_without_signing_in() -> None:
    repo = FakeCollectionRepo()
    request = await _queued(repo)
    async with _client(_app(repo)) as client:
        assert (await client.get("/api/v1/admin/collection-requests")).status_code == 401
        assert (
            await client.delete(f"/api/v1/admin/collection-requests/{request}")
        ).status_code == 401
        assert (
            await client.post(f"/api/v1/admin/collection-requests/{request}/run")
        ).status_code == 401
        client.cookies.set(COOKIE_NAME, "9999999999.abc", path="/api/v1/admin")
        forged = await client.get("/api/v1/admin/collection-requests")
    assert forged.status_code == 401
    assert len(repo.rows) == 1


async def test_a_wrong_password_is_refused_and_guessing_is_limited() -> None:
    async with _client(_app(FakeCollectionRepo())) as client:
        codes = []
        for _ in range(4):
            r = await client.post(
                "/api/v1/admin/login", json={"username": "admin", "password": "nope-nope-nope"}
            )
            codes.append(r.status_code)
        right_but_late = await client.post(
            "/api/v1/admin/login", json={"username": "admin", "password": PASSWORD}
        )
    assert codes == [401, 401, 401, 429]
    assert right_but_late.status_code == 429  # the window is used up, whoever asks
    assert COOKIE_NAME not in right_but_late.cookies


async def test_calls_without_the_admin_header_are_refused() -> None:
    app = _app(FakeCollectionRepo())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/v1/admin/login", json={"username": "admin", "password": PASSWORD}
        )
    assert r.status_code == 403


async def test_signing_in_gives_a_strict_httponly_cookie_and_unlocks_the_queue() -> None:
    repo = FakeCollectionRepo(cafes_near=3)
    await _queued(repo, count=2)
    async with _client(_app(repo)) as client:
        login = await client.post(
            "/api/v1/admin/login", json={"username": "admin", "password": PASSWORD}
        )
        cookie = login.headers["set-cookie"].lower()
        assert (
            "httponly" in cookie and "samesite=strict" in cookie and "path=/api/v1/admin" in cookie
        )
        assert login.headers["cache-control"] == "no-store"
        assert (await client.get("/api/v1/admin/session")).json() == {"user": "admin"}
        body = (await client.get("/api/v1/admin/collection-requests")).json()
        await client.post("/api/v1/admin/logout")
        client.cookies.clear()
        after = await client.get("/api/v1/admin/session")
    assert body["collector_running"] is False
    assert body["counts"] == {"pending": 1, "running": 0, "done": 0, "failed": 0}
    item = body["items"][0]
    assert item["status"] == "pending" and item["request_count"] == 2 and item["cafes_nearby"] == 3
    assert item["cell_key"] and item["lat"] and item["lng"]
    assert after.status_code == 401


async def test_the_admin_can_delete_requeue_and_run_requests() -> None:
    repo = FakeCollectionRepo()
    doomed = await _queued(repo)
    failed = await _queued(repo, GeoPoint(35.18, 129.07))
    await repo.mark_failed(failed, NOON, "boom")
    launcher = FakeLauncher()
    base = "/api/v1/admin/collection-requests"
    async with _client(_app(repo, launcher)) as client:
        await _sign_in(client)
        assert (await client.delete(f"{base}/{doomed}")).status_code == 204
        assert (await client.delete(f"{base}/{doomed}")).status_code == 404
        assert (await client.post(f"{base}/{failed}/requeue")).status_code == 204
        run = await client.post(f"{base}/{failed}/run")
        launcher.running = True
        busy = await client.post(f"{base}/{failed}/run")
        launcher.running = False
        launcher.unavailable = True
        offline = await client.post(f"{base}/{failed}/run")
    assert run.status_code == 202 and run.json() == {"job": f"job-{failed}"}
    assert busy.status_code == 409 and "다른 수집" in busy.json()["detail"]
    assert offline.status_code == 503
    assert launcher.launched == [failed]
    row = await repo.get(failed)
    assert row is not None and row.status is CollectionStatus.PENDING


async def test_a_running_request_cannot_be_deleted_from_the_page() -> None:
    repo = FakeCollectionRepo()
    request = await _queued(repo)
    await repo.mark_running(request, NOON)
    async with _client(_app(repo)) as client:
        await _sign_in(client)
        r = await client.delete(f"/api/v1/admin/collection-requests/{request}")
    assert r.status_code == 409 and "수집 중" in r.json()["detail"]
    assert len(repo.rows) == 1


# --- the cluster launcher ----------------------------------------------------------------------

CRONJOB: dict[str, Any] = {
    "spec": {
        "jobTemplate": {
            "metadata": {},
            "spec": {
                "backoffLimit": 0,
                "activeDeadlineSeconds": 12000,
                "template": {
                    "metadata": {"labels": {"app.kubernetes.io/name": "aicafe-collector"}},
                    "spec": {
                        "restartPolicy": "Never",
                        "containers": [
                            {
                                "name": "collector",
                                "image": "registry/aicafe-backend:9",
                                "command": ["python", "-m", "cli", "collect-requests"],
                                "args": ["--budget-minutes", "150", "--max-requests", "10"],
                            }
                        ],
                    },
                },
            },
        }
    }
}


def _launcher(handler: Any, tmp_path: Any, dry_run: bool = False) -> KubernetesCollectorLauncher:
    token = tmp_path / "token"
    token.write_text("secret-token\n")
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return KubernetesCollectorLauncher(http, "aicafe", "aicafe-collector", token, dry_run)


async def test_a_manual_job_is_the_nightly_job_with_other_arguments(tmp_path: Any) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=CRONJOB)
        return httpx.Response(201, json={})

    launcher = _launcher(handler, tmp_path)
    name = await launcher.launch(42)
    get, post = seen
    assert get.url.path == "/apis/batch/v1/namespaces/aicafe/cronjobs/aicafe-collector"
    assert post.url.path == "/apis/batch/v1/namespaces/aicafe/jobs" and not post.url.params
    assert post.headers["authorization"] == "Bearer secret-token"
    job = json.loads(post.content)
    container = job["spec"]["template"]["spec"]["containers"][0]
    assert container["args"] == ["--request-id", "42", "--budget-minutes", "60"]
    assert container["image"] == "registry/aicafe-backend:9"  # everything else is the nightly job
    assert container["command"][-1] == "collect-requests"
    assert job["spec"]["ttlSecondsAfterFinished"] == 86_400
    assert job["spec"]["activeDeadlineSeconds"] == 5400
    assert job["metadata"]["name"] == name and name.startswith("aicafe-collect-now-42-")
    assert job["metadata"]["labels"]["aicafe/trigger"] == "admin"
    # the nightly CronJob itself is untouched
    assert (
        CRONJOB["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["args"][1]
        == "150"
    )


async def test_dry_run_asks_the_cluster_to_validate_without_creating(tmp_path: Any) -> None:
    posted: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posted.append(request)
        return httpx.Response(200, json=CRONJOB)

    await _launcher(handler, tmp_path, dry_run=True).launch(1)
    assert posted[0].url.params["dryRun"] == "All"


async def test_the_launcher_sees_a_working_collector_pod(tmp_path: Any) -> None:
    def pods(items: list[dict[str, Any]]) -> Any:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["labelSelector"] == "app.kubernetes.io/name=aicafe-collector"
            return httpx.Response(200, json={"items": items})

        return handler

    running = {"status": {"phase": "Running"}, "metadata": {}}
    finished = {"status": {"phase": "Succeeded"}, "metadata": {}}
    stopping = {"status": {"phase": "Running"}, "metadata": {"deletionTimestamp": "x"}}
    assert await _launcher(pods([finished, running]), tmp_path).is_running()
    assert not await _launcher(pods([finished, stopping]), tmp_path).is_running()
    assert not await _launcher(pods([]), tmp_path).is_running()


@pytest.mark.parametrize("status", [403, 404, 500])
async def test_a_refusal_from_the_cluster_becomes_collector_unavailable(
    tmp_path: Any, status: int
) -> None:
    launcher = _launcher(lambda request: httpx.Response(status, json={}), tmp_path)
    with pytest.raises(CollectorUnavailable):
        await launcher.launch(1)
    with pytest.raises(CollectorUnavailable):
        await launcher.is_running()


async def test_outside_a_cluster_nothing_can_be_started(tmp_path: Any) -> None:
    launcher = in_cluster_launcher("aicafe-collector", tmp_path)  # no service account files here
    assert isinstance(launcher, UnavailableCollectorLauncher)
    assert not await launcher.is_running()
    with pytest.raises(CollectorUnavailable):
        await launcher.launch(1)
