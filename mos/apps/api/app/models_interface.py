"""Interface Messages (IMOS Data Center 标配) — integration message log.

InterfaceMessage: one row per inbound/outbound integration exchange
(EDIFACT, nomination template, HTTP push/pull, file drop, …). The table is an
honest audit trail: payload is stored verbatim, status reflects the last known
processing result, retry bookkeeping is first-class.

There is no real external system behind this module yet — see
``app.services.interface_messages.process_message`` for the stub processor.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class InterfaceMessage(Base):
    """A single interface exchange, scoped to one tenant.

    direction:  inbound | outbound
    channel:    edifact | nom_template | http | file | …
    status:     pending | success | failed
    payload:    raw message body (JSON object for structured channels,
                plain string for EDIFACT/text payloads)
    """

    __tablename__ = "interface_messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    direction: Mapped[str] = mapped_column(String(16), nullable=False, default="inbound")
    channel: Mapped[str] = mapped_column(Text, nullable=False, default="http")
    interface_code: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    external_ref: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    payload: Mapped[dict | list | str | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
