"""Platform ops: datastore bindings, deployment profiles, init wizard, monitoring."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TenantDatastoreBinding(Base):
    """Per-tenant datastore binding. Runtime still defaults to the primary engine;
    this table + resolver reserve multi-engine routing without switching yet.
    """

    __tablename__ = "tenant_datastore_bindings"
    __table_args__ = (UniqueConstraint("tenant_id", "purpose"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, default="primary")  # primary|analytics|archive
    engine: Mapped[str] = mapped_column(Text, nullable=False)  # sqlite|postgres|mysql|cloud_rds
    host_mode: Mapped[str] = mapped_column(Text, default="local")  # local|server|cloud
    cloud_provider: Mapped[str | None] = mapped_column(Text)  # aliyun|aws|azure|tencent|huawei|none
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    # Encrypted connection URL (never return raw to clients)
    connection_cipher: Mapped[str] = mapped_column(Text, nullable=False)
    connection_hint: Mapped[str] = mapped_column(Text, default="")  # masked / redacted preview
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(Text, default="draft")  # draft|verified|active|disabled
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_test_message: Mapped[str | None] = mapped_column(Text)
    routing_policy: Mapped[str] = mapped_column(Text, default="bind_only")  # bind_only|prefer_tenant|force_tenant
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PlatformDeploymentProfile(Base):
    """Reusable deployment templates (compose / single host / cloud VM)."""

    __tablename__ = "platform_deployment_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # docker_compose|single_host|cloud_vm
    cloud_provider: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    # Template payload: services, ports, env keys, resource hints, compose snippet refs
    template: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(Text, default="active")
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    last_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    apply_log: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SystemInitStep(Base):
    """Platform initialization wizard steps (schema / seed / verify)."""

    __tablename__ = "system_init_steps"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    action_kind: Mapped[str] = mapped_column(Text, nullable=False)  # ensure_schema|seed_catalog|seed_demo|verify_ready|custom
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(Text, default="pending")  # pending|running|done|failed|skipped
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_result: Mapped[dict] = mapped_column(JSON, default=dict)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MonitorMetric(Base):
    """Latest / historical monitor metric samples for the platform ops console."""

    __tablename__ = "monitor_metrics"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, default="system")  # system|database|app|resource
    unit: Mapped[str] = mapped_column(Text, default="")
    value: Mapped[float] = mapped_column(Numeric(18, 4), default=0)
    labels: Mapped[dict] = mapped_column(JSON, default=dict)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AlertRule(Base):
    """Alert rules evaluated against monitor snapshots."""

    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    metric_code: Mapped[str] = mapped_column(Text, nullable=False)
    operator: Mapped[str] = mapped_column(String(8), default="gt")  # gt|gte|lt|lte|eq
    threshold: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    severity: Mapped[str] = mapped_column(Text, default="warning")  # info|warning|critical
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    channels: Mapped[dict] = mapped_column(JSON, default=dict)  # {console: true, email: false}
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_state: Mapped[str] = mapped_column(Text, default="ok")  # ok|firing
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
