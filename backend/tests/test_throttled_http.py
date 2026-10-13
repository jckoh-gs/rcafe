import httpx
import pytest
import respx

from app.adapters.outbound.clients.throttled_http import (
    BlockedError,
    ThrottledClient,
    UpstreamError,
)

URL = "https://example.test/x"


def _client(http: httpx.AsyncClient, retries: int = 2, failures: int = 99) -> ThrottledClient:
    return ThrottledClient(
        http, min_interval_s=0, jitter_s=0, max_retries=retries, max_consecutive_failures=failures
    )


@respx.mock
async def test_transient_400_and_500_are_retried() -> None:
    respx.get(URL).mock(
        side_effect=[httpx.Response(400), httpx.Response(503), httpx.Response(200, text="ok")]
    )
    async with httpx.AsyncClient() as http:
        response = await _client(http).get(URL)
    assert response is not None and response.text == "ok"


@respx.mock
async def test_gives_up_after_retries_with_upstream_error() -> None:
    respx.get(URL).mock(return_value=httpx.Response(400))
    async with httpx.AsyncClient() as http:
        with pytest.raises(UpstreamError):
            await _client(http, retries=1).get(URL)


@respx.mock
async def test_404_returns_none_and_429_raises_blocked() -> None:
    respx.get(URL).mock(side_effect=[httpx.Response(404), httpx.Response(429)])
    async with httpx.AsyncClient() as http:
        client = _client(http)
        assert await client.get(URL) is None
        with pytest.raises(BlockedError):
            await client.get(URL)


@respx.mock
async def test_circuit_breaker_stops_after_consecutive_failures() -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(400))
    async with httpx.AsyncClient() as http:
        with pytest.raises(BlockedError):
            await _client(http, retries=10, failures=3).get(URL)
    assert route.call_count == 3  # did not keep hammering
