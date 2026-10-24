"""全局错误响应信封（P1-3）。

**问题**：全仓有 160+ 处 ``HTTPException``，其中 30 处是 403/409 的
``detail={"code": ..., ...}`` —— **没有 ``message``**。前端拿到的响应体只有一
个机器码，人话得靠前端那张错误字典去翻译；字典没覆盖到的码就只剩一句
``HTTP 409`` 给用户看。

**做法**：不逐处改 160 个 raise（改多了必漏），而是在**应用层**统一兜底 ——
凡是 ``detail`` 是字典且缺 ``message`` 的，一律补一句人话。

**不破坏现有契约**：

- ``detail`` 是字符串的**原样返回**（很多前端分支和测试直接比对字符串）；
- ``detail`` 是字典的**保留全部原字段**，只补一个 ``message`` 键；
- 状态码与自定义 header（``WWW-Authenticate`` 等）照旧。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

log = logging.getLogger("marios.errors")

#: 后端稳定 code → 人话（英文兜底；前端有本地化字典，会优先用前端译文）
_CODE_MESSAGES: dict[str, str] = {
    "MODULE_NOT_LICENSED": "This module is not licensed for your tenant.",
    "INVALID_STATE": "This action is not allowed in the record's current status.",
    "FORBIDDEN": "You do not have permission for this action.",
    "PERMISSION_DENIED": "You do not have permission for this action.",
    "STALE_WRITE": "This record was modified by someone else — refresh and retry.",
    "CONFLICT": "The record changed — refresh and retry.",
    "PERIOD_CLOSED": "This accounting period is closed.",
    "APPROVAL_LIMIT": "Amount exceeds your approval limit.",
    "RATE_LIMITED": "Too many requests — try again shortly.",
    "ALREADY_VOIDED": "This payment has already been voided.",
    "ALREADY_REVERSED": "This entry has already been reversed.",
    "ALREADY_SETTLED": "This record is already settled.",
    "NOT_FOUND": "Record not found.",
    "DUPLICATE": "A record with the same key already exists.",
}

_STATUS_MESSAGES: dict[int, str] = {
    400: "The request was rejected — check the values you entered.",
    401: "Authentication is required.",
    403: "Access denied for your role or module license.",
    404: "Not found.",
    409: "The record changed — refresh and retry.",
    422: "Validation failed — check the form.",
    429: "Too many requests — try again shortly.",
}


def _default_message(status_code: int, code: str, detail: dict) -> str:
    if code and code in _CODE_MESSAGES:
        return _CODE_MESSAGES[code]
    # 带上一点上下文，运维在日志里能直接看出是哪条规则拦的
    extra = ""
    for key in ("entity", "module", "field", "current", "target"):
        val = detail.get(key)
        if val:
            extra = f" ({key}={val})"
            break
    base = _STATUS_MESSAGES.get(status_code, "The operation was rejected.")
    return f"{base}{extra}"


def install_error_handlers(app: FastAPI) -> None:
    """给 app 装上统一的 HTTPException 处理器（幂等）。"""

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(_request, exc: HTTPException):  # noqa: ANN001
        detail = exc.detail
        if isinstance(detail, dict):
            payload = dict(detail)
            if not payload.get("message"):
                code = str(payload.get("code") or "")
                payload["message"] = _default_message(exc.status_code, code, payload)
                payload.setdefault("code", code or f"HTTP_{exc.status_code}")
            body: dict = {"detail": payload}
        elif isinstance(detail, str):
            # 字符串 detail 本身就是人话 —— 原样返回，不改契约
            body = {"detail": detail}
        else:
            body = {"detail": detail}
        return JSONResponse(
            status_code=exc.status_code,
            content=body,
            headers=getattr(exc, "headers", None),
        )

    log.debug("error envelope handler installed")
