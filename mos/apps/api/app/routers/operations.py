"""Operations, PortCall, Twin L1–L2."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.models_domain import (
    Charter,
    Claim,
    Estimate,
    Invoice,
    LaytimeCalc,
    NoonReport,
    OffHireEvent,
    PortCall,
    SofEvent,
    TwinAlert,
    Voyage,
)
from app.models_voyage_ext import VoyageInstruction, VoyageNote
from app.models_wave1 import Counterparty, Port, Vessel
from app.security import AuthContext, require_module
from app.services.pnl import PNL_LINE_KEYS, voyage_pnl_row
from app.services.port_functions import normalize_function_code
from app.services.alert_engine import assert_no_blocking_alerts
from app.services.audit import audit
from app.services.notifications import notify_once, role_recipients
from app.services.recycle import soft_delete
from app.services.report_sequence import assert_report_sequence, derive_report_stage
from app.services.tenant_guard import scoped_get
from app.services.state_machine import VOYAGE_TRANSITIONS, InvalidState, transition

router = APIRouter(tags=["Operations"])

# SOF（Statement of Facts）标准事件码表
SOF_EVENT_CODES: dict[str, str] = {
    "NOR": "Notice of Readiness 递交备妥通知书",
    "EOSP": "End of Sea Passage 海上航行结束（抵港）",
    "ANCHOR": "抛锚（抵锚地待泊）",
    "AWSP": "All Fast 缆绳全部带妥（靠妥）",
    "POB": "Pilot on Board 引航员登船",
    "DOCKED": "靠泊就位",
    "SHIFTED_BERTH": "移泊（更换泊位）",
    "COMMENCED": "开始装卸作业",
    "COMPLETED": "装卸作业完成",
    "HOSES_OFF": "拆除输油软管（货油作业收尾）",
    "BL_DATE": "提单签发日期",
    "SAILED": "开航离港",
}

# 现实时序上早于 NOR 的事件（抵港/抛锚/引航员登船/带缆均发生在递交通知书之前），
# 豁免"不得早于 NOR"的下界校验
SOF_PRE_NOR_EXEMPT: frozenset[str] = frozenset({"EOSP", "ANCHOR", "POB", "AWSP"})


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _alive(status: str | None) -> bool:
    return status != "deleted"


def _voyage_alert_context(row: Voyage) -> dict:
    """告警规则评估上下文（field 路径 voyage.* → evaluate_condition）。"""
    return {
        "voyage": {
            "voyage_no": row.voyage_no,
            "status": row.status,
            "cargo": row.cargo,
            "vessel_id": str(row.vessel_id) if row.vessel_id else None,
            "charter_id": str(row.charter_id) if row.charter_id else None,
        }
    }


class VoyageIn(BaseModel):
    voyage_no: str
    vessel_id: UUID | None = None
    charter_id: UUID | None = None
    cargo: str | None = None


class VoyageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    voyage_no: str
    status: str
    vessel_id: UUID | None
    charter_id: UUID | None
    cargo: str | None
    updated_at: datetime | None = None


class PortCallIn(BaseModel):
    voyage_id: UUID
    port_id: UUID | None = None
    seq: int = 1
    purpose: str = "load"
    function_code: str | None = None
    eta: datetime | None = None
    etd: datetime | None = None
    agent: str | None = None
    timezone: str = "UTC"


class PortCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    voyage_id: UUID
    port_id: UUID | None
    seq: int
    purpose: str
    function_code: str | None = None
    eta: datetime | None
    etd: datetime | None
    ata: datetime | None
    atd: datetime | None
    nor_at: datetime | None
    eosp_at: datetime | None
    bl_date: datetime | None
    agent: str | None
    timezone: str


class PortCallUpdate(BaseModel):
    """部分更新 — 只有显式传入的字段才落地（model_fields_set 语义）。"""

    port_id: UUID | None = None
    seq: int | None = None
    purpose: str | None = None
    function_code: str | None = None
    eta: datetime | None = None
    etd: datetime | None = None
    ata: datetime | None = None
    atd: datetime | None = None
    nor_at: datetime | None = None
    eosp_at: datetime | None = None
    bl_date: datetime | None = None
    agent: str | None = None
    timezone: str | None = None


class NoonIn(BaseModel):
    voyage_id: UUID
    report_at: datetime
    lat: float | None = None
    lon: float | None = None
    speed: float | None = None
    rob_fo: float | None = None
    rob_do: float | None = None
    eta_next: datetime | None = None
    remarks: str | None = None
    wind_bf: float | None = None
    sea_state: str | None = None
    current_kn: float | None = None


class NoonOut(BaseModel):
    id: UUID
    eta_deviation_hours: float | None = None
    wind_bf: float | None = None
    sea_state: str | None = None
    current_kn: float | None = None
    stage: str | None = None  # 推导的活动报告阶段（sea/arrival/in_port/cargo/bunker/departure/sof）


class SofIn(BaseModel):
    port_call_id: UUID
    event_code: str
    event_at: datetime
    local_tz: str = "UTC"
    remarks: str | None = None


class SofEventUpdate(BaseModel):
    event_code: str | None = None
    event_at: datetime | None = None
    local_tz: str | None = None
    remarks: str | None = None


@router.get("/voyages", response_model=list[VoyageOut])
def list_voyages(auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    from app.services.data_scope import apply_data_scope, effective_scope

    stmt = select(Voyage).where(Voyage.tenant_id == auth.tenant_id, Voyage.status != "deleted")
    stmt = apply_data_scope(stmt, Voyage, auth.user_id, effective_scope(db, auth.tenant_id, auth.roles, "operations"))
    rows = db.scalars(stmt.order_by(Voyage.created_at.desc())).all()
    return [VoyageOut.model_validate(r) for r in rows]


@router.post("/voyages", response_model=VoyageOut)
def create_voyage(body: VoyageIn, auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    if body.vessel_id is not None and scoped_get(db, Vessel, body.vessel_id, auth.tenant_id) is None:
        raise HTTPException(404, "Vessel not found")
    if body.charter_id is not None and scoped_get(db, Charter, body.charter_id, auth.tenant_id) is None:
        raise HTTPException(404, "Charter not found")
    row = Voyage(
        tenant_id=auth.tenant_id,
        voyage_no=body.voyage_no,
        vessel_id=body.vessel_id,
        charter_id=body.charter_id,
        cargo=body.cargo,
        status="planned",
        created_by=auth.user_id,
        updated_by=auth.user_id,
    )
    # Tasks & Alerts 可阻断保存：命中 blocking 高优先级规则 → 409 ALERT_BLOCKED
    assert_no_blocking_alerts(db, auth.tenant_id, "voyage", _voyage_alert_context(row))
    db.add(row)
    db.commit()
    db.refresh(row)
    return VoyageOut.model_validate(row)


class VoyageUpdate(BaseModel):
    voyage_no: str | None = None
    cargo: str | None = None
    vessel_id: UUID | None = None
    clear_vessel: bool = False


@router.patch("/voyages/{voyage_id}", response_model=VoyageOut)
def update_voyage(
    voyage_id: UUID,
    body: VoyageUpdate,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = db.get(Voyage, voyage_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Voyage not found")
    fields = body.model_fields_set
    if "voyage_no" in fields and body.voyage_no is not None:
        row.voyage_no = body.voyage_no
    if "cargo" in fields:
        row.cargo = body.cargo
    if body.clear_vessel or ("vessel_id" in fields and body.vessel_id is None):
        row.vessel_id = None
    elif body.vessel_id is not None:
        if scoped_get(db, Vessel, body.vessel_id, auth.tenant_id) is None:
            raise HTTPException(404, "Vessel not found")
        row.vessel_id = body.vessel_id
    # Tasks & Alerts 可阻断保存：字段落地后、提交前评估 blocking 规则
    assert_no_blocking_alerts(db, auth.tenant_id, "voyage", _voyage_alert_context(row))
    row.updated_by = auth.user_id
    audit(
        db,
        action="voyage.update",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="voyage",
        entity_id=str(row.id),
        detail={"fields": sorted(fields)},
    )
    db.commit()
    db.refresh(row)
    return VoyageOut.model_validate(row)


@router.delete("/voyages/{voyage_id}")
def delete_voyage(voyage_id: UUID, auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    row = db.get(Voyage, voyage_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Voyage not found")
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="voyage",
        row=row,
        title=row.voyage_no,
    )
    db.commit()
    return {"ok": True, "recycled": True}


class VoyageTransition(BaseModel):
    target: str


@router.post("/voyages/{voyage_id}/transition", response_model=VoyageOut)
def voyage_transition(
    voyage_id: UUID,
    body: VoyageTransition,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = db.get(Voyage, voyage_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Voyage not found")
    prev = row.status
    row.status = transition("voyage", row.status, body.target, VOYAGE_TRANSITIONS)
    now = datetime.now(timezone.utc)
    if body.target == "in_progress":
        if not row.started_at:
            row.started_at = now
        if prev == "completed":
            row.completed_at = None  # reopen：清除完成时间，保留原始开航时间
    if body.target == "completed":
        row.completed_at = now
    # Tasks & Alerts 可阻断保存：状态落地后、提交前评估 blocking 规则
    assert_no_blocking_alerts(db, auth.tenant_id, "voyage", _voyage_alert_context(row))
    audit(
        db,
        action="voyage.transition",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="voyage",
        entity_id=str(row.id),
        detail={"from": prev, "to": body.target},
    )
    db.commit()
    db.refresh(row)
    return VoyageOut.model_validate(row)


# ── Batch operations (C2-P2) ──────────────────────────────────────────────
# POST /voyages/batch — 批量 close / reopen / assign。
# 语义（部分成功允许）：
#   200 {ok:[id], failed:[{id,code,message}]} — 至少一个成功（或空输入无失败）
#   409 — 全部失败时返回第一个错误（detail 带 code/message，并附 failed 明细）
#   403 — batch close 角色不足（operations|management|tenant_admin）
#   422 BATCH_TOO_LARGE — voyage_ids > 200
# 未知/跨租户 id 记入 failed（NOT_FOUND），不整体 404、不泄露存在性。
# 状态机只走 VOYAGE_TRANSITIONS 边；reopen 走 completed → in_progress（清
# completed_at、保留 started_at），cancelled 无出边仍按 INVALID_STATE 记入 failed。

BATCH_MAX_IDS = 200
_BATCH_CLOSE_ROLES = {"operations", "management", "tenant_admin"}
_BATCH_ACTIONS = ("close", "reopen", "assign")
# close → completed（与 lifecycle「Closed」步骤一致）；reopen → in_progress
# （仅 completed 可重开；cancelled 终态 INVALID_STATE；非终态报 NOT_CLOSED）。
_BATCH_ACTION_TARGET = {"close": "completed", "reopen": "in_progress"}


class VoyageBatchIn(BaseModel):
    action: str
    voyage_ids: list[UUID]
    operator: str | None = None


class VoyageBatchFail(BaseModel):
    id: str
    code: str
    message: str


class VoyageBatchOut(BaseModel):
    ok: list[str]
    failed: list[VoyageBatchFail]


def _batch_fail(vid: UUID, code: str, message: str) -> dict:
    return {"id": str(vid), "code": code, "message": message}


def _batch_fail_from_exc(vid: UUID, exc: HTTPException) -> dict:
    detail = exc.detail
    if isinstance(detail, dict):
        return _batch_fail(vid, str(detail.get("code") or "ERROR"), str(detail.get("message") or detail))
    return _batch_fail(vid, "ERROR", str(detail))


@router.post("/voyages/batch", response_model=VoyageBatchOut)
def voyages_batch(
    body: VoyageBatchIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """批量操作航次：close（→completed）/ reopen（completed→in_progress）/ assign（写 meta.operator）。

    部分成功允许；全部失败时 409 带第一个错误。逐条独立提交/回滚。
    """
    if body.action not in _BATCH_ACTIONS:
        raise HTTPException(422, detail={"code": "INVALID_ACTION", "message": f"action must be one of {list(_BATCH_ACTIONS)}"})
    if len(body.voyage_ids) > BATCH_MAX_IDS:
        raise HTTPException(
            422,
            detail={"code": "BATCH_TOO_LARGE", "message": f"voyage_ids must be <= {BATCH_MAX_IDS}", "max": BATCH_MAX_IDS},
        )
    # IMOS：批量关闭属运营关账动作，收紧到运营/管理角色
    if body.action == "close" and not (_BATCH_CLOSE_ROLES & set(auth.roles or [])):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "Batch close requires operations/management role"})
    if body.action == "assign" and not (body.operator or "").strip():
        raise HTTPException(422, detail={"code": "OPERATOR_REQUIRED", "message": "operator is required for assign"})

    # 去重保序
    seen: set[UUID] = set()
    ids: list[UUID] = []
    for vid in body.voyage_ids:
        if vid not in seen:
            seen.add(vid)
            ids.append(vid)

    ok: list[str] = []
    failed: list[dict] = []
    target = _BATCH_ACTION_TARGET.get(body.action)

    for vid in ids:
        try:
            row = db.get(Voyage, vid)
            if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
                failed.append(_batch_fail(vid, "NOT_FOUND", "Voyage not found"))
                continue
            if body.action == "reopen" and row.status not in ("completed", "cancelled"):
                # reopen 只对终态有意义；planned→in_progress 是 start，不是 reopen
                failed.append(_batch_fail(vid, "NOT_CLOSED", f"Voyage is {row.status}, not closed"))
                continue
            if body.action == "assign":
                meta = dict(row.meta or {})
                meta["operator"] = body.operator.strip()
                row.meta = meta
                audit(
                    db,
                    action="voyage.assign",
                    tenant_id=auth.tenant_id,
                    actor_user_id=auth.user_id,
                    entity_type="voyage",
                    entity_id=str(row.id),
                    detail={"operator": body.operator.strip()},
                )
            else:
                prev = row.status
                try:
                    row.status = transition("voyage", row.status, target, VOYAGE_TRANSITIONS)
                except InvalidState as exc:
                    failed.append(_batch_fail_from_exc(vid, exc))
                    continue
                now = datetime.now(timezone.utc)
                if target == "completed":
                    row.completed_at = now
                elif target == "in_progress":
                    if not row.started_at:
                        row.started_at = now
                    if prev == "completed":
                        row.completed_at = None  # reopen：清完成时间
                assert_no_blocking_alerts(db, auth.tenant_id, "voyage", _voyage_alert_context(row))
                audit(
                    db,
                    action="voyage.transition",
                    tenant_id=auth.tenant_id,
                    actor_user_id=auth.user_id,
                    entity_type="voyage",
                    entity_id=str(row.id),
                    detail={"from": prev, "to": target, "batch": body.action},
                )
            db.commit()
            ok.append(str(vid))
        except HTTPException as exc:
            db.rollback()
            failed.append(_batch_fail_from_exc(vid, exc))
        except Exception as exc:  # noqa: BLE001 — 单条失败不拖垮整批
            db.rollback()
            failed.append(_batch_fail(vid, "ERROR", str(exc)))

    # 汇总审计（独立事务，即使 0 成功也留痕）
    audit(
        db,
        action="voyage.batch",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="voyage",
        entity_id=None,
        detail={"action": body.action, "ok": len(ok), "failed": len(failed)},
        commit=True,
    )

    if not ok and failed:
        first = failed[0]
        raise HTTPException(
            409,
            detail={"code": first["code"], "message": first["message"], "failed": failed},
        )
    return {"ok": ok, "failed": failed}


# ── Voyage itinerary template (C2-P3) ─────────────────────────────────────
# POST /voyages/{id}/copy-itinerary → 新航次（planned）+ 复制挂靠。
# 时间语义：ETA/ETD 按绝对时间原样复制（新航次尚无计划日期，绝对复制最简单可辩护）。
# 执行事实（ATA/ATD/NOR/EOSP/B/L）不复制。as_template=true 仅表示“副本即模板”，
# 不额外落库（无模板注册表）。新航次状态用 planned（VOYAGE_TRANSITIONS 无 draft 态）。


@router.post("/voyages/{voyage_id}/copy-itinerary", response_model=VoyageOut)
def copy_voyage_itinerary(
    voyage_id: UUID,
    as_template: bool = Query(False),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """复制航次挂靠行程到新航次（planned）。模板=副本本身，无额外注册。"""
    src = db.get(Voyage, voyage_id)
    if not src or src.tenant_id != auth.tenant_id or not _alive(src.status):
        raise HTTPException(404, "Voyage not found")
    src_calls = db.scalars(
        select(PortCall)
        .where(
            PortCall.tenant_id == auth.tenant_id,
            PortCall.voyage_id == src.id,
            PortCall.deleted_at.is_(None),
        )
        .order_by(PortCall.seq)
    ).all()

    base_no = f"{src.voyage_no}-COPY"
    new_no = base_no
    n = 1
    while db.scalar(select(Voyage.id).where(Voyage.tenant_id == auth.tenant_id, Voyage.voyage_no == new_no)):
        n += 1
        new_no = f"{base_no}-{n}"

    row = Voyage(
        tenant_id=auth.tenant_id,
        voyage_no=new_no,
        vessel_id=src.vessel_id,
        charter_id=src.charter_id,
        cargo=src.cargo,
        status="planned",
        meta={"copied_from": str(src.id), "as_template": bool(as_template)},
    )
    assert_no_blocking_alerts(db, auth.tenant_id, "voyage", _voyage_alert_context(row))
    db.add(row)
    db.flush()
    for pc in src_calls:
        db.add(
            PortCall(
                tenant_id=auth.tenant_id,
                voyage_id=row.id,
                port_id=pc.port_id,
                seq=pc.seq,
                purpose=pc.purpose,
                function_code=pc.function_code,
                eta=pc.eta,
                etd=pc.etd,
                agent=pc.agent,
                timezone=pc.timezone,
            )
        )
    audit(
        db,
        action="voyage.copy_itinerary",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="voyage",
        entity_id=str(row.id),
        detail={"from": str(src.id), "port_calls": len(src_calls), "as_template": bool(as_template)},
    )
    db.commit()
    db.refresh(row)
    return VoyageOut.model_validate(row)


# Estimate results → P&L line keys; keys without an estimate counterpart stay None.
_EST_LINE_MAP = {
    "revenue": "total_revenue",
    "bunker": "bunker_cost",
    "commission": "commission",
    "emissions": "emissions_cost",
}


def _pnl_block(db: Session, tenant_id: UUID, voyage: Voyage, estimate: Estimate | None) -> dict:
    row = voyage_pnl_row(db, tenant_id, voyage.id) or {}
    results = (estimate.results if estimate else None) or {}
    lines_actual = row.get("lines_actual") or {}
    lines = []
    for key in PNL_LINE_KEYS:
        est_key = _EST_LINE_MAP.get(key)
        estimated = float(results[est_key]) if est_key and results.get(est_key) is not None else None
        actual = float(lines_actual[key]) if lines_actual.get(key) is not None else None
        variance = (actual - estimated) if estimated is not None and actual is not None else None
        lines.append({"key": key, "estimated": estimated, "actual": actual, "variance": variance})
    return {
        "estimated_pnl": row.get("estimated_pnl"),
        "actual_pnl": row.get("actual_pnl"),
        "variance_pnl": row.get("variance_pnl"),
        "currency": results.get("currency") or "USD",
        "lines": lines,
    }


def _lifecycle(
    voyage: Voyage,
    charter: Charter | None,
    estimate: Estimate | None,
    laytimes: list[LaytimeCalc],
    invoices: list[Invoice],
    claims: list[Claim],
) -> list[dict]:
    def _step(key: str, en: str, zh: str, state: str, href: str, d_en: str, d_zh: str | None = None) -> dict:
        return {
            "key": key,
            "label": {"en": en, "zh": zh},
            "state": state,
            "href": href,
            # detail 双语（旧前端读字符串时兼容 str，新前端按 locale 选 en/zh）
            "detail": d_en,
            "detail_i18n": {"en": d_en, "zh": d_zh if d_zh is not None else d_en},
        }

    vid = voyage.id
    finalized = [lt for lt in laytimes if lt.status == "finalized"]
    payable = [i for i in invoices if i.status != "void"]
    all_paid = bool(payable) and all(i.status == "paid" for i in payable)
    open_claims = [c for c in claims if c.status in ("open", "negotiating")]
    completed = voyage.status == "completed"

    steps = [
        _step(
            "estimate", "Estimate", "估算",
            "done" if estimate else "todo",
            "/estimates",
            f"{estimate.title} · {estimate.status}" if estimate else "No estimate linked",
            f"{estimate.title} · {estimate.status}" if estimate else "未关联估算",
        ),
        _step(
            "charter", "Charter", "租约",
            ("done" if charter and charter.status in ("active", "completed") else "current") if charter else "todo",
            "/charters",
            f"{charter.charter_no} · {charter.status}" if charter else "No charter linked",
            f"{charter.charter_no} · {charter.status}" if charter else "未关联租约",
        ),
        _step(
            "execution", "Execution", "执行",
            "done" if completed else ("current" if voyage.status == "in_progress" else "todo"),
            f"/operations/voyages/{vid}",
            f"{voyage.status}" + (f" · started {voyage.started_at.date().isoformat()}" if voyage.started_at else ""),
            f"{voyage.status}" + (f" · 开始于 {voyage.started_at.date().isoformat()}" if voyage.started_at else ""),
        ),
        _step(
            "laytime", "Laytime", "滞期费",
            "done" if finalized else ("current" if laytimes else "todo"),
            "/finance",
            f"{len(laytimes)} calc{'s' if len(laytimes) != 1 else ''} · {len(finalized)} finalized" if laytimes else "No laytime calc",
            f"{len(laytimes)} 份计算 · {len(finalized)} 份定稿" if laytimes else "无滞期费计算",
        ),
        _step(
            "invoicing", "Invoicing", "开票",
            "done" if all_paid else ("current" if payable else "todo"),
            "/finance",
            f"{len(payable)} invoice{'s' if len(payable) != 1 else ''} · {sum(1 for i in payable if i.status == 'paid')} paid"
            if payable
            else "No invoices",
            f"{len(payable)} 张发票 · {sum(1 for i in payable if i.status == 'paid')} 张已付"
            if payable
            else "无发票",
        ),
        _step(
            "settlement", "Settlement", "结算",
            "done" if payable and all_paid and not open_claims else ("current" if payable or claims else "todo"),
            "/finance",
            f"{len(open_claims)} open claim{'s' if len(open_claims) != 1 else ''}" if open_claims else "Nothing outstanding",
            f"{len(open_claims)} 项未决索赔" if open_claims else "无未结事项",
        ),
        _step(
            "closed", "Closed", "关闭",
            ("done" if payable and all_paid and not open_claims else "current") if completed else "todo",
            f"/operations/voyages/{vid}",
            f"completed {voyage.completed_at.date().isoformat()}" if voyage.completed_at else "Voyage not completed",
            f"完成于 {voyage.completed_at.date().isoformat()}" if voyage.completed_at else "航次未完成",
        ),
    ]
    return steps


@router.get("/voyages/{voyage_id}/overview")
def voyage_overview(
    voyage_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """Voyage 360: charter, estimate, lifecycle, ops docs, laytime/claims/invoices, P&L."""
    v = db.get(Voyage, voyage_id)
    if not v or v.tenant_id != auth.tenant_id or not _alive(v.status):
        raise HTTPException(404, "Voyage not found")
    vessel = db.get(Vessel, v.vessel_id) if v.vessel_id else None
    charter = db.get(Charter, v.charter_id) if v.charter_id else None
    if charter and charter.tenant_id != auth.tenant_id:
        charter = None
    estimate = db.get(Estimate, charter.estimate_id) if charter and charter.estimate_id else None
    counterparty = db.get(Counterparty, charter.counterparty_id) if charter and charter.counterparty_id else None
    port_calls = db.scalars(
        select(PortCall)
        .where(
            PortCall.tenant_id == auth.tenant_id,
            PortCall.voyage_id == v.id,
            PortCall.deleted_at.is_(None),
        )
        .order_by(PortCall.seq)
    ).all()
    noon_count = len(
        db.scalars(
            select(NoonReport).where(
                NoonReport.tenant_id == auth.tenant_id,
                NoonReport.voyage_id == v.id,
                NoonReport.deleted_at.is_(None),
            )
        ).all()
    )
    laytimes = db.scalars(
        select(LaytimeCalc).where(LaytimeCalc.tenant_id == auth.tenant_id, LaytimeCalc.voyage_id == v.id)
    ).all()
    claims = db.scalars(
        select(Claim).where(Claim.tenant_id == auth.tenant_id, Claim.voyage_id == v.id, Claim.status != "deleted")
    ).all()
    invoices = db.scalars(
        select(Invoice).where(Invoice.tenant_id == auth.tenant_id, Invoice.voyage_id == v.id, Invoice.status != "deleted")
    ).all()
    off_hire = db.scalars(
        select(OffHireEvent).where(
            OffHireEvent.tenant_id == auth.tenant_id,
            OffHireEvent.voyage_id == v.id,
            OffHireEvent.status != "deleted",
        )
    ).all()
    results = (estimate.results if estimate else None) or {}
    return {
        "voyage": {
            "id": str(v.id),
            "voyage_no": v.voyage_no,
            "status": v.status,
            "vessel_id": str(v.vessel_id) if v.vessel_id else None,
            "vessel_name": vessel.name if vessel else None,
            "charter_id": str(v.charter_id) if v.charter_id else None,
            "cp_date": v.cp_date.isoformat() if v.cp_date else None,
            "started_at": v.started_at.isoformat() if v.started_at else None,
            "completed_at": v.completed_at.isoformat() if v.completed_at else None,
        },
        "charter": {
            "id": str(charter.id),
            "charter_no": charter.charter_no,
            "charter_type": charter.charter_type,
            "status": charter.status,
            "counterparty_name": counterparty.name if counterparty else None,
            "estimate_id": str(charter.estimate_id) if charter.estimate_id else None,
        }
        if charter
        else None,
        "estimate": {
            "id": str(estimate.id),
            "status": estimate.status,
            "results_summary": {
                "total_revenue": results.get("total_revenue"),
                "voyage_cost": results.get("voyage_cost"),
                "tce": results.get("tce"),
            },
        }
        if estimate
        else None,
        "lifecycle": _lifecycle(v, charter, estimate, laytimes, invoices, claims),
        "port_calls": [
            {
                "id": str(pc.id),
                "seq": pc.seq,
                "purpose": pc.purpose,
                "function_code": pc.function_code,
                "port_id": str(pc.port_id) if pc.port_id else None,
                "eta": pc.eta.isoformat() if pc.eta else None,
                "etd": pc.etd.isoformat() if pc.etd else None,
                "ata": pc.ata.isoformat() if pc.ata else None,
                "atd": pc.atd.isoformat() if pc.atd else None,
                "nor_at": pc.nor_at.isoformat() if pc.nor_at else None,
                "agent": pc.agent,
            }
            for pc in port_calls
        ],
        "noon_reports_count": noon_count,
        "laytime": [
            {
                "id": str(lt.id),
                "status": lt.status,
                "result_type": (lt.results or {}).get("result_type"),
                "amount": (lt.results or {}).get("amount"),
                "currency": (lt.results or {}).get("currency"),
            }
            for lt in laytimes
        ],
        "claims": [
            {
                "id": str(c.id),
                "claim_no": c.claim_no,
                "status": c.status,
                "amount": float(c.amount or 0),
                "currency": c.currency,
                "time_bar": c.time_bar.isoformat() if c.time_bar else None,
            }
            for c in claims
        ],
        "invoices": [
            {
                "id": str(i.id),
                "invoice_no": i.invoice_no,
                "invoice_type": i.invoice_type,
                "status": i.status,
                "amount": float(i.amount or 0),
                "tax_amount": float(i.tax_amount or 0),
                "paid_amount": float(i.paid_amount or 0),
                "currency": i.currency,
                "due_date": i.due_date.isoformat() if i.due_date else None,
            }
            for i in invoices
        ],
        "off_hire": [
            {
                "id": str(o.id),
                "start_at": o.start_at.isoformat() if o.start_at else None,
                "end_at": o.end_at.isoformat() if o.end_at else None,
                "deduct_hire": bool(o.deduct_hire),
                "status": o.status,
                "reason": o.reason,
            }
            for o in off_hire
        ],
        "pnl": _pnl_block(db, auth.tenant_id, v, estimate),
    }


# ── 航次备注 / 指示 / 活动流（voyage workspace Notes·Instructions·Activity 标签） ──


class VoyageNoteIn(BaseModel):
    """前端同时发 content 与 body，二者等价；content 优先。"""

    content: str | None = None
    body: str | None = None
    note_date: date | None = None
    kind: str | None = None  # instructions only: general|owner|charterer|agent
    ack: bool | None = None  # instructions only


class VoyageNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    voyage_id: UUID
    content: str
    body: str  # content 的别名镜像，前端 noteText() 两个字段都读
    note: str  # 同上，第三个别名
    note_date: date | None = None
    author_name: str | None = None
    created_by_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    kind: str | None = None  # instructions
    ack: bool | None = None  # instructions


def _get_alive_voyage(db: Session, tenant_id: UUID, voyage_id: UUID) -> Voyage:
    v = db.get(Voyage, voyage_id)
    if not v or v.tenant_id != tenant_id or not _alive(v.status):
        raise HTTPException(404, "Voyage not found")
    return v


def _note_text(body: VoyageNoteIn, *, required: bool) -> str | None:
    """content/body 等价（content 优先）。新建必填；PATCH 时缺省表示不改文本。"""
    if body.content is None and body.body is None:
        if required:
            raise HTTPException(422, "Note content is required")
        return None
    text = body.content if body.content is not None else body.body
    text = text or ""
    if not text.strip():
        raise HTTPException(422, "Note content is required")
    return text


def _note_out(row: VoyageNote | VoyageInstruction, author: User | None) -> VoyageNoteOut:
    text = row.content or ""
    out = VoyageNoteOut(
        id=row.id,
        voyage_id=row.voyage_id,
        content=text,
        body=text,
        note=text,
        note_date=row.note_date,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
    name = (author.full_name or author.email) if author else None
    out.author_name = name
    out.created_by_name = name
    if isinstance(row, VoyageInstruction):
        out.kind = row.kind
        out.ack = row.ack
    return out


def _list_notes(db: Session, model: type[VoyageNote] | type[VoyageInstruction], tenant_id: UUID, voyage_id: UUID) -> list:
    rows = db.scalars(
        select(model)
        .where(
            model.tenant_id == tenant_id,
            model.voyage_id == voyage_id,
            model.deleted_at.is_(None),
        )
        .order_by(model.created_at.desc())
    ).all()
    if not rows:
        return []
    user_ids = {r.created_by for r in rows if r.created_by}
    users = (
        {u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids))).all()} if user_ids else {}
    )
    return [_note_out(r, users.get(r.created_by)) for r in rows]


def _write_note(
    db: Session,
    *,
    model: type[VoyageNote] | type[VoyageInstruction],
    auth: AuthContext,
    voyage_id: UUID,
    body: VoyageNoteIn,
    note_id: UUID | None = None,
) -> VoyageNoteOut:
    _get_alive_voyage(db, auth.tenant_id, voyage_id)
    text = _note_text(body, required=note_id is None)
    if note_id is not None:
        row = db.get(model, note_id)
        if not row or row.tenant_id != auth.tenant_id or row.voyage_id != voyage_id or row.deleted_at:
            raise HTTPException(404, "Note not found")
        if text is not None:
            row.content = text
        if body.note_date is not None:
            row.note_date = body.note_date
        if isinstance(row, VoyageInstruction):
            if body.kind:
                row.kind = body.kind
            if body.ack is not None:
                row.ack = body.ack
        audit(
            db,
            action="update",
            tenant_id=auth.tenant_id,
            actor_user_id=auth.user_id,
            entity_type=model.__tablename__,
            entity_id=row.id,
        )
    else:
        row = model(
            tenant_id=auth.tenant_id,
            voyage_id=voyage_id,
            content=text,
            note_date=body.note_date,
            created_by=auth.user_id,
        )
        if isinstance(row, VoyageInstruction):
            if body.kind:
                row.kind = body.kind
            if body.ack is not None:
                row.ack = body.ack
        db.add(row)
        db.flush()  # row.id 就绪 —— audit / notify 用得到
        audit(
            db,
            action="create",
            tenant_id=auth.tenant_id,
            actor_user_id=auth.user_id,
            entity_type=model.__tablename__,
            entity_id=row.id,
            detail={"voyage_id": str(voyage_id)},
        )
        # 通知运营/管理人员：新备注直达工作台对应 tab（notify_once 按日去重防轰炸）
        tab = "instructions" if isinstance(row, VoyageInstruction) else "notes"
        kind_label = "instruction" if tab == "instructions" else "note"
        voyage = db.get(Voyage, voyage_id)
        recipients = [u for u in role_recipients(db, auth.tenant_id, ("operations", "management")) if u.id != auth.user_id]
        notify_once(
            db,
            auth.tenant_id,
            recipients,
            title=f"New voyage {kind_label}",
            body=f"{voyage.voyage_no if voyage else ''}: {(text or '')[:180]}",
            href=f"/operations/voyages/{voyage_id}/workspace?tab={tab}",
            level="info",
        )
    db.commit()
    db.refresh(row)
    author = db.get(User, row.created_by) if row.created_by else None
    return _note_out(row, author)


def _delete_note(
    db: Session,
    *,
    model: type[VoyageNote] | type[VoyageInstruction],
    auth: AuthContext,
    voyage_id: UUID,
    note_id: UUID,
) -> dict:
    row = db.get(model, note_id)
    if not row or row.tenant_id != auth.tenant_id or row.voyage_id != voyage_id or row.deleted_at:
        raise HTTPException(404, "Note not found")
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type=model.__tablename__,
        row=row,
        title=(row.content or "")[:80],
    )
    audit(
        db,
        action="delete",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type=model.__tablename__,
        entity_id=row.id,
    )
    db.commit()
    return {"id": str(note_id), "deleted": True}


@router.get("/voyages/{voyage_id}/notes", response_model=list[VoyageNoteOut])
def list_voyage_notes(
    voyage_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    _get_alive_voyage(db, auth.tenant_id, voyage_id)
    return _list_notes(db, VoyageNote, auth.tenant_id, voyage_id)


@router.post("/voyages/{voyage_id}/notes", response_model=VoyageNoteOut)
def create_voyage_note(
    voyage_id: UUID,
    body: VoyageNoteIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    return _write_note(db, model=VoyageNote, auth=auth, voyage_id=voyage_id, body=body)


@router.patch("/voyages/{voyage_id}/notes/{note_id}", response_model=VoyageNoteOut)
def update_voyage_note(
    voyage_id: UUID,
    note_id: UUID,
    body: VoyageNoteIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    return _write_note(db, model=VoyageNote, auth=auth, voyage_id=voyage_id, body=body, note_id=note_id)


@router.delete("/voyages/{voyage_id}/notes/{note_id}")
def remove_voyage_note(
    voyage_id: UUID,
    note_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    return _delete_note(db, model=VoyageNote, auth=auth, voyage_id=voyage_id, note_id=note_id)


@router.get("/voyages/{voyage_id}/instructions", response_model=list[VoyageNoteOut])
def list_voyage_instructions(
    voyage_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    _get_alive_voyage(db, auth.tenant_id, voyage_id)
    return _list_notes(db, VoyageInstruction, auth.tenant_id, voyage_id)


@router.post("/voyages/{voyage_id}/instructions", response_model=VoyageNoteOut)
def create_voyage_instruction(
    voyage_id: UUID,
    body: VoyageNoteIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    return _write_note(db, model=VoyageInstruction, auth=auth, voyage_id=voyage_id, body=body)


@router.patch("/voyages/{voyage_id}/instructions/{note_id}", response_model=VoyageNoteOut)
def update_voyage_instruction(
    voyage_id: UUID,
    note_id: UUID,
    body: VoyageNoteIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    return _write_note(db, model=VoyageInstruction, auth=auth, voyage_id=voyage_id, body=body, note_id=note_id)


@router.delete("/voyages/{voyage_id}/instructions/{note_id}")
def remove_voyage_instruction(
    voyage_id: UUID,
    note_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    return _delete_note(db, model=VoyageInstruction, auth=auth, voyage_id=voyage_id, note_id=note_id)


@router.get("/voyages/{voyage_id}/activity")
def voyage_activity(
    voyage_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """派生活动流：靠离泊（ATA/ATD）+ SOF 事件 + 停租 + 备注/指示增改，按时间倒序。"""
    _get_alive_voyage(db, auth.tenant_id, voyage_id)
    items: list[dict] = []

    port_calls = db.scalars(
        select(PortCall)
        .where(
            PortCall.tenant_id == auth.tenant_id,
            PortCall.voyage_id == voyage_id,
            PortCall.deleted_at.is_(None),
        )
        .order_by(PortCall.seq)
    ).all()
    port_names = {}
    port_ids = {p.port_id for p in port_calls if p.port_id}
    if port_ids:
        port_names = {
            p.id: p.name for p in db.scalars(select(Port).where(Port.id.in_(port_ids))).all()
        }
    for pc in port_calls:
        pname = port_names.get(pc.port_id, "") or ""
        if pc.ata:
            items.append(
                {
                    "id": f"{pc.id}-ata",
                    "at": pc.ata.isoformat(),
                    "kind": "port",
                    "title": f"ATA · {pname}",
                    "message": f"Arrived at {pname}" if pname else "Arrived",
                }
            )
        if pc.atd:
            items.append(
                {
                    "id": f"{pc.id}-atd",
                    "at": pc.atd.isoformat(),
                    "kind": "port",
                    "title": f"ATD · {pname}",
                    "message": f"Departed {pname}" if pname else "Departed",
                }
            )

    sof_events = db.scalars(
        select(SofEvent)
        .join(PortCall, SofEvent.port_call_id == PortCall.id)
        .where(
            SofEvent.tenant_id == auth.tenant_id,
            PortCall.voyage_id == voyage_id,
            SofEvent.deleted_at.is_(None),
        )
        .order_by(SofEvent.event_at)
    ).all()
    for ev in sof_events:
        items.append(
            {
                "id": str(ev.id),
                "at": ev.event_at.isoformat(),
                "kind": "sof",
                "title": ev.event_code,
                "message": ev.remarks or SOF_EVENT_CODES.get(ev.event_code, ev.event_code),
            }
        )

    off_hire = db.scalars(
        select(OffHireEvent).where(
            OffHireEvent.tenant_id == auth.tenant_id,
            OffHireEvent.voyage_id == voyage_id,
        )
    ).all()
    for oh in off_hire:
        items.append(
            {
                "id": str(oh.id),
                "at": oh.start_at.isoformat(),
                "kind": "off_hire",
                "title": "Off-hire",
                "message": oh.reason or (oh.event_type or "off-hire"),
            }
        )

    for model, kind in ((VoyageNote, "note"), (VoyageInstruction, "instruction")):
        for n in _list_notes(db, model, auth.tenant_id, voyage_id):
            items.append(
                {
                    "id": str(n.id),
                    "at": (n.updated_at or n.created_at).isoformat() if (n.updated_at or n.created_at) else None,
                    "kind": kind,
                    "title": kind.title(),
                    "message": (n.content or "")[:160],
                }
            )

    items.sort(key=lambda x: x.get("at") or "", reverse=True)
    return items


@router.post("/port-calls", response_model=PortCallOut)
def create_port_call(body: PortCallIn, auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    v = db.get(Voyage, body.voyage_id)
    if not v or v.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Voyage not found")
    body.function_code = normalize_function_code(body.function_code)
    row = PortCall(tenant_id=auth.tenant_id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return PortCallOut.model_validate(row)


@router.get("/port-calls", response_model=list[PortCallOut])
def list_port_calls(
    voyage_id: UUID | None = None,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    stmt = select(PortCall).where(PortCall.tenant_id == auth.tenant_id, PortCall.deleted_at.is_(None))
    if voyage_id:
        stmt = stmt.where(PortCall.voyage_id == voyage_id)
    rows = db.scalars(stmt.order_by(PortCall.seq)).all()
    return [PortCallOut.model_validate(r) for r in rows]


@router.patch("/port-calls/{port_call_id}", response_model=PortCallOut)
def update_port_call(
    port_call_id: UUID,
    body: PortCallUpdate,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = db.get(PortCall, port_call_id)
    if not row or row.tenant_id != auth.tenant_id or row.deleted_at is not None:
        raise HTTPException(404, "Port call not found")
    fields = body.model_fields_set
    if "port_id" in fields and body.port_id is not None:
        if scoped_get(db, Port, body.port_id, auth.tenant_id) is None:
            raise HTTPException(404, "Port not found")
    if "function_code" in fields:
        body.function_code = normalize_function_code(body.function_code)
    for name in (
        "port_id",
        "seq",
        "purpose",
        "function_code",
        "eta",
        "etd",
        "ata",
        "atd",
        "nor_at",
        "eosp_at",
        "bl_date",
        "agent",
        "timezone",
    ):
        if name in fields:
            setattr(row, name, getattr(body, name))
    audit(
        db,
        action="port_call.update",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="port_call",
        entity_id=str(row.id),
        detail={"fields": sorted(fields)},
    )
    db.commit()
    db.refresh(row)
    return PortCallOut.model_validate(row)


@router.delete("/port-calls/{port_call_id}")
def delete_port_call(
    port_call_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = db.get(PortCall, port_call_id)
    if not row or row.tenant_id != auth.tenant_id or row.deleted_at is not None:
        raise HTTPException(404, "Port call not found")
    # 并发原子认领（25 用户并发验收修复）：条件 UPDATE 保证同一挂靠港并发删除只有一方
    # 成功。旧读-改-写会让多方都读到“未删”状态、各自 soft_delete 后都返回 200。
    claimed = (
        db.query(PortCall)
        .filter(PortCall.id == row.id, PortCall.tenant_id == auth.tenant_id, PortCall.deleted_at.is_(None))
        .update({"deleted_at": datetime.now(timezone.utc)}, synchronize_session=False)
    )
    if claimed != 1:
        raise HTTPException(404, "Port call not found")
    # 软删挂靠港本身；其 SOF 事件保持原样（列表按“挂靠港存活”过滤，
    # 回收站恢复挂靠港后事件随之重新可见，避免级联丢失）
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="port_call",
        row=row,
        title=f"Port call #{row.seq}",
    )
    db.commit()
    return {"ok": True, "recycled": True}


@router.get("/port-calls/{port_call_id}/sof-summary")
def sof_summary(port_call_id: UUID, auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    """SOF 标准事件时间线 + 作业/等泊时长，供 laytime from-sof 消费。"""
    pc = db.get(PortCall, port_call_id)
    if not pc or pc.tenant_id != auth.tenant_id or pc.deleted_at is not None:
        raise HTTPException(404, "Port call not found")
    rows = db.scalars(
        select(SofEvent)
        .where(SofEvent.tenant_id == auth.tenant_id, SofEvent.port_call_id == pc.id, SofEvent.deleted_at.is_(None))
        .order_by(SofEvent.event_at.asc())
    ).all()
    by_code: dict[str, datetime] = {}
    for r in rows:
        by_code.setdefault(r.event_code.upper(), r.event_at)

    def _hours(start: datetime | None, end: datetime | None) -> float | None:
        if start and end:
            return round((_as_utc(end) - _as_utc(start)).total_seconds() / 3600.0, 2)
        return None

    return {
        "port_call_id": str(pc.id),
        "port_id": str(pc.port_id) if pc.port_id else None,
        "timezone": pc.timezone,
        "events": [{"code": r.event_code, "at": r.event_at.isoformat() if r.event_at else None} for r in rows],
        "working_hours": _hours(by_code.get("COMMENCED"), by_code.get("COMPLETED")),
        "waiting_hours": _hours(by_code.get("NOR"), by_code.get("COMMENCED")),
    }


@router.post("/noon-reports", response_model=NoonOut)
def create_noon(body: NoonIn, auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    v = db.get(Voyage, body.voyage_id)
    if not v or v.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Voyage not found")
    # Activity Report 审批顺序链：阶段不得回退（同阶段可重复；CFGRelaxReportSequence 可关）
    stage = assert_report_sequence(
        db,
        auth.tenant_id,
        v.id,
        report_at=body.report_at,
        lat=body.lat,
        lon=body.lon,
        speed=body.speed,
        remarks=body.remarks,
        voyage_no=v.voyage_no,
    )
    deviation = None
    # ETA deviation vs first port call ETA
    pc = db.scalar(
        select(PortCall)
        .where(PortCall.voyage_id == v.id, PortCall.deleted_at.is_(None))
        .order_by(PortCall.seq)
        .limit(1)
    )
    if pc and pc.eta and body.eta_next:
        eta = pc.eta if pc.eta.tzinfo else pc.eta.replace(tzinfo=timezone.utc)
        eta_next = body.eta_next if body.eta_next.tzinfo else body.eta_next.replace(tzinfo=timezone.utc)
        deviation = Decimal(str((eta_next - eta).total_seconds() / 3600.0))
        if abs(deviation) >= 6:
            db.add(
                TwinAlert(
                    tenant_id=auth.tenant_id,
                    level="warn",
                    title=f"ETA deviation {float(deviation):.1f}h",
                    body=f"Voyage {v.voyage_no} noon ETA drift",
                    href=f"/operations/voyages/{v.id}",
                    vessel_id=v.vessel_id,
                    voyage_id=v.id,
                )
            )
    row = NoonReport(
        tenant_id=auth.tenant_id,
        voyage_id=body.voyage_id,
        report_at=body.report_at,
        lat=body.lat,
        lon=body.lon,
        speed=body.speed,
        rob_fo=body.rob_fo,
        rob_do=body.rob_do,
        eta_next=body.eta_next,
        remarks=body.remarks,
        wind_bf=body.wind_bf,
        sea_state=body.sea_state,
        current_kn=body.current_kn,
        eta_deviation_hours=deviation,
    )
    db.add(row)
    db.commit()
    return NoonOut(
        id=row.id,
        eta_deviation_hours=float(deviation) if deviation is not None else None,
        wind_bf=body.wind_bf,
        sea_state=body.sea_state,
        current_kn=body.current_kn,
        stage=stage,
    )


class NoonDetail(BaseModel):
    """午报全字段读模型 — 列表/编辑用（NoonOut 是创建响应的精简形态）。"""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    voyage_id: UUID
    report_at: datetime
    lat: float | None = None
    lon: float | None = None
    speed: float | None = None
    rob_fo: float | None = None
    rob_do: float | None = None
    eta_next: datetime | None = None
    remarks: str | None = None
    eta_deviation_hours: float | None = None
    wind_bf: float | None = None
    sea_state: str | None = None
    current_kn: float | None = None


class NoonUpdate(BaseModel):
    report_at: datetime | None = None
    lat: float | None = None
    lon: float | None = None
    speed: float | None = None
    rob_fo: float | None = None
    rob_do: float | None = None
    eta_next: datetime | None = None
    remarks: str | None = None
    wind_bf: float | None = None
    sea_state: str | None = None
    current_kn: float | None = None


def _noon_deviation(db: Session, tenant_id: UUID, voyage_id: UUID, eta_next: datetime | None) -> Decimal | None:
    """ETA 偏差 = 首个挂靠港 ETA vs eta_next（与创建时同一口径）。"""
    if eta_next is None:
        return None
    pc = db.scalar(
        select(PortCall)
        .where(
            PortCall.tenant_id == tenant_id,
            PortCall.voyage_id == voyage_id,
            PortCall.deleted_at.is_(None),
        )
        .order_by(PortCall.seq)
        .limit(1)
    )
    if not (pc and pc.eta):
        return None
    eta = pc.eta if pc.eta.tzinfo else pc.eta.replace(tzinfo=timezone.utc)
    nxt = eta_next if eta_next.tzinfo else eta_next.replace(tzinfo=timezone.utc)
    return Decimal(str((nxt - eta).total_seconds() / 3600.0))


def _noon_detail(row: NoonReport, stage: str | None = None) -> dict:
    return {
        "id": row.id,
        "voyage_id": row.voyage_id,
        "report_at": row.report_at,
        "lat": float(row.lat) if row.lat is not None else None,
        "lon": float(row.lon) if row.lon is not None else None,
        "speed": float(row.speed) if row.speed is not None else None,
        "rob_fo": float(row.rob_fo) if row.rob_fo is not None else None,
        "rob_do": float(row.rob_do) if row.rob_do is not None else None,
        "eta_next": row.eta_next,
        "remarks": row.remarks,
        "eta_deviation_hours": float(row.eta_deviation_hours) if row.eta_deviation_hours is not None else None,
        "wind_bf": float(row.wind_bf) if row.wind_bf is not None else None,
        "sea_state": row.sea_state,
        "current_kn": float(row.current_kn) if row.current_kn is not None else None,
        "stage": stage,
    }


def _get_alive_noon(db: Session, tenant_id: UUID, noon_id: UUID) -> NoonReport:
    row = db.get(NoonReport, noon_id)
    if not row or row.tenant_id != tenant_id or row.deleted_at is not None:
        raise HTTPException(404, "Noon report not found")
    return row


@router.get("/noon-reports")
def list_noon_reports(
    voyage_id: UUID | None = None,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    stmt = select(NoonReport).where(NoonReport.tenant_id == auth.tenant_id, NoonReport.deleted_at.is_(None))
    if voyage_id:
        stmt = stmt.where(NoonReport.voyage_id == voyage_id)
    rows = db.scalars(stmt.order_by(NoonReport.report_at.asc())).all()
    # stage 推导按航次分组（同一航次的挂靠港窗口只取一次）
    pc_cache: dict[UUID, list] = {}
    out = []
    for r in rows:
        if r.voyage_id not in pc_cache:
            pc_cache[r.voyage_id] = db.scalars(
                select(PortCall).where(
                    PortCall.voyage_id == r.voyage_id,
                    PortCall.deleted_at.is_(None),
                )
            ).all()
        stage = derive_report_stage(
            report_at=r.report_at,
            lat=float(r.lat) if r.lat is not None else None,
            lon=float(r.lon) if r.lon is not None else None,
            speed=float(r.speed) if r.speed is not None else None,
            remarks=r.remarks,
            port_calls=pc_cache[r.voyage_id],
        )
        out.append(_noon_detail(r, stage))
    return out


@router.get("/noon-reports/{noon_id}")
def get_noon_report(
    noon_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = _get_alive_noon(db, auth.tenant_id, noon_id)
    pcs = db.scalars(
        select(PortCall).where(PortCall.voyage_id == row.voyage_id, PortCall.deleted_at.is_(None))
    ).all()
    stage = derive_report_stage(
        report_at=row.report_at,
        lat=float(row.lat) if row.lat is not None else None,
        lon=float(row.lon) if row.lon is not None else None,
        speed=float(row.speed) if row.speed is not None else None,
        remarks=row.remarks,
        port_calls=pcs,
    )
    return _noon_detail(row, stage)


@router.patch("/noon-reports/{noon_id}")
def update_noon_report(
    noon_id: UUID,
    body: NoonUpdate,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = _get_alive_noon(db, auth.tenant_id, noon_id)
    fields = body.model_fields_set
    for name in (
        "report_at",
        "lat",
        "lon",
        "speed",
        "rob_fo",
        "rob_do",
        "eta_next",
        "remarks",
        "wind_bf",
        "sea_state",
        "current_kn",
    ):
        if name in fields:
            setattr(row, name, getattr(body, name))
    if "eta_next" in fields or "report_at" in fields:
        row.eta_deviation_hours = _noon_deviation(db, auth.tenant_id, row.voyage_id, row.eta_next)
    audit(
        db,
        action="noon_report.update",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="noon_report",
        entity_id=str(row.id),
        detail={"fields": sorted(fields)},
    )
    db.commit()
    db.refresh(row)
    return _noon_detail(row)


@router.delete("/noon-reports/{noon_id}")
def delete_noon_report(
    noon_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = _get_alive_noon(db, auth.tenant_id, noon_id)
    row.deleted_at = datetime.now(timezone.utc)
    audit(
        db,
        action="noon_report.delete",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="noon_report",
        entity_id=str(row.id),
        detail={"voyage_id": str(row.voyage_id)},
    )
    db.commit()
    return {"ok": True, "recycled": True}


def _assert_sof_code(code: str) -> None:
    if code not in SOF_EVENT_CODES:
        raise HTTPException(
            422,
            detail={
                "code": "INVALID_SOF_EVENT_CODE",
                "message": f"Unknown SOF event code '{code}'",
                "allowed": sorted(SOF_EVENT_CODES),
            },
        )


def _assert_sof_sequence(existing: list[SofEvent], code: str, event_at: datetime) -> None:
    """SOF 时序校验：NOR 不得晚于最早非豁免事件；非豁免事件不得早于 NOR。
    existing 应已排除软删行与（PATCH 场景下的）自身行。"""
    at = _as_utc(event_at)
    if code == "NOR":
        non_exempt = [e for e in existing if e.event_code.upper() not in SOF_PRE_NOR_EXEMPT]
        if non_exempt:
            earliest = min(_as_utc(e.event_at) for e in non_exempt)
            if at > earliest:
                raise HTTPException(
                    422,
                    detail={"code": "SOF_SEQUENCE_VIOLATION", "message": "NOR must not be later than existing events of this port call"},
                )
    elif code not in SOF_PRE_NOR_EXEMPT:
        nors = [e for e in existing if e.event_code.upper() == "NOR"]
        if nors:
            nor_at = min(_as_utc(e.event_at) for e in nors)
            if at < nor_at:
                raise HTTPException(
                    422,
                    detail={"code": "SOF_SEQUENCE_VIOLATION", "message": "Event time must not be earlier than NOR of this port call"},
                )


@router.post("/sof-events")
def create_sof(body: SofIn, auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    pc = db.get(PortCall, body.port_call_id)
    if not pc or pc.tenant_id != auth.tenant_id or pc.deleted_at is not None:
        raise HTTPException(404, "Port call not found")
    code = body.event_code.upper()
    _assert_sof_code(code)
    existing = db.scalars(
        select(SofEvent).where(SofEvent.port_call_id == pc.id, SofEvent.deleted_at.is_(None))
    ).all()
    _assert_sof_sequence(existing, code, body.event_at)
    row = SofEvent(tenant_id=auth.tenant_id, **body.model_dump())
    db.add(row)
    if code == "NOR":
        if not pc.nor_at:
            pc.nor_at = body.event_at
        if not pc.ata:
            pc.ata = body.event_at
    if code == "EOSP" and not pc.eosp_at:
        pc.eosp_at = body.event_at
    if code == "BL_DATE" and not pc.bl_date:
        pc.bl_date = body.event_at
    if code in {"COMPLETED", "SAILED"}:
        pc.atd = body.event_at
    db.commit()
    return {"id": str(row.id), "event_code": row.event_code}


@router.get("/sof-events")
def list_sof_events(
    port_call_id: UUID | None = None,
    voyage_id: UUID | None = None,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    q = select(SofEvent).where(SofEvent.tenant_id == auth.tenant_id, SofEvent.deleted_at.is_(None))
    if port_call_id:
        q = q.where(SofEvent.port_call_id == port_call_id)
    elif voyage_id:
        pc_ids = db.scalars(
            select(PortCall.id).where(
                PortCall.tenant_id == auth.tenant_id,
                PortCall.voyage_id == voyage_id,
                PortCall.deleted_at.is_(None),
            )
        ).all()
        q = q.where(SofEvent.port_call_id.in_(pc_ids or [UUID(int=0)]))
    rows = db.scalars(q.order_by(SofEvent.event_at.asc())).all()
    # 挂靠港已软删的事件不对外暴露（恢复挂靠港后重新可见）
    alive_pcs = {
        pc.id
        for pc in db.scalars(
            select(PortCall).where(
                PortCall.tenant_id == auth.tenant_id,
                PortCall.id.in_([r.port_call_id for r in rows] or [UUID(int=0)]),
            )
        ).all()
        if pc.deleted_at is None
    }
    rows = [r for r in rows if r.port_call_id in alive_pcs]
    return [
        {
            "id": str(r.id),
            "port_call_id": str(r.port_call_id),
            "event_code": r.event_code,
            "event_at": r.event_at.isoformat() if r.event_at else None,
            "local_tz": r.local_tz,
            "remarks": r.remarks,
        }
        for r in rows
    ]


def _sof_public(r: SofEvent) -> dict:
    return {
        "id": str(r.id),
        "port_call_id": str(r.port_call_id),
        "event_code": r.event_code,
        "event_at": r.event_at.isoformat() if r.event_at else None,
        "local_tz": r.local_tz,
        "remarks": r.remarks,
    }


def _get_alive_sof(db: Session, tenant_id: UUID, event_id: UUID) -> SofEvent:
    row = db.get(SofEvent, event_id)
    if not row or row.tenant_id != tenant_id or row.deleted_at is not None:
        raise HTTPException(404, "SOF event not found")
    pc = db.get(PortCall, row.port_call_id)
    if not pc or pc.deleted_at is not None:
        raise HTTPException(404, "SOF event not found")
    return row


@router.patch("/sof-events/{event_id}")
def update_sof_event(
    event_id: UUID,
    body: SofEventUpdate,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = _get_alive_sof(db, auth.tenant_id, event_id)
    fields = body.model_fields_set
    new_code = (body.event_code.upper() if "event_code" in fields and body.event_code else row.event_code)
    if "event_code" in fields:
        _assert_sof_code(new_code)
    new_at = body.event_at if "event_at" in fields and body.event_at is not None else row.event_at
    if "event_code" in fields or "event_at" in fields:
        others = db.scalars(
            select(SofEvent).where(
                SofEvent.port_call_id == row.port_call_id,
                SofEvent.deleted_at.is_(None),
                SofEvent.id != row.id,
            )
        ).all()
        _assert_sof_sequence(others, new_code, new_at)

    old_at = row.event_at
    if "event_code" in fields:
        row.event_code = new_code
    if "event_at" in fields and body.event_at is not None:
        row.event_at = body.event_at
    if "local_tz" in fields:
        row.local_tz = body.local_tz or "UTC"
    if "remarks" in fields:
        row.remarks = body.remarks

    # 挂靠港派生时间字段：仅当其值来源于被改事件的旧时间时同步更新
    pc = db.get(PortCall, row.port_call_id)
    if pc and old_at is not None:
        old_utc = _as_utc(old_at)
        new_utc = _as_utc(row.event_at)
        if new_utc != old_utc:
            if row.event_code == "NOR":
                if pc.nor_at and _as_utc(pc.nor_at) == old_utc:
                    pc.nor_at = row.event_at
                if pc.ata and _as_utc(pc.ata) == old_utc:
                    pc.ata = row.event_at
            elif row.event_code == "EOSP" and pc.eosp_at and _as_utc(pc.eosp_at) == old_utc:
                pc.eosp_at = row.event_at
            elif row.event_code == "BL_DATE" and pc.bl_date and _as_utc(pc.bl_date) == old_utc:
                pc.bl_date = row.event_at
            elif row.event_code in {"COMPLETED", "SAILED"} and pc.atd and _as_utc(pc.atd) == old_utc:
                pc.atd = row.event_at

    audit(
        db,
        action="sof_event.update",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="sof_event",
        entity_id=str(row.id),
        detail={"fields": sorted(fields)},
    )
    db.commit()
    db.refresh(row)
    return _sof_public(row)


@router.delete("/sof-events/{event_id}")
def delete_sof_event(
    event_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = _get_alive_sof(db, auth.tenant_id, event_id)
    row.deleted_at = datetime.now(timezone.utc)
    audit(
        db,
        action="sof_event.delete",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="sof_event",
        entity_id=str(row.id),
        detail={"event_code": row.event_code},
    )
    db.commit()
    return {"ok": True, "recycled": True}


@router.get("/twin/fleet")
def twin_fleet(auth: AuthContext = Depends(require_module("twin")), db: Session = Depends(get_db)):
    vessels = db.scalars(select(Vessel).where(Vessel.tenant_id == auth.tenant_id)).all()
    voyages = db.scalars(select(Voyage).where(Voyage.tenant_id == auth.tenant_id, Voyage.status == "in_progress")).all()
    by_vessel = {v.vessel_id: v for v in voyages if v.vessel_id}
    points = []
    for ves in vessels:
        voy = by_vessel.get(ves.id)
        noon = None
        if voy:
            noon = db.scalar(
                select(NoonReport)
                .where(NoonReport.voyage_id == voy.id, NoonReport.deleted_at.is_(None))
                .order_by(NoonReport.report_at.desc())
                .limit(1)
            )
        points.append(
            {
                "vessel_id": str(ves.id),
                "name": ves.name,
                "imo": ves.imo,
                "voyage_no": voy.voyage_no if voy else None,
                "lat": float(noon.lat) if noon and noon.lat is not None else None,
                "lon": float(noon.lon) if noon and noon.lon is not None else None,
                "status": voy.status if voy else "idle",
            }
        )
    return {"level": "L1", "vessels": points}


@router.get("/twin/voyages/{voyage_id}")
def twin_voyage(voyage_id: UUID, auth: AuthContext = Depends(require_module("twin")), db: Session = Depends(get_db)):
    v = db.get(Voyage, voyage_id)
    if not v or v.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Voyage not found")
    calls = db.scalars(
        select(PortCall)
        .where(PortCall.voyage_id == v.id, PortCall.deleted_at.is_(None))
        .order_by(PortCall.seq)
    ).all()
    noons = db.scalars(
        select(NoonReport)
        .where(NoonReport.voyage_id == v.id, NoonReport.deleted_at.is_(None))
        .order_by(NoonReport.report_at)
    ).all()
    return {
        "level": "L2",
        "voyage": VoyageOut.model_validate(v).model_dump(),
        "port_calls": [PortCallOut.model_validate(c).model_dump() for c in calls],
        "noon_track": [
            {"at": n.report_at.isoformat(), "lat": float(n.lat) if n.lat is not None else None, "lon": float(n.lon) if n.lon is not None else None}
            for n in noons
        ],
    }


# 句式里的可枚举词（原因/证书名）小词表 —— 未命中回落英文原词
_TWIN_REASON_ZH = {
    "weather routing": "气象绕航",
    "weather": "天气",
    "port congestion": "港口拥堵",
    "crew change": "换员",
}
_TWIN_CERT_ZH = {
    "Class Annual Survey": "船级社年度检验",
    "Annual Survey": "年度检验",
    "SMC": "安全管理证书",
    "ISSC": "ISPS 证书",
    "IOPP": "防污证书",
    "Class Certificate": "船级社证书",
}


def _twin_alert_i18n(title: str, body: str | None) -> tuple[dict, dict | None]:
    """TwinAlert.title/body 是自由文本 —— 按已知句式补 {en, zh}（home._ship_alerts 的 title_i18n 先例）。

    未知句式回落原文；演示种子与午报 ETA 偏差告警的句式均已覆盖。
    """
    t_zh = title
    b_zh = body
    m = re.match(r"ETA slip (\S+) on (\S+) — (.+)$", title)
    if m:
        slip, voy, reason = m.groups()
        t_zh = f"{voy} 预计抵港延误 {slip} — {_TWIN_REASON_ZH.get(reason, reason)}"
    else:
        m = re.match(r"ETA deviation ([-+\d.]+h)$", title)
        if m:
            t_zh = f"预计抵港偏差 {m.group(1)}"
        else:
            m = re.match(r"NOR window approaching (\S+)$", title)
            if m:
                t_zh = f"{m.group(1)} NOR 窗口临近"
            else:
                m = re.match(r"Certificate (.+) due (\d+)d — (.+)$", title)
                if m:
                    cert, days, vessel = m.groups()
                    t_zh = f"{vessel} {_TWIN_CERT_ZH.get(cert, cert)} {days} 天后到期"
    if body:
        if body == "North Atlantic gale delay":
            b_zh = "北大西洋大风延误"
        else:
            m = re.match(r"Voyage (\S+) noon ETA drift$", body)
            if m:
                b_zh = f"航次 {m.group(1)} 午报 ETA 偏移"
    return (
        {"en": title, "zh": t_zh},
        {"en": body, "zh": b_zh} if body else None,
    )


@router.get("/twin/alerts")
def twin_alerts(auth: AuthContext = Depends(require_module("twin")), db: Session = Depends(get_db)):
    rows = db.scalars(select(TwinAlert).where(TwinAlert.tenant_id == auth.tenant_id).order_by(TwinAlert.created_at.desc()).limit(50)).all()
    items = []
    for r in rows:
        title_i18n, body_i18n = _twin_alert_i18n(r.title, r.body)
        items.append(
            {
                "id": str(r.id),
                "level": r.level,
                "title": r.title,
                "title_i18n": title_i18n,
                "body": r.body,
                "body_i18n": body_i18n,
                "href": r.href,
                "voyage_id": str(r.voyage_id) if r.voyage_id else None,
            }
        )
    return items


@router.post("/twin/what-if")
def twin_whatif(
    body: dict,
    auth: AuthContext = Depends(require_module("twin")),
    db: Session = Depends(get_db),
):
    from app.services.estimate_engine import compute_estimate

    estimate_inputs = body.get("estimate_inputs") or body
    try:
        base = compute_estimate(estimate_inputs, db=db, tenant_id=auth.tenant_id)
        faster = dict(estimate_inputs)
        faster["sea_days"] = float(Decimal(str(estimate_inputs.get("sea_days") or 10)) * Decimal("0.9"))
        alt = compute_estimate(faster, db=db, tenant_id=auth.tenant_id)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "INVALID_ESTIMATE_INPUT", "message": str(exc)})
    return {"level": "L4", "base_tce": base["tce"], "faster_tce": alt["tce"], "delta_tce": alt["tce"] - base["tce"]}


@router.get("/ops/eta-watch")
def ops_eta_watch(
    deviation_threshold_h: float = Query(12.0, ge=1),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """D7 ETA 监控：午报/AIS 船位快照 + ETA 偏差预警。"""
    from app.services.eta_service import eta_watch

    return eta_watch(db, auth.tenant_id, deviation_threshold_h=deviation_threshold_h)
