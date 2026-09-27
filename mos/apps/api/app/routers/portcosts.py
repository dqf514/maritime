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
from app.services.port_cost_benchmark import benchmark_for_port, over_benchmark

router = APIRouter()


# —— Port disbursements ——
class PdaIn(BaseModel):
    voyage_id: UUID | None = None
    port_call_id: UUID | None = None
    pda_amount: float
    currency: str = "USD"
    lines: dict = Field(default_factory=dict)


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
    db.commit()
    return {
        "id": str(row.id),
        "status": row.status,
        "pda_amount": float(row.pda_amount or 0),
        "fda_amount": float(row.fda_amount or 0),
        "variance": float(row.variance or 0),
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
    ]




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
