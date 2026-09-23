"""Time-charter (TCI/TCO) contract and hire-statement models."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base


class TimeCharterContract(Base):
    """Time-charter contract (TCI in / TCO out).

    Extends the generic Charter with TC-specific lifecycle fields.
    `charter_id` points to the parent Charter row that holds the commercial
    fixture (hire_per_day, delivery/redelivery ports, commission, etc.).
    """

    __tablename__ = "time_charter_contracts"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False
    )
    charter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("charters.id"), nullable=False
    )
    contract_type: Mapped[str] = mapped_column(
        String(8), nullable=False
    )  # tci | tco
    vessel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vessels.id"), nullable=False
    )
    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("counterparties.id"), nullable=False
    )
    delivery_port: Mapped[str | None] = mapped_column(Text)
    delivery_date: Mapped[date | None] = mapped_column(Date)
    redelivery_port: Mapped[str | None] = mapped_column(Text)
    redelivery_date: Mapped[date | None] = mapped_column(Date)
    hire_rate: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False
    )  # daily hire
    hire_currency: Mapped[str] = mapped_column(String(3), default="USD")
    payment_frequency: Mapped[str] = mapped_column(
        String(16), default="monthly"
    )  # monthly | semi_monthly
    cancel_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        String(16), default="draft"
    )  # draft | active | completed | cancelled
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class HireStatement(Base):
    """Periodic hire statement (invoice equivalent for TC contracts).

    Each statement covers a billing period and itemises gross hire,
    off-hire deductions, bunker adjustments and other corrections.
    """

    __tablename__ = "hire_statements"
    __table_args__ = (
        UniqueConstraint("tenant_id", "statement_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("time_charter_contracts.id"), nullable=False
    )
    statement_number: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    hire_days: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=0
    )
    off_hire_days: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=0
    )
    gross_hire: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=0
    )
    off_hire_deduction: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=0
    )
    bunker_adjustment: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=0
    )
    other_adjustments: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=0
    )
    net_hire: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=0
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(
        String(16), default="draft"
    )  # draft | sent | approved | paid | void
    breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
