"""Phase 6 COA (Contract of Affreightment) models — COA 一等公民.

A COA contract hangs off a parent Charter (``charter_id``) and is fulfilled
through a sequence of itineraries (each a planned lifting leg). Liftings
(``CoaLifting`` in ``models_domain``) are allocated against itineraries via
``CoaAllocation``; ``CoaItinerary.allocated_qty`` is maintained as the running
sum so allocation vs contracted qty is one query away.

Multi-tenant: every table carries ``tenant_id``; the contract header uses the
``deleted_at`` soft-delete convention (see ``app.services.tenant_guard``).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
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

# rate_basis: how the COA freight is priced
COA_RATE_BASES = ("per_voyage", "per_mt", "lumpsum")
COA_QTY_UNITS = ("mt", "bbl")
COA_STATUSES = ("draft", "active", "completed", "cancelled")


class CoaContract(Base):
    """COA 合同头：总量、执行窗口、计价方式（per_voyage / per_mt / lumpsum）。"""

    __tablename__ = "coa_contracts"
    __table_args__ = (UniqueConstraint("tenant_id", "coa_no"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    coa_no: Mapped[str] = mapped_column(Text, nullable=False)  # doc number COA-YYYY-NNNNN
    charter_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("charters.id"), nullable=False, index=True)
    total_qty: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
    qty_unit: Mapped[str] = mapped_column(String(8), default="mt", nullable=False)  # mt | bbl
    period_from: Mapped[date] = mapped_column(Date, nullable=False)
    period_to: Mapped[date] = mapped_column(Date, nullable=False)
    rate_basis: Mapped[str] = mapped_column(String(16), default="per_voyage", nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    cargo_spec: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)  # draft|active|completed|cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CoaItinerary(Base):
    """COA 航次计划行（分单）：一票货 / 一个装-卸窗口；``allocated_qty`` 为已分摊合计。"""

    __tablename__ = "coa_itineraries"
    __table_args__ = (UniqueConstraint("coa_contract_id", "seq"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    coa_contract_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("coa_contracts.id"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    load_port_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ports.id"))
    disch_port_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ports.id"))
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
    allocated_qty: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=Decimal("0"), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CoaAllocation(Base):
    """分摊记录：一票 CoaLifting 指派到一行 CoaItinerary（每票只分摊一次）。"""

    __tablename__ = "coa_allocations"
    __table_args__ = (UniqueConstraint("lifting_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    coa_contract_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("coa_contracts.id"), nullable=False, index=True
    )
    itinerary_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("coa_itineraries.id"), nullable=False, index=True
    )
    lifting_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("coa_liftings.id"), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
