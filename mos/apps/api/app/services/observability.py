"""Structured logging & per-request observability.

- configure_logging(): process-wide structured logs. Every record carries
  ts/level/logger/message plus request_id (via a contextvar filter), so log
  lines emitted inside a request can be correlated.
  **格式默认 JSON**（审计 P2-12「结构化日志是 key=value 文本，不是 JSON —
  需 grok/regex 解析」）；``LOG_FORMAT=kv`` 可切回人读的 key=value。
- RequestObservabilityMiddleware: generates or propagates X-Request-ID
  (uuid4), stores it on request.state.request_id, echoes it in the response
  header, and emits one access log line per request with
  method/path/status/duration_ms.

Implemented as a pure ASGI middleware (not BaseHTTPMiddleware) so streaming
responses and the TestClient behave exactly as before.
"""

from __future__ import annotations

import json
import logging
import re
import threading
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


class JsonFormatter(logging.Formatter):
    """一行一条 JSON —— 日志采集（Loki/ELK/CloudWatch）可直接解析。

    字段：``ts`` / ``level`` / ``logger`` / ``request_id`` / ``message``，
    额外字段走 ``record.__dict__`` 里以 ``marios_`` 开头的键（不与标准字段
    冲突）。异常走 ``exc`` 字段（traceback 原文）。

    审计 P2-12：原来是 key=value 文本，上日志平台要写正则/grok 解析，
    字段名一旦变就静默丢数。JSON 是约定俗成的最低成本。
    """

    #: JSON 里不作为「额外字段」导出的标准属性。
    _RESERVED = frozenset(
        {
            "args",
            "asctime",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "message",
            "module",
            "msecs",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "taskName",
            "thread",
            "threadName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key.startswith("_"):
                continue
            if key in payload:
                continue
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                value = repr(value)
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: int | str = logging.INFO) -> None:
    """Idempotent root-logger setup; called once at app startup (app/main.py).

    ``LOG_FORMAT``：``json``（默认）/ ``kv``。走 ``get_settings()`` 读，
    但读不到（未初始化配置）时退回 JSON。
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    try:
        from app.config import get_settings

        log_format = (get_settings().log_format or "json").strip().lower()
    except Exception:  # noqa: BLE001 — 配置不可用时不应阻止启动
        log_format = "json"
    handler = logging.StreamHandler()
    handler.setFormatter(KeyValueFormatter() if log_format == "kv" else JsonFormatter())
    handler.addFilter(RequestIDFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Tame noisy third parties without silencing them entirely.
    # uvicorn.access 的访问日志被降级：RequestObservabilityMiddleware 已经
    # 打过一条**带 request_id** 的访问日志，重复打只会双份。
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    _CONFIGURED = True


# ── 进程内指标（3.7 可观测性）：/metrics 输出，Prometheus 文本格式 ──

METRICS: dict[str, float] = {
    "http_requests_total": 0,
    "http_request_duration_ms_sum": 0.0,
    "http_5xx_total": 0,
    "slow_queries_total": 0,
}

#: 指标写入锁 —— 旧实现是裸 ``+=``，多线程下会丢计数（审计 P2-12）。
_METRICS_LOCK = threading.Lock()

#: 延迟直方图桶（ms）—— Prometheus 惯例。有了分桶才能算 P95/P99；
#: 光有 sum 算不出分位数（审计 P2-12「没有 histogram / 分位数」）。
DURATION_BUCKETS_MS: tuple[float, ...] = (
    5,
    10,
    25,
    50,
    100,
    250,
    500,
    1000,
    2500,
    5000,
    10000,
    30000,
    60000,
)
#: 各桶的累计计数（与 DURATION_BUCKETS_MS 一一对应）。
DURATION_BUCKET_COUNTS: list[int] = [0] * len(DURATION_BUCKETS_MS)
#: 超出最大桶的请求数。
DURATION_OVERFLOW = 0


def _bump_duration(duration_ms: float) -> None:
    global DURATION_OVERFLOW
    for i, edge in enumerate(DURATION_BUCKETS_MS):
        if duration_ms <= edge:
            DURATION_BUCKET_COUNTS[i] += 1
            return
    DURATION_OVERFLOW += 1


def record_request(duration_ms: float, status_code: int) -> None:
    with _METRICS_LOCK:
        METRICS["http_requests_total"] += 1
        METRICS["http_request_duration_ms_sum"] += duration_ms
        if (status_code or 500) >= 500:
            METRICS["http_5xx_total"] += 1
        _bump_duration(duration_ms)


def duration_quantile(q: float) -> float:
    """延迟分位数（ms）—— 由直方图桶线性插值估算。

    只在**桶边界**上取值：桶内的真实分布不可知，线性插值是 Prometheus
    ``histogram_quantile`` 的同款近似。没有样本时返回 0.0。
    """
    with _METRICS_LOCK:
        total = int(METRICS["http_requests_total"])
        counts = list(DURATION_BUCKET_COUNTS)
        overflow = DURATION_OVERFLOW
    if total <= 0:
        return 0.0
    target = max(0.0, min(1.0, q)) * total
    seen = 0
    prev_edge = 0.0
    for edge, count in zip(DURATION_BUCKETS_MS, counts, strict=False):
        seen += count
        if seen >= target:
            if count <= 0:
                return edge
            # 桶内线性插值
            within = (target - (seen - count)) / count
            return prev_edge + (edge - prev_edge) * within
        prev_edge = edge
    # 超出最大桶
    if overflow > 0:
        return DURATION_BUCKETS_MS[-1]
    return prev_edge


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
        "# HELP http_request_duration_ms HTTP request latency histogram (ms).",
        "# TYPE http_request_duration_ms histogram",
    ]
    with _METRICS_LOCK:
        counts = list(DURATION_BUCKET_COUNTS)
        overflow = DURATION_OVERFLOW
    cumulative = 0
    for edge, count in zip(DURATION_BUCKETS_MS, counts, strict=False):
        cumulative += count
        lines.append(
            f'http_request_duration_ms_bucket{{le="{edge:g}"}} {cumulative}'
        )
    cumulative += overflow
    lines.append(f'http_request_duration_ms_bucket{{le="+Inf"}} {cumulative}')
    lines.append(f"http_request_duration_ms_sum {METRICS['http_request_duration_ms_sum']:.1f}")
    lines.append(f"http_request_duration_ms_count {cumulative}")
    # —— 引擎级指标（P3-7）——
    engines = sorted(
        {k[len("engine_calls_"):] for k in METRICS if k.startswith("engine_calls_")}
    )
    if engines:
        lines.append("# HELP engine_calls_total Engine invocations by engine.")
        lines.append("# TYPE engine_calls_total counter")
        lines.append(f"engine_calls_total {int(METRICS.get('engine_calls_total', 0))}")
        lines.append("# HELP engine_duration_ms_sum Total engine time by engine (ms).")
        lines.append("# TYPE engine_duration_ms_sum counter")
        lines.append(
            f"engine_duration_ms_sum {METRICS.get('engine_duration_ms_sum', 0.0):.1f}"
        )
        for name in engines:
            lines.append(f'engine_calls_total{{engine="{name}"}} {int(METRICS.get(f"engine_calls_{name}", 0))}')
            lines.append(
                f'engine_duration_ms_sum{{engine="{name}"}} '
                f'{METRICS.get(f"engine_duration_ms_sum_{name}", 0.0):.1f}'
            )
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
            with _METRICS_LOCK:
                METRICS["slow_queries_total"] += 1
            log.warning("slow query %.0fms: %s", elapsed_ms, statement[:200])


#: 客户端提供的 X-Request-ID 只允许「字母/数字/点/横线/下划线」，长度 ≤ 64。
#: 旧实现原样回显：客户端塞进来一串 ``\r\n`` 或 10KB 文本，会被原样写进
#: **访问日志**（日志注入 / 日志伪造）和**响应头**（响应头注入）。
#:
#: ⚠️ 结尾必须用 ``\Z`` 而不是 ``$`` —— Python 的 ``$`` 还能匹配**换行符
#: 之前**的位置，所以 ``"abc\n"`` 会被 ``$`` 判为合法（``re.match`` 匹配到
#: 换行前就成功），换行原样进日志与响应头 → 响应头注入面。
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}\Z")


def _sanitize_request_id(raw: str | None) -> str:
    """合法就沿用客户端的 id（方便跨系统串联），不合法就自己生成一个。"""
    if raw and _REQUEST_ID_RE.match(raw):
        return raw
    return str(uuid.uuid4())


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
        # 头字节不保证是 UTF-8 —— 严格 decode 会抛 UnicodeDecodeError → 500。
        # latin-1 + replace 是"一字节一字符"的映射，永不抛错。
        raw_request_id = headers.get(b"x-request-id", b"").decode("latin-1", errors="replace")
        request_id = _sanitize_request_id(raw_request_id)
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


# ── 引擎级 tracing（P3-7）────────────────────────────────────────────────
#
# 审计 P3-7「引擎无 tracing/OpenTelemetry」：请求层有 request-id 与 Prometheus
# 指标，但**计算引擎**（TCE / 滞期 / 租金 / 总账 / P&L）是黑盒 ——
# 一次慢请求到底是"引擎慢"还是"数据库慢"无法区分。
#
# 这里补一层**零依赖**的最小 tracing：
# - 每个引擎调用生成一个 span_id，与当前 request_id 关联；
# - 结构化日志一行 ``engine.span``（engine / duration_ms / status / span_id）；
# - Prometheus 侧新增 ``engine_calls_total`` / ``engine_duration_ms_sum``
#   （按引擎名分桶），并在 ``/metrics`` 里输出。
#
# 不引入 OpenTelemetry 依赖：OTel 需要 collector/exporter 才有用，纯进程内
# 场景下只会增加安装面与启动开销。要接 OTel 时把 ``_ENGINE_SPAN_SINK`` 换成
# OTel tracer 即可，其余调用点不用动。

#: 已注册的引擎 span 出口 —— 换成 OTel tracer 时只改这一处。
_ENGINE_SPAN_SINK = None

_ENGINE_LOG = logging.getLogger("marios.engine")


def record_engine_span(engine: str, duration_ms: float, status: str = "ok") -> str:
    """登记一次引擎调用，返回 span_id。

    ``status`` 取 ``ok`` / ``error``。
    """
    span_id = uuid.uuid4().hex[:16]
    with _METRICS_LOCK:
        METRICS["engine_calls_total"] = METRICS.get("engine_calls_total", 0) + 1
        METRICS["engine_duration_ms_sum"] = METRICS.get("engine_duration_ms_sum", 0.0) + duration_ms
        key = f"engine_calls_{engine}"
        METRICS[key] = METRICS.get(key, 0) + 1
        key = f"engine_duration_ms_sum_{engine}"
        METRICS[key] = METRICS.get(key, 0.0) + duration_ms
    if _ENGINE_SPAN_SINK is not None:
        try:
            _ENGINE_SPAN_SINK(engine, duration_ms, status, span_id)
        except Exception:  # noqa: BLE001 — tracing 永远不能影响业务
            pass
    _ENGINE_LOG.info(
        "engine=%s duration_ms=%.2f status=%s span_id=%s request_id=%s",
        engine,
        duration_ms,
        status,
        span_id,
        current_request_id(),
    )
    return span_id


def traced(engine: str):
    """装饰器：给引擎入口套一层 span 计时 + 指标。

    - 正常返回 → ``status="ok"``；
    - 抛异常 → ``status="error"`` 并**原样抛出**（不改语义）；
    - 计时用 ``perf_counter``，不受系统时钟调整影响。

    用法::

        @traced("estimate")
        def compute_estimate(...): ...
    """

    def _wrap(fn):
        import functools

        @functools.wraps(fn)
        def _inner(*args, **kwargs):
            start = time.perf_counter()
            try:
                out = fn(*args, **kwargs)
            except Exception:
                record_engine_span(engine, (time.perf_counter() - start) * 1000, "error")
                raise
            record_engine_span(engine, (time.perf_counter() - start) * 1000, "ok")
            return out

        return _inner

    return _wrap
