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

_request_id: ContextVar[str] = ContextVar("marios_request_id", default="-")

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


# ── 进程内指标（3.7 可观测性）：/metrics 输出，Prometheus 文本格式 ──

METRICS: dict[str, float] = {
    "http_requests_total": 0,
    "http_request_duration_ms_sum": 0.0,
    "http_5xx_total": 0,
    "slow_queries_total": 0,
}


def record_request(duration_ms: float, status_code: int) -> None:
    METRICS["http_requests_total"] += 1
    METRICS["http_request_duration_ms_sum"] += duration_ms
    if (status_code or 500) >= 500:
        METRICS["http_5xx_total"] += 1


def render_prometheus() -> str:
    lines = [
        "# HELP http_requests_total Total HTTP requests handled.",
        "# TYPE http_requests_total counter",
        f"http_requests_total {int(METRICS['http_requests_total'])}",
        "# HELP http_request_duration_ms_sum Sum of request durations in ms.",
        "# TYPE http_request_duration_ms_sum counter",
        f"http_request_duration_ms_sum {METRICS['http_request_duration_ms_sum']:.1f}",
        "# HELP http_5xx_total Total 5xx responses.",
        "# TYPE http_5xx_total counter",
        f"http_5xx_total {int(METRICS['http_5xx_total'])}",
        "# HELP slow_queries_total SQL statements slower than the threshold.",
        "# TYPE slow_queries_total counter",
        f"slow_queries_total {int(METRICS['slow_queries_total'])}",
    ]
    return chr(10).join(lines) + chr(10)


_SLOW_INSTALLED = False
_SLOW_THRESHOLD_MS = 200.0


def install_slow_query_log(threshold_ms: float = 200.0) -> None:
    """SQLAlchemy 事件：超阈值语句告警 + 计数（settings.slow_query_ms 控制）。

    幂等：监听器只注册一次，重复调用仅更新阈值（避免多监听器争抢计时键）。
    """
    global _SLOW_INSTALLED, _SLOW_THRESHOLD_MS
    _SLOW_THRESHOLD_MS = threshold_ms
    if _SLOW_INSTALLED:
        return
    _SLOW_INSTALLED = True
    import time as _time

    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    log = logging.getLogger("marios.slow_query")

    @event.listens_for(Engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        conn.info["q_start"] = _time.perf_counter()

    @event.listens_for(Engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        start = conn.info.get("q_start")
        if start is None:
            return
        elapsed_ms = (_time.perf_counter() - start) * 1000
        if elapsed_ms >= _SLOW_THRESHOLD_MS:
            METRICS["slow_queries_total"] += 1
            log.warning("slow query %.0fms: %s", elapsed_ms, statement[:200])


class RequestObservabilityMiddleware:
    """ASGI middleware: request-id propagation + one access log per request."""

    def __init__(self, app: ASGIApp, logger_name: str = "marios.access") -> None:
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
            record_request(duration_ms, status_code)
            self.log.info(
                "%s %s -> %s (%.1fms)",
                scope.get("method", "-"),
                scope.get("path", "-"),
                status_code or 500,
                duration_ms,
            )
            _request_id.reset(token)
