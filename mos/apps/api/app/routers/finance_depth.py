"""财务纵深路由 — 转开/代垫发票（rebilling）+ 佣金八类（commissions）。

- ``/rebill-invoices``：代垫费用转开给对手方，含超额度（over-cap）标记与
  draft→sent→paid/cancelled 状态推进；
- ``/commissions``：佣金类型目录、计佣试算、佣金明细落库。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_domain import Invoice
from app.models_finance_ext import CommissionType, RebillInvoice
from app.models_wave1 import Counterparty
from app.pagination import envelope, paginate
from app.security import AuthContext, require_module
from app.services.commission import (
    calculate_commission,
    commission_type_catalog,
    create_commission_record,
)
from app.services.doc_numbering import next_doc_number
from app.services.tenant_guard import scoped_get, scoped_query

router = APIRouter()

REBILL_STATUSES = ("draft", "sent", "paid", "cancelled")
REBILL_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("sent", "cancelled"),
    "sent": ("paid", "cancelled"),
    "paid": (),
    "cancelled": (),
}
REBILL_EXPENSE_TYPES = ("port_expense", "bunker", "other")


def _f(val: Any) -> float:
    return float(val or 0)


def _rebill_out(row: RebillInvoice) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "rebill_no": row.rebill_no,
        "source_invoice_id": str(row.source_invoice_id) if row.source_invoice_id else None,
        "source_expense_type": row.source_expense_type,
        "counterparty_id": str(row.counterparty_id) if row.counterparty_id else None,
        "amount": _f(row.amount),
        "currency": row.currency,
        "status": row.status,
        "over_cap": bool(row.over_cap),
        "cap_amount": _f(row.cap_amount) if row.cap_amount is not None else None,
        "notes": row.notes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _commission_out(row: CommissionType) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "commission_type": row.commission_type,
        "base_amount": _f(row.base_amount),
        "rate_pct": _f(row.rate_pct),
        "calculated_amount": _f(row.calculated_amount),
        "currency": row.currency,
        "invoice_id": str(row.invoice_id) if row.invoice_id else None,
        "counterparty_id": str(row.counterparty_id) if row.counterparty_id else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _over_cap(amount: Decimal, cap_amount: Decimal | None) -> bool:
    return cap_amount is not None and Decimal(str(amount)) > Decimal(str(cap_amount))


# —— 转开/代垫发票 ————————————————————————————————————————————


class RebillIn(BaseModel):
    source_invoice_id: UUID | None = None
    source_expense_type: str = "other"
    counterparty_id: UUID | None = None
    amount: float = Field(..., gt=0)
    currency: str = "USD"
    cap_amount: float | None = None
    notes: str | None = None


class RebillPatch(BaseModel):
    source_expense_type: str | None = None
    counterparty_id: UUID | None = None
    amount: float | None = Field(None, gt=0)
    currency: str | None = None
    cap_amount: float | None = None
    notes: str | None = None


def _assert_rebill_refs(db: Session, tenant_id: UUID, body: RebillIn | RebillPatch) -> None:
    source_invoice_id = getattr(body, "source_invoice_id", None)
    if source_invoice_id is not None:
        if scoped_get(db, Invoice, source_invoice_id, tenant_id) is None:
            raise HTTPException(404, detail={"code": "INVOICE_NOT_FOUND", "message": str(source_invoice_id)})
    counterparty_id = getattr(body, "counterparty_id", None)
    if counterparty_id is not None:
        if scoped_get(db, Counterparty, counterparty_id, tenant_id) is None:
            raise HTTPException(404, detail={"code": "COUNTERPARTY_NOT_FOUND", "message": str(counterparty_id)})
    expense_type = getattr(body, "source_expense_type", None)
    if expense_type is not None and expense_type not in REBILL_EXPENSE_TYPES:
        raise HTTPException(
            422,
            detail={"code": "BAD_EXPENSE_TYPE", "message": f"expected one of {REBILL_EXPENSE_TYPES}"},
        )


@router.post("/rebill-invoices")
def create_rebill(
    body: RebillIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    _assert_rebill_refs(db, auth.tenant_id, body)
    row = RebillInvoice(
        tenant_id=auth.tenant_id,
        rebill_no=next_doc_number(db, auth.tenant_id, RebillInvoice, RebillInvoice.rebill_no, "RB"),
        source_invoice_id=body.source_invoice_id,
        source_expense_type=body.source_expense_type,
        counterparty_id=body.counterparty_id,
        amount=Decimal(str(body.amount)),
        currency=body.currency,
        status="draft",
        cap_amount=Decimal(str(body.cap_amount)) if body.cap_amount is not None else None,
        over_cap=_over_cap(Decimal(str(body.amount)), Decimal(str(body.cap_amount)) if body.cap_amount is not None else None),
        notes=body.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _rebill_out(row)


@router.get("/rebill-invoices")
def list_rebills(
    status: str | None = Query(None),
    over_cap: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    stmt = scoped_query(db, RebillInvoice, auth.tenant_id).order_by(RebillInvoice.created_at.desc())
    if status:
        stmt = stmt.where(RebillInvoice.status == status)
    if over_cap is not None:
        stmt = stmt.where(RebillInvoice.over_cap == over_cap)
    rows, total = paginate(db, stmt, limit, offset)
    return envelope([_rebill_out(r) for r in rows], total, limit, offset)


@router.get("/rebill-invoices/over-cap")
def list_rebills_over_cap(
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """超额度转开清单（无分页，量小；告警面板用）。"""
    stmt = (
        scoped_query(db, RebillInvoice, auth.tenant_id)
        .where(RebillInvoice.over_cap == True)  # noqa: E712
        .order_by(RebillInvoice.created_at.desc())
    )
    rows = db.scalars(stmt).all()
    return [_rebill_out(r) for r in rows]


@router.get("/rebill-invoices/{rebill_id}")
def get_rebill(
    rebill_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, RebillInvoice, rebill_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, detail={"code": "REBILL_NOT_FOUND", "message": str(rebill_id)})
    return _rebill_out(row)


@router.patch("/rebill-invoices/{rebill_id}")
def patch_rebill(
    rebill_id: UUID,
    body: RebillPatch,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, RebillInvoice, rebill_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, detail={"code": "REBILL_NOT_FOUND", "message": str(rebill_id)})
    if row.status not in ("draft", "sent"):
        raise HTTPException(
            409,
            detail={"code": "INVALID_STATE", "message": f"Cannot edit rebill in status {row.status}"},
        )
    _assert_rebill_refs(db, auth.tenant_id, body)
    if body.source_expense_type is not None:
        row.source_expense_type = body.source_expense_type
    if body.counterparty_id is not None:
        row.counterparty_id = body.counterparty_id
    if body.amount is not None:
        row.amount = Decimal(str(body.amount))
    if body.currency is not None:
        row.currency = body.currency
    if body.cap_amount is not None:
        row.cap_amount = Decimal(str(body.cap_amount))
    if body.notes is not None:
        row.notes = body.notes
    row.over_cap = _over_cap(Decimal(str(row.amount)), Decimal(str(row.cap_amount)) if row.cap_amount is not None else None)
    db.commit()
    db.refresh(row)
    return _rebill_out(row)


@router.post("/rebill-invoices/{rebill_id}/transition")
def transition_rebill(
    rebill_id: UUID,
    target: str,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, RebillInvoice, rebill_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, detail={"code": "REBILL_NOT_FOUND", "message": str(rebill_id)})
    if target not in REBILL_TRANSITIONS.get(row.status, ()):
        raise HTTPException(
            409,
            detail={"code": "INVALID_STATE", "message": f"Cannot move rebill from {row.status} to {target}"},
        )
    row.status = target
    db.commit()
    db.refresh(row)
    return _rebill_out(row)


@router.delete("/rebill-invoices/{rebill_id}")
def delete_rebill(
    rebill_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, RebillInvoice, rebill_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, detail={"code": "REBILL_NOT_FOUND", "message": str(rebill_id)})
    row.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "deleted_at": row.deleted_at.isoformat()}


# —— 佣金八类 ————————————————————————————————————————————————


class CommissionCalcIn(BaseModel):
    commission_type: str
    base_amount: float = Field(..., ge=0)
    rate_pct: float | None = Field(None, ge=0)


class CommissionCreateIn(CommissionCalcIn):
    invoice_id: UUID | None = None
    counterparty_id: UUID | None = None
    currency: str = "USD"


@router.get("/commissions/types")
def list_commission_types(auth: AuthContext = Depends(require_module("finance"))):
    return commission_type_catalog()


@router.post("/commissions/calculate")
def calc_commission(
    body: CommissionCalcIn,
    auth: AuthContext = Depends(require_module("finance")),
):
    try:
        return calculate_commission(body.commission_type, body.base_amount, body.rate_pct)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "BAD_COMMISSION_TYPE", "message": str(exc)})


@router.post("/commissions")
def create_commission(
    body: CommissionCreateIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    if body.invoice_id is not None and scoped_get(db, Invoice, body.invoice_id, auth.tenant_id) is None:
        raise HTTPException(404, detail={"code": "INVOICE_NOT_FOUND", "message": str(body.invoice_id)})
    if body.counterparty_id is not None and scoped_get(db, Counterparty, body.counterparty_id, auth.tenant_id) is None:
        raise HTTPException(404, detail={"code": "COUNTERPARTY_NOT_FOUND", "message": str(body.counterparty_id)})
    try:
        row = create_commission_record(
            db,
            auth.tenant_id,
            body.commission_type,
            body.base_amount,
            body.rate_pct,
            invoice_id=body.invoice_id,
            counterparty_id=body.counterparty_id,
            currency=body.currency,
        )
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "BAD_COMMISSION_TYPE", "message": str(exc)})
    db.commit()
    db.refresh(row)
    return _commission_out(row)


@router.get("/commissions")
def list_commissions(
    commission_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    stmt = scoped_query(db, CommissionType, auth.tenant_id).order_by(CommissionType.created_at.desc())
    if commission_type:
        stmt = stmt.where(CommissionType.commission_type == commission_type)
    rows, total = paginate(db, stmt, limit, offset)
    return envelope([_commission_out(r) for r in rows], total, limit, offset)
