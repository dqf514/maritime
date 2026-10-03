"""过驳/驳运业务模型（Lightering & Barging，最小可用）。

LighteringOp: 反向过驳 / FSO / STS 过驳作业
BargeOp: 驳船加油 / 过驳 / 转运作业
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LighteringOp(Base):
    __tablename__ = "lightering_ops"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    op_no: Mapped[str] = mapped_column(String(32), nullable=False)
    lightering_type: Mapped[str] = mapped_column(String(32), nullable=False)  # reverse_lightering|fso|stS
    vessel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vessels.id"), nullable=False, index=True)
    location: Mapped[str | None] = mapped_column(Text)
    qty_lightered: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    status: Mapped[str] = mapped_column(String(16), default="planned")  # planned|in_progress|completed|cancelled
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BargeOp(Base):
    __tablename__ = "barge_ops"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    op_no: Mapped[str] = mapped_column(String(32), nullable=False)
    barge_name: Mapped[str] = mapped_column(Text, nullable=False)
    barge_type: Mapped[str | None] = mapped_column(String(32))
    operation_type: Mapped[str] = mapped_column(String(16), nullable=False)  # bunkering|lightering|transport
    vessel_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vessels.id"), index=True)
    port_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ports.id"))
    qty: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    status: Mapped[str] = mapped_column(String(16), default="planned")  # planned|in_progress|completed|cancelled
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
