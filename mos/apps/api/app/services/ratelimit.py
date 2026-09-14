"""In-process sliding-window rate limiting for auth-sensitive endpoints."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import HTTPException, Request, status

from app.config import get_settings


class SlidingWindowLimiter:
    def __init__(self, max_hits: int, window_seconds: float):
        self.max_hits = max_hits
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] >= self.window_seconds:
                q.popleft()
            if len(q) >= self.max_hits:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_limiters: dict[str, SlidingWindowLimiter] = {}


def rate_limit(scope: str, *, max_hits: int = 5, window_seconds: float = 60.0) -> Callable:
    """FastAPI dependency: 429 when `scope` exceeds max_hits per window per client IP."""

    limiter = _limiters.setdefault(scope, SlidingWindowLimiter(max_hits, window_seconds))

    def _dep(request: Request) -> None:
        if not get_settings().rate_limit_enabled:
            return
        ip = request.client.host if request.client else "unknown"
        if not limiter.allow(ip):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"code": "RATE_LIMITED", "message": "Too many requests, try again later"},
            )

    return _dep
