"""汇率日期规则 — FX rate date basis per invoice type.

``rate_date_basis`` decides which date an FX rate is taken from:

- ``departure`` — vessel departure date of the voyage
- ``arrival``   — vessel arrival date of the voyage
- ``invoice``   — invoice date
- ``posted``    — posting / GMT date

Additive only: when no active ``FxDateRule`` row exists for an invoice type the
conversion keeps its historical behaviour (latest rate). See
:func:`resolve_fx_rate`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_finance_ext import FxDateRule
from app.models_wave1 import ExchangeRate
from app.services.invoice_types import is_valid_invoice_type, normalize_invoice_type

RATE_DATE_BASES: tuple[str, ...] = ("departure", "arrival", "invoice", "posted")
DEFAULT_RATE_DATE_BASIS = "invoice"

# Context keys a caller may supply to pick_rate_date(), parallel to RATE_DATE_BASES.
_CONTEXT_KEYS = {
    "departure": ("departure", "departure_date", "sailing_date"),
    "arrival": ("arrival", "arrival_date"),
    "invoice": ("invoice", "invoice_date"),
    "posted": ("posted", "posted_date", "gmt_date"),
}


def validate_rate_date_basis(basis: str) -> str:
    """Return ``basis`` if valid; raise ``ValueError`` otherwise."""
    key = (basis or "").strip().lower()
    if key not in RATE_DATE_BASES:
        raise ValueError(f"rate_date_basis must be one of {list(RATE_DATE_BASES)}")
    return key


def _canonical_type(invoice_type: str) -> str:
    if is_valid_invoice_type(invoice_type):
        return normalize_invoice_type(invoice_type)
    return (invoice_type or "").strip().upper()


def get_rule(db: Session, tenant_id: UUID, invoice_type: str) -> FxDateRule | None:
    """Active rule row for the (canonical) invoice type, or ``None``."""
    return db.scalar(
        select(FxDateRule).where(
            FxDateRule.tenant_id == tenant_id,
            FxDateRule.invoice_type == _canonical_type(invoice_type),
            FxDateRule.active.is_(True),
        )
    )


def rule_applies(db: Session, tenant_id: UUID, invoice_type: str) -> bool:
    """True when an active rule row exists for this invoice type."""
    return get_rule(db, tenant_id, invoice_type) is not None


def effective_basis(db: Session, tenant_id: UUID, invoice_type: str) -> str:
    """Configured basis for the invoice type, else :data:`DEFAULT_RATE_DATE_BASIS`."""
    row = get_rule(db, tenant_id, invoice_type)
    return row.rate_date_basis if row else DEFAULT_RATE_DATE_BASIS


def pick_rate_date(basis: str, context: dict | None) -> date | None:
    """Map a basis onto a concrete date from a caller-supplied context dict.

    Accepts flexible keys (e.g. ``departure`` / ``departure_date``). Returns
    ``None`` when the context carries no date for the basis.
    """
    if not context:
        return None
    key = (basis or "").strip().lower()
    for name in _CONTEXT_KEYS.get(key, (key,)):
        if name in context and context[name] is not None:
            value = context[name]
            return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    return None


def upsert_rule(
    db: Session,
    tenant_id: UUID,
    invoice_type: str,
    rate_date_basis: str,
    active: bool = True,
) -> FxDateRule:
    """Create or update the tenant's rule for ``invoice_type`` (idempotent)."""
    basis = validate_rate_date_basis(rate_date_basis)
    if not is_valid_invoice_type(invoice_type):
        raise ValueError(f"Unknown invoice_type: {invoice_type!r}")
    code = normalize_invoice_type(invoice_type)
    row = db.scalar(
        select(FxDateRule).where(
            FxDateRule.tenant_id == tenant_id,
            FxDateRule.invoice_type == code,
        )
    )
    if row is None:
        row = FxDateRule(
            tenant_id=tenant_id,
            invoice_type=code,
            rate_date_basis=basis,
            active=active,
        )
        db.add(row)
    else:
        row.rate_date_basis = basis
        row.active = active
    return row


def resolve_fx_rate(
    db: Session,
    tenant_id: UUID,
    currency: str,
    base_ccy: str,
    *,
    invoice_type: str | None = None,
    context_date: date | None = None,
) -> Decimal | None:
    """FX rate converting 1 unit of ``currency`` into ``base_ccy``.

    When an active ``FxDateRule`` exists for ``invoice_type`` **and** a
    ``context_date`` is provided, the rate is taken as of that date (latest
    ``rate_date <= context_date``). Otherwise — including when no rule row
    exists — the historical default applies: the absolute latest rate.
    """
    if currency == base_ccy:
        return Decimal("1")
    as_of: date | None = None
    if invoice_type is not None and context_date is not None and rule_applies(db, tenant_id, invoice_type):
        as_of = context_date
    q = select(ExchangeRate).where(
        ExchangeRate.base_currency == currency,
        ExchangeRate.quote_currency == base_ccy,
        (ExchangeRate.tenant_id == tenant_id) | (ExchangeRate.tenant_id.is_(None)),
    )
    if as_of is not None:
        q = q.where(ExchangeRate.rate_date <= as_of)
    row = db.scalars(q.order_by(ExchangeRate.rate_date.desc()).limit(1)).first()
    return Decimal(str(row.rate)) if row else None
