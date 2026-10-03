"""付款域路由 — 付款批次（payment batches）+ 付款条件/方式/银行账户 + 预收预付。

批次链路：选应付发票 → 建批次（一发票一 Payment 行）→ 审批（入账 paid_amount）
→ 冲正（回滚）→ 导出银行付款指令 XML（iMOS SimplePayment 兼容）。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_domain import Invoice, Payment, PaymentBatch
from app.models_finance_ext import (
    AdvanceAllocation,
    AdvancePayment,
    BankAccount,
    PaymentMethod,
    PaymentTerm,
)
from app.models_wave1 import Counterparty
from app.pagination import envelope, paginate
from app.security import AuthContext, require_module
from app.services import payment_batch as pb_service
from app.services.doc_numbering import next_doc_number
from app.services.tenant_guard import scoped_get, scoped_query

router = APIRouter()

BANK_CHARGE_MODES = ("shared", "sender", "receiver")
ADVANCE_DIRECTIONS = ("payment", "receipt")
ADVANCE_STATUSES = ("unallocated", "partially_allocated", "fully_allocated")


def _f(val: Any) -> float:
    return float(val or 0)


def _batch_out(row: PaymentBatch) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "batch_number": row.batch_number,
        "batch_date": row.batch_date.isoformat() if row.batch_date else None,
        "status": row.status,
        "total_amount": _f(row.total_amount),
        "currency": row.currency,
        "payment_count": row.payment_count,
        "bank_charge_mode": row.bank_charge_mode,
        "approval_user_id": str(row.approval_user_id) if row.approval_user_id else None,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _payment_out(row: Payment) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "invoice_id": str(row.invoice_id),
        "batch_id": str(row.batch_id) if row.batch_id else None,
        "amount": _f(row.amount),
        "currency": row.currency,
        "paid_at": row.paid_at.isoformat() if row.paid_at else None,
        "reference": row.reference,
    }


# —— 付款批次 ————————————————————————————————————————————————


class BatchIn(BaseModel):
    invoice_ids: list[UUID] = Field(..., min_length=1)
    batch_date: date | None = None
    bank_charge_mode: str = "shared"


@router.get("/payments/payable-invoices")
def list_payable_invoices(
    due_before: date | None = Query(None),
    counterparty_id: UUID | None = Query(None),
    currency: str | None = Query(None),
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """可入批次的应付发票（issued / partially_paid 且有余额）。"""
    rows = pb_service.select_payable_invoices(
        db,
        auth.tenant_id,
        due_before=due_before,
        counterparty_id=counterparty_id,
        currency=currency,
    )
    return [
        {
            "id": str(r.id),
            "invoice_no": r.invoice_no,
            "invoice_type": r.invoice_type,
            "status": r.status,
            "counterparty_id": str(r.counterparty_id) if r.counterparty_id else None,
            "amount": _f(r.amount),
            "paid_amount": _f(r.paid_amount),
            "outstanding": _f(r.amount) - _f(r.paid_amount),
            "currency": r.currency,
            "due_date": r.due_date.isoformat() if r.due_date else None,
        }
        for r in rows
    ]


@router.post("/payments/batches")
def create_payment_batch(
    body: BatchIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    if body.bank_charge_mode not in BANK_CHARGE_MODES:
        raise HTTPException(
            422,
            detail={"code": "BAD_BANK_CHARGE_MODE", "message": f"expected one of {BANK_CHARGE_MODES}"},
        )
    invoices = []
    for iid in body.invoice_ids:
        inv = scoped_get(db, Invoice, iid, auth.tenant_id)
        if inv is None:
            raise HTTPException(404, detail={"code": "INVOICE_NOT_FOUND", "message": str(iid)})
        if inv.status not in ("issued", "partially_paid"):
            raise HTTPException(
                409,
                detail={"code": "INVALID_STATE", "message": f"Invoice {inv.invoice_no} is {inv.status}, not payable"},
            )
        invoices.append(inv)
    currencies = {inv.currency for inv in invoices}
    if len(currencies) > 1:
        raise HTTPException(
            422,
            detail={"code": "MIXED_CURRENCY", "message": f"Batch must share one currency, got {sorted(currencies)}"},
        )
    batch = pb_service.create_batch(
        db,
        auth.tenant_id,
        body.invoice_ids,
        body.batch_date or date.today(),
        bank_charge_mode=body.bank_charge_mode,
        user_id=auth.user_id,
    )
    db.commit()
    db.refresh(batch)
    return _batch_out(batch)


@router.get("/payments/batches")
def list_payment_batches(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    stmt = scoped_query(db, PaymentBatch, auth.tenant_id).order_by(PaymentBatch.created_at.desc())
    if status:
        stmt = stmt.where(PaymentBatch.status == status)
    rows, total = paginate(db, stmt, limit, offset)
    return envelope([_batch_out(r) for r in rows], total, limit, offset)


@router.get("/payments/batches/{batch_id}")
def get_payment_batch(
    batch_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    batch = scoped_get(db, PaymentBatch, batch_id, auth.tenant_id)
    if batch is None:
        raise HTTPException(404, detail={"code": "BATCH_NOT_FOUND", "message": str(batch_id)})
    payments = db.scalars(
        select(Payment).where(Payment.tenant_id == auth.tenant_id, Payment.batch_id == batch.id)
    ).all()
    return {**_batch_out(batch), "payments": [_payment_out(p) for p in payments]}


@router.post("/payments/batches/{batch_id}/approve")
def approve_payment_batch(
    batch_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    batch = scoped_get(db, PaymentBatch, batch_id, auth.tenant_id)
    if batch is None:
        raise HTTPException(404, detail={"code": "BATCH_NOT_FOUND", "message": str(batch_id)})
    try:
        batch = pb_service.approve_batch(db, batch, auth.user_id)
    except ValueError as exc:
        raise HTTPException(409, detail={"code": "INVALID_STATE", "message": str(exc)})
    db.commit()
    db.refresh(batch)
    return _batch_out(batch)


@router.post("/payments/batches/{batch_id}/reverse")
def reverse_payment_batch(
    batch_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    batch = scoped_get(db, PaymentBatch, batch_id, auth.tenant_id)
    if batch is None:
        raise HTTPException(404, detail={"code": "BATCH_NOT_FOUND", "message": str(batch_id)})
    try:
        batch = pb_service.reverse_batch(db, batch)
    except ValueError as exc:
        raise HTTPException(409, detail={"code": "INVALID_STATE", "message": str(exc)})
    db.commit()
    db.refresh(batch)
    return _batch_out(batch)


@router.get("/payments/batches/{batch_id}/export-xml")
def export_payment_batch_xml(
    batch_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    batch = scoped_get(db, PaymentBatch, batch_id, auth.tenant_id)
    if batch is None:
        raise HTTPException(404, detail={"code": "BATCH_NOT_FOUND", "message": str(batch_id)})
    payments = db.scalars(
        select(Payment).where(Payment.tenant_id == auth.tenant_id, Payment.batch_id == batch.id)
    ).all()
    xml = pb_service.export_payment_xml(batch, list(payments))
    return Response(content=xml, media_type="application/xml")


# —— 付款条件 / 方式 / 银行账户 ————————————————————————————————


class PaymentTermIn(BaseModel):
    name: str
    days: int = Field(..., ge=0)
    discount_pct: float | None = Field(None, ge=0)
    discount_days: int | None = Field(None, ge=0)


class PaymentMethodIn(BaseModel):
    name: str
    code: str
    is_active: bool = True


class BankAccountIn(BaseModel):
    bank_name: str
    account_name: str
    account_number: str
    swift_code: str | None = None
    iban: str | None = None
    currency: str = "USD"
    is_default: bool = False
    counterparty_id: UUID | None = None


def _term_out(row: PaymentTerm) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "days": row.days,
        "discount_pct": _f(row.discount_pct) if row.discount_pct is not None else None,
        "discount_days": row.discount_days,
    }


def _method_out(row: PaymentMethod) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "code": row.code,
        "is_active": bool(row.is_active),
    }


def _bank_out(row: BankAccount) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "bank_name": row.bank_name,
        "account_name": row.account_name,
        "account_number": row.account_number,
        "swift_code": row.swift_code,
        "iban": row.iban,
        "currency": row.currency,
        "is_default": bool(row.is_default),
        "counterparty_id": str(row.counterparty_id) if row.counterparty_id else None,
    }


@router.get("/payments/terms")
def list_payment_terms(
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(scoped_query(db, PaymentTerm, auth.tenant_id).order_by(PaymentTerm.days.asc())).all()
    return [_term_out(r) for r in rows]


@router.post("/payments/terms")
def create_payment_term(
    body: PaymentTermIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    row = PaymentTerm(
        tenant_id=auth.tenant_id,
        name=body.name,
        days=body.days,
        discount_pct=Decimal(str(body.discount_pct)) if body.discount_pct is not None else None,
        discount_days=body.discount_days,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _term_out(row)


@router.patch("/payments/terms/{term_id}")
def patch_payment_term(
    term_id: UUID,
    body: PaymentTermIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, PaymentTerm, term_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, detail={"code": "TERM_NOT_FOUND", "message": str(term_id)})
    row.name = body.name
    row.days = body.days
    row.discount_pct = Decimal(str(body.discount_pct)) if body.discount_pct is not None else None
    row.discount_days = body.discount_days
    db.commit()
    db.refresh(row)
    return _term_out(row)


@router.delete("/payments/terms/{term_id}")
def delete_payment_term(
    term_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, PaymentTerm, term_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, detail={"code": "TERM_NOT_FOUND", "message": str(term_id)})
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/payments/methods")
def list_payment_methods(
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(scoped_query(db, PaymentMethod, auth.tenant_id).order_by(PaymentMethod.code.asc())).all()
    return [_method_out(r) for r in rows]


@router.post("/payments/methods")
def create_payment_method(
    body: PaymentMethodIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    row = PaymentMethod(tenant_id=auth.tenant_id, name=body.name, code=body.code, is_active=body.is_active)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _method_out(row)


@router.patch("/payments/methods/{method_id}")
def patch_payment_method(
    method_id: UUID,
    body: PaymentMethodIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, PaymentMethod, method_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, detail={"code": "METHOD_NOT_FOUND", "message": str(method_id)})
    row.name = body.name
    row.code = body.code
    row.is_active = body.is_active
    db.commit()
    db.refresh(row)
    return _method_out(row)


@router.delete("/payments/methods/{method_id}")
def delete_payment_method(
    method_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, PaymentMethod, method_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, detail={"code": "METHOD_NOT_FOUND", "message": str(method_id)})
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/payments/bank-accounts")
def list_bank_accounts(
    counterparty_id: UUID | None = Query(None),
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    stmt = scoped_query(db, BankAccount, auth.tenant_id).order_by(BankAccount.is_default.desc())
    if counterparty_id:
        stmt = stmt.where(BankAccount.counterparty_id == counterparty_id)
    rows = db.scalars(stmt).all()
    return [_bank_out(r) for r in rows]


@router.post("/payments/bank-accounts")
def create_bank_account(
    body: BankAccountIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    if body.counterparty_id is not None and scoped_get(db, Counterparty, body.counterparty_id, auth.tenant_id) is None:
        raise HTTPException(404, detail={"code": "COUNTERPARTY_NOT_FOUND", "message": str(body.counterparty_id)})
    row = BankAccount(
        tenant_id=auth.tenant_id,
        bank_name=body.bank_name,
        account_name=body.account_name,
        account_number=body.account_number,
        swift_code=body.swift_code,
        iban=body.iban,
        currency=body.currency,
        is_default=body.is_default,
        counterparty_id=body.counterparty_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _bank_out(row)


@router.patch("/payments/bank-accounts/{account_id}")
def patch_bank_account(
    account_id: UUID,
    body: BankAccountIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, BankAccount, account_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, detail={"code": "BANK_ACCOUNT_NOT_FOUND", "message": str(account_id)})
    row.bank_name = body.bank_name
    row.account_name = body.account_name
    row.account_number = body.account_number
    row.swift_code = body.swift_code
    row.iban = body.iban
    row.currency = body.currency
    row.is_default = body.is_default
    row.counterparty_id = body.counterparty_id
    db.commit()
    db.refresh(row)
    return _bank_out(row)


@router.delete("/payments/bank-accounts/{account_id}")
def delete_bank_account(
    account_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, BankAccount, account_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, detail={"code": "BANK_ACCOUNT_NOT_FOUND", "message": str(account_id)})
    db.delete(row)
    db.commit()
    return {"ok": True}


# —— 预收 / 预付 + 核销 ————————————————————————————————————————


class AdvanceIn(BaseModel):
    direction: str = "payment"
    counterparty_id: UUID | None = None
    amount: float = Field(..., gt=0)
    currency: str = "USD"
    notes: str | None = None


class AllocateIn(BaseModel):
    invoice_id: UUID
    amount: float = Field(..., gt=0)


def _advance_out(row: AdvancePayment, allocations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    out = {
        "id": str(row.id),
        "advance_no": row.advance_no,
        "direction": row.direction,
        "counterparty_id": str(row.counterparty_id) if row.counterparty_id else None,
        "amount": _f(row.amount),
        "currency": row.currency,
        "allocated_amount": _f(row.allocated_amount),
        "status": row.status,
        "notes": row.notes,
    }
    if allocations is not None:
        out["allocations"] = allocations
    return out


@router.post("/payments/advances")
def create_advance(
    body: AdvanceIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    if body.direction not in ADVANCE_DIRECTIONS:
        raise HTTPException(422, detail={"code": "BAD_DIRECTION", "message": f"expected one of {ADVANCE_DIRECTIONS}"})
    if body.counterparty_id is not None and scoped_get(db, Counterparty, body.counterparty_id, auth.tenant_id) is None:
        raise HTTPException(404, detail={"code": "COUNTERPARTY_NOT_FOUND", "message": str(body.counterparty_id)})
    prefix = "AR" if body.direction == "receipt" else "AP"
    row = AdvancePayment(
        tenant_id=auth.tenant_id,
        advance_no=next_doc_number(db, auth.tenant_id, AdvancePayment, AdvancePayment.advance_no, prefix),
        direction=body.direction,
        counterparty_id=body.counterparty_id,
        amount=Decimal(str(body.amount)),
        currency=body.currency,
        allocated_amount=Decimal("0"),
        status="unallocated",
        notes=body.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _advance_out(row)


@router.get("/payments/advances")
def list_advances(
    direction: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    stmt = scoped_query(db, AdvancePayment, auth.tenant_id).order_by(AdvancePayment.created_at.desc())
    if direction:
        stmt = stmt.where(AdvancePayment.direction == direction)
    if status:
        stmt = stmt.where(AdvancePayment.status == status)
    rows, total = paginate(db, stmt, limit, offset)
    return envelope([_advance_out(r) for r in rows], total, limit, offset)


def _allocations_of(db: Session, tenant_id: UUID, advance_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(AdvanceAllocation)
        .where(AdvanceAllocation.tenant_id == tenant_id, AdvanceAllocation.advance_id == advance_id)
        .order_by(AdvanceAllocation.created_at.asc())
    ).all()
    return [
        {
            "id": str(a.id),
            "advance_id": str(a.advance_id),
            "invoice_id": str(a.invoice_id),
            "amount": _f(a.amount),
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in rows
    ]


@router.get("/payments/advances/{advance_id}")
def get_advance(
    advance_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, AdvancePayment, advance_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, detail={"code": "ADVANCE_NOT_FOUND", "message": str(advance_id)})
    return _advance_out(row, _allocations_of(db, auth.tenant_id, row.id))


@router.post("/payments/advances/{advance_id}/allocate")
def allocate_advance(
    advance_id: UUID,
    body: AllocateIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """把预收/预付核销到发票：金额不得超过剩余额度，状态随之推进。"""
    row = scoped_get(db, AdvancePayment, advance_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, detail={"code": "ADVANCE_NOT_FOUND", "message": str(advance_id)})
    inv = scoped_get(db, Invoice, body.invoice_id, auth.tenant_id)
    if inv is None:
        raise HTTPException(404, detail={"code": "INVOICE_NOT_FOUND", "message": str(body.invoice_id)})
    amount = Decimal(str(body.amount))
    remaining = Decimal(str(row.amount)) - Decimal(str(row.allocated_amount or 0))
    if amount > remaining:
        raise HTTPException(
            409,
            detail={
                "code": "OVER_ALLOCATION",
                "message": f"Allocation {amount} exceeds remaining advance {remaining}",
            },
        )
    alloc = AdvanceAllocation(
        tenant_id=auth.tenant_id,
        advance_id=row.id,
        invoice_id=inv.id,
        amount=amount,
    )
    db.add(alloc)
    row.allocated_amount = Decimal(str(row.allocated_amount or 0)) + amount
    if row.allocated_amount >= Decimal(str(row.amount)):
        row.status = "fully_allocated"
    elif row.allocated_amount > 0:
        row.status = "partially_allocated"
    else:
        row.status = "unallocated"
    db.commit()
    db.refresh(row)
    return _advance_out(row, _allocations_of(db, auth.tenant_id, row.id))
