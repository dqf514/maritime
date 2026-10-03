"""Phase 4 rate tables — 运价/费率表与定价模板.

Generic dimension-keyed rate storage backing commercial pricing:
freight matrices (load/disch port), surcharges, demurrage / laytime rates
and bunker surcharges. Lookup semantics live in ``app.services.rates``
(dimension specificity cascade); templates bind several tables into one
pricing recipe for an estimate.

Multi-tenant: every table carries ``tenant_id``; parents use the
``deleted_at`` soft-delete convention (see ``app.services.tenant_guard``).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


# Rate table kinds — kept as free strings (String(32)) for tenant extensibility,
# validated at the router layer against this set.
RATE_TABLE_KINDS = (
    "freight_matrix",
    "surcharge",
    "demurrage_rate",
    "laytime_hours_rate",
    "bunker_surcharge",
)

RATE_UNITS = ("per_mt", "lumpsum", "per_day", "per_hour", "pct")


class RateTable(Base):
    """费率表头：kind 决定 dims 语义与 lookup 用法。"""

    __tablename__ = "rate_tables"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RateTableRow(Base):
    """费率行：dims 为维度键值对 (load_port/disch_port/cargo_type/...)，
    lookup 时按维度匹配数 (更具体优先) + priority 决定胜出行。"""

    __tablename__ = "rate_table_rows"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    rate_table_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("rate_tables.id"), nullable=False, index=True
    )
    dims: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(16))  # per_mt / lumpsum / per_day / ...
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # higher wins ties
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PricingTemplate(Base):
    """定价模板：把多张费率表绑成一套报价配方 (freight + surcharge + demurrage...)。"""

    __tablename__ = "pricing_templates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # {freight: <table_id>, surcharge: <table_id>, demurrage: <table_id>, ...}
    rate_table_refs: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    rules: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # pricing rules
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
