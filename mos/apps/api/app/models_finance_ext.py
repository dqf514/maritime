"""Finance-extension models: credit notes, risk limits, sanctions audit, off-hire."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
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


# OffHireEvent is canonically defined in app.models_domain (P0 commercial contract:
# includes voyage_id + status open/closed). Re-exported here so existing
# `from app.models_finance_ext import OffHireEvent` imports keep working.
from app.models_domain import OffHireEvent  # noqa: F401
