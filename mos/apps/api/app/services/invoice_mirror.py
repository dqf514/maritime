"""Mirror invoice generation — creates counterparty invoice with reversed direction.

When company A issues a freight invoice to company B, a mirror invoice is
auto-generated for company B's books with the same amount/currency/fx_rate
but opposite debit/credit direction. The mirror follows an independent
approval workflow.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import Invoice
from app.services.doc_numbering import next_doc_number

MIRROR_TYPES = {
    "freight",
    "demurrage",
    "despatch",
    "bunker",
    "port_da",
    "tc_hire",
    "broker_commission",
    "carbon_allowance",
    "eu_ets",
}


def create_mirror_invoice(
    db: Session,
    source: Invoice,
    counterparty_tenant_id: UUID,
) -> Invoice:
    """Generate a mirror invoice for the counterparty.

    The mirror copies amount, currency, fx_rate, voyage, and invoice_type
    from the source. The mirror's ``mirror_of_id`` points back to the source.
    The mirror starts in ``draft`` status with its own invoice_no.
    """
    if source.invoice_type not in MIRROR_TYPES:
        raise ValueError(f"Invoice type '{source.invoice_type}' is not mirrorable")

    mirror_no = next_doc_number(db, counterparty_tenant_id, Invoice, Invoice.invoice_no, "INV")

    mirror = Invoice(
        id=uuid.uuid4(),
        tenant_id=counterparty_tenant_id,
        invoice_no=mirror_no,
        invoice_type=source.invoice_type,
        status="draft",
        counterparty_id=source.counterparty_id,
        voyage_id=source.voyage_id,
        currency=source.currency,
        amount=source.amount,
        base_amount=source.base_amount,
        fx_rate=source.fx_rate,
        tax_amount=source.tax_amount,
        due_date=source.due_date,
        mirror_of_id=source.id,
        bill_by=source.bill_by,
        commission_basis=source.commission_basis,
    )
    db.add(mirror)
    return mirror


def get_mirror_chain(db: Session, invoice_id: UUID, tenant_id: UUID) -> list[dict]:
    """Return the source + its mirror (if any) for display."""
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != tenant_id:
        return []

    chain = [
        {
            "id": str(inv.id),
            "invoice_no": inv.invoice_no,
            "status": inv.status,
            "amount": str(inv.amount),
            "currency": inv.currency,
            "is_mirror": inv.mirror_of_id is not None,
        }
    ]

    if inv.mirror_of_id:
        source = db.get(Invoice, inv.mirror_of_id)
        if source:
            chain.insert(
                0,
                {
                    "id": str(source.id),
                    "invoice_no": source.invoice_no,
                    "status": source.status,
                    "amount": str(source.amount),
                    "currency": source.currency,
                    "is_mirror": source.mirror_of_id is not None,
                },
            )
    else:
        mirror_stmt = select(Invoice).where(
            Invoice.mirror_of_id == inv.id,
            Invoice.tenant_id == tenant_id,
        )
        mirror = db.scalars(mirror_stmt).first()
        if mirror:
            chain.append(
                {
                    "id": str(mirror.id),
                    "invoice_no": mirror.invoice_no,
                    "status": mirror.status,
                    "amount": str(mirror.amount),
                    "currency": mirror.currency,
                    "is_mirror": True,
                }
            )

    return chain
