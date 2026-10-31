"""In-process sliding-window rate limiting for auth-sensitive endpoints.

两种用法：

1. **依赖式**（``Depends(rate_limit("auth.login"))``）—— 挂在单个端点上。
   现有用法：``auth.login`` / ``auth.invite`` / ``auth.email_verify`` /
   ``auth.magic_link``。
2. **中间件式**（``RateLimitMiddleware``）—— 按**路径前缀**批量覆盖
   审计 P1-20 点名的"无限流"面：导出 / PDF / 报表 / AI。
   依赖式只保护了 4 个认证端点，导出、PDF 生成、报表执行、AI 推理
   **全部没有上限** —— 一次误点就能把 DB / LLM 额度打满。

限流器是**进程内**实现（每个 worker 一份）。多副本部署时实际额度是
``副本数 × max_hits``；换成 Redis 后端是 P2 的"接上 Redis"那一档。
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import HTTPException, Request, status
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

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


def rate_limit(
    scope: str,
    *,
    max_hits: int = 5,
    window_seconds: float = 60.0,
    per_account: bool = False,
) -> Callable:
    """FastAPI dependency: 429 when `scope` exceeds max_hits per window per client IP.

    ``per_account=True`` 时，计数键是 ``IP + 请求体里的邮箱`` —— 登录专用。
    只按 IP 计的话，一个人连输错几次密码会把**同一出口 IP 下的同事**一起
    锁掉（办公室 NAT 出口就是一个 IP）。按账号计之后，防爆破的力度不变
    （同一账号同一 IP 仍是 5 次/分钟），但互不牵连。
    """

    limiter = _limiters.setdefault(scope, SlidingWindowLimiter(max_hits, window_seconds))

    async def _dep(request: Request) -> None:
        if not get_settings().rate_limit_enabled:
            return
        ip = request.client.host if request.client else "unknown"
        key = ip
        if per_account:
            try:
                raw = await request.body()
                payload = json.loads(raw or b"{}")
                email = str(payload.get("email") or payload.get("username") or "").strip().lower()
            except Exception:  # noqa: BLE001 — 解析不了就按 IP 计，不放行
                email = ""
            if email:
                key = f"{ip}|{email}"
        if not limiter.allow(key):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"code": "RATE_LIMITED", "message": "Too many requests, try again later"},
            )

    return _dep


# —— 路径级限流（审计 P1-20）—————————————————————————————————————
#
# 认证类端点由上面的依赖式限流保护；这里覆盖"高成本 + 无上限"的面：
#   * 导出（CSV / XML / XLSX）—— 一次全表扫描
#   * PDF / 单据渲染 —— CPU 密集，还可能拉外部字体
#   * 报表执行 —— 任意维度的聚合
#   * AI 推理 —— 按 token 计费，最贵
#
# 每条策略: (scope, 路径前缀, 每窗口最大次数, 窗口秒数)
# 窗口取 60 秒 —— 够宽松，正常使用碰不到；异常/恶意的突发会被挡住。

_PATH_POLICIES: tuple[tuple[str, str, int, float], ...] = (
    ("ai", "/api/v1/ai", 30, 60.0),
    # Settings CRUD is interactive admin work (tab loads issue several GETs and
    # each save reloads the grid). 20/min was too tight and surfaced as
    # "请求过于频繁" while editing skill bindings. Inference stays at 30/min.
    ("ai", "/api/v1/settings/ai", 120, 60.0),
    ("export", "/api/v1/export", 60, 60.0),
    ("export", "/api/v1/exports", 60, 60.0),
    ("export", "/api/v1/imports", 30, 60.0),
    ("report", "/api/v1/reports", 40, 60.0),
    ("document", "/api/v1/documents", 30, 60.0),
    ("document", "/api/v1/office", 40, 60.0),
    ("payment_export", "/api/v1/payments", 30, 60.0),
    ("file", "/api/v1/files", 120, 60.0),
    ("file", "/api/v1/uploads", 120, 60.0),
)

#: 后缀策略 —— 导出端点散落在各处（``/invoices/{id}/export-xml``、
#: ``/payments/batches/{id}/export``、``/reports/{id}/export``），前缀盖不住。
_SUFFIX_POLICIES: tuple[tuple[str, str, int, float], ...] = (
    ("export", "/export", 60, 60.0),
    ("export", "/export-xml", 60, 60.0),
    ("export", "/export-csv", 60, 60.0),
    ("export", "/export-xlsx", 60, 60.0),
    ("export", "/preview/pdf", 30, 60.0),
)

#: 策略键 → (scope, limiter)
_path_limiters: dict[str, tuple[str, SlidingWindowLimiter]] = {}


def _path_limiter(key: str) -> tuple[str, SlidingWindowLimiter]:
    hit = _path_limiters.get(key)
    if hit is None:
        # 策略是 4 元组 (scope, path, max_hits, window) —— path 已由 key 命中。
        scope, _path, max_hits, window = next(
            p for p in (_PATH_POLICIES + _SUFFIX_POLICIES) if p[1] == key
        )
        hit = (scope, SlidingWindowLimiter(max_hits, window))
        _path_limiters[key] = hit
    return hit


def reset_path_limiters() -> None:
    """清空路径级限流器（测试用）。"""
    for _scope, limiter in _path_limiters.values():
        limiter.reset()


def _match_policy(path: str) -> str | None:
    """最长的匹配前缀优先 —— ``/api/v1/reports`` 要盖过 ``/api/v1/report``。

    后缀策略优先级高于前缀：``/api/v1/invoices/{id}/export-xml`` 既是
    ``/api/v1/...`` 下的路径，又明确是"导出"，应当走导出策略。
    """
    for _scope, suffix, _max_hits, _window in _SUFFIX_POLICIES:
        if path.endswith(suffix):
            return suffix
    best: str | None = None
    for _scope, prefix, _max_hits, _window in _PATH_POLICIES:
        if path.startswith(prefix) and (best is None or len(prefix) > len(best)):
            best = prefix
    return best


class RateLimitMiddleware:
    """ASGI middleware：按路径前缀限流导出 / PDF / 报表 / AI。

    与依赖式限流的区别：中间件在**路由匹配之前**生效，所以它覆盖的是
    "一整片端点"，而不是逐个端点挂依赖 —— 以后新增端点自动被覆盖。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if not get_settings().rate_limit_enabled:
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        prefix = _match_policy(path)
        if prefix is None:
            await self.app(scope, receive, send)
            return

        _scope, limiter = _path_limiter(prefix)
        client = scope.get("client")
        ip = str(client[0]) if client else "unknown"
        if not limiter.allow(ip):
            response = JSONResponse(
                status_code=429,
                content={
                    "detail": {
                        "code": "RATE_LIMITED",
                        "message": "Too many requests, try again later",
                        "scope": _scope,
                    }
                },
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

