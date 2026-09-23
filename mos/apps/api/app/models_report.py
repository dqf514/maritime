"""Phase 6 — Report engine models.

ReportDefinition: Configurable report definitions (system presets + custom)
ReportSchedule: Automated report scheduling with email delivery
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
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ReportDefinition(Base):
    """Configurable report definition.

    data_source types:
    - preset: Built-in report (voyage_pnl, bunker, tce_analysis, etc.)
    - sql: Custom SQL query
    - api: Data sourced from API endpoint
    """

    __tablename__ = "report_definitions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    report_name: Mapped[str] = mapped_column(String(128), nullable=False)
    report_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )  # voyage_pnl | bunker | tce_analysis | fleet_performance | counterparty | age_days | speed | custom
    data_source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="preset"
    )  # preset | sql | api
    query: Mapped[str | None] = mapped_column(Text)  # SQL or preset dataset name
    parameters: Mapped[dict | None] = mapped_column(JSON, default=dict)
    columns: Mapped[dict | None] = mapped_column(JSON, default=dict)
    filters: Mapped[dict | None] = mapped_column(JSON, default=list)
    sort: Mapped[dict | None] = mapped_column(JSON, default=list)
    template: Mapped[str | None] = mapped_column(String(64))  # excel | pdf | csv | html
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )


class ReportSchedule(Base):
    """Automated report schedule with email delivery."""

    __tablename__ = "report_schedules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("report_definitions.id"), nullable=False, index=True
    )
    schedule_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="on_demand"
    )  # daily | weekly | monthly | on_demand
    cron_expression: Mapped[str | None] = mapped_column(String(64))
    recipients: Mapped[dict | None] = mapped_column(JSON, default=list)
    output_format: Mapped[str] = mapped_column(
        String(16), nullable=False, default="excel"
    )  # excel | pdf | csv
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
