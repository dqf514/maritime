"""AI 上下文快照 — 把「用户当前在看的记录/表单」打包成 LLM 可读文本。

全局助手与表单填充都需要知道用户正对着什么。本模块负责从数据库拉取实体
的关键字段（或直接接受前端提交的表单字段），产出一份紧凑的摘要，注入
prompt 的 CONTEXT 块。设计原则：

- 永不抛错：任何解析失败返回 ``None``/``{}``，AI 退化为无上下文模式；
- 永不越权：所有查询强制 ``tenant_id`` 过滤；
- 紧凑：单实体摘要控制在几十行内，避免吃掉 prompt 预算。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

log = logging.getLogger("marios.ai_context")


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def _pick(obj: Any, *names: str) -> dict:
    """从 ORM 行/字典里挑出存在的字段（跳过 None/空串）。"""
    out: dict[str, Any] = {}
    for n in names:
        v = obj.get(n) if isinstance(obj, dict) else getattr(obj, n, None)
        if v is None or v == "":
            continue
        out[n] = _iso(v) if isinstance(v, datetime) else v
    return out


def _money(v: Any) -> str:
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


# ── 实体摘要 ────────────────────────────────────────────────────────────
# 每个 handler 返回 (entity_label, fields_dict)；未注册类型返回 None。


def _summarize_estimate(db: Session, tenant_id: UUID, eid: UUID) -> tuple[str, dict] | None:
    from app.models_domain import Estimate

    row = db.scalar(select(Estimate).where(Estimate.id == eid, Estimate.tenant_id == tenant_id))
    if not row:
        return None
    fields = _pick(row, "title", "mode", "status")
    fields["vessel"] = row.vessel.name if row.vessel else None
    fields["counterparty"] = row.counterparty.name if row.counterparty else None
    inputs = dict(row.inputs or {})
    results = dict(row.results or {})
    for k in ("cargo", "load_port", "discharge_port", "laycan", "freight_rate", "demurrage_rate"):
        if inputs.get(k) is not None:
            fields[f"input.{k}"] = inputs[k]
    for k in ("tce", "total_revenue", "total_cost", "voyage_days"):
        if results.get(k) is not None:
            try:
                fields[f"result.{k}"] = _money(results[k])
            except Exception:  # noqa: BLE001
                fields[f"result.{k}"] = results[k]
    return "estimate", {k: v for k, v in fields.items() if v is not None}


def _summarize_voyage(db: Session, tenant_id: UUID, eid: UUID) -> tuple[str, dict] | None:
    from app.models_domain import PortCall, Voyage

    row = db.scalar(select(Voyage).where(Voyage.id == eid, Voyage.tenant_id == tenant_id))
    if not row:
        return None
    fields = _pick(row, "voyage_no", "status", "etd", "eta", "nor_at")
    fields["vessel"] = row.vessel.name if row.vessel else None
    ports = db.scalars(
        select(PortCall)
        .where(PortCall.voyage_id == row.id, PortCall.tenant_id == tenant_id)
        .order_by(PortCall.seq)
    ).all()
    if ports:
        fields["port_calls"] = ", ".join(
            f"{p.port_code or p.port or '?'}({p.status or '?'})" for p in ports
        )
    meta = dict(row.meta or {})
    if meta.get("nor_at"):
        fields["meta.nor_at"] = meta["nor_at"]
    return "voyage", {k: v for k, v in fields.items() if v is not None}


def _summarize_charter(db: Session, tenant_id: UUID, eid: UUID) -> tuple[str, dict] | None:
    from app.models_domain import Charter

    row = db.scalar(select(Charter).where(Charter.id == eid, Charter.tenant_id == tenant_id))
    if not row:
        return None
    fields = _pick(row, "charter_no", "status", "charter_type", "laycan_from", "laycan_to")
    fields["vessel"] = row.vessel.name if getattr(row, "vessel", None) else None
    cp = getattr(row, "counterparty", None)
    if cp is not None:
        fields["counterparty"] = cp.name
    inputs = dict(getattr(row, "inputs", None) or {})
    for k in ("cargo", "freight_rate", "demurrage_rate", "despatch_rate"):
        if inputs.get(k) is not None:
            fields[f"term.{k}"] = inputs[k]
    return "charter", {k: v for k, v in fields.items() if v is not None}


def _summarize_invoice(db: Session, tenant_id: UUID, eid: UUID) -> tuple[str, dict] | None:
    from app.models_gl import Invoice

    row = db.scalar(select(Invoice).where(Invoice.id == eid, Invoice.tenant_id == tenant_id))
    if not row:
        return None
    fields = _pick(row, "invoice_no", "status", "currency", "due_date", "issued_at")
    for k in ("amount", "tax", "total"):
        v = getattr(row, k, None)
        if v is not None:
            try:
                fields[k] = _money(v)
            except Exception:  # noqa: BLE001
                fields[k] = v
    cp = getattr(row, "counterparty", None)
    if cp is not None:
        fields["counterparty"] = cp.name
    return "invoice", {k: v for k, v in fields.items() if v is not None}


def _summarize_laytime(db: Session, tenant_id: UUID, eid: UUID) -> tuple[str, dict] | None:
    from app.models_domain import LaytimeCalc

    row = db.scalar(select(LaytimeCalc).where(LaytimeCalc.id == eid, LaytimeCalc.tenant_id == tenant_id))
    if not row:
        return None
    fields = _pick(row, "status", "booking_reference")
    inputs = dict(row.inputs or {})
    results = dict(row.results or {})
    if inputs.get("sof_events"):
        fields["sof_events"] = len(inputs["sof_events"])
    if inputs.get("allowed_days") is not None:
        fields["allowed_days"] = inputs["allowed_days"]
    for k in ("laytime_days", "demurrage_days", "despatch_days", "demurrage_amount"):
        if results.get(k) is not None:
            fields[f"result.{k}"] = results[k]
    return "laytime", {k: v for k, v in fields.items() if v is not None}


def _summarize_vessel(db: Session, tenant_id: UUID, eid: UUID) -> tuple[str, dict] | None:
    from app.models_wave1 import Vessel

    row = db.scalar(select(Vessel).where(Vessel.id == eid, Vessel.tenant_id == tenant_id))
    if not row:
        return None
    fields = _pick(row, "name", "imo", "flag", "dwt", "built", "status")
    return "vessel", {k: v for k, v in fields.items() if v is not None}


_SUMMARIZERS = {
    "estimate": _summarize_estimate,
    "voyage": _summarize_voyage,
    "charter": _summarize_charter,
    "invoice": _summarize_invoice,
    "laytime": _summarize_laytime,
    "vessel": _summarize_vessel,
}


def summarize_entity(db: Session, tenant_id: UUID, entity_type: str, entity_id: Any) -> dict | None:
    """按类型拉取实体摘要。未注册类型或查不到 → None（永不抛错）。"""
    fn = _SUMMARIZERS.get(str(entity_type or "").lower())
    if fn is None:
        return None
    try:
        eid = UUID(str(entity_id))
    except (ValueError, TypeError):
        return None
    try:
        hit = fn(db, tenant_id, eid)
        return {"entity_type": hit[0], "summary": hit[1]} if hit else None
    except Exception:  # noqa: BLE001 — 摘要失败不阻断 AI
        log.exception("ai_context: summarize %s/%s failed", entity_type, entity_id)
        return None


def build_context(
    db: Session,
    tenant_id: UUID,
    *,
    entity_type: str | None = None,
    entity_id: Any = None,
    page: str | None = None,
    form_fields: dict | None = None,
    selected_text: str | None = None,
    extra: dict | None = None,
) -> dict:
    """组装 AI 用的上下文字典（存进 conv.context_json / 直接拼 prompt）。

    - 实体摘要（能识别就带）
    - 表单当前值（前端提交的字段快照）
    - 选中文本（compare 场景：用户划了一段数字/条款来问）
    - 页面路径
    """
    ctx: dict[str, Any] = {}
    if page:
        ctx["page"] = str(page)[:300]
    if entity_type and entity_id is not None:
        ctx["entity_type"] = str(entity_type)
        ctx["entity_id"] = str(entity_id)
        snap = summarize_entity(db, tenant_id, entity_type, entity_id)
        if snap:
            ctx["summary"] = snap["summary"]
    if form_fields:
        # 只保留标量/短值 —— 大对象会撑爆 prompt
        ctx["form_fields"] = {
            k: (v if isinstance(v, (str, int, float, bool)) or v is None else str(v)[:200])
            for k, v in list(form_fields.items())[:40]
        }
    if selected_text and str(selected_text).strip():
        ctx["text"] = str(selected_text)[:4000]
    if extra and isinstance(extra, dict):
        ctx["extra"] = {k: str(v)[:300] for k, v in list(extra.items())[:20]}
    ctx["captured_at"] = datetime.now(timezone.utc).isoformat()
    return ctx
