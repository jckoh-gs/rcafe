"""A small in-process sliding-window rate limiter (a single API replica needs no shared store)."""

from __future__ import annotations

import time
from collections import deque

from fastapi import Request


class RateLimiter:
    def __init__(self, max_events: int, window_s: float, max_keys: int = 10_000) -> None:
        self._max_events = max_events
        self._window_s = window_s
        self._max_keys = max_keys
        self._events: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        queue = self._events.setdefault(key, deque())
        while queue and queue[0] <= now - self._window_s:
            queue.popleft()
        if len(queue) >= self._max_events:
            return False
        queue.append(now)
        if len(self._events) > self._max_keys:  # drop idle keys so the table cannot grow forever
            for stale in [
                k for k, q in self._events.items() if not q or q[-1] <= now - self._window_s
            ]:
                self._events.pop(stale, None)
        return True


def client_ip(request: Request) -> str:
    """Best-effort visitor address behind Traefik and nginx.

    Both proxies append the address they saw, so the visitor is the second entry from the right
    ("<spoofed...>, <visitor>, <traefik>"); with a single entry (dev proxy) it is that entry.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    parts = [p.strip() for p in forwarded.split(",") if p.strip()]
    if len(parts) >= 2:
        return parts[-2]
    if parts:
        return parts[-1]
    return request.client.host if request.client else "unknown"
