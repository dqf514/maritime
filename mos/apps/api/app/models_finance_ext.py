"""Finance-extension models: credit notes, risk limits, sanctions audit, off-hire.

Finance depth (Phase 6) additions: rebill invoices (代垫转开), commission
records (8 佣金类型), payment terms/methods/bank accounts, advance
payments/receipts with allocations.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CreditNote(Base):
    """红冲 credit note against an invoice (status: draft|issued|void)."""

    __tablename__ = "credit_notes"
    __table_args__ = (UniqueConstraint("tenant_id", "credit_note_no"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("invoices.id"), nullable=False)
    credit_note_no: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RiskLimit(Base):
    """VaR limit per scope. scope: "global" | "symbol:<SYMBOL>" | "counterparty:<key>"."""

    __tablename__ = "risk_limits"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    limit_type: Mapped[str] = mapped_column(String(16), default="var_1d")
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SanctionsScreening(Base):
    """Audit row written on every sanctions assertion."""

    __tablename__ = "sanctions_screenings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    screened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    provider: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(16), default="clear")


class BunkerInquiry(Base):
    """Supplier quote collected for a bunker order (询比价).

    status: quoted|accepted|rejected. Accepting an inquiry writes its price and
    supplier back onto the order and rejects the remaining quotes. Index-priced
    orders also record an accepted inquiry row (supplier "INDEX:<symbol>") so
    the pricing source stays auditable.
    """

    __tablename__ = "bunker_inquiries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("bunker_orders.id"), nullable=False)
    supplier: Mapped[str | None] = mapped_column(String(128))
    quoted_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    quoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(16), default="quoted")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class RebillInvoice(Base):
    """转开/代垫发票 — expense incurred for a counterparty, rebilled onward.

    ``over_cap`` is derived on write: True when ``cap_amount`` is set and
    ``amount`` exceeds it (超额度转开告警).
    """

    __tablename__ = "rebill_invoices"
    __table_args__ = (UniqueConstraint("tenant_id", "rebill_no"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    rebill_no: Mapped[str] = mapped_column(Text, nullable=False)
    source_invoice_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("invoices.id"))
    source_expense_type: Mapped[str] = mapped_column(String(32), default="other")  # port_expense|bunker|other
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("counterparties.id"))
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(Text, default="draft")  # draft|sent|paid|cancelled
    over_cap: Mapped[bool] = mapped_column(Boolean, default=False)
    cap_amount: Mapped[float | None] = mapped_column(Numeric(18, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CommissionType(Base):
    """佣金明细 — one row per calculated commission.

    ``commission_type`` covers the 8 maritime commission kinds:
    address_commission | brokerage | demurrage_commission | claim_commission |
    freight_relet_commission | owner_commission | bareboat_commission |
    equipment_commission.
    """

    __tablename__ = "commission_types"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    commission_type: Mapped[str] = mapped_column(String(32), nullable=False)
    base_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    rate_pct: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False)
    calculated_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("invoices.id"))
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("counterparties.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaymentTerm(Base):
    """付款条件 — Net 30 / Net 60 / COD … with early-discount window."""

    __tablename__ = "payment_terms"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    discount_pct: Mapped[float | None] = mapped_column(Numeric(8, 4))
    discount_days: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaymentMethod(Base):
    """付款方式 — T/T, L/C, D/P …"""

    __tablename__ = "payment_methods"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BankAccount(Base):
    """银行账户 — own or counterparty bank details used on payment instructions."""

    __tablename__ = "bank_accounts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    bank_name: Mapped[str] = mapped_column(Text, nullable=False)
    account_name: Mapped[str] = mapped_column(Text, nullable=False)
    account_number: Mapped[str] = mapped_column(Text, nullable=False)
    swift_code: Mapped[str | None] = mapped_column(String(16))
    iban: Mapped[str | None] = mapped_column(String(34))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("counterparties.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AdvancePayment(Base):
    """预收/预付 — money moved ahead of invoice settlement.

    ``direction``: payment (预付) | receipt (预收). ``status`` tracks how much
    of ``amount`` has been allocated to invoices.
    """

    __tablename__ = "advance_payments"
    __table_args__ = (UniqueConstraint("tenant_id", "advance_no"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    advance_no: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False, default="payment")  # payment|receipt
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("counterparties.id"))
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    allocated_amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    status: Mapped[str] = mapped_column(Text, default="unallocated")  # unallocated|partially_allocated|fully_allocated
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AdvanceAllocation(Base):
    """预收/预付核销 — allocation of an advance against a concrete invoice."""

    __tablename__ = "advance_allocations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    advance_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("advance_payments.id"), nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("invoices.id"), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# OffHireEvent is canonically defined in app.models_domain (P0 commercial contract:
# includes voyage_id + status open/closed). Re-exported here so existing
# `from app.models_finance_ext import OffHireEvent` imports keep working.
from app.models_domain import OffHireEvent  # noqa: F401
