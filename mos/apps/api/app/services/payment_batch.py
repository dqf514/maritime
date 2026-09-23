"""Payment batch service — batch invoice payments into a single instruction set.

Supports:
- Auto-selecting payable invoices by due date / counterparty / currency
- Batch creation with sequential numbering (PB-YYYY-NNNNN)
- Bank charge allocation modes (shared / sender / receiver)
- Payment instruction XML export (iMOS SimplePayment compatible)
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models_domain import Invoice, Payment, PaymentBatch
from app.services.doc_numbering import next_doc_number


def select_payable_invoices(
    db: Session,
    tenant_id: UUID,
    due_before: date | None = None,
    counterparty_id: UUID | None = None,
    currency: str | None = None,
) -> list[Invoice]:
    """Find issued invoices that still have an outstanding balance."""
    stmt = select(Invoice).where(
        Invoice.tenant_id == tenant_id,
        Invoice.status.in_(["issued", "partially_paid"]),
    )
    if due_before:
        stmt = stmt.where(Invoice.due_date <= due_before)
    if counterparty_id:
        stmt = stmt.where(Invoice.counterparty_id == counterparty_id)
    if currency:
        stmt = stmt.where(Invoice.currency == currency)
    return list(db.scalars(stmt).all())


def create_batch(
    db: Session,
    tenant_id: UUID,
    invoice_ids: list[UUID],
    batch_date: date,
    bank_charge_mode: str = "shared",
    user_id: UUID | None = None,
) -> PaymentBatch:
    """Create a payment batch from selected invoices.

    Generates one Payment row per invoice, all linked to the new batch.
    """
    batch_no = next_doc_number(db, tenant_id, PaymentBatch, PaymentBatch.batch_number, "PB")

    invoices = []
    for iid in invoice_ids:
        inv = db.get(Invoice, iid)
        if not inv or inv.tenant_id != tenant_id:
            continue
        if inv.status not in ("issued", "partially_paid"):
            continue
        invoices.append(inv)

    total = sum((inv.amount - inv.paid_amount) for inv in invoices)

    batch = PaymentBatch(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        batch_number=batch_no,
        batch_date=batch_date,
        status="draft",
        total_amount=total,
        currency=invoices[0].currency if invoices else "USD",
        payment_count=len(invoices),
        bank_charge_mode=bank_charge_mode,
        approval_user_id=user_id,
    )
    db.add(batch)
    db.flush()

    for inv in invoices:
        outstanding = inv.amount - inv.paid_amount
        payment = Payment(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            invoice_id=inv.id,
            batch_id=batch.id,
            amount=outstanding,
            currency=inv.currency,
        )
        db.add(payment)

    db.flush()
    return batch


def approve_batch(db: Session, batch: PaymentBatch, user_id: UUID) -> PaymentBatch:
    """Mark batch as processing and transition linked invoices to partially_paid."""
    if batch.status != "draft":
        raise ValueError(f"Batch status is '{batch.status}', expected 'draft'")

    batch.status = "processing"
    batch.approval_user_id = user_id
    batch.approved_at = datetime.now()

    stmt = select(Payment).where(Payment.batch_id == batch.id)
    payments = db.scalars(stmt).all()
    for pay in payments:
        inv = db.get(Invoice, pay.invoice_id)
        if inv:
            inv.paid_amount = inv.paid_amount + pay.amount
            inv.status = "partially_paid" if inv.paid_amount < inv.amount else "paid"

    batch.status = "completed"
    db.flush()
    return batch


def reverse_batch(db: Session, batch: PaymentBatch) -> PaymentBatch:
    """Reverse a completed batch — undo payment amounts on linked invoices."""
    if batch.status not in ("completed", "processing"):
        raise ValueError(f"Cannot reverse batch in status '{batch.status}'")

    stmt = select(Payment).where(Payment.batch_id == batch.id)
    payments = db.scalars(stmt).all()
    for pay in payments:
        inv = db.get(Invoice, pay.invoice_id)
        if inv:
            inv.paid_amount = max(Decimal(0), inv.paid_amount - pay.amount)
            if inv.paid_amount == 0:
                inv.status = "issued"
            else:
                inv.status = "partially_paid"

    batch.status = "reversed"
    db.flush()
    return batch


def export_payment_xml(batch: PaymentBatch, payments: list[Payment]) -> str:
    """Generate iMOS SimplePayment-compatible XML for bank instruction."""
    root = ET.Element("PaymentInstructions")
    root.set("batchNumber", batch.batch_number)
    root.set("batchDate", batch.batch_date.isoformat())
    root.set("currency", batch.currency)
    root.set("totalAmount", str(batch.total_amount))

    for pay in payments:
        elem = ET.SubElement(root, "Payment")
        elem.set("id", str(pay.id))
        elem.set("invoiceId", str(pay.invoice_id))
        elem.set("amount", str(pay.amount))
        elem.set("currency", pay.currency)
        if pay.reference:
            elem.set("reference", pay.reference)
        ET.SubElement(elem, "BankChargeMode").text = batch.bank_charge_mode or "shared"

    return ET.tostring(root, encoding="unicode", xml_declaration=True)
