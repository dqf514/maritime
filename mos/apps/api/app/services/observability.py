"""Structured logging & per-request observability.

- configure_logging(): process-wide key=value structured logs. Every record
  carries ts/level/logger/message plus request_id (via a contextvar filter),
  so log lines emitted inside a request can be correlated.
- RequestObservabilityMiddleware: generates or propagates X-Request-ID
  (uuid4), stores it on request.state.request_id, echoes it in the response
  header, and emits one access log line per request with
  method/path/status/duration_ms.

Implemented as a pure ASGI middleware (not BaseHTTPMiddleware) so streaming
responses and the TestClient behave exactly as before.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"

_request_id: ContextVar[str] = ContextVar("voyageos_request_id", default="-")

_CONFIGURED = False


def current_request_id() -> str:
    return _request_id.get()


class RequestIDFilter(logging.Filter):
    """Inject the current request id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


class KeyValueFormatter(logging.Formatter):
    """ts=... level=... logger=... request_id=... message="..." one-line format."""

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z")
        message = record.getMessage().replace('"', '\\"')
        line = (
            f'ts={ts} level={record.levelname} logger={record.name} '
            f'request_id={getattr(record, "request_id", "-")} message="{message}"'
        )
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def configure_logging(level: int | str = logging.INFO) -> None:
    """Idempotent root-logger setup; called once at app startup (app/main.py)."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(KeyValueFormatter())
    handler.addFilter(RequestIDFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Tame noisy third parties without silencing them entirely
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    _CONFIGURED = True


class RequestObservabilityMiddleware:
    """ASGI middleware: request-id propagation + one access log per request."""

    def __init__(self, app: ASGIApp, logger_name: str = "voyageos.access") -> None:
        self.app = app
        self.log = logging.getLogger(logger_name)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        request_id = headers.get(b"x-request-id", b"").decode() or str(uuid.uuid4())
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        token = _request_id.set(request_id)

        status_code = 0
        start = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", []).append(
                    (b"x-request-id", request_id.encode())
                )
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self.log.info(
                "%s %s -> %s (%.1fms)",
                scope.get("method", "-"),
                scope.get("path", "-"),
                status_code or 500,
                duration_ms,
            )
            _request_id.reset(token)
