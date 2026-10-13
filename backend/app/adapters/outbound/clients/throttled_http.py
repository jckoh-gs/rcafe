"""HTTP client with a polite request rate, jitter, and bounded retries."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Mapping

import httpx

from app.domain.ports import PlaceFetchError

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.6,en;q=0.4",
    "Referer": "https://map.naver.com/",
}


class BlockedError(RuntimeError):
    """The upstream refused us (rate limit / block). Callers must stop crawling."""


class UpstreamError(PlaceFetchError):
    """The upstream kept failing after retries."""


class ThrottledClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        min_interval_s: float = 1.0,
        jitter_s: float = 0.3,
        max_retries: int = 2,
        max_consecutive_failures: int = 5,
    ) -> None:
        self._client = client
        self._min_interval_s = min_interval_s
        self._jitter_s = jitter_s
        self._max_retries = max_retries
        self._max_consecutive_failures = max_consecutive_failures
        self._consecutive_failures = 0
        self._lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def _wait_turn(self) -> None:
        async with self._lock:
            delay = self._min_interval_s + random.uniform(0, self._jitter_s)
            wait = self._last_request_at + delay - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()

    async def get(self, url: str, params: Mapping[str, str] | None = None) -> httpx.Response | None:
        """GET with throttling. Returns None on 404; raises BlockedError on 403/429.

        Repeated failures trip a circuit breaker: a persistent 4xx/5xx usually means we are being
        throttled, so we stop instead of retrying harder.
        """
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            await self._wait_turn()
            try:
                response = await self._client.get(url, params=params)
            except httpx.TransportError as exc:
                last_error = exc
            else:
                if response.status_code == 404:
                    self._consecutive_failures = 0
                    return None
                if response.status_code in (403, 429):
                    raise BlockedError(f"{response.status_code} from {response.url.host}")
                if response.status_code < 400:
                    self._consecutive_failures = 0
                    return response
                last_error = UpstreamError(f"{response.status_code} from {response.url.host}")
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._max_consecutive_failures:
                raise BlockedError(
                    f"{self._consecutive_failures} consecutive failures on {url.split('?')[0]}: "
                    f"{last_error}"
                )
            await asyncio.sleep(min(2**attempt, 15))
        raise UpstreamError(f"giving up on {url}: {last_error}")
