"""Laytime, Claims, Port Cost, Bunker, Finance, Market, Emissions, Pool, Risk, Portal."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_domain import (
    BunkerOrder,
    Claim,
    DqIssue,
    EmissionRecord,
    Invoice,
    LaytimeCalc,
    MarketQuote,
    Payment,
    Pool,
    PoolPeriod,
    PoolVessel,
    PortDisbursement,
    PortalMessage,
    BerthWindow,
    RiskPosition,
    Document,
    VoyageAccrual,
)
from app.security import AuthContext, require_module
from app.services.laytime_engine import compute_laytime
from app.services.recycle import soft_delete
from app.services.state_machine import (
    BUNKER_TRANSITIONS,
    CLAIM_TRANSITIONS,
    INVOICE_TRANSITIONS,
    LAYTIME_TRANSITIONS,
    PDA_TRANSITIONS,
    POOL_PERIOD_TRANSITIONS,
    transition,
)

router = APIRouter(tags=["Finance & Claims"])


def _alive(status: str | None) -> bool:
    return status != "deleted"


# —— Laytime ——
class LaytimeIn(BaseModel):
    voyage_id: UUID | None = None
    port_call_id: UUID | None = None
    inputs: dict = Field(default_factory=dict)


@router.post("/laytimes")
def create_laytime(body: LaytimeIn, auth: AuthContext = Depends(require_module("laytime")), db: Session = Depends(get_db)):
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
def list_laytimes(auth: AuthContext = Depends(require_module("laytime")), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(LaytimeCalc).where(LaytimeCalc.tenant_id == auth.tenant_id, LaytimeCalc.status != "deleted")
    ).all()
    return [
        {
            "id": str(r.id),
            "voyage_id": str(r.voyage_id) if r.voyage_id else None,
            "port_call_id": str(r.port_call_id) if r.port_call_id else None,
            "status": r.status,
            "inputs": r.inputs or {},
            "results": r.results or {},
        }
        for r in rows
    ]


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
    if body.voyage_id is not None:
        row.voyage_id = body.voyage_id
    if body.port_call_id is not None:
        row.port_call_id = body.port_call_id
    row.inputs = body.inputs or row.inputs
    if row.status == "calculated":
        row.status = "draft"
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


# —— Claims ——
class ClaimIn(BaseModel):
    claim_type: str = "demurrage"
    voyage_id: UUID | None = None
    laytime_id: UUID | None = None
    amount: float | None = None
    currency: str = "USD"
    time_bar: date | None = None
    notes: str | None = None


@router.post("/claims")
def create_claim(body: ClaimIn, auth: AuthContext = Depends(require_module("claims")), db: Session = Depends(get_db)):
    amount = body.amount
    if amount is None and body.laytime_id:
        lt = db.get(LaytimeCalc, body.laytime_id)
        if lt and lt.results:
            amount = float(lt.results.get("amount") or 0)
    row = Claim(
        tenant_id=auth.tenant_id,
        claim_no=f"CL-{datetime.now().strftime('%Y%m%d')}-{str(uuid4())[:5].upper()}",
        claim_type=body.claim_type,
        voyage_id=body.voyage_id,
        laytime_id=body.laytime_id,
        amount=amount,
        currency=body.currency,
        time_bar=body.time_bar,
        notes=body.notes,
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "claim_no": row.claim_no, "status": row.status, "amount": float(row.amount or 0)}


@router.post("/claims/{claim_id}/transition")
def claim_transition(claim_id: UUID, target: str, auth: AuthContext = Depends(require_module("claims")), db: Session = Depends(get_db)):
    row = db.get(Claim, claim_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Claim not found")
    row.status = transition("claim", row.status, target, CLAIM_TRANSITIONS)
    if target == "settled":
        row.settlement_amount = row.amount
    db.commit()
    return {"id": str(row.id), "status": row.status}


class ClaimUpdate(BaseModel):
    amount: float | None = None
    notes: str | None = None
    claim_type: str | None = None


@router.patch("/claims/{claim_id}")
def update_claim(
    claim_id: UUID,
    body: ClaimUpdate,
    auth: AuthContext = Depends(require_module("claims")),
    db: Session = Depends(get_db),
):
    row = db.get(Claim, claim_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Claim not found")
    if body.amount is not None:
        row.amount = body.amount
    if body.notes is not None:
        row.notes = body.notes
    if body.claim_type is not None:
        row.claim_type = body.claim_type
    db.commit()
    return {"id": str(row.id), "claim_no": row.claim_no, "status": row.status, "amount": float(row.amount or 0)}


@router.delete("/claims/{claim_id}")
def delete_claim(claim_id: UUID, auth: AuthContext = Depends(require_module("claims")), db: Session = Depends(get_db)):
    row = db.get(Claim, claim_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Claim not found")
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="claim",
        row=row,
        title=row.claim_no,
    )
    db.commit()
    return {"ok": True, "recycled": True}


@router.get("/claims")
def list_claims(auth: AuthContext = Depends(require_module("claims")), db: Session = Depends(get_db)):
    rows = db.scalars(select(Claim).where(Claim.tenant_id == auth.tenant_id, Claim.status != "deleted")).all()
    return [{"id": str(r.id), "claim_no": r.claim_no, "status": r.status, "amount": float(r.amount or 0)} for r in rows]


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


# —— Bunker ——
class BunkerIn(BaseModel):
    vessel_id: UUID | None = None
    voyage_id: UUID | None = None
    grade: str = "VLSFO"
    qty_ordered: float
    unit_price: float
    rob_before: float | None = None


@router.post("/bunker-orders")
def create_bunker(body: BunkerIn, auth: AuthContext = Depends(require_module("bunker")), db: Session = Depends(get_db)):
    row = BunkerOrder(
        tenant_id=auth.tenant_id,
        order_no=f"BNK-{datetime.now().strftime('%Y%m%d')}-{str(uuid4())[:5].upper()}",
        vessel_id=body.vessel_id,
        voyage_id=body.voyage_id,
        grade=body.grade,
        qty_ordered=body.qty_ordered,
        unit_price=body.unit_price,
        rob_before=body.rob_before,
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "order_no": row.order_no, "status": row.status}


@router.post("/bunker-orders/{order_id}/transition")
def bunker_transition(
    order_id: UUID,
    target: str,
    qty_delivered: float | None = None,
    consumption: float | None = None,
    auth: AuthContext = Depends(require_module("bunker")),
    db: Session = Depends(get_db),
):
    row = db.get(BunkerOrder, order_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Bunker order not found")
    row.status = transition("bunker_order", row.status, target, BUNKER_TRANSITIONS)
    if qty_delivered is not None:
        row.qty_delivered = Decimal(str(qty_delivered))
    if consumption is not None:
        row.consumption = Decimal(str(consumption))
    if target == "delivered":
        before = Decimal(str(row.rob_before or 0))
        delivered = Decimal(str(row.qty_delivered or row.qty_ordered or 0))
        cons = Decimal(str(row.consumption or 0))
        row.rob_after = before + delivered - cons
        # ROB conservation check
        expected = before + delivered - cons
        if row.rob_after != expected:
            raise HTTPException(409, detail={"code": "ROB_IMBALANCE", "message": "ROB conservation failed"})
    db.commit()
    return {
        "id": str(row.id),
        "status": row.status,
        "rob_before": float(row.rob_before or 0),
        "rob_after": float(row.rob_after or 0),
        "qty_delivered": float(row.qty_delivered or 0),
    }


@router.get("/bunker-orders")
def list_bunker(auth: AuthContext = Depends(require_module("bunker")), db: Session = Depends(get_db)):
    rows = db.scalars(select(BunkerOrder).where(BunkerOrder.tenant_id == auth.tenant_id)).all()
    return [
        {
            "id": str(r.id),
            "order_no": r.order_no,
            "status": r.status,
            "vessel_id": str(r.vessel_id) if r.vessel_id else None,
            "voyage_id": str(r.voyage_id) if r.voyage_id else None,
            "grade": r.grade,
            "qty_ordered": float(r.qty_ordered or 0),
            "qty_delivered": float(r.qty_delivered or 0) if r.qty_delivered is not None else None,
            "unit_price": float(r.unit_price or 0),
            "rob_before": float(r.rob_before or 0) if r.rob_before is not None else None,
            "rob_after": float(r.rob_after or 0) if r.rob_after is not None else None,
            "consumption": float(r.consumption or 0) if r.consumption is not None else None,
            "currency": r.currency,
            "amount": float(r.qty_ordered or 0) * float(r.unit_price or 0),
        }
        for r in rows
    ]


class BunkerUpdate(BaseModel):
    grade: str | None = None
    qty_ordered: float | None = None
    unit_price: float | None = None
    rob_before: float | None = None
    vessel_id: UUID | None = None
    voyage_id: UUID | None = None


@router.patch("/bunker-orders/{order_id}")
def update_bunker(
    order_id: UUID,
    body: BunkerUpdate,
    auth: AuthContext = Depends(require_module("bunker")),
    db: Session = Depends(get_db),
):
    row = db.get(BunkerOrder, order_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Bunker order not found")
    if body.grade is not None:
        row.grade = body.grade
    if body.qty_ordered is not None:
        row.qty_ordered = body.qty_ordered
    if body.unit_price is not None:
        row.unit_price = body.unit_price
    if body.rob_before is not None:
        row.rob_before = body.rob_before
    if body.vessel_id is not None:
        row.vessel_id = body.vessel_id
    if body.voyage_id is not None:
        row.voyage_id = body.voyage_id
    db.commit()
    return {"id": str(row.id), "order_no": row.order_no, "status": row.status}


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


# —— Finance ——
class InvoiceIn(BaseModel):
    invoice_type: str = "freight"
    counterparty_id: UUID | None = None
    voyage_id: UUID | None = None
    amount: float
    tax_amount: float = 0
    currency: str = "USD"
    due_date: date | None = None


@router.post("/invoices")
def create_invoice(body: InvoiceIn, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    row = Invoice(
        tenant_id=auth.tenant_id,
        invoice_no=f"INV-{datetime.now().strftime('%Y%m%d')}-{str(uuid4())[:5].upper()}",
        invoice_type=body.invoice_type,
        counterparty_id=body.counterparty_id,
        voyage_id=body.voyage_id,
        amount=body.amount,
        tax_amount=body.tax_amount,
        currency=body.currency,
        due_date=body.due_date,
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "invoice_no": row.invoice_no, "status": row.status, "amount": float(row.amount)}


@router.post("/invoices/{invoice_id}/transition")
def invoice_transition(invoice_id: UUID, target: str, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    row = db.get(Invoice, invoice_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Invoice not found")
    row.status = transition("invoice", row.status, target, INVOICE_TRANSITIONS)
    if target == "issued":
        row.issued_at = datetime.now().astimezone()
    db.commit()
    return {"id": str(row.id), "status": row.status}


class InvoiceUpdate(BaseModel):
    amount: float | None = None
    tax_amount: float | None = None
    due_date: date | None = None
    invoice_type: str | None = None


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
    if body.amount is not None:
        row.amount = body.amount
    if body.tax_amount is not None:
        row.tax_amount = body.tax_amount
    if body.due_date is not None:
        row.due_date = body.due_date
    if body.invoice_type is not None:
        row.invoice_type = body.invoice_type
    db.commit()
    return {
        "id": str(row.id),
        "invoice_no": row.invoice_no,
        "status": row.status,
        "amount": float(row.amount),
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
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != auth.tenant_id or not _alive(inv.status):
        raise HTTPException(404, "Invoice not found")
    if inv.status not in {"issued", "partially_paid"}:
        raise HTTPException(409, detail={"code": "INVALID_STATE", "message": f"Cannot pay invoice in status {inv.status}"})
    pay = Payment(tenant_id=auth.tenant_id, invoice_id=inv.id, amount=amount, currency=inv.currency, reference=reference)
    db.add(pay)
    inv.paid_amount = Decimal(str(inv.paid_amount or 0)) + Decimal(str(amount))
    total = Decimal(str(inv.amount)) + Decimal(str(inv.tax_amount or 0))
    if inv.paid_amount >= total:
        inv.status = transition("invoice", inv.status, "paid", INVOICE_TRANSITIONS)
    elif inv.status == "issued":
        inv.status = transition("invoice", "issued", "partially_paid", INVOICE_TRANSITIONS)
    db.commit()
    return {"invoice_id": str(inv.id), "status": inv.status, "paid_amount": float(inv.paid_amount)}


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


@router.get("/invoices")
def list_invoices(auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    rows = db.scalars(select(Invoice).where(Invoice.tenant_id == auth.tenant_id, Invoice.status != "deleted")).all()
    return [
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
        }
        for r in rows
    ]


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


# —— Market / DQ / Emissions / Analytics ——
@router.post("/market/quotes")
def add_quote(symbol: str, value: float, quote_date: date | None = None, auth: AuthContext = Depends(require_module("analytics")), db: Session = Depends(get_db)):
    qd = quote_date or date.today()
    row = db.scalar(
        select(MarketQuote).where(
            MarketQuote.tenant_id == auth.tenant_id,
            MarketQuote.symbol == symbol,
            MarketQuote.quote_date == qd,
        )
    )
    if row:
        row.value = value
        row.source = "manual"
    else:
        row = MarketQuote(tenant_id=auth.tenant_id, symbol=symbol, value=value, quote_date=qd, source="manual")
        db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "symbol": symbol, "value": float(row.value), "quote_date": qd.isoformat()}


@router.get("/market/quotes")
def list_quotes(auth: AuthContext = Depends(require_module("analytics")), db: Session = Depends(get_db)):
    rows = db.scalars(select(MarketQuote).where(MarketQuote.tenant_id == auth.tenant_id)).all()
    return [{"symbol": r.symbol, "value": float(r.value), "quote_date": r.quote_date.isoformat()} for r in rows]


@router.post("/dq/issues")
def create_dq(rule_code: str, entity_type: str, entity_id: str, message: str, auth: AuthContext = Depends(require_module("analytics")), db: Session = Depends(get_db)):
    row = DqIssue(tenant_id=auth.tenant_id, rule_code=rule_code, entity_type=entity_type, entity_id=entity_id, message=message)
    db.add(row)
    db.commit()
    return {"id": str(row.id), "status": row.status}


@router.get("/dq/issues")
def list_dq(auth: AuthContext = Depends(require_module("analytics")), db: Session = Depends(get_db)):
    rows = db.scalars(select(DqIssue).where(DqIssue.tenant_id == auth.tenant_id)).all()
    return [{"id": str(r.id), "rule_code": r.rule_code, "message": r.message, "status": r.status} for r in rows]


@router.post("/emissions")
def create_emission(
    voyage_id: UUID | None = None,
    vessel_id: UUID | None = None,
    fo_mt: float = 0,
    do_mt: float = 0,
    auth: AuthContext = Depends(require_module("emissions")),
    db: Session = Depends(get_db),
):
    co2 = fo_mt * 3.114 + do_mt * 3.206
    cii = "C" if co2 > 1000 else "B" if co2 > 500 else "A"
    row = EmissionRecord(tenant_id=auth.tenant_id, voyage_id=voyage_id, vessel_id=vessel_id, fo_mt=fo_mt, do_mt=do_mt, co2_mt=co2, cii_rating=cii)
    db.add(row)
    db.commit()
    return {"id": str(row.id), "co2_mt": co2, "cii_rating": cii}


@router.get("/emissions")
def list_emissions(auth: AuthContext = Depends(require_module("emissions")), db: Session = Depends(get_db)):
    rows = db.scalars(select(EmissionRecord).where(EmissionRecord.tenant_id == auth.tenant_id)).all()
    return [
        {
            "id": str(r.id),
            "voyage_id": str(r.voyage_id) if r.voyage_id else None,
            "vessel_id": str(r.vessel_id) if r.vessel_id else None,
            "fo_mt": float(r.fo_mt or 0),
            "do_mt": float(r.do_mt or 0),
            "co2_mt": float(r.co2_mt or 0),
            "cii_rating": r.cii_rating,
            "period": r.period,
        }
        for r in rows
    ]


class FuelEuIn(BaseModel):
    voyage_id: UUID | None = None
    vessel_id: UUID | None = None
    fo_mt: float = 0
    do_mt: float = 0
    lng_mt: float = 0
    distance_nm: float = 0
    cargo_mt: float = 0
    eu_share: float = 1.0  # fraction of voyage in EU scope
    ets_price_eur: float = 70.0
    fueleu_penalty_eur_per_tco2e: float = 2400.0


@router.post("/emissions/fueleu-calc")
def fueleu_calc(body: FuelEuIn, auth: AuthContext = Depends(require_module("emissions")), db: Session = Depends(get_db)):
    """FuelEU / EU ETS style calculator — persists EmissionRecord + returns compliance snapshot."""
    # Simplified GHG intensity (gCO2e/MJ) vs FuelEU target trajectory
    energy_mj = body.fo_mt * 42700 + body.do_mt * 42700 + body.lng_mt * 48000  # approx LHV MJ/t
    co2e_t = body.fo_mt * 3.114 + body.do_mt * 3.206 + body.lng_mt * 2.75
    intensity = (co2e_t * 1_000_000 / energy_mj) if energy_mj > 0 else 0.0
    target_2025 = 89.34  # illustrative FuelEU reference gCO2e/MJ
    compliance_balance_t = max(0.0, (intensity - target_2025) / 1_000_000 * energy_mj) * body.eu_share
    ets_allowances = co2e_t * body.eu_share
    ets_cost = ets_allowances * body.ets_price_eur
    fueleu_penalty = compliance_balance_t * body.fueleu_penalty_eur_per_tco2e
    cii = "C" if co2e_t > 1000 else "B" if co2e_t > 500 else "A"
    row = EmissionRecord(
        tenant_id=auth.tenant_id,
        voyage_id=body.voyage_id,
        vessel_id=body.vessel_id,
        fo_mt=body.fo_mt,
        do_mt=body.do_mt,
        co2_mt=co2e_t,
        cii_rating=cii,
        period="fueleu",
    )
    db.add(row)
    db.commit()
    return {
        "id": str(row.id),
        "co2e_t": round(co2e_t, 3),
        "ghg_intensity": round(intensity, 4),
        "target_intensity": target_2025,
        "compliance_balance_t": round(compliance_balance_t, 4),
        "ets_allowances_t": round(ets_allowances, 3),
        "ets_cost_eur": round(ets_cost, 2),
        "fueleu_penalty_eur": round(fueleu_penalty, 2),
        "total_compliance_cost_eur": round(ets_cost + fueleu_penalty, 2),
        "cii_rating": cii,
        "format": "FuelEU_EU_ETS_v1",
    }


@router.get("/emissions/export")
def export_emissions(auth: AuthContext = Depends(require_module("emissions")), db: Session = Depends(get_db)):
    rows = db.scalars(select(EmissionRecord).where(EmissionRecord.tenant_id == auth.tenant_id)).all()
    return {
        "format": "EU_ETS_FuelEU_v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "rows": [
            {
                "voyage_id": str(r.voyage_id) if r.voyage_id else None,
                "vessel_id": str(r.vessel_id) if r.vessel_id else None,
                "fo_mt": float(r.fo_mt or 0),
                "do_mt": float(r.do_mt or 0),
                "co2_mt": float(r.co2_mt or 0),
                "cii": r.cii_rating,
                "period": r.period,
            }
            for r in rows
        ],
    }


@router.get("/analytics/reports/tce")
def report_tce(auth: AuthContext = Depends(require_module("analytics")), db: Session = Depends(get_db)):
    from app.models_domain import Estimate

    rows = db.scalars(select(Estimate).where(Estimate.tenant_id == auth.tenant_id, Estimate.status.in_(["calculated", "converted"]))).all()
    return [{"title": r.title, "tce": (r.results or {}).get("tce"), "id": str(r.id)} for r in rows]


@router.get("/analytics/reports/voyage-pnl")
def report_pnl(auth: AuthContext = Depends(require_module("analytics")), db: Session = Depends(get_db)):
    """Dynamic voyage P&L: estimate vs actual revenue/cost drivers."""
    from app.models_domain import Charter, Estimate, Voyage

    voyages = db.scalars(select(Voyage).where(Voyage.tenant_id == auth.tenant_id)).all()
    invs = db.scalars(select(Invoice).where(Invoice.tenant_id == auth.tenant_id)).all()
    pdas = db.scalars(select(PortDisbursement).where(PortDisbursement.tenant_id == auth.tenant_id)).all()
    bunkers = db.scalars(select(BunkerOrder).where(BunkerOrder.tenant_id == auth.tenant_id)).all()

    rev_by: dict[str, float] = {}
    paid_by: dict[str, float] = {}
    for i in invs:
        key = str(i.voyage_id) if i.voyage_id else "unassigned"
        rev_by[key] = rev_by.get(key, 0) + float(i.amount or 0)
        paid_by[key] = paid_by.get(key, 0) + float(i.paid_amount or 0)

    pda_by: dict[str, float] = {}
    for p in pdas:
        if not p.voyage_id:
            continue
        key = str(p.voyage_id)
        amt = float(p.fda_amount or p.pda_amount or 0)
        pda_by[key] = pda_by.get(key, 0) + amt

    bunker_by: dict[str, float] = {}
    for b in bunkers:
        if not b.voyage_id:
            continue
        key = str(b.voyage_id)
        qty = float(b.qty_delivered or b.qty_ordered or 0)
        price = float(b.unit_price or 0)
        bunker_by[key] = bunker_by.get(key, 0) + qty * price

    out = []
    for v in voyages:
        vid = str(v.id)
        est_rev = 0.0
        est_cost = 0.0
        est_tce = None
        if v.charter_id:
            ch = db.get(Charter, v.charter_id)
            if ch and ch.estimate_id:
                est = db.get(Estimate, ch.estimate_id)
                if est and est.results:
                    est_rev = float(est.results.get("total_revenue") or 0)
                    est_cost = float(est.results.get("voyage_cost") or 0)
                    est_tce = est.results.get("tce")
        act_rev = rev_by.get(vid, 0.0)
        act_cost = pda_by.get(vid, 0.0) + bunker_by.get(vid, 0.0)
        act_pnl = act_rev - act_cost
        est_pnl = est_rev - est_cost
        out.append(
            {
                "voyage_id": vid,
                "voyage_no": v.voyage_no,
                "status": v.status,
                "cargo": v.cargo,
                "estimated_revenue": est_rev,
                "estimated_cost": est_cost,
                "estimated_pnl": est_pnl,
                "estimated_tce": est_tce,
                "actual_revenue": act_rev,
                "actual_cost": act_cost,
                "actual_pnl": act_pnl,
                "variance_pnl": act_pnl - est_pnl,
                "paid_amount": paid_by.get(vid, 0.0),
                "port_cost": pda_by.get(vid, 0.0),
                "bunker_cost": bunker_by.get(vid, 0.0),
                "revenue": act_rev,
            }
        )
    if "unassigned" in rev_by:
        out.append(
            {
                "voyage_id": "unassigned",
                "voyage_no": "UNASSIGNED",
                "status": "—",
                "cargo": None,
                "estimated_revenue": 0,
                "estimated_cost": 0,
                "estimated_pnl": 0,
                "estimated_tce": None,
                "actual_revenue": rev_by["unassigned"],
                "actual_cost": 0,
                "actual_pnl": rev_by["unassigned"],
                "variance_pnl": rev_by["unassigned"],
                "paid_amount": paid_by.get("unassigned", 0),
                "port_cost": 0,
                "bunker_cost": 0,
                "revenue": rev_by["unassigned"],
            }
        )
    return out


# —— Pooling / Risk / Berth / Portal / Docs ——
@router.get("/pools")
def list_pools(auth: AuthContext = Depends(require_module("pooling")), db: Session = Depends(get_db)):
    rows = db.scalars(select(Pool).where(Pool.tenant_id == auth.tenant_id)).all()
    out = []
    for r in rows:
        vessels = db.scalars(select(PoolVessel).where(PoolVessel.pool_id == r.id, PoolVessel.left_on.is_(None))).all()
        periods = db.scalars(select(PoolPeriod).where(PoolPeriod.pool_id == r.id)).all()
        out.append(
            {
                "id": str(r.id),
                "name": r.name,
                "vessel_count": len(vessels),
                "vessels": [{"id": str(v.id), "vessel_id": str(v.vessel_id), "points": float(v.points)} for v in vessels],
                "periods": [
                    {
                        "id": str(p.id),
                        "label": p.label,
                        "total_pool_result": float(p.total_pool_result or 0),
                        "status": p.status,
                        "distribution": p.distribution or {},
                    }
                    for p in periods
                ],
            }
        )
    return out


@router.post("/pools")
def create_pool(name: str, auth: AuthContext = Depends(require_module("pooling")), db: Session = Depends(get_db)):
    row = Pool(tenant_id=auth.tenant_id, name=name)
    db.add(row)
    db.commit()
    return {"id": str(row.id), "name": name}


@router.post("/pools/{pool_id}/vessels")
def add_pool_vessel(pool_id: UUID, vessel_id: UUID, points: float = 1.0, auth: AuthContext = Depends(require_module("pooling")), db: Session = Depends(get_db)):
    pool = db.get(Pool, pool_id)
    if not pool or pool.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Pool not found")
    row = PoolVessel(pool_id=pool_id, vessel_id=vessel_id, points=points, joined_on=date.today())
    db.add(row)
    db.commit()
    return {"id": str(row.id)}


@router.post("/pools/{pool_id}/periods")
def create_period(pool_id: UUID, label: str, total_pool_result: float, auth: AuthContext = Depends(require_module("pooling")), db: Session = Depends(get_db)):
    pool = db.get(Pool, pool_id)
    if not pool or pool.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Pool not found")
    vessels = db.scalars(select(PoolVessel).where(PoolVessel.pool_id == pool_id, PoolVessel.left_on.is_(None))).all()
    total_points = sum(float(v.points) for v in vessels) or 1.0
    dist = {str(v.vessel_id): round(total_pool_result * float(v.points) / total_points, 2) for v in vessels}
    row = PoolPeriod(pool_id=pool_id, label=label, total_pool_result=total_pool_result, distribution=dist, status="calculating")
    db.add(row)
    db.commit()
    return {"id": str(row.id), "distribution": dist, "status": row.status}


@router.post("/pools/periods/{period_id}/settle")
def settle_period(period_id: UUID, auth: AuthContext = Depends(require_module("pooling")), db: Session = Depends(get_db)):
    row = db.get(PoolPeriod, period_id)
    if not row:
        raise HTTPException(404, "Period not found")
    pool = db.get(Pool, row.pool_id)
    if not pool or pool.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Pool not found")
    row.status = transition("pool_period", row.status, "settled", POOL_PERIOD_TRANSITIONS)
    db.commit()
    return {"id": str(row.id), "status": row.status, "distribution": row.distribution}


@router.post("/risk/positions")
def create_risk(symbol: str, qty: float, entry_price: float, side: str = "long", auth: AuthContext = Depends(require_module("risk")), db: Session = Depends(get_db)):
    var_1d = abs(qty * entry_price * 0.02)
    limit = 100000
    row = RiskPosition(
        tenant_id=auth.tenant_id,
        symbol=symbol,
        side=side,
        qty=qty,
        entry_price=entry_price,
        mark_price=entry_price,
        var_1d=var_1d,
        limit_breach=var_1d > limit,
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "var_1d": var_1d, "limit_breach": row.limit_breach}


@router.get("/risk/positions")
def list_risk(auth: AuthContext = Depends(require_module("risk")), db: Session = Depends(get_db)):
    rows = db.scalars(select(RiskPosition).where(RiskPosition.tenant_id == auth.tenant_id)).all()
    return [{"id": str(r.id), "symbol": r.symbol, "var_1d": float(r.var_1d or 0), "limit_breach": r.limit_breach} for r in rows]


class BerthIn(BaseModel):
    berth_name: str
    start_at: datetime
    end_at: datetime
    port_id: UUID | None = None
    voyage_id: UUID | None = None


@router.post("/berths")
def create_berth(body: BerthIn, auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    row = BerthWindow(
        tenant_id=auth.tenant_id,
        berth_name=body.berth_name,
        start_at=body.start_at,
        end_at=body.end_at,
        port_id=body.port_id,
        voyage_id=body.voyage_id,
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "berth_name": body.berth_name, "status": row.status}


@router.post("/portal/messages")
def portal_message(counterparty_id: UUID, subject: str, body: str | None = None, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    row = PortalMessage(tenant_id=auth.tenant_id, counterparty_id=counterparty_id, subject=subject, body=body)
    db.add(row)
    db.commit()
    return {"id": str(row.id)}


@router.get("/portal/invoices")
def portal_invoices(counterparty_id: UUID, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Invoice).where(Invoice.tenant_id == auth.tenant_id, Invoice.counterparty_id == counterparty_id)
    ).all()
    return [{"invoice_no": r.invoice_no, "status": r.status, "amount": float(r.amount)} for r in rows]


@router.post("/documents")
def create_doc(entity_type: str, entity_id: UUID, title: str, doc_type: str = "file", auth: AuthContext = Depends(require_module("docs")), db: Session = Depends(get_db)):
    row = Document(tenant_id=auth.tenant_id, entity_type=entity_type, entity_id=entity_id, title=title, doc_type=doc_type, storage_uri=f"demo://{entity_type}/{entity_id}/{title}")
    db.add(row)
    db.commit()
    return {"id": str(row.id), "storage_uri": row.storage_uri}
