"""Security audit trail — append-only log of auth-sensitive events."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AuditLog(Base):
    """One row per security-relevant event (login, token issue, password change,
    user lifecycle, role changes).

    tenant_id / actor_user_id are nullable: some events happen before a tenant
    or user is resolved (e.g. login with an unknown tenant code).
    Rows are never updated or deleted by application code.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    action: Mapped[str] = mapped_column(Text, index=True)  # e.g. auth.login_success
    entity_type: Mapped[str | None] = mapped_column(Text)  # e.g. user / tenant
    entity_id: Mapped[str | None] = mapped_column(Text)  # str: not all entities use UUID keys
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
