"""Starts collector runs as Kubernetes Jobs, using the API pod's own service account.

The Job is copied from the nightly CronJob (same image, Secret, limits, security context) and only
its arguments change, so a run started by hand can never drift from the scheduled one. The service
account is allowed to create Jobs, read that CronJob and list pods in this namespace, nothing else
(`deploy/k8s/base/admin-rbac.yaml`).
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from app.domain.ports import CollectorUnavailable

log = logging.getLogger(__name__)

SERVICE_ACCOUNT_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
API_HOST = "https://kubernetes.default.svc"
COLLECTOR_LABEL = "app.kubernetes.io/name=aicafe-collector"
MANUAL_BUDGET_MINUTES = 60
MANUAL_DEADLINE_S = 5400  # the Job is killed 30 minutes after its own budget at the latest
KEEP_FINISHED_S = 86_400


class KubernetesCollectorLauncher:
    def __init__(
        self,
        http: httpx.AsyncClient,
        namespace: str,
        cronjob: str,
        token_path: Path,
        dry_run: bool = False,
    ) -> None:
        self._http = http
        self._namespace = namespace
        self._cronjob = cronjob
        self._token_path = token_path
        self._dry_run = dry_run

    async def aclose(self) -> None:
        await self._http.aclose()

    async def is_running(self) -> bool:
        pods = await self._call(
            "GET",
            f"/api/v1/namespaces/{self._namespace}/pods",
            params={"labelSelector": COLLECTOR_LABEL},
        )
        return any(
            pod.get("status", {}).get("phase") in ("Pending", "Running")
            and not pod.get("metadata", {}).get("deletionTimestamp")
            for pod in pods.get("items", [])
        )

    async def launch(self, request_id: int) -> str:
        cronjob = await self._call(
            "GET", f"/apis/batch/v1/namespaces/{self._namespace}/cronjobs/{self._cronjob}"
        )
        job = self._job_from(cronjob, request_id)
        params = {"dryRun": "All"} if self._dry_run else None
        await self._call(
            "POST", f"/apis/batch/v1/namespaces/{self._namespace}/jobs", json=job, params=params
        )
        name = str(job["metadata"]["name"])
        log.info("started collector job %s for request %s", name, request_id)
        return name

    def _job_from(self, cronjob: dict[str, Any], request_id: int) -> dict[str, Any]:
        template = copy.deepcopy(cronjob["spec"]["jobTemplate"])
        spec: dict[str, Any] = template["spec"]
        spec["activeDeadlineSeconds"] = MANUAL_DEADLINE_S
        spec["ttlSecondsAfterFinished"] = KEEP_FINISHED_S
        container = spec["template"]["spec"]["containers"][0]
        container["args"] = [
            "--request-id",
            str(request_id),
            "--budget-minutes",
            str(MANUAL_BUDGET_MINUTES),
        ]
        stamp = datetime.now().strftime("%m%d%H%M%S")
        labels = {
            **template.get("metadata", {}).get("labels", {}),
            "app.kubernetes.io/name": "aicafe-collector",
            "aicafe/trigger": "admin",
        }
        return {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {
                "name": f"aicafe-collect-now-{request_id}-{stamp}",
                "namespace": self._namespace,
                "labels": labels,
            },
            "spec": spec,
        }

    async def _call(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            token = self._token_path.read_text(encoding="utf-8").strip()
            response = await self._http.request(
                method,
                f"{API_HOST}{path}",
                json=json,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        except (OSError, httpx.HTTPError) as exc:
            raise CollectorUnavailable("클러스터에 연결하지 못했어요.") from exc
        if response.status_code >= 400:
            log.warning("kubernetes API answered %s for %s %s", response.status_code, method, path)
            raise CollectorUnavailable(f"클러스터가 요청을 거절했어요 ({response.status_code}).")
        body: dict[str, Any] = response.json()
        return body


class UnavailableCollectorLauncher:
    """Used outside the cluster (local development): nothing can be started from here."""

    async def aclose(self) -> None:
        return None

    async def is_running(self) -> bool:
        return False

    async def launch(self, request_id: int) -> str:
        raise CollectorUnavailable("클러스터 안에서만 즉시 실행을 쓸 수 있어요.")


def in_cluster_launcher(
    cronjob: str, service_account_dir: Path = SERVICE_ACCOUNT_DIR
) -> KubernetesCollectorLauncher | UnavailableCollectorLauncher:
    """A launcher for the pod's own namespace, or one that says so when not inside a cluster."""
    token = service_account_dir / "token"
    namespace = service_account_dir / "namespace"
    ca = service_account_dir / "ca.crt"
    if not (token.is_file() and namespace.is_file() and ca.is_file()):
        return UnavailableCollectorLauncher()
    http = httpx.AsyncClient(verify=str(ca), timeout=httpx.Timeout(10.0))
    return KubernetesCollectorLauncher(
        http, namespace.read_text(encoding="utf-8").strip(), cronjob, token
    )
