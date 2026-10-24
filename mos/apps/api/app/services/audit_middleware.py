"""Blanket audit coverage for state-changing API requests (审计 P1-19)。

## 为什么要有这个中间件

审计报告 P1-19 的结论是：``app/routers/`` 下 67 个路由文件里有 **54 个
``audit()`` 调用数为 0** —— 财务审批、单据出档、导出、连接器凭据变更、
平台套餐变更**全部没有留痕**。逐个端点手工补 ``audit()`` 是 1.5 人日的
工作量，而且**下一个新端点又会漏**。

所以这里用中间件做**兜底全覆盖**：凡是**已认证用户**发起的**成功**的
写操作（POST / PUT / PATCH / DELETE），自动落一条 AuditLog。

## 与显式 ``audit()`` 的关系

- 显式 ``audit()``（路由内调用）是**高质量**记录：带 ``entity_id``、
  业务 ``detail``、语义化 ``action``（如 ``voyage.update``）。
- 本中间件是**低质量但完整**的记录：``action`` 形如 ``invoice.post``，
  ``entity_type`` 由路由路径推断，``entity_id`` 取路径参数。

两者并存不冲突。中间件保证"**任何**写操作都不会没有留痕"，显式调用保证
"**关键**写操作有可读的业务语义"。

## 几条刻意的取舍

1. **只写成功（2xx/3xx）的请求。**
   失败请求不写 —— 否则未认证的扫描/爆破流量会把审计表撑爆（DB 放大攻击），
   而且认证类端点本来就有自己的失败审计（``auth.login_failed`` 等）。
2. **必须能验签出 JWT 才写。**
   归属信息（``tenant_id`` / ``actor_user_id``）来自**验签通过**的 JWT，
   不是随便解出来的 payload —— 否则伪造的 Authorization 头就能往审计表里
   写任意"某人干了某事"的假记录。没有 JWT 的请求（匿名端点、API Key）
   跳过，中间件宁可不写也不写错。
3. **独立事务。**
   审计行用**自己的** Session 提交，不搭业务事务。业务回滚时审计仍然在
   —— 这正是审计想要的语义（"他试过"也是事件）。代价是审计行可能比业务
   行晚几十毫秒落库。
4. **绝不抛异常。**
   审计写失败只记日志，绝不影响业务响应。
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from jose import JWTError, jwt
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("marios.audit")

#: 只有会改变状态的动词才需要留痕。读操作不是"事件"。
AUDITED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: 永远不审计的路径前缀 —— 基础设施 / 文档 / 元数据，不是业务变更。
SKIP_PATH_PREFIXES = (
    "/healthz",
    "/readyz",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/meta/",
)

#: 路由模板的路径前缀 —— 用来切出 entity_type。
_API_ROOT = "/api/v1/"

#: 少数路径段的复数形态与既有 entity_type 词表对不上，单独映射。
_ENTITY_ALIASES = {
    "port-calls": "port_call",
    "port-disbursements": "port_disbursement",
    "off-hire-events": "off_hire_event",
    "sof-events": "sof_event",
    "noon-reports": "noon_report",
    "tc-contracts": "tc_contract",
    "coa-contracts": "coa_contract",
    "pdas": "pda",
    "pdus": "pdu",
    "laytimes": "laytime",
    "laytime-statements": "laytime_statement",
    "bunker-orders": "bunker_order",
    "bunker-requirements": "bunker_requirement",
    "bunker-options": "bunker_option",
    "rate-tables": "rate_table",
    "pricing-templates": "pricing_template",
    "clause-templates": "clause_template",
    "ship-certificates": "ship_certificate",
    "ship-work-orders": "ship_work_order",
    "ship-terminals": "ship_terminal",
    "ship-reports": "ship_report",
    "webhook-endpoints": "webhook_endpoint",
    "email-accounts": "email_account",
    "org-units": "org_unit",
    "cargo-names": "cargo_name",
    "cargo-groups": "cargo_group",
    "port-berths": "port_berth",
    "port-aliases": "port_alias",
    "port-distances": "port_distance",
    "charter-offers": "charter_offer",
    "master-contracts": "master_contract",
    "dq-issues": "dq_issue",
    "open-positions": "open_position",
    "time-charters": "time_charter",
    "time-charter-contracts": "time_charter_contract",
}


def _entity_type_from_route(route_path: str | None, raw_path: str) -> str | None:
    """从路由模板（``/api/v1/invoices/{invoice_id}``）推出 entity_type。

    取 ``/api/v1/`` 之后的第一段，去掉 ``{...}`` 占位符，复数转单数
    （``invoices`` → ``invoice``），这样能落进工作台操作日志的
    ``_ENTITY_MODULE`` / ``_ENTITY_HREF`` 词表。
    """
    path = route_path or raw_path
    if path.startswith(_API_ROOT):
        rest = path[len(_API_ROOT):]
    else:
        return None
    segment = rest.split("/", 1)[0]
    if not segment or segment.startswith("{"):
        return None
    alias = _ENTITY_ALIASES.get(segment)
    if alias:
        return alias
    if segment.endswith("s") and not segment.endswith("ss"):
        singular = segment[:-1]
        # "voyages" → "voyage"；但 "cargos" → "cargo"（已经是单数则保留原样）
        return singular
    return segment


def _token_from_scope(scope: Scope) -> str | None:
    """从 Authorization 头或 HttpOnly cookie 里取原始 token。"""
    for key, value in scope.get("headers", []):
        if key == b"authorization":
            raw = value.decode("latin-1", "ignore")
            if raw[:7].lower() == "bearer ":
                return raw[7:].strip() or None
    for key, value in scope.get("headers", []):
        if key == b"cookie":
            raw = value.decode("latin-1", "ignore")
            for part in raw.split(";"):
                name, _, val = part.strip().partition("=")
                if name in ("marios_token", "voyageos_token") and val:
                    return val
    return None


def _verified_claims(scope: Scope) -> dict[str, Any] | None:
    """验签 JWT 并取出归属信息；验不过就返回 None（宁可不写也不写错）。"""
    token = _token_from_scope(scope)
    if not token:
        return None
    from app.config import get_settings

    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except JWTError:
        return None
    except Exception:  # noqa: BLE001 — 任何解码失败都当作"无归属"
        return None


def _client_ip(scope: Scope) -> str | None:
    client = scope.get("client")
    if client:
        return str(client[0])
    return None


def _query_keys(scope: Scope) -> list[str]:
    """只记 query 的**键名**，不记值 —— 值里可能有令牌/口令。"""
    raw = scope.get("query_string", b"")
    if not raw:
        return []
    try:
        from urllib.parse import parse_qsl

        return sorted({k for k, _ in parse_qsl(raw.decode("latin-1", "ignore"))})[:20]
    except Exception:  # noqa: BLE001
        return []


def _write_audit_row(
    *,
    action: str,
    tenant_id: UUID | None,
    actor_user_id: UUID | None,
    entity_type: str | None,
    entity_id: str | None,
    detail: dict[str, Any],
    ip: str | None,
) -> None:
    """在**独立事务**里写一行审计。永不抛异常。"""
    try:
        import app.db as db_mod
        from app.services.audit import append_audit_row

        session = db_mod.SessionLocal()
        try:
            append_audit_row(
                session,
                action=action,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                detail=detail,
                ip=ip,
            )
            session.commit()
        except Exception:  # noqa: BLE001
            session.rollback()
            raise
        finally:
            session.close()
    except Exception:  # noqa: BLE001 — 审计失败不能影响业务
        log.exception("audit middleware write failed action=%s", action)


class AuditTrailMiddleware:
    """ASGI middleware：写操作自动留痕。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "")).upper()
        path = str(scope.get("path", ""))
        if method not in AUDITED_METHODS or path.startswith(SKIP_PATH_PREFIXES):
            await self.app(scope, receive, send)
            return

        status_code = 0

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message.get("status", 0))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            # 业务异常：没有"成功的变更"，不写审计行。
            raise

        if not (200 <= status_code < 400):
            return

        claims = _verified_claims(scope)
        if not claims:
            # 没有可验证的归属信息 —— 不写（避免伪造的归属污染审计表）。
            return

        raw_actor = claims.get("sub")
        raw_tenant = claims.get("tenant_id")
        try:
            actor_user_id = UUID(str(raw_actor)) if raw_actor else None
        except (TypeError, ValueError):
            actor_user_id = None
        try:
            tenant_id = UUID(str(raw_tenant)) if raw_tenant else None
        except (TypeError, ValueError):
            tenant_id = None
        if actor_user_id is None or tenant_id is None:
            return

        route = scope.get("route")
        route_path = getattr(route, "path", None)
        entity_type = _entity_type_from_route(route_path, path)
        path_params = scope.get("path_params") or {}
        entity_id = None
        if path_params:
            # 优先取名字里带 id 的那个参数
            for key in sorted(path_params):
                if key.endswith("_id") or key == "id":
                    entity_id = str(path_params[key])
                    break
            if entity_id is None:
                entity_id = str(next(iter(path_params.values())))

        action = f"{entity_type or 'api'}.{method.lower()}"
        detail: dict[str, Any] = {
            "method": method,
            "path": path,
            "status": status_code,
            "source": "http_middleware",
        }
        if route_path:
            detail["route"] = route_path
        qk = _query_keys(scope)
        if qk:
            detail["query_keys"] = qk
        state = scope.get("state") or {}
        if state.get("request_id"):
            detail["request_id"] = state["request_id"]

        ip = _client_ip(scope)
        await run_in_threadpool(
            _write_audit_row,
            action=action,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail,
            ip=ip,
        )
