"""Phase 4 — MariLink ship-shore communication models.

ShipTerminal: Ship-side terminal/device registration
ShipForm: Configurable form templates for ship reporting
ShipReport: Submitted report instances with review workflow
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ShipTerminal(Base):
    """Ship-side terminal registration.

    Tracks devices installed on vessels for MariLink communication.
    """

    __tablename__ = "ship_terminals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    vessel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vessels.id"), nullable=False, index=True
    )
    terminal_key: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True
    )  # unique device identifier
    device_info: Mapped[dict | None] = mapped_column(JSON)  # UA, OS, screen, etc.
    sw_version: Mapped[str | None] = mapped_column(String(32))  # PWA version
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_position: Mapped[dict | None] = mapped_column(JSON)  # {lat, lon, heading, speed}
    offline_queue_size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(
        String(16), default="active"
    )  # active | inactive | maintenance
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )


class ShipForm(Base):
    """Configurable form template for ship-side reporting.

    Admin defines form schema; ship crew fills and submits.
    """

    __tablename__ = "ship_forms"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    form_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # noon_report | bunker_report | rob_report | incident | arrival_notice | departure_report
    form_name: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_json: Mapped[dict] = mapped_column(JSON, default=dict)  # JSON Schema
    fields_json: Mapped[list | None] = mapped_column(JSON)  # ordered field definitions
    auto_import: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # auto-import into NoonReport/BunkerOrder on approval
    target_model: Mapped[str | None] = mapped_column(
        String(64)
    )  # noon_report | bunker_order | null
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )


class ShipReport(Base):
    """Submitted report instance from ship terminal.

    Supports review workflow: submitted → review → approved/rejected.
    On approval, auto-imports data into target model if configured.
    """

    __tablename__ = "ship_reports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    terminal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ship_terminals.id"), nullable=False, index=True
    )
    form_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ship_forms.id"), nullable=False
    )
    voyage_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("voyages.id"), index=True
    )
    form_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    report_ref: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )  # e.g. NR-20260923-001
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    submitted_by: Mapped[str] = mapped_column(String(128))  # ship user name/rank
    data_json: Mapped[dict] = mapped_column(JSON, default=dict)  # form field values
    position: Mapped[dict | None] = mapped_column(JSON)  # GPS at submission
    status: Mapped[str] = mapped_column(
        String(16), default="submitted"
    )  # submitted | review | approved | rejected
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str | None] = mapped_column(Text)
    imported_model: Mapped[str | None] = mapped_column(String(64))  # what was auto-imported
    imported_id: Mapped[uuid.UUID | None] = mapped_column(
        JSON
    )  # ID of imported record
    sync_status: Mapped[str] = mapped_column(
        String(16), default="synced"
    )  # synced | pending | conflict
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
