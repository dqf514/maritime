"""池业务纵深模型 — 管理费/管理费率与按期分摊明细。

PoolFee: 池层面的管理费/管理费（pct 或 fixed），按 fee_type 各保留一条生效记录
PoolDistribution: 某结算期内每条船的分摊明细（points → gross/fee_deduction/net）
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PoolFee(Base):
    __tablename__ = "pool_fees"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    pool_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("pools.id"), nullable=False, index=True)
    fee_type: Mapped[str] = mapped_column(String(16), nullable=False)  # management | admin
    fee_basis: Mapped[str] = mapped_column(String(8), nullable=False, default="pct")  # pct | fixed
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    active: Mapped[bool] = mapped_column(default=True)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PoolDistribution(Base):
    __tablename__ = "pool_distributions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    period_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("pool_periods.id"), nullable=False, index=True)
    vessel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vessels.id"), nullable=False, index=True)
    points: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0)
    gross_share: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    fee_deduction: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    net_share: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    paid_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | paid
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
