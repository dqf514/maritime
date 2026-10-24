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

    **防篡改哈希链**（P1-19）：每一行带 ``prev_hash``（同一租户上一行的
    ``row_hash``）与 ``row_hash``（本行内容 + prev_hash 的 sha256）。改动
    任何一行（哪怕改完再把哈希改回去）都会让链断掉 —— ``services/audit.py``
    的 ``verify_chain`` 能指出断在第几行。链是**按租户**串的（跨租户不串）。
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
    #: 同一租户上一行的 row_hash（链首行为空串）
    prev_hash: Mapped[str | None] = mapped_column(Text)
    #: 本行的内容哈希（sha256）
    row_hash: Mapped[str | None] = mapped_column(Text, index=True)
