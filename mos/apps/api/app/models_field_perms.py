"""Field-level permissions (字段级权限).

FieldPermission — per-tenant role×entity×field access mode (read|write|hidden).
One row per (tenant_id, entity, field, role); uniqueness is enforced in
app/services/field_perms.py (and mirrored by a DB unique constraint).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, Uuid, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class FieldPermission(Base):
    __tablename__ = "field_permissions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "entity", "field", "role", name="uq_field_perm_tenant_entity_field_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    entity: Mapped[str] = mapped_column(Text, nullable=False)  # e.g. counterparty | invoice | vessel
    field: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, default="read", nullable=False)  # read | write | hidden
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
