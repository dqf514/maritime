"""Phase 3 货盘 (cargo) 主档 — 商业货盘实体, 供集中排程 (scheduling) 使用."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
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


class Cargo(Base):
    __tablename__ = "cargoes"
    __table_args__ = (UniqueConstraint("tenant_id", "cargo_no"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    cargo_no: Mapped[str] = mapped_column(Text, nullable=False)  # 单号 doc number CGO-YYYY-NNNNN
    cargo_type: Mapped[str | None] = mapped_column(String(32))  # bulk|liquid|dry
    commodity: Mapped[str | None] = mapped_column(Text)
    qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    qty_unit: Mapped[str | None] = mapped_column(String(8))  # mt|bbl
    load_port_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ports.id"))
    disch_port_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ports.id"))
    laycan_from: Mapped[date | None] = mapped_column(Date)
    laycan_to: Mapped[date | None] = mapped_column(Date)
    charterer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("counterparties.id"))
    freight_basis: Mapped[str | None] = mapped_column(String(16))  # per_mt|lumpsum|worldscale
    freight_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|booked|nominated|fixed|completed|cancelled
    voyage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("voyages.id"))
    charter_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("charters.id"))
    coa_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # COA reference (no dedicated table)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
