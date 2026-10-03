"""Phase 6/8 — Report engine models.

ReportDefinition: Configurable report definitions (system presets + custom)
ReportSchedule: Automated report scheduling with email delivery

Phase 8 (Report Designer): declarative query-spec metadata —
ReportDataset: catalog of queryable datasets (entity → base table + fields)
ReportJoin: saved join graph of a declarative report (query_spec v2)
ReportField: saved field list of a declarative report (query_spec v2)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    text,
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
    # Phase 8 declarative query spec (spec_version == "v2"); None for legacy reports
    query_spec: Mapped[dict | None] = mapped_column(JSON, default=dict)
    spec_version: Mapped[str | None] = mapped_column(String(16))
    template: Mapped[str | None] = mapped_column(String(64))  # excel | pdf | csv | html
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
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
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )


class ReportDataset(Base):
    """Queryable dataset catalog for the Report Designer (global, seeded).

    ``entity`` is the logical key used inside query specs (voyages, invoices, ...);
    ``base_table`` is the physical table name. ``fields`` carries display metadata
    for the designer: [{name, type, label, table_alias}].
    """

    __tablename__ = "report_datasets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)  # display name
    entity: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    base_table: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    fields: Mapped[dict | None] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )


class ReportJoin(Base):
    """Join edge of a declarative report (mirrors query_spec["joins"])."""

    __tablename__ = "report_joins"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    report_definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("report_definitions.id"), nullable=False, index=True
    )
    left_dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("report_datasets.id"), nullable=False
    )
    right_dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("report_datasets.id"), nullable=False
    )
    join_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="left"
    )  # inner|left|right
    left_field: Mapped[str] = mapped_column(String(128), nullable=False)
    right_field: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )


class ReportField(Base):
    """Selected field of a declarative report (mirrors query_spec["fields"])."""

    __tablename__ = "report_fields"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    report_definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("report_definitions.id"), nullable=False, index=True
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("report_datasets.id"), nullable=False
    )
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    expression: Mapped[str | None] = mapped_column(Text)  # e.g. "qty * price"
    agg: Mapped[str | None] = mapped_column(String(16))  # sum|avg|count|min|max
    format: Mapped[str | None] = mapped_column(String(16))  # number|date|currency
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )
