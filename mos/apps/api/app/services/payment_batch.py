"""Payment batch service — batch invoice payments into a single instruction set.

Supports:
- Auto-selecting payable invoices by due date / counterparty / currency
- Batch creation with sequential numbering (PB-YYYY-NNNNN)
- Bank charge allocation modes (shared / sender / receiver)
- Payment instruction XML export (standard payment compatible)
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
from app.services.money import invoice_gross, invoice_open
from app.services.state_machine import INVOICE_TRANSITIONS, transition
from app.services.timeutil import utcnow_naive


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
        if invoice_open(inv) <= 0:
            continue  # 已结清 —— 不该进批次
        invoices.append(inv)

    # P0-B4：未收口径 = 金额 + 税 − 已收（与单笔收款 / 账龄一致）。
    # 旧实现用 `amount - paid_amount`，**漏掉了税** —— 有税发票会被少付一笔税。
    total = sum((invoice_open(inv) for inv in invoices), Decimal("0"))

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
        created_by=user_id,
    )
    db.add(batch)
    db.flush()

    for inv in invoices:
        outstanding = invoice_open(inv)
        payment = Payment(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            invoice_id=inv.id,
            batch_id=batch.id,
            amount=outstanding,
            currency=inv.currency,
            created_by=user_id,
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
    batch.approved_at = utcnow_naive()

    stmt = select(Payment).where(Payment.batch_id == batch.id)
    payments = db.scalars(stmt).all()
    for pay in payments:
        inv = db.get(Invoice, pay.invoice_id)
        if not inv:
            continue
        inv.paid_amount = (inv.paid_amount or 0) + pay.amount
        # 状态判定用**总额**（金额 + 税），与单笔收款一致
        total = invoice_gross(inv)
        if inv.paid_amount >= total:
            inv.status = "paid"
        elif inv.paid_amount > 0:
            inv.status = "partially_paid"

    batch.status = "completed"
    db.flush()
    return batch


def reverse_batch(db: Session, batch: PaymentBatch) -> PaymentBatch:
    """Reverse a completed batch — undo payment amounts on linked invoices.

    P1-B5：冲销走**台账**（写一条金额为负、``reference="VOID:<batch id>"`` 的
    Payment 行），而不是只在发票上把 ``paid_amount`` 减掉。旧实现留下一条
    「已收款但账上查无此笔」的记录，付款台账和发票余额对不上。
    """
    if batch.status not in ("completed", "processing"):
        raise ValueError(f"Cannot reverse batch in status '{batch.status}'")

    void_ref = f"VOID:{batch.id}"
    existing = db.scalar(
        select(Payment).where(Payment.tenant_id == batch.tenant_id, Payment.reference == void_ref)
    )
    if existing:
        raise ValueError("Batch is already reversed")

    stmt = select(Payment).where(Payment.batch_id == batch.id)
    payments = db.scalars(stmt).all()
    for pay in payments:
        inv = db.get(Invoice, pay.invoice_id)
        if not inv:
            continue
        db.add(
            Payment(
                tenant_id=batch.tenant_id,
                invoice_id=inv.id,
                batch_id=batch.id,
                amount=-Decimal(str(pay.amount)),
                currency=pay.currency,
                reference=void_ref,
            )
        )
        inv.paid_amount = max(Decimal(0), (inv.paid_amount or 0) - Decimal(str(pay.amount)))
        # 状态必须走状态机 —— 以前直接赋值，能做出「paid → issued」这种非法转移
        # （INVOICE_TRANSITIONS 里 paid 只能退到 partially_paid）。审计 P1-B5
        target = "issued" if inv.paid_amount == 0 else ("partially_paid" if inv.status == "paid" else None)
        if target and target != inv.status:
            if inv.status == "paid" and target == "issued":
                # paid → issued 没有直接边：先退到 partially_paid 再退回 issued
                inv.status = transition("invoice", inv.status, "partially_paid", INVOICE_TRANSITIONS)
            inv.status = transition("invoice", inv.status, target, INVOICE_TRANSITIONS)

    batch.status = "reversed"
    db.flush()
    return batch


def export_payment_xml(batch: PaymentBatch, payments: list[Payment]) -> str:
    """Generate standard payment-compatible XML for bank instruction."""
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
