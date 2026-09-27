"""发票/收款/红冲/应计路由（红冲不变量见 services/finance_workflow）。"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.pagination import envelope, paginate
from app.security import AuthContext, require_module

from app.models_domain import Charter, Invoice, Payment, Voyage, VoyageAccrual
from app.models_finance_ext import CreditNote, OffHireEvent
from app.services.doc_numbering import next_doc_number
from app.services.finance_workflow import assert_void_allowed, record_payment
from app.services.hire_engine import create_hire_statement
from app.services.recycle import soft_delete
from app.services.state_machine import INVOICE_TRANSITIONS, transition

from app.routers._finance_common import INVOICE_TYPES, _alive, _as_utc_naive, _base_currency, _credited_amount, _resolve_fx_rate

from app.models_wave1 import Counterparty
from app.services.sanctions import assert_not_sanctioned
from app.services.tenant_guard import scoped_get

router = APIRouter()


@router.get("/invoices/{invoice_id}")
def get_invoice(
    invoice_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """单据详情（U2）：可深链的发票单条视图。"""
    r = scoped_get(db, Invoice, invoice_id, auth.tenant_id)
    if r is None:
        raise HTTPException(404, "Invoice not found")
    return {
        "id": str(r.id),
        "invoice_no": r.invoice_no,
        "invoice_type": r.invoice_type,
        "status": r.status,
        "amount": float(r.amount),
        "tax_amount": float(r.tax_amount or 0),
        "paid_amount": float(r.paid_amount or 0),
        "voyage_id": str(r.voyage_id) if r.voyage_id else None,
        "counterparty_id": str(r.counterparty_id) if r.counterparty_id else None,
        "currency": r.currency,
        "due_date": r.due_date.isoformat() if r.due_date else None,
        "gl_posted": bool(r.gl_posted),
        "mirror_of_id": str(r.mirror_of_id) if r.mirror_of_id else None,
        "bill_by": r.bill_by,
        "commission_basis": r.commission_basis,
    }


# —— Finance ——
class InvoiceIn(BaseModel):
    invoice_type: str = "freight"
    counterparty_id: UUID | None = None
    voyage_id: UUID | None = None
    amount: float
    tax_amount: float = 0
    currency: str = "USD"
    due_date: date | None = None
    fx_rate: float | None = None
    bill_by: str | None = None
    commission_basis: str | None = None


@router.post("/invoices")
def create_invoice(body: InvoiceIn, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    if body.invoice_type not in INVOICE_TYPES:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_INVOICE_TYPE", "message": f"invoice_type must be one of {sorted(INVOICE_TYPES)}"},
        )
    if body.counterparty_id:
        party = db.get(Counterparty, body.counterparty_id)
        if not party or party.tenant_id != auth.tenant_id or party.deleted_at:
            raise HTTPException(404, "Counterparty not found")
        assert_not_sanctioned(db, auth.tenant_id, party.id)
    if body.voyage_id:
        voyage = db.get(Voyage, body.voyage_id)
        if not voyage or voyage.tenant_id != auth.tenant_id:
            raise HTTPException(404, "Voyage not found")
    amount = Decimal(str(body.amount)).quantize(Decimal("0.01"))
    tax_amount = Decimal(str(body.tax_amount)).quantize(Decimal("0.01"))
    if amount < 0 or tax_amount < 0:
        raise HTTPException(422, detail={"code": "INVALID_AMOUNT", "message": "amount/tax_amount must be >= 0"})
    fx_rate = None
    base_amount = None
    if body.fx_rate is not None:
        if body.fx_rate <= 0:
            raise HTTPException(422, detail={"code": "INVALID_FX_RATE", "message": "fx_rate must be > 0"})
        fx_rate = Decimal(str(body.fx_rate))
    else:
        fx_rate = _resolve_fx_rate(db, auth.tenant_id, body.currency, _base_currency(db, auth.tenant_id))
    if fx_rate is not None:
        base_amount = (amount * fx_rate).quantize(Decimal("0.01"))
    row = Invoice(
        tenant_id=auth.tenant_id,
        invoice_no=next_doc_number(db, auth.tenant_id, Invoice, Invoice.invoice_no, "INV"),
        invoice_type=body.invoice_type,
        counterparty_id=body.counterparty_id,
        voyage_id=body.voyage_id,
        amount=amount,
        tax_amount=tax_amount,
        currency=body.currency,
        due_date=body.due_date,
        bill_by=body.bill_by,
        commission_basis=body.commission_basis,
    )
    if fx_rate is not None:
        row.fx_rate = fx_rate
    if base_amount is not None:
        row.base_amount = base_amount
    db.add(row)
    db.commit()
    return {
        "id": str(row.id),
        "invoice_no": row.invoice_no,
        "status": row.status,
        "amount": float(row.amount),
        "fx_rate": float(fx_rate) if fx_rate is not None else None,
        "base_amount": float(base_amount) if base_amount is not None else None,
    }


@router.post("/invoices/{invoice_id}/transition")
def invoice_transition(invoice_id: UUID, target: str, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    from app.models_saas import WorkflowDefinition, WorkflowInstance
    from app.services.saas_engine import assert_feature, start_workflow

    row = db.get(Invoice, invoice_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Invoice not found")

    if target in {"pending_approval", "issued"}:
        assert_feature(db, auth.tenant_id, auth.roles, "invoice.issue")

    has_wf = db.scalar(
        select(WorkflowDefinition).where(
            WorkflowDefinition.tenant_id == auth.tenant_id,
            WorkflowDefinition.entity_type == "invoice",
            WorkflowDefinition.enabled.is_(True),
        )
    )
    if target == "issued" and has_wf and "tenant_admin" not in auth.roles:
        running = db.scalar(
            select(WorkflowInstance).where(
                WorkflowInstance.tenant_id == auth.tenant_id,
                WorkflowInstance.entity_type == "invoice",
                WorkflowInstance.entity_id == row.id,
                WorkflowInstance.status == "running",
            )
        )
        if running or row.status == "pending_approval":
            raise HTTPException(
                status_code=409,
                detail={"code": "WORKFLOW_REQUIRED", "message": "Invoice must be approved via workflow inbox"},
            )

    if target == "void":
        # 红冲不变量（INV-VOID-CREDIT）集中在服务层；见 services/finance_workflow.py
        assert_void_allowed(db, row)

    row.status = transition("invoice", row.status, target, INVOICE_TRANSITIONS)
    if target == "pending_approval" and has_wf:
        start_workflow(db, tenant_id=auth.tenant_id, entity_type="invoice", entity_id=row.id, started_by=auth.user_id)
    if target == "issued":
        row.issued_at = datetime.now().astimezone()
    db.commit()
    return {"id": str(row.id), "status": row.status}


class InvoiceUpdate(BaseModel):
    amount: float | None = None
    tax_amount: float | None = None
    due_date: date | None = None
    invoice_type: str | None = None
    bill_by: str | None = None
    commission_basis: str | None = None


@router.patch("/invoices/{invoice_id}")
def update_invoice(
    invoice_id: UUID,
    body: InvoiceUpdate,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    row = db.get(Invoice, invoice_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Invoice not found")
    if body.invoice_type is not None and body.invoice_type not in INVOICE_TYPES:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_INVOICE_TYPE", "message": f"invoice_type must be one of {sorted(INVOICE_TYPES)}"},
        )
    locked = row.status in {"issued", "partially_paid", "paid"} or row.gl_posted
    requested = {
        f
        for f in ("amount", "tax_amount", "due_date", "invoice_type")
        if f in body.model_fields_set and getattr(body, f) is not None
    }
    if locked and requested:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INVOICE_LOCKED",
                "message": f"Cannot modify {sorted(requested)} on invoice in status {row.status}"
                + (" (GL posted)" if row.gl_posted else ""),
                "fields": sorted(requested),
                "status": row.status,
            },
        )
    new_amount = Decimal(str(row.amount))
    new_tax = Decimal(str(row.tax_amount or 0))
    if body.amount is not None:
        new_amount = Decimal(str(body.amount)).quantize(Decimal("0.01"))
    if body.tax_amount is not None:
        new_tax = Decimal(str(body.tax_amount)).quantize(Decimal("0.01"))
    if new_amount < 0 or new_tax < 0:
        raise HTTPException(422, detail={"code": "INVALID_AMOUNT", "message": "amount/tax_amount must be >= 0"})
    paid = Decimal(str(row.paid_amount or 0))
    if new_amount + new_tax < paid:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "AMOUNT_BELOW_PAID",
                "message": f"New total {new_amount + new_tax} is below already paid amount {paid}",
                "paid_amount": float(paid),
            },
        )
    if body.amount is not None:
        row.amount = new_amount
    if body.tax_amount is not None:
        row.tax_amount = new_tax
    if body.due_date is not None:
        row.due_date = body.due_date
    if body.invoice_type is not None:
        row.invoice_type = body.invoice_type
    if body.bill_by is not None:
        row.bill_by = body.bill_by
    if body.commission_basis is not None:
        row.commission_basis = body.commission_basis
    db.commit()
    return {
        "id": str(row.id),
        "invoice_no": row.invoice_no,
        "status": row.status,
        "amount": float(row.amount),
    }


class CreditNoteIn(BaseModel):
    amount: float
    reason: str | None = None


@router.post("/invoices/{invoice_id}/credit-note")
def create_credit_note(
    invoice_id: UUID,
    body: CreditNoteIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """红冲: issue a credit note against an invoice (capped at the un-credited balance)."""
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != auth.tenant_id or not _alive(inv.status):
        raise HTTPException(404, "Invoice not found")
    amt = Decimal(str(body.amount)).quantize(Decimal("0.01"))
    if amt <= 0:
        raise HTTPException(422, detail={"code": "INVALID_AMOUNT", "message": "Credit note amount must be > 0"})
    total = Decimal(str(inv.amount)) + Decimal(str(inv.tax_amount or 0))
    credited = _credited_amount(db, inv.id)
    balance = total - credited
    if amt > balance:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CREDIT_EXCEEDS_BALANCE",
                "message": f"Credit note {amt} exceeds un-credited balance {balance}",
                "balance": float(balance),
            },
        )
    row = CreditNote(
        tenant_id=auth.tenant_id,
        invoice_id=inv.id,
        credit_note_no=next_doc_number(db, auth.tenant_id, CreditNote, CreditNote.credit_note_no, "CN"),
        amount=amt,
        reason=body.reason,
        status="issued",
        issued_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "credit_note_no": row.credit_note_no, "amount": float(row.amount), "status": row.status}


@router.get("/invoices/{invoice_id}/credit-notes")
def list_credit_notes(invoice_id: UUID, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Invoice not found")
    rows = db.scalars(
        select(CreditNote).where(CreditNote.invoice_id == inv.id).order_by(CreditNote.credit_note_no)
    ).all()
    return [
        {
            "id": str(r.id),
            "credit_note_no": r.credit_note_no,
            "amount": float(r.amount or 0),
            "reason": r.reason,
            "status": r.status,
            "issued_at": r.issued_at.isoformat() if r.issued_at else None,
        }
        for r in rows
    ]


class HireScheduleIn(BaseModel):
    charter_id: UUID
    period_start: date
    period_end: date


@router.post("/invoices/hire-schedule")
def hire_schedule(body: HireScheduleIn, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    """Generate a draft hire invoice for a time-charter period, net of off-hire and address commission."""
    ch = db.get(Charter, body.charter_id)
    if not ch or ch.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Charter not found")
    hire_per_day = getattr(ch, "hire_per_day", None)
    if not hire_per_day:
        raise HTTPException(422, detail={"code": "NO_HIRE_RATE", "message": "Charter has no hire_per_day rate"})
    if body.period_end <= body.period_start:
        raise HTTPException(422, detail={"code": "INVALID_PERIOD", "message": "period_end must be after period_start"})
    ps = datetime.combine(body.period_start, time.min)
    pe = datetime.combine(body.period_end, time.min)
    gross_days = (pe - ps).total_seconds() / 86400
    offhire_days = 0.0
    for ev in db.scalars(
        select(OffHireEvent).where(
            OffHireEvent.tenant_id == auth.tenant_id,
            OffHireEvent.charter_id == ch.id,
            OffHireEvent.deduct_hire.is_(True),
        )
    ).all():
        if ev.end_at is None:
            continue
        s = max(_as_utc_naive(ev.start_at), ps)
        e = min(_as_utc_naive(ev.end_at), pe)
        if e > s:
            offhire_days += (e - s).total_seconds() / 86400
    offhire_days = min(offhire_days, gross_days)
    billable_days = gross_days - offhire_days
    rate = Decimal(str(hire_per_day))
    gross_amount = (rate * Decimal(str(billable_days))).quantize(Decimal("0.01"))
    comm_pct = Decimal(str(getattr(ch, "address_comm_pct", None) or 0))
    comm_amount = (gross_amount * comm_pct / Decimal("100")).quantize(Decimal("0.01"))
    net_amount = gross_amount - comm_amount
    meta = {
        "hire": {
            "charter_id": str(ch.id),
            "period_start": body.period_start.isoformat(),
            "period_end": body.period_end.isoformat(),
            "gross_days": round(gross_days, 4),
            "offhire_days": round(offhire_days, 4),
            "billable_days": round(billable_days, 4),
            "hire_per_day": float(rate),
            "gross_amount": float(gross_amount),
            "address_comm_pct": float(comm_pct),
            "address_comm_amount": float(comm_amount),
        }
    }
    if ch.counterparty_id:
        assert_not_sanctioned(db, auth.tenant_id, ch.counterparty_id)
    row = Invoice(
        tenant_id=auth.tenant_id,
        invoice_no=next_doc_number(db, auth.tenant_id, Invoice, Invoice.invoice_no, "INV"),
        invoice_type="hire",
        counterparty_id=ch.counterparty_id,
        amount=net_amount,
        tax_amount=Decimal("0"),
        currency="USD",
        meta=meta,
    )
    db.add(row)
    db.commit()
    return {
        "id": str(row.id),
        "invoice_no": row.invoice_no,
        "status": row.status,
        "invoice_type": row.invoice_type,
        "amount": float(row.amount),
        "meta": row.meta,
    }


@router.delete("/invoices/{invoice_id}")
def delete_invoice(invoice_id: UUID, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    row = db.get(Invoice, invoice_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Invoice not found")
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="invoice",
        row=row,
        title=row.invoice_no,
    )
    db.commit()
    return {"ok": True, "recycled": True}


# fix payment status assignment
@router.post("/invoices/{invoice_id}/payments")
def add_payment(
    invoice_id: UUID,
    amount: float,
    reference: str | None = None,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    from app.services.saas_engine import assert_feature

    assert_feature(db, auth.tenant_id, auth.roles, "invoice.collect")
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != auth.tenant_id or not _alive(inv.status):
        raise HTTPException(404, "Invoice not found")
    if inv.counterparty_id:
        assert_not_sanctioned(db, auth.tenant_id, inv.counterparty_id)
    if inv.status not in {"issued", "partially_paid"}:
        raise HTTPException(409, detail={"code": "INVALID_STATE", "message": f"Cannot pay invoice in status {inv.status}"})
    record_payment(db, inv, amount, reference=reference)
    db.commit()
    return {"invoice_id": str(inv.id), "status": inv.status, "paid_amount": float(inv.paid_amount)}

@router.get("/invoices/{invoice_id}/payments")
def list_payments(invoice_id: UUID, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Invoice not found")
    rows = (
        db.query(Payment)
        .filter(Payment.invoice_id == inv.id, Payment.tenant_id == auth.tenant_id)
        .order_by(Payment.paid_at.asc())
        .all()
    )
    return [
        {
            "id": str(p.id),
            "amount": float(p.amount),
            "currency": p.currency,
            "reference": p.reference,
            "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            "is_void_reversal": bool(p.reference and p.reference.startswith("VOID:")),
        }
        for p in rows
    ]


@router.post("/invoices/{invoice_id}/gl-post")
def gl_post(invoice_id: UUID, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Invoice not found")
    if inv.status not in {"issued", "partially_paid", "paid"}:
        raise HTTPException(409, detail={"code": "INVALID_STATE", "message": "Invoice not issuable for GL"})
    inv.gl_posted = True
    inv.meta = {**(inv.meta or {}), "gl_posted_at": datetime.now(timezone.utc).isoformat()}
    db.commit()
    return {"id": str(inv.id), "gl_posted": True}


@router.post("/payments/{payment_id}/void")
def void_payment(payment_id: UUID, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    """付款冲正: reverse a payment and write the invoice paid_amount / status back.

    折中方案: Payment 模型定义在 models_domain.py(本任务不可改),无法新增
    voided_at 列,因此保留原 payment 记录,另写一条金额为负的反向 payment,
    以 reference = "VOID:<原 payment id>" 作为冲正关联与幂等标记。
    """
    pay = db.get(Payment, payment_id)
    if not pay or pay.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Payment not found")
    if Decimal(str(pay.amount)) <= 0 or (pay.reference or "").startswith("VOID:"):
        raise HTTPException(409, detail={"code": "INVALID_PAYMENT", "message": "Cannot void a reversal entry"})
    inv = db.get(Invoice, pay.invoice_id)
    if not inv or inv.tenant_id != auth.tenant_id or not _alive(inv.status):
        raise HTTPException(404, "Invoice not found")
    if inv.gl_posted:
        raise HTTPException(
            status_code=409,
            detail={"code": "GL_POSTED", "message": "Invoice is GL posted; voiding its payments is forbidden"},
        )
    if inv.status not in {"issued", "partially_paid", "paid"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "INVALID_STATE", "message": f"Cannot void a payment on invoice in status {inv.status}"},
        )
    void_ref = f"VOID:{pay.id}"
    existing = db.scalar(select(Payment).where(Payment.invoice_id == inv.id, Payment.reference == void_ref))
    if existing:
        raise HTTPException(409, detail={"code": "ALREADY_VOIDED", "message": "Payment is already voided"})
    reverse = Payment(
        tenant_id=auth.tenant_id,
        invoice_id=inv.id,
        amount=-Decimal(str(pay.amount)),
        currency=pay.currency,
        reference=void_ref,
    )
    db.add(reverse)
    db.flush()
    total_paid = sum(
        (Decimal(str(p.amount)) for p in db.scalars(select(Payment).where(Payment.invoice_id == inv.id)).all()),
        Decimal("0"),
    ).quantize(Decimal("0.01"))
    inv.paid_amount = total_paid
    total = Decimal(str(inv.amount)) + Decimal(str(inv.tax_amount or 0))
    target = "paid" if total_paid >= total else "partially_paid" if total_paid > 0 else "issued"
    if target != inv.status:
        # Reversal goes backwards through the machine; hop paid → partially_paid first
        # when the payment void reopens a fully paid invoice to zero received.
        if inv.status == "paid" and target == "issued":
            inv.status = transition("invoice", inv.status, "partially_paid", INVOICE_TRANSITIONS)
        inv.status = transition("invoice", inv.status, target, INVOICE_TRANSITIONS)
    db.commit()
    return {
        "payment_id": str(pay.id),
        "reversal_id": str(reverse.id),
        "invoice_id": str(inv.id),
        "status": inv.status,
        "paid_amount": float(inv.paid_amount),
    }


@router.get("/invoices")
def list_invoices(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    voyage_id: UUID | None = Query(None),
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    q = select(Invoice).where(Invoice.tenant_id == auth.tenant_id, Invoice.status != "deleted")
    if voyage_id is not None:
        q = q.where(Invoice.voyage_id == voyage_id)
    rows, total = paginate(db, q.order_by(Invoice.invoice_no), limit, offset)
    return envelope(
        [
            {
                "id": str(r.id),
                "invoice_no": r.invoice_no,
                "invoice_type": r.invoice_type,
                "status": r.status,
                "amount": float(r.amount),
                "paid_amount": float(r.paid_amount or 0),
                "voyage_id": str(r.voyage_id) if r.voyage_id else None,
                "counterparty_id": str(r.counterparty_id) if r.counterparty_id else None,
                "currency": r.currency,
                "due_date": r.due_date.isoformat() if r.due_date else None,
                "gl_posted": bool(r.gl_posted),
                "mirror_of_id": str(r.mirror_of_id) if r.mirror_of_id else None,
                "bill_by": r.bill_by,
                "commission_basis": r.commission_basis,
            }
            for r in rows
        ],
        total,
        limit,
        offset,
    )


@router.get("/finance/aging")
def aging(auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    rows = db.scalars(select(Invoice).where(Invoice.tenant_id == auth.tenant_id, Invoice.status.in_(["issued", "partially_paid"]))).all()
    return [
        {
            "invoice_no": r.invoice_no,
            "open_amount": float(Decimal(str(r.amount)) + Decimal(str(r.tax_amount or 0)) - Decimal(str(r.paid_amount or 0))),
            "due_date": r.due_date.isoformat() if r.due_date else None,
        }
        for r in rows
    ]


class AccrualIn(BaseModel):
    voyage_id: UUID | None = None
    period_ym: str
    line_type: str = "freight"
    amount: float
    currency: str = "USD"
    notes: str | None = None


@router.get("/finance/accruals")
def list_accruals(auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    rows = db.scalars(select(VoyageAccrual).where(VoyageAccrual.tenant_id == auth.tenant_id)).all()
    return [
        {
            "id": str(r.id),
            "voyage_id": str(r.voyage_id) if r.voyage_id else None,
            "period_ym": r.period_ym,
            "line_type": r.line_type,
            "amount": float(r.amount or 0),
            "currency": r.currency,
            "status": r.status,
            "notes": r.notes,
        }
        for r in rows
    ]


@router.post("/finance/accruals")
def create_accrual(body: AccrualIn, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    row = VoyageAccrual(
        tenant_id=auth.tenant_id,
        voyage_id=body.voyage_id,
        period_ym=body.period_ym,
        line_type=body.line_type,
        amount=body.amount,
        currency=body.currency,
        notes=body.notes,
        status="draft",
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "status": row.status}


@router.post("/finance/accruals/{accrual_id}/post")
def post_accrual(accrual_id: UUID, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    row = db.get(VoyageAccrual, accrual_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Accrual not found")
    if row.status != "draft":
        raise HTTPException(409, detail={"code": "INVALID_STATE", "message": f"Cannot post from {row.status}"})
    row.status = "posted"
    db.commit()
    return {"id": str(row.id), "status": row.status}




class ReconcileLine(BaseModel):
    amount: float
    reference: str | None = None
    date: str | None = None


class ReconcilePreviewIn(BaseModel):
    lines: list[ReconcileLine]


class ReconcileMatch(BaseModel):
    invoice_id: UUID
    amount: float
    reference: str | None = None
    paid_at: str | None = None


class ReconcileApplyIn(BaseModel):
    matches: list[ReconcileMatch]


@router.post("/finance/reconciliation/preview")
def reconciliation_preview(
    body: ReconcilePreviewIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """D21 银行核销：流水 → 未结发票的配对建议（不落库，人工确认）。"""
    from app.models_wave1 import Counterparty
    from app.services.reconciliation import suggest_matches

    invoices = list(
        db.scalars(
            select(Invoice).where(
                Invoice.tenant_id == auth.tenant_id,
                Invoice.status.in_(["issued", "partially_paid"]),
            )
        ).all()
    )
    names = {
        str(c.id): c.name
        for c in db.scalars(select(Counterparty).where(Counterparty.tenant_id == auth.tenant_id)).all()
    }
    return suggest_matches([l.model_dump() for l in body.lines], invoices, names)


@router.post("/finance/reconciliation/apply")
def reconciliation_apply(
    body: ReconcileApplyIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """D21 核销入账：确认的配对逐笔记收款（同一事务，任一失败整体回滚）。"""
    from app.services.saas_engine import assert_feature

    assert_feature(db, auth.tenant_id, auth.roles, "invoice.collect")
    applied = []
    for m in body.matches:
        inv = db.get(Invoice, m.invoice_id)
        if not inv or inv.tenant_id != auth.tenant_id or not _alive(inv.status):
            raise HTTPException(404, detail={"code": "INVOICE_NOT_FOUND", "message": f"invoice {m.invoice_id}"})
        if inv.counterparty_id:
            assert_not_sanctioned(db, auth.tenant_id, inv.counterparty_id)
        record_payment(db, inv, m.amount, reference=m.reference)
        applied.append({"invoice_id": str(inv.id), "status": inv.status})
    db.commit()
    return {"applied": applied}


@router.get("/invoices/{invoice_id}/commission-plan")
def invoice_commission_plan(
    invoice_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """D4 佣金计划：地址佣金扣减 + 经纪佣金金额（按租约佣金字段）。"""
    from app.services.commission import commission_plan

    inv = scoped_get(db, Invoice, invoice_id, auth.tenant_id)
    if inv is None:
        raise HTTPException(404, "Invoice not found")
    return commission_plan(db, inv)


@router.post("/invoices/{invoice_id}/commission-invoices")
def create_commission_invoices(
    invoice_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """D4 佣金链：按经纪佣金生成草稿佣金发票（无佣金返回 422）。"""
    from app.services.commission import create_brokerage_invoice

    inv = scoped_get(db, Invoice, invoice_id, auth.tenant_id)
    if inv is None:
        raise HTTPException(404, "Invoice not found")
    created = create_brokerage_invoice(db, inv, user_id=auth.user_id)
    if created is None:
        raise HTTPException(422, detail={"code": "NO_COMMISSION", "message": "No brokerage commission on linked charter"})
    db.commit()
    return {"id": str(created.id), "invoice_no": created.invoice_no, "amount": float(created.amount)}
