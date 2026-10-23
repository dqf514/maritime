"""Voyage workspace extension models — 航次工作台补充表.

Covers the P2 voyage-workspace gaps the frontend already calls:
notes（航次备注）、instructions（航次指示/申明）. Activity log is derived at
read time from port calls / SOF / off-hire / these tables (no extra table).
Rows are tenant-scoped and hung off ``voyages.id``; soft delete follows the
``deleted_at`` convention (see ``app.services.recycle``).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class VoyageNote(Base):
    """Free-form voyage note (workspace → Notes tab)."""

    __tablename__ = "voyage_notes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    voyage_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("voyages.id"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    note_date: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 软删（recycle 约定）


class VoyageInstruction(Base):
    """Voyage instruction / statement (workspace → Instructions tab)."""

    __tablename__ = "voyage_instructions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    voyage_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("voyages.id"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    note_date: Mapped[date | None] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(Text, default="general")  # general|owner|charterer|agent
    ack: Mapped[bool] = mapped_column(default=False)  # 船端/执行方已确认
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 软删（recycle 约定）
