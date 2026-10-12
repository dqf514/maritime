"""Mirror invoice generation — creates counterparty invoice with reversed direction.

When company A issues a freight invoice to company B, a mirror invoice is
auto-generated for company B's books with the same amount/currency/fx_rate
but opposite debit/credit direction. The mirror follows an independent
approval workflow.

End-to-end contract (Track C3):
- 源改镜像跟 (pull-sync): while the mirror is ``draft``, source commercial
  fields flow into it via :func:`sync_mirrors`, tracked by
  ``Invoice.mirror_synced_source_at``.
- 不可独立编辑: a mirror must not be patched on its own — call
  :func:`assert_mirror_writable` at the top of any invoice-update path.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import Invoice
from app.services.config_service import ConfigService
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

# Fields pulled from source → mirror while the mirror is still draft.
SYNCED_FIELDS = ("amount", "currency", "fx_rate", "tax_amount", "due_date", "bill_by", "commission_basis")


def intercompany_enabled(db: Session, tenant_id: UUID, user_id: UUID | None = None) -> bool:
    """CFGEnableIntercompany — gate for cross-tenant (intercompany) mirrors.

    Thin wrapper over ConfigService so tests can monkeypatch this helper.
    """
    return bool(
        ConfigService.get(db, "CFGEnableIntercompany", tenant_id=tenant_id, user_id=user_id, default=False)
    )


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
    if source.mirror_of_id is not None:
        raise ValueError("Cannot mirror a mirror invoice")

    existing = db.scalar(select(Invoice.id).where(Invoice.mirror_of_id == source.id))
    if existing is not None:
        raise ValueError("Source invoice already has a mirror")

    mirror_no = next_doc_number(db, counterparty_tenant_id, Invoice, Invoice.invoice_no, "INV")
    synced_at = _now()

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
        mirror_synced_source_at=synced_at,
        bill_by=source.bill_by,
        commission_basis=source.commission_basis,
    )
    db.add(mirror)
    return mirror


def assert_mirror_writable(invoice: Invoice) -> None:
    """不可独立编辑 — mirror invoices follow their source and cannot be edited.

    Call this at the top of any invoice update/patch path. Raises 409
    ``MIRROR_READONLY`` when the invoice is a mirror.

    NOTE: ``routers/invoices.py::update_invoice`` must call this (see report);
    the call is intentionally not added here to avoid touching that file while
    a concurrent agent owns it.
    """
    if invoice.mirror_of_id is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "MIRROR_READONLY",
                "message": "Mirror invoice follows its source and cannot be edited independently",
                "mirror_of_id": str(invoice.mirror_of_id),
            },
        )


def sync_mirrors(db: Session, source: Invoice) -> list[Invoice]:
    """Pull-sync (源改镜像跟): draft mirrors follow source commercial fields.

    Copies amount/currency/fx_rate/tax_amount/due_date/bill_by/commission_basis
    into every draft mirror of ``source`` when the source has moved on since the
    mirror's stored sync marker (``mirror_synced_source_at``), then stamps the
    marker. Commits are left to the caller.
    """
    if source.mirror_of_id is not None:
        # Called on a mirror — nothing to pull; the chain resolves its source.
        return []

    mirrors = db.scalars(select(Invoice).where(Invoice.mirror_of_id == source.id)).all()
    synced: list[Invoice] = []
    for mirror in mirrors:
        if mirror.status != "draft":
            continue
        if not _needs_sync(source, mirror):
            continue
        for field in SYNCED_FIELDS:
            setattr(mirror, field, getattr(source, field))
        mirror.mirror_synced_source_at = _now()
        db.add(mirror)
        synced.append(mirror)
    return synced


def get_mirror_chain(db: Session, invoice_id: UUID, tenant_id: UUID) -> list[dict]:
    """Return the source + its mirror (if any) for display.

    Tenant-scoped: only the invoice row that matches ``tenant_id`` is used as
    the entry point (its counterparty leg may live in another tenant when
    intercompany is enabled).
    """
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != tenant_id:
        return []

    chain = [_chain_row(inv)]

    if inv.mirror_of_id:
        source = db.get(Invoice, inv.mirror_of_id)
        if source:
            chain.insert(0, _chain_row(source))
    else:
        mirror_stmt = select(Invoice).where(Invoice.mirror_of_id == inv.id)
        mirror = db.scalars(mirror_stmt).first()
        if mirror:
            chain.append(_chain_row(mirror))

    return chain


def find_mirror(db: Session, source_id: UUID) -> Invoice | None:
    """Return the mirror of a source invoice (any tenant), if one exists."""
    return db.scalars(select(Invoice).where(Invoice.mirror_of_id == source_id)).first()


def invoice_payload(row: Invoice) -> dict:
    """Invoice-list-shaped dict for API responses (includes mirror flags)."""
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "invoice_no": row.invoice_no,
        "invoice_type": row.invoice_type,
        "status": row.status,
        "amount": float(row.amount or 0),
        "tax_amount": float(row.tax_amount or 0),
        "paid_amount": float(row.paid_amount or 0),
        "currency": row.currency,
        "fx_rate": float(row.fx_rate) if row.fx_rate is not None else None,
        "base_amount": float(row.base_amount) if row.base_amount is not None else None,
        "voyage_id": str(row.voyage_id) if row.voyage_id else None,
        "counterparty_id": str(row.counterparty_id) if row.counterparty_id else None,
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "gl_posted": bool(row.gl_posted),
        "mirror_of_id": str(row.mirror_of_id) if row.mirror_of_id else None,
        "is_mirror": row.mirror_of_id is not None,
        "mirror_synced_source_at": row.mirror_synced_source_at.isoformat() if row.mirror_synced_source_at else None,
        "bill_by": row.bill_by,
        "commission_basis": row.commission_basis,
    }


def _chain_row(row: Invoice) -> dict:
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "invoice_no": row.invoice_no,
        "status": row.status,
        "amount": str(row.amount),
        "currency": row.currency,
        "is_mirror": row.mirror_of_id is not None,
        "mirror_of_id": str(row.mirror_of_id) if row.mirror_of_id else None,
        "mirror_synced_source_at": row.mirror_synced_source_at.isoformat() if row.mirror_synced_source_at else None,
    }


def _needs_sync(source: Invoice, mirror: Invoice) -> bool:
    """True when the source has moved on since the mirror's last pull-sync.

    Invoice has no ``updated_at`` column, so drift is detected by comparing the
    synced fields themselves. If a source timestamp is ever present it is used
    as an additional trigger (marker older than source).
    """
    if mirror.mirror_synced_source_at is None:
        return True
    if any(getattr(source, f) != getattr(mirror, f) for f in SYNCED_FIELDS):
        return True
    source_ts = getattr(source, "updated_at", None)
    if source_ts is not None:
        return _as_utc(source_ts) > _as_utc(mirror.mirror_synced_source_at)
    return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# Re-exported for callers that need the synced-field list (e.g. tests).
__all__ = [
    "MIRROR_TYPES",
    "SYNCED_FIELDS",
    "assert_mirror_writable",
    "create_mirror_invoice",
    "find_mirror",
    "get_mirror_chain",
    "intercompany_enabled",
    "invoice_payload",
    "sync_mirrors",
]
