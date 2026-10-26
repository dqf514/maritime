"""港口使费 PDA/FDA 路由。"""

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

from app.models_domain import PortDisbursement, Voyage
from app.services.state_machine import PDA_TRANSITIONS, transition

from app.routers._finance_common import _alive
from app.services.domain_events import emit
from app.services.port_cost_benchmark import benchmark_for_port, over_benchmark
from app.services.recycle import soft_delete

router = APIRouter()


# —— Port disbursements ——
class PdaIn(BaseModel):
    voyage_id: UUID | None = None
    port_call_id: UUID | None = None
    pda_amount: float
    currency: str = "USD"
    lines: dict = Field(default_factory=dict)


class PdaPatchIn(BaseModel):
    voyage_id: UUID | None = None
    port_call_id: UUID | None = None
    pda_amount: float | None = None
    fda_amount: float | None = None
    currency: str | None = None
    lines: dict | None = None


# Statuses where money is already committed / billed — edits and deletes blocked.
_PDA_LOCKED_STATUSES = {"approved", "fda", "closed"}


@router.post("/port-disbursements")
def create_pda(body: PdaIn, auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    row = PortDisbursement(
        tenant_id=auth.tenant_id,
        voyage_id=body.voyage_id,
        port_call_id=body.port_call_id,
        pda_amount=body.pda_amount,
        currency=body.currency,
        lines=body.lines,
        status="draft",
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "status": row.status, "pda_amount": float(row.pda_amount or 0)}


@router.post("/port-disbursements/{pda_id}/transition")
def pda_transition(
    pda_id: UUID,
    target: str,
    fda_amount: float | None = None,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = db.get(PortDisbursement, pda_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "PDA not found")
    row.status = transition("pda/fda", row.status, target, PDA_TRANSITIONS)
    if target == "fda" and fda_amount is not None:
        row.fda_amount = Decimal(str(fda_amount))
        row.variance = Decimal(str(fda_amount)) - Decimal(str(row.pda_amount or 0))
    if target == "closed":
        # 域事件：尝试自动过账 GL，失败降级为财务任务（services/automation.py）
        emit(
            db, auth.tenant_id, "pda.closed", "port_disbursement", row.id,
            payload={
                "voyage_id": str(row.voyage_id) if row.voyage_id else None,
                "pda_amount": float(row.pda_amount or 0),
                "fda_amount": float(row.fda_amount or 0) if row.fda_amount is not None else None,
                "currency": row.currency or "USD",
            },
            user_id=auth.user_id,
        )
    db.commit()
    return {
        "id": str(row.id),
        "status": row.status,
        "pda_amount": float(row.pda_amount or 0),
        "fda_amount": float(row.fda_amount or 0),
        "variance": float(row.variance or 0),
    }


@router.post("/port-disbursements/{pda_id}/gl-post")
def pda_gl_post(
    pda_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """PDA/FDA 手动触发 GL 过账（与关闭时的自动过账同一引擎，幂等）。"""
    from app.services.automation import try_post_pda_journal

    row = db.get(PortDisbursement, pda_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "PDA not found")
    journal, outcome = try_post_pda_journal(db, auth.tenant_id, row, user_id=auth.user_id)
    db.commit()
    return {
        "id": str(row.id),
        "posted": journal is not None,
        "journal_id": str(journal.id) if journal is not None else None,
        "outcome": outcome,
    }


@router.get("/port-disbursements")
def list_pda(auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    rows = db.scalars(select(PortDisbursement).where(PortDisbursement.tenant_id == auth.tenant_id)).all()
    return [
        {
            "id": str(r.id),
            "voyage_id": str(r.voyage_id) if r.voyage_id else None,
            "port_call_id": str(r.port_call_id) if r.port_call_id else None,
            "status": r.status,
            "pda_amount": float(r.pda_amount or 0),
            "fda_amount": float(r.fda_amount or 0) if r.fda_amount is not None else None,
            "variance": float(r.variance or 0) if r.variance is not None else None,
            "currency": r.currency,
            "lines": r.lines or {},
        }
        for r in rows
        if _alive(r.status)
    ]


def _pda_or_404(db: Session, tenant_id: UUID, pda_id: UUID) -> PortDisbursement:
    row = db.get(PortDisbursement, pda_id)
    if not row or row.tenant_id != tenant_id or not _alive(row.status):
        raise HTTPException(404, "PDA not found")
    return row


@router.patch("/port-disbursements/{pda_id}")
def update_pda(
    pda_id: UUID,
    body: PdaPatchIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = _pda_or_404(db, auth.tenant_id, pda_id)
    if row.status in _PDA_LOCKED_STATUSES:
        raise HTTPException(409, detail={"code": "INVALID_STATE", "message": f"PDA in status '{row.status}' cannot be edited", "status": row.status})
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(row, k, v)
    if "pda_amount" in data or "fda_amount" in data:
        if row.fda_amount is not None:
            row.variance = Decimal(str(row.fda_amount)) - Decimal(str(row.pda_amount or 0))
        else:
            row.variance = None
    db.commit()
    return {
        "id": str(row.id),
        "status": row.status,
        "pda_amount": float(row.pda_amount or 0),
        "fda_amount": float(row.fda_amount or 0) if row.fda_amount is not None else None,
        "variance": float(row.variance or 0) if row.variance is not None else None,
        "currency": row.currency,
        "lines": row.lines or {},
    }


@router.delete("/port-disbursements/{pda_id}")
def delete_pda(
    pda_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = _pda_or_404(db, auth.tenant_id, pda_id)
    if row.status in _PDA_LOCKED_STATUSES:
        raise HTTPException(409, detail={"code": "INVALID_STATE", "message": f"PDA in status '{row.status}' cannot be deleted", "status": row.status})
    soft_delete(db, tenant_id=auth.tenant_id, user_id=auth.user_id, entity_type="port_disbursement", row=row, title=f"PDA {row.id}")
    db.commit()
    return {"ok": True, "recycled": True}




@router.get("/port-costs/benchmark")
def port_cost_benchmark(
    port_id: UUID | None = Query(None),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """D8 费用基准：按港口/费目的历史确认费用统计（估算参考）。"""
    return benchmark_for_port(db, auth.tenant_id, port_id)


@router.get("/port-costs/over-benchmark")
def port_cost_over_benchmark(
    tolerance: float = Query(0.25, ge=0),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """D8 超基准预警：在办 PDA 中超出历史基准 (1+tolerance) 的费目行。"""
    return {"items": over_benchmark(db, auth.tenant_id, tolerance=tolerance)}
