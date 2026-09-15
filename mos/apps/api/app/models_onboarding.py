"""New-user onboarding checklist state (per-user dismiss flag)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class OnboardingState(Base):
    __tablename__ = "onboarding_states"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
