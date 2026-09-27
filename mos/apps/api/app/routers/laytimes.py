"""Laytime 计算路由（U1 列表协议 + D12 对账）。"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.pagination import envelope, paginate
from app.security import AuthContext, require_module

from app.models_domain import Charter, LaytimeCalc, PortCall, SofEvent, Voyage
from app.services.laytime_engine import compute_laytime, compute_laytime_statement
from app.services.clause_library import materialize_params
from app.services.recycle import soft_delete
from app.services.state_machine import LAYTIME_TRANSITIONS, transition
from app.services.tenant_guard import scoped_get

from app.routers._finance_common import _alive

from app.models_wave1 import Port

router = APIRouter()


# —— Laytime ——
class LaytimeIn(BaseModel):
    voyage_id: UUID | None = None
    port_call_id: UUID | None = None
    inputs: dict = Field(default_factory=dict)


@router.post("/laytimes")
def create_laytime(body: LaytimeIn, auth: AuthContext = Depends(require_module("laytime")), db: Session = Depends(get_db)):
    if body.voyage_id is not None and scoped_get(db, Voyage, body.voyage_id, auth.tenant_id) is None:
        raise HTTPException(404, "Voyage not found")
    if body.port_call_id is not None and scoped_get(db, PortCall, body.port_call_id, auth.tenant_id) is None:
        raise HTTPException(404, "Port call not found")
    row = LaytimeCalc(tenant_id=auth.tenant_id, voyage_id=body.voyage_id, port_call_id=body.port_call_id, inputs=body.inputs)
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


