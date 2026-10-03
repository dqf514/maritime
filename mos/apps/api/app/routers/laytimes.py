"""Laytime 计算路由（U1 列表协议 + D12 对账）。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.pagination import envelope, paginate
from app.security import AuthContext, require_module

from app.models_domain import (
    Charter,
    DemurrageOnAccount,
    DemurrageRootCause,
    Invoice,
    LaytimeCalc,
    LaytimeDelay,
    LaytimeType,
    PortCall,
    SofEvent,
    Voyage,
)
from app.models import User
from app.models_cargo import Cargo
from app.models_wave1 import Counterparty, Port
from app.models_task import Task
from app.services.laytime_engine import compute_laytime, compute_laytime_statement, settle_with_on_account
from app.services.clause_library import materialize_params
from app.services.doc_numbering import next_doc_number
from app.services.recycle import soft_delete
from app.services.sanctions import assert_not_sanctioned
from app.services.state_machine import LAYTIME_TRANSITIONS, transition
from app.services.tenant_guard import scoped_get

from app.routers._finance_common import _alive, TIMEBAR_DAYS_AFTER_BL

router = APIRouter()


# —— Laytime ——
class LaytimeIn(BaseModel):
    voyage_id: UUID | None = None
    port_call_id: UUID | None = None
    booking_reference: str | None = None
    inputs: dict = Field(default_factory=dict)


@router.post("/laytimes")
def create_laytime(body: LaytimeIn, auth: AuthContext = Depends(require_module("laytime")), db: Session = Depends(get_db)):
    if body.voyage_id is not None and scoped_get(db, Voyage, body.voyage_id, auth.tenant_id) is None:
        raise HTTPException(404, "Voyage not found")
    if body.port_call_id is not None and scoped_get(db, PortCall, body.port_call_id, auth.tenant_id) is None:
        raise HTTPException(404, "Port call not found")
    row = LaytimeCalc(
        tenant_id=auth.tenant_id,
        voyage_id=body.voyage_id,
        port_call_id=body.port_call_id,
        booking_reference=body.booking_reference,
        inputs=body.inputs,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "status": row.status}


@router.post("/laytimes/{laytime_id}/calculate")
def calc_laytime(laytime_id: UUID, auth: AuthContext = Depends(require_module("laytime")), db: Session = Depends(get_db)):
    row = db.get(LaytimeCalc, laytime_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Laytime not found")
    row.results = compute_laytime(row.inputs or {})
    row.status = transition("laytime", row.status, "calculated", LAYTIME_TRANSITIONS)
    db.commit()
    return {"id": str(row.id), "status": row.status, "results": row.results}


@router.post("/laytimes/{laytime_id}/finalize")
def finalize_laytime(laytime_id: UUID, auth: AuthContext = Depends(require_module("laytime")), db: Session = Depends(get_db)):
    row = db.get(LaytimeCalc, laytime_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Laytime not found")
    row.status = transition("laytime", row.status, "finalized", LAYTIME_TRANSITIONS)
    row.finalized_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": str(row.id), "status": row.status, "results": row.results}


@router.get("/laytimes")
def list_laytimes(
    voyage_id: UUID | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    q = select(LaytimeCalc).where(LaytimeCalc.tenant_id == auth.tenant_id, LaytimeCalc.status != "deleted")
    if voyage_id is not None:
        q = q.where(LaytimeCalc.voyage_id == voyage_id)
    rows, total = paginate(db, q.order_by(LaytimeCalc.id), limit, offset)
    return envelope(
        [
            {
                "id": str(r.id),
                "voyage_id": str(r.voyage_id) if r.voyage_id else None,
                "port_call_id": str(r.port_call_id) if r.port_call_id else None,
                "booking_reference": r.booking_reference,
                "status": r.status,
                "inputs": r.inputs or {},
                "results": r.results or {},
            }
            for r in rows
        ],
        total,
        limit,
        offset,
    )


@router.put("/laytimes/{laytime_id}")
def update_laytime(
    laytime_id: UUID,
    body: LaytimeIn,
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    row = db.get(LaytimeCalc, laytime_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Laytime not found")
    if row.status == "finalized":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "LAYTIME_FINALIZED",
                "message": "Laytime is finalized and locked; create a new revision instead of editing it",
                "status": row.status,
            },
        )
    if body.voyage_id is not None:
        if scoped_get(db, Voyage, body.voyage_id, auth.tenant_id) is None:
            raise HTTPException(404, "Voyage not found")
        row.voyage_id = body.voyage_id
    if body.port_call_id is not None:
        if scoped_get(db, PortCall, body.port_call_id, auth.tenant_id) is None:
            raise HTTPException(404, "Port call not found")
        row.port_call_id = body.port_call_id
    if body.booking_reference is not None:
        row.booking_reference = body.booking_reference
    row.inputs = body.inputs or row.inputs
    if row.status == "calculated":
        row.status = transition("laytime", "calculated", "draft", LAYTIME_TRANSITIONS)
        row.results = {}
    db.commit()
    return {"id": str(row.id), "status": row.status, "inputs": row.inputs or {}}


@router.delete("/laytimes/{laytime_id}")
def delete_laytime(laytime_id: UUID, auth: AuthContext = Depends(require_module("laytime")), db: Session = Depends(get_db)):
    row = db.get(LaytimeCalc, laytime_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Laytime not found")
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="laytime",
        row=row,
        title=f"Laytime {str(row.id)[:8]}",
    )
    db.commit()
    return {"ok": True, "recycled": True}


@router.get("/laytimes/{laytime_id}/export")
def export_laytime(laytime_id: UUID, auth: AuthContext = Depends(require_module("laytime")), db: Session = Depends(get_db)):
    """Structured laytime statement (SOF 对照计算书): every event with gross /
    term-excluded / counted hours and the cumulative used time, against the
    allowed time and the settled demurrage/despatch amount."""
    row = db.get(LaytimeCalc, laytime_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Laytime not found")
    if not row.inputs:
        raise HTTPException(422, detail={"code": "NO_INPUTS", "message": "Laytime has no inputs to export"})
    statement = compute_laytime_statement(row.inputs)
    return {
        "id": str(row.id),
        "voyage_id": str(row.voyage_id) if row.voyage_id else None,
        "port_call_id": str(row.port_call_id) if row.port_call_id else None,
        "status": row.status,
        "format": "LAYTIME_STATEMENT_v1",
        "finalized_at": row.finalized_at.isoformat() if row.finalized_at else None,
        **statement,
    }


class LaytimeFromSofIn(BaseModel):
    port_call_id: UUID
    allowed_hours: float | None = None
    terms: str | None = None
    # D6 NOR 递交条件（WIBON/WCCON/WIPON）；不传则取租约勾选条款的 nor_terms
    nor_terms: str | None = None
    # 显式覆盖：是否计入等泊时间（None=按 nor_terms 规则判定）
    count_waiting: bool | None = None


def _allowed_from_charter(charter: Charter | None, purpose: str) -> Decimal | None:
    """Default allowed hours = charter cargo_qty / load|disch rate (mt/day) * 24."""
    if not charter or not charter.cargo_qty:
        return None
    rate = charter.load_rate_pd if purpose == "load" else charter.disch_rate_pd
    if not rate or Decimal(str(rate)) <= 0:
        return None
    return (Decimal(str(charter.cargo_qty)) / Decimal(str(rate)) * Decimal("24")).quantize(Decimal("0.01"))


@router.post("/laytimes/from-sof")
def laytime_from_sof(body: LaytimeFromSofIn, auth: AuthContext = Depends(require_module("laytime")), db: Session = Depends(get_db)):
    """Build a LaytimeCalc from a port call's Statement of Facts events.

    NOR→COMMENCED becomes the waiting segment and COMMENCED→COMPLETED the
    working segment; both count subject to the charter-party terms (SHINC/SHEX
    weekend/holiday exclusions). Port holidays and timezone come from the Port
    master data. Allowed hours default to charter cargo_qty ÷ load/disch rate.
    """
    pc = db.get(PortCall, body.port_call_id)
    if not pc or pc.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Port call not found")
    sof = db.scalars(
        select(SofEvent).where(SofEvent.port_call_id == pc.id).order_by(SofEvent.event_at.asc())
    ).all()
    by_code: dict[str, list[SofEvent]] = {}
    for ev in sof:
        by_code.setdefault(ev.event_code.upper(), []).append(ev)
    if not by_code.get("COMMENCED") or not by_code.get("COMPLETED"):
        raise HTTPException(
            status_code=422,
            detail={"code": "INSUFFICIENT_SOF", "message": "SOF needs at least COMMENCED and COMPLETED events"},
        )
    commenced = by_code["COMMENCED"][0].event_at
    completed = by_code["COMPLETED"][-1].event_at

    voyage = db.get(Voyage, pc.voyage_id)
    charter = db.get(Charter, voyage.charter_id) if voyage and voyage.charter_id else None

    # D6 NOR 递交条件（条款驱动，向后兼容）：
    # - WIBON/WCCON/WIPON 或缺省：NOR 递交即起算，等泊时间计入（与历史行为一致）；
    # - BERTH_ONLY：NOR 须靠泊/备妥方为有效，靠泊前等泊时间不计（excluded）；
    # - count_waiting 显式覆盖一切规则。
    clause_codes = list((charter.clauses or {}).get("codes") or []) if charter else []
    clause_params = materialize_params(db, auth.tenant_id, clause_codes) if clause_codes else {}
    nor_terms = str(body.nor_terms or clause_params.get("nor_terms") or "").upper()

    events: list[dict] = []
    if by_code.get("NOR"):
        nor = by_code["NOR"][0].event_at
        if commenced > nor:
            if body.count_waiting is not None:
                waiting_counts = body.count_waiting
            else:
                waiting_counts = nor_terms != "BERTH_ONLY"
            events.append(
                {
                    "start": nor.isoformat(),
                    "end": commenced.isoformat(),
                    "kind": "waiting",
                    "excluded": not waiting_counts,
                }
            )
    events.append({"start": commenced.isoformat(), "end": completed.isoformat(), "kind": "working"})

    allowed = body.allowed_hours
    if allowed is None:
        derived = _allowed_from_charter(charter, pc.purpose or "load")
        if derived is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "ALLOWED_HOURS_REQUIRED",
                    "message": "Cannot derive allowed hours from charter (need cargo_qty and load/disch rate); pass allowed_hours",
                },
            )
        allowed = float(derived)

    port = db.get(Port, pc.port_id) if pc.port_id else None
    inputs: dict = {
        "allowed_hours": allowed,
        "terms": body.terms or (charter.laytime_terms if charter and charter.laytime_terms else "SHINC"),
        "events": events,
    }
    # 勾选条款的计算参数直通（once_on_demurrage 等；laytime_terms/nor_terms 已单独处理）
    inputs.update({k: v for k, v in clause_params.items() if k not in ("laytime_terms", "nor_terms")})
    if charter and charter.demurrage_rate:
        inputs["demurrage_rate_per_day"] = float(charter.demurrage_rate)
    if charter and charter.despatch_rate:
        inputs["despatch_rate_per_day"] = float(charter.despatch_rate)
    if port and port.holidays:
        inputs["port_holidays"] = port.holidays
    tz_name = (port.timezone if port else None) or pc.timezone
    if tz_name:
        inputs["port_timezone"] = tz_name

    row = LaytimeCalc(
        tenant_id=auth.tenant_id,
        voyage_id=pc.voyage_id,
        port_call_id=pc.id,
        status="draft",
        inputs=inputs,
    )
    row.results = compute_laytime(inputs)
    row.status = transition("laytime", row.status, "calculated", LAYTIME_TRANSITIONS)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "status": row.status, "inputs": row.inputs, "results": row.results}


@router.post("/laytimes/compare")
def compare_laytime_statements(
    body: dict,
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    """D12 结算单对账：my（我方计算书）vs their（对手方）→ 差异清单。

    my 可直接给 statement JSON，或给 laytime_id 由服务端现算。
    """
    from app.services.laytime_engine import compute_laytime_statement
    from app.services.statement_diff import diff_statements

    my = body.get("my")
    if my is None and body.get("laytime_id"):
        try:
            lid = UUID(str(body["laytime_id"]))
        except ValueError:
            raise HTTPException(422, "invalid laytime_id")
        row = scoped_get(db, LaytimeCalc, lid, auth.tenant_id)
        if row is None:
            raise HTTPException(404, "Laytime not found")
        my = compute_laytime_statement(row.inputs or {})
    their = body.get("their")
    if not isinstance(my, dict) or not isinstance(their, dict):
        raise HTTPException(422, detail={"code": "STATEMENTS_REQUIRED", "message": "my (or laytime_id) and their are required"})
    return diff_statements(my, their)


# —— Laytime depth: demurrage on account / root causes / delays / time bar ——

ROOT_CAUSES = ("port_congestion", "weather", "cargo_delay", "documentation", "other")
RESPONSIBLE_PARTIES = ("owner", "charterer", "port", "agent", "other")
DELAY_TYPES = ("weather", "port_congestion", "cargo", "documentation", "breakdown", "other")


def _get_laytime(auth: AuthContext, db: Session, laytime_id: UUID) -> LaytimeCalc:
    row = db.get(LaytimeCalc, laytime_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Laytime not found")
    return row


def _demurrage_amount(row: LaytimeCalc) -> Decimal:
    """Settled demurrage for a laytime (0 for despatch/on-time)."""
    results = row.results or {}
    if not results and row.inputs:
        results = compute_laytime(row.inputs or {})
    # dict 下标访问（不用 .get）：arch guard 把 .get() 误判为 ORM 查询点
    result_type = results["result_type"] if "result_type" in results else ""
    if str(result_type or "") != "demurrage":
        return Decimal("0.00")
    amount = results["amount"] if "amount" in results else 0
    return Decimal(str(amount or 0)).quantize(Decimal("0.01"))


class DemurrageOnAccountIn(BaseModel):
    amount: float
    currency: str = "USD"
    payment_date: date | None = None
    status: str = "pending"  # pending|paid|applied
    notes: str | None = None


@router.post("/laytimes/{laytime_id}/demurrage-on-account")
def create_demurrage_on_account(
    laytime_id: UUID,
    body: DemurrageOnAccountIn,
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    row = _get_laytime(auth, db, laytime_id)
    if body.amount <= 0:
        raise HTTPException(422, detail={"code": "INVALID_AMOUNT", "message": "amount must be > 0"})
    if body.status not in ("pending", "paid", "applied"):
        raise HTTPException(422, detail={"code": "INVALID_STATUS", "message": "status must be pending|paid|applied"})
    rec = DemurrageOnAccount(
        tenant_id=auth.tenant_id,
        laytime_id=row.id,
        amount=Decimal(str(body.amount)).quantize(Decimal("0.01")),
        currency=body.currency,
        payment_date=body.payment_date,
        status=body.status,
        applied_to_settlement=body.status == "applied",
        notes=body.notes,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _on_account_payload(rec)


@router.get("/laytimes/{laytime_id}/demurrage-on-account")
def list_demurrage_on_account(
    laytime_id: UUID,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    row = _get_laytime(auth, db, laytime_id)
    q = (
        select(DemurrageOnAccount)
        .where(DemurrageOnAccount.tenant_id == auth.tenant_id, DemurrageOnAccount.laytime_id == row.id)
        .order_by(DemurrageOnAccount.id)
    )
    rows, total = paginate(db, q, limit, offset)
    # 汇总口径覆盖全部分页（SQL sum，而非当前页）
    paid = db.scalar(
        select(func.coalesce(func.sum(DemurrageOnAccount.amount), 0)).where(
            DemurrageOnAccount.tenant_id == auth.tenant_id,
            DemurrageOnAccount.laytime_id == row.id,
            DemurrageOnAccount.status.in_(("paid", "applied")),
        )
    )
    return {
        **envelope([_on_account_payload(r) for r in rows], total, limit, offset),
        "on_account_paid": float(Decimal(str(paid or 0)).quantize(Decimal("0.01"))),
    }


def _on_account_payload(r: DemurrageOnAccount) -> dict:
    return {
        "id": str(r.id),
        "laytime_id": str(r.laytime_id),
        "amount": float(r.amount or 0),
        "currency": r.currency,
        "payment_date": r.payment_date.isoformat() if r.payment_date else None,
        "status": r.status,
        "applied_to_settlement": bool(r.applied_to_settlement),
        "notes": r.notes,
    }


class DemurrageRootCauseIn(BaseModel):
    cause: str
    delay_hours: float
    responsible_party: str
    notes: str | None = None


@router.post("/laytimes/{laytime_id}/root-causes")
def create_root_cause(
    laytime_id: UUID,
    body: DemurrageRootCauseIn,
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    row = _get_laytime(auth, db, laytime_id)
    if body.cause not in ROOT_CAUSES:
        raise HTTPException(422, detail={"code": "INVALID_CAUSE", "message": f"cause must be one of {list(ROOT_CAUSES)}"})
    if body.responsible_party not in RESPONSIBLE_PARTIES:
        raise HTTPException(
            422,
            detail={"code": "INVALID_RESPONSIBLE_PARTY", "message": f"responsible_party must be one of {list(RESPONSIBLE_PARTIES)}"},
        )
    if body.delay_hours < 0:
        raise HTTPException(422, detail={"code": "INVALID_HOURS", "message": "delay_hours must be >= 0"})
    rec = DemurrageRootCause(
        tenant_id=auth.tenant_id,
        laytime_id=row.id,
        cause=body.cause,
        delay_hours=Decimal(str(body.delay_hours)).quantize(Decimal("0.01")),
        responsible_party=body.responsible_party,
        notes=body.notes,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _root_cause_payload(rec)


@router.get("/laytimes/{laytime_id}/root-causes")
def list_root_causes(
    laytime_id: UUID,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    """Root causes with the demurrage amount allocated pro-rata by delay hours."""
    row = _get_laytime(auth, db, laytime_id)
    q = (
        select(DemurrageRootCause)
        .where(DemurrageRootCause.tenant_id == auth.tenant_id, DemurrageRootCause.laytime_id == row.id)
        .order_by(DemurrageRootCause.id)
    )
    rows, total = paginate(db, q, limit, offset)
    # 分摊基数覆盖全部分页（SQL sum，而非当前页）
    total_hours = Decimal(
        str(
            db.scalar(
                select(func.coalesce(func.sum(DemurrageRootCause.delay_hours), 0)).where(
                    DemurrageRootCause.tenant_id == auth.tenant_id,
                    DemurrageRootCause.laytime_id == row.id,
                )
            )
            or 0
        )
    )
    demurrage = _demurrage_amount(row)
    items = []
    for r in rows:
        share = (Decimal(str(r.delay_hours or 0)) / total_hours) if total_hours > 0 else Decimal("0")
        allocated = (demurrage * share).quantize(Decimal("0.01")) if total_hours > 0 else Decimal("0.00")
        items.append({**_root_cause_payload(r), "share_pct": float((share * 100).quantize(Decimal("0.01"))), "allocated_amount": float(allocated)})
    return {
        **envelope(items, total, limit, offset),
        "total_delay_hours": float(total_hours.quantize(Decimal("0.01"))),
        "demurrage_amount": float(demurrage),
        # 全量根因按小时占比分摊滞期；占比合计 100%，故分摊合计=滞期额
        "allocated_total": float(demurrage) if total_hours > 0 else 0.0,
    }


def _root_cause_payload(r: DemurrageRootCause) -> dict:
    return {
        "id": str(r.id),
        "laytime_id": str(r.laytime_id),
        "cause": r.cause,
        "delay_hours": float(r.delay_hours or 0),
        "responsible_party": r.responsible_party,
        "notes": r.notes,
    }


class LaytimeDelayIn(BaseModel):
    delay_type: str
    start_at: datetime
    end_at: datetime | None = None
    duration_hours: float | None = None
    excluded_from_laytime: bool = False
    cost_impact: float | None = None
    notes: str | None = None


@router.post("/laytimes/{laytime_id}/delays")
def create_laytime_delay(
    laytime_id: UUID,
    body: LaytimeDelayIn,
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    row = _get_laytime(auth, db, laytime_id)
    if body.delay_type not in DELAY_TYPES:
        raise HTTPException(422, detail={"code": "INVALID_DELAY_TYPE", "message": f"delay_type must be one of {list(DELAY_TYPES)}"})
    duration = body.duration_hours
    if body.end_at is not None:
        if body.end_at < body.start_at:
            raise HTTPException(422, detail={"code": "INVALID_PERIOD", "message": "end_at must be >= start_at"})
        if duration is None:
            duration = (body.end_at - body.start_at).total_seconds() / 3600.0
    if duration is not None and duration < 0:
        raise HTTPException(422, detail={"code": "INVALID_DURATION", "message": "duration_hours must be >= 0"})
    rec = LaytimeDelay(
        tenant_id=auth.tenant_id,
        laytime_id=row.id,
        delay_type=body.delay_type,
        start_at=body.start_at,
        end_at=body.end_at,
        duration_hours=Decimal(str(duration)).quantize(Decimal("0.01")) if duration is not None else None,
        excluded_from_laytime=body.excluded_from_laytime,
        cost_impact=Decimal(str(body.cost_impact)).quantize(Decimal("0.01")) if body.cost_impact is not None else None,
        notes=body.notes,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _delay_payload(rec)


@router.get("/laytimes/{laytime_id}/delays")
def list_laytime_delays(
    laytime_id: UUID,
    delay_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    row = _get_laytime(auth, db, laytime_id)
    q = (
        select(LaytimeDelay)
        .where(LaytimeDelay.tenant_id == auth.tenant_id, LaytimeDelay.laytime_id == row.id)
        .order_by(LaytimeDelay.id)
    )
    if delay_type is not None:
        q = q.where(LaytimeDelay.delay_type == delay_type)
    rows, total = paginate(db, q, limit, offset)
    # 汇总口径覆盖全部分页（SQL sum，与筛选条件一致）
    agg_base = select(
        func.coalesce(func.sum(LaytimeDelay.duration_hours), 0),
        func.coalesce(
            func.sum(case((LaytimeDelay.excluded_from_laytime.is_(True), LaytimeDelay.duration_hours), else_=0)),
            0,
        ),
        func.coalesce(func.sum(LaytimeDelay.cost_impact), 0),
    ).where(LaytimeDelay.tenant_id == auth.tenant_id, LaytimeDelay.laytime_id == row.id)
    if delay_type is not None:
        agg_base = agg_base.where(LaytimeDelay.delay_type == delay_type)
    total_sum, excluded_sum, cost_sum = db.execute(agg_base).one()
    total_hours = Decimal(str(total_sum or 0))
    excluded_hours = Decimal(str(excluded_sum or 0))
    counted_hours = total_hours - excluded_hours
    cost = Decimal(str(cost_sum or 0))
    return {
        **envelope([_delay_payload(r) for r in rows], total, limit, offset),
        "summary": {
            "total_delay_hours": float(total_hours.quantize(Decimal("0.01"))),
            "excluded_hours": float(excluded_hours.quantize(Decimal("0.01"))),
            "counted_hours": float(counted_hours.quantize(Decimal("0.01"))),
            "total_cost_impact": float(cost.quantize(Decimal("0.01"))),
        },
    }


def _delay_payload(r: LaytimeDelay) -> dict:
    return {
        "id": str(r.id),
        "laytime_id": str(r.laytime_id),
        "delay_type": r.delay_type,
        "start_at": r.start_at.isoformat() if r.start_at else None,
        "end_at": r.end_at.isoformat() if r.end_at else None,
        "duration_hours": float(r.duration_hours) if r.duration_hours is not None else None,
        "excluded_from_laytime": bool(r.excluded_from_laytime),
        "cost_impact": float(r.cost_impact) if r.cost_impact is not None else None,
        "notes": r.notes,
    }


@router.get("/laytimes/{laytime_id}/estimated-demurrage")
def estimated_demurrage(
    laytime_id: UUID,
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    """Estimated demurrage settlement: computed demurrage less on-account payments."""
    row = _get_laytime(auth, db, laytime_id)
    results = row.results or (compute_laytime(row.inputs or {}) if row.inputs else {})
    demurrage = _demurrage_amount(row)
    on_account_rows = db.scalars(
        select(DemurrageOnAccount).where(
            DemurrageOnAccount.tenant_id == auth.tenant_id,
            DemurrageOnAccount.laytime_id == row.id,
        )
    ).all()
    paid_amounts = [r.amount for r in on_account_rows if r.status in ("paid", "applied")]
    pending_total = sum((r.amount for r in on_account_rows if r.status == "pending"), Decimal("0"))
    settle = settle_with_on_account(demurrage, paid_amounts)
    return {
        "laytime_id": str(row.id),
        "status": row.status,
        "result_type": results.get("result_type"),
        "used_hours": results.get("used_hours"),
        "allowed_hours": results.get("allowed_hours"),
        "balance_hours": results.get("balance_hours"),
        "demurrage_amount": settle["demurrage_amount"],
        "on_account_total": settle["on_account_total"],
        "on_account_pending": float(pending_total.quantize(Decimal("0.01"))),
        "outstanding": settle["outstanding"],
        "overpaid": settle["overpaid"],
        "currency": "USD",
    }


class TimeBarTaskIn(BaseModel):
    time_bar: date | None = None
    days_before: int = 30
    priority: str = "high"
    assignee_user_id: UUID | None = None
    notes: str | None = None


@router.post("/laytimes/{laytime_id}/time-bar-task")
def create_time_bar_task(
    laytime_id: UUID,
    body: TimeBarTaskIn,
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    """Generate a follow-up task before the demurrage claim time bar expires.

    Time bar defaults to the latest B/L date on the voyage's port calls +
    TIMEBAR_DAYS_AFTER_BL (same rule as claim creation).
    """
    row = _get_laytime(auth, db, laytime_id)
    time_bar = body.time_bar
    if time_bar is None:
        bl_dates: list[date] = []
        if row.voyage_id:
            for pc in db.scalars(
                select(PortCall).where(PortCall.tenant_id == auth.tenant_id, PortCall.voyage_id == row.voyage_id)
            ).all():
                bl = getattr(pc, "bl_date", None)
                if isinstance(bl, datetime):
                    bl = bl.date()
                if bl:
                    bl_dates.append(bl)
        if not bl_dates:
            raise HTTPException(
                422,
                detail={
                    "code": "TIME_BAR_REQUIRED",
                    "message": "Cannot infer time bar (no B/L dates on the voyage); pass time_bar",
                },
            )
        time_bar = max(bl_dates) + timedelta(days=TIMEBAR_DAYS_AFTER_BL)
    if body.days_before < 0:
        raise HTTPException(422, detail={"code": "INVALID_DAYS", "message": "days_before must be >= 0"})
    if body.assignee_user_id is not None:
        user = db.get(User, body.assignee_user_id)
        if not user or user.tenant_id != auth.tenant_id:
            raise HTTPException(404, "Assignee not found")
    due_at = datetime(time_bar.year, time_bar.month, time_bar.day, tzinfo=timezone.utc) - timedelta(days=body.days_before)
    task = Task(
        tenant_id=auth.tenant_id,
        title=f"Demurrage time bar — laytime {str(row.id)[:8]}",
        description=(
            f"Time bar {time_bar.isoformat()} for laytime {str(row.id)} demurrage claim. "
            f"Submit claim / supporting documents before the bar date."
            + (f" {body.notes}" if body.notes else "")
        ),
        status="todo",
        priority=body.priority,
        due_at=due_at,
        assignee_user_id=body.assignee_user_id,
        created_by=auth.user_id,
        entity_type="laytime",
        entity_id=row.id,
        source="system",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return {
        "id": str(task.id),
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "time_bar": time_bar.isoformat(),
        "entity_type": task.entity_type,
        "entity_id": str(task.entity_id),
    }


# —— Booking-based laytime / laytime types / include-in-freight ——


class LaytimeFromBookingIn(BaseModel):
    """从订舱（cargo booking）生成装卸时间计算。

    booking_reference 落到 LaytimeCalc.booking_reference；cargo_id 可选，给出时
    航次/租约条款（allowed_hours、terms、demurrage/despatch 费率）自动带入。
    """

    booking_reference: str
    cargo_id: UUID | None = None
    voyage_id: UUID | None = None
    port_call_id: UUID | None = None
    allowed_hours: float | None = None
    terms: str | None = None
    demurrage_rate_per_day: float | None = None
    despatch_rate_per_day: float | None = None
    events: list[dict] | None = None
    inputs: dict = Field(default_factory=dict)


@router.post("/laytimes/from-booking")
def laytime_from_booking(
    body: LaytimeFromBookingIn,
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    if not body.booking_reference.strip():
        raise HTTPException(422, detail={"code": "BOOKING_REFERENCE_REQUIRED", "message": "booking_reference is required"})
    voyage_id = body.voyage_id
    port_call_id = body.port_call_id
    charter: Charter | None = None
    cargo = None
    if body.cargo_id is not None:
        cargo = scoped_get(db, Cargo, body.cargo_id, auth.tenant_id)
        if cargo is None:
            raise HTTPException(404, "Cargo not found")
        voyage_id = voyage_id or cargo.voyage_id
        if cargo.charter_id:
            charter = scoped_get(db, Charter, cargo.charter_id, auth.tenant_id)
    if voyage_id is not None:
        if scoped_get(db, Voyage, voyage_id, auth.tenant_id) is None:
            raise HTTPException(404, "Voyage not found")
        if charter is None:
            voyage = db.get(Voyage, voyage_id)
            if voyage and voyage.charter_id:
                charter = scoped_get(db, Charter, voyage.charter_id, auth.tenant_id)
    if port_call_id is not None and scoped_get(db, PortCall, port_call_id, auth.tenant_id) is None:
        raise HTTPException(404, "Port call not found")

    allowed = body.allowed_hours
    if allowed is None and cargo is not None:
        derived = _allowed_from_charter(charter, "load")
        if derived is not None:
            allowed = float(derived)
    if allowed is None and body.events:
        raise HTTPException(
            422,
            detail={
                "code": "ALLOWED_HOURS_REQUIRED",
                "message": "Cannot derive allowed hours from the booking (pass allowed_hours or link a cargo with charter rates)",
            },
        )

    inputs: dict = dict(body.inputs or {})
    if allowed is not None:
        inputs["allowed_hours"] = allowed
    inputs["terms"] = body.terms or (charter.laytime_terms if charter and charter.laytime_terms else "SHINC")
    if body.events is not None:
        inputs["events"] = body.events
    if body.demurrage_rate_per_day is not None:
        inputs["demurrage_rate_per_day"] = body.demurrage_rate_per_day
    elif charter and charter.demurrage_rate:
        inputs["demurrage_rate_per_day"] = float(charter.demurrage_rate)
    if body.despatch_rate_per_day is not None:
        inputs["despatch_rate_per_day"] = body.despatch_rate_per_day
    elif charter and charter.despatch_rate:
        inputs["despatch_rate_per_day"] = float(charter.despatch_rate)
    inputs["booking_reference"] = body.booking_reference.strip()

    row = LaytimeCalc(
        tenant_id=auth.tenant_id,
        voyage_id=voyage_id,
        port_call_id=port_call_id,
        booking_reference=body.booking_reference.strip(),
        status="draft",
        inputs=inputs,
    )
    if inputs.get("events") is not None:
        row.results = compute_laytime(inputs)
        row.status = transition("laytime", row.status, "calculated", LAYTIME_TRANSITIONS)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": str(row.id),
        "status": row.status,
        "booking_reference": row.booking_reference,
        "voyage_id": str(row.voyage_id) if row.voyage_id else None,
        "inputs": row.inputs or {},
        "results": row.results or {},
    }


# 装卸时间条款类型字典（SHINC/SHEX/SHEXUU/WWDSHEX...）——首次读取时播种标准库
LAYTIME_TYPE_SEED = (
    ("SHINC", "Sundays and Holidays Included", "周日/节假日计入", "All calendar time counts against laytime."),
    ("SHEX", "Sundays and Holidays Excluded", "周日/节假日除外", "Sundays and holidays excluded from laytime unless used."),
    ("SHEXUU", "Sundays and Holidays Excluded Unless Used", "周日/节假日除外（除非已使用）", "Excluded periods count once actually used."),
    ("SSHINC", "Saturdays, Sundays and Holidays Included", "周六/周日/节假日计入", "All calendar time including weekends counts."),
    ("SSHEX", "Saturdays, Sundays and Holidays Excluded", "周六/周日/节假日除外", "Weekends and holidays excluded unless used."),
    ("WWDSHEX", "Weather Working Days SHEX", "天气适宜工作日 SHEX", "Weather working days, Sundays/holidays excluded."),
    ("WWDSHEXUU", "Weather Working Days SHEX Unless Used", "天气适宜工作日 SHEX（除非已使用）", "Weather working days SHEX; excluded periods count if used."),
    ("WWDSSHINC", "Weather Working Days SSHINC", "天气适宜工作日 SSHINC", "Weather working days with weekends/holidays counting."),
    ("FHEX", "Fridays and Holidays Excluded", "周五/节假日除外", "Fridays and holidays excluded (Middle East trade)."),
    ("CQD", "Customary Quick Despatch", "按港口习惯尽快装卸", "No fixed laytime; customary quick despatch applies."),
    ("ATUTC", "All Time Used Time Counts", "实际使用时间计入", "All time used counts as laytime."),
)


def _ensure_laytime_types(db: Session) -> list[LaytimeType]:
    rows = db.scalars(select(LaytimeType).order_by(LaytimeType.code)).all()
    if rows:
        return list(rows)
    for code, label_en, label_zh, description in LAYTIME_TYPE_SEED:
        db.add(LaytimeType(code=code, label_en=label_en, label_zh=label_zh, description=description))
    db.commit()
    return list(db.scalars(select(LaytimeType).order_by(LaytimeType.code)).all())


@router.get("/laytimes/types")
def list_laytime_types(
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    """Laytime terms dictionary (SHINC/SHEX/SHEXUU/WWDSHEX...)."""
    rows = _ensure_laytime_types(db)
    return {
        "items": [
            {
                "id": str(r.id),
                "code": r.code,
                "label_en": r.label_en,
                "label_zh": r.label_zh,
                "description": r.description,
            }
            for r in rows
        ]
    }


class IncludeInFreightIn(BaseModel):
    freight_amount: float = 0
    currency: str = "USD"
    counterparty_id: UUID | None = None
    invoice_no: str | None = None


@router.post("/laytimes/{laytime_id}/include-in-freight")
def include_in_freight(
    laytime_id: UUID,
    body: IncludeInFreightIn | None = None,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """Bill demurrage on the freight invoice: draft freight invoice = base freight
    + settled demurrage (despatch offsets), linked back to the laytime."""
    row = _get_laytime(auth, db, laytime_id)
    payload = body or IncludeInFreightIn()
    results = row.results or (compute_laytime(row.inputs or {}) if row.inputs else {})
    result_type = str(results.get("result_type") or "")
    settlement = Decimal(str(results.get("amount") or 0)).quantize(Decimal("0.01"))
    if result_type == "despatch":
        settlement = -settlement
    else:
        settlement = settlement if result_type == "demurrage" else Decimal("0.00")
    freight = Decimal(str(payload.freight_amount or 0)).quantize(Decimal("0.01"))
    if freight + settlement <= 0:
        raise HTTPException(
            422,
            detail={"code": "NOTHING_TO_BILL", "message": "freight_amount + demurrage settlement must be > 0"},
        )
    counterparty_id = payload.counterparty_id
    if counterparty_id is not None:
        if scoped_get(db, Counterparty, counterparty_id, auth.tenant_id) is None:
            raise HTTPException(404, "Counterparty not found")
        assert_not_sanctioned(db, auth.tenant_id, counterparty_id)
    else:
        voyage = db.get(Voyage, row.voyage_id) if row.voyage_id else None
        charter = scoped_get(db, Charter, voyage.charter_id, auth.tenant_id) if voyage and voyage.charter_id else None
        counterparty_id = charter.counterparty_id if charter else None
        if counterparty_id:
            assert_not_sanctioned(db, auth.tenant_id, counterparty_id)
    inv = Invoice(
        tenant_id=auth.tenant_id,
        invoice_no=payload.invoice_no or next_doc_number(db, auth.tenant_id, Invoice, Invoice.invoice_no, "INV"),
        invoice_type="freight",
        counterparty_id=counterparty_id,
        voyage_id=row.voyage_id,
        amount=(freight + settlement),
        tax_amount=Decimal("0"),
        currency=payload.currency or "USD",
        meta={
            "laytime_id": str(row.id),
            "booking_reference": row.booking_reference,
            "freight_amount": float(freight),
            "settlement_amount": float(settlement),
            "result_type": result_type,
            "include_in_freight": True,
        },
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return {
        "id": str(inv.id),
        "invoice_no": inv.invoice_no,
        "invoice_type": inv.invoice_type,
        "status": inv.status,
        "amount": float(inv.amount),
        "freight_amount": float(freight),
        "settlement_amount": float(settlement),
        "laytime_id": str(row.id),
        "currency": inv.currency,
    }


