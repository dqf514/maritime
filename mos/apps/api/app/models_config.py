"""Phase 3 — Configurable Intelligence Layer models.

ConfigFlag: System/tenant/user configuration flags with caching
BusinessRuleDefinition: Enhanced business rules engine
AlertRule + TaskRule: Alert and task automation
UdfDefinition + UdfValue: User-defined fields
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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ConfigFlag(Base):
    """System configuration flag with multi-scope support.

    Scope hierarchy: platform < tenant < user (user overrides tenant overrides platform)
    """

    __tablename__ = "config_flags"
    __table_args__ = (
        UniqueConstraint("scope_key", "flag_key", name="uq_config_flag_scope_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), index=True
    )
    scope_key: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )  # "platform" | tenant UUID | user UUID
    flag_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    flag_value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="string"
    )  # bool | number | string | json
    category: Mapped[str] = mapped_column(
        String(64), nullable=False, default="general", index=True
    )  # financials | operations | bunkering | emissions | general
    description: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )


class BusinessRuleDefinition(Base):
    """Enhanced business rule definition.

    Rule types:
    - pnl_mapping: Expense → GL account mapping
    - commission: Commission calculation rules
    - approval: Approval hierarchy rules
    - validation: Data validation rules
    - notification: Notification trigger rules
    - pricing: Pricing strategy rules
    """

    __tablename__ = "business_rule_definitions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    rule_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )  # pnl_mapping | commission | approval | validation | notification | pricing
    entity_type: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # voyage | charter | invoice | vessel | estimate
    priority: Mapped[int] = mapped_column(Integer, default=100)
    condition_json: Mapped[dict] = mapped_column(JSON, default=dict)
    action_json: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )


class ConfigAlertRule(Base):
    """Alert/reminder rule definition.

    Triggers automated alerts based on conditions.
    """

    __tablename__ = "config_alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # invoice | voyage | vessel | certificate
    condition_json: Mapped[dict] = mapped_column(JSON, default=dict)
    alert_message: Mapped[str] = mapped_column(Text, nullable=False)
    alert_priority: Mapped[str] = mapped_column(
        String(16), default="normal"
    )  # low | normal | high | urgent
    frequency_days: Mapped[int | None] = mapped_column(Integer)  # repeat every N days
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )


class TaskRule(Base):
    """Task automation rule.

    Automatically creates tasks based on conditions.
    """

    __tablename__ = "task_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    trigger_entity_type: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # voyage | charter | invoice
    trigger_condition: Mapped[dict] = mapped_column(JSON, default=dict)
    task_title: Mapped[str] = mapped_column(String(256), nullable=False)
    task_description: Mapped[str | None] = mapped_column(Text)
    assign_to_role: Mapped[str | None] = mapped_column(String(64))
    due_days_offset: Mapped[int | None] = mapped_column(Integer)  # days from trigger
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )


class UdfDefinition(Base):
    """User-defined field definition.

    Allows tenants to add custom fields to standard entities.
    """

    __tablename__ = "udf_definitions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "entity_type", "field_key", name="uq_udf_def_entity_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )  # voyage | charter | invoice | vessel
    field_key: Mapped[str] = mapped_column(String(64), nullable=False)
    field_label: Mapped[str] = mapped_column(String(128), nullable=False)
    field_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="string"
    )  # string | number | date | boolean | select
    options_json: Mapped[dict | None] = mapped_column(JSON)  # for select type
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    default_value: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )


class UdfValue(Base):
    """User-defined field value.

    Stores actual values for UDF fields on entities.
    """

    __tablename__ = "udf_values"
    __table_args__ = (
        UniqueConstraint(
            "definition_id", "entity_id", name="uq_udf_value_def_entity"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("udf_definitions.id"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    field_value: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
