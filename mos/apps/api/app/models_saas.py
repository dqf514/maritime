"""SaaS platform: plans, subscriptions, usage metering, payments, org, workflows."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    Uuid,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SaaSPlan(Base):
    """Developer-defined commercial plans (like Feishu seats + AI packs)."""

    __tablename__ = "saas_plans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    billing_period: Mapped[str] = mapped_column(Text, default="monthly")  # monthly|yearly
    price_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    included_modules: Mapped[dict] = mapped_column(JSON, default=dict)  # {module: true}
    included_quotas: Mapped[dict] = mapped_column(JSON, default=dict)  # {ai.tokens: 1e6, ...}
    seat_limit: Mapped[int | None] = mapped_column(default=None)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(Text, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UsageMeterDef(Base):
    __tablename__ = "usage_meter_defs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # ai.tokens, api.calls, storage.gb
    name: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, default="count")
    description: Mapped[str | None] = mapped_column(Text)
    overage_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")


class UsagePack(Base):
    """Prepaid top-up packs (AI calls etc.)."""

    __tablename__ = "usage_packs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    meter_code: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    price_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(Text, default="active")


class TenantSubscription(Base):
    __tablename__ = "tenant_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("saas_plans.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, default="trialing")  # trialing|active|past_due|cancelled
    started_on: Mapped[date] = mapped_column(Date, nullable=False)
    current_period_end: Mapped[date | None] = mapped_column(Date)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantWallet(Base):
    __tablename__ = "tenant_wallets"
    __table_args__ = (UniqueConstraint("tenant_id", "meter_code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    meter_code: Mapped[str] = mapped_column(Text, nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    reserved: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UsageLedger(Base):
    __tablename__ = "usage_ledger"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    meter_code: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    direction: Mapped[str] = mapped_column(Text, default="consume")  # consume|credit|adjust
    ref_type: Mapped[str | None] = mapped_column(Text)
    ref_id: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))


class PaymentProvider(Base):
    __tablename__ = "payment_providers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # stripe|alipay|wechat|manual
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="adapter_pending")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    secret_ref: Mapped[str | None] = mapped_column(Text)


class PaymentOrder(Base):
    __tablename__ = "payment_orders"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    provider_code: Mapped[str] = mapped_column(Text, default="manual")
    purpose: Mapped[str] = mapped_column(Text, nullable=False)  # subscription|usage_pack
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(Text, default="pending")  # pending|paid|failed|cancelled
    ref_type: Mapped[str | None] = mapped_column(Text)
    ref_id: Mapped[str | None] = mapped_column(Text)
    checkout_url: Mapped[str | None] = mapped_column(Text)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlatformAiEndpoint(Base):
    """Developer-managed AI gateway endpoints (tenant consumes via quota)."""

    __tablename__ = "platform_ai_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    provider_type: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text)
    model_default: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active")
    meter_code: Mapped[str] = mapped_column(Text, default="ai.tokens")
    tokens_per_call_est: Mapped[int] = mapped_column(default=1000)
    config: Mapped[dict] = mapped_column(JSON, default=dict)


class TenantCompanyProfile(Base):
    __tablename__ = "tenant_company_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), unique=True, nullable=False)
    legal_name: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    logo_url: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(Text)
    tax_no: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    brand_primary: Mapped[str | None] = mapped_column(Text, default="#1A9B96")
    brand_secondary: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrgUnit(Base):
    __tablename__ = "org_units"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("org_units.id"))
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    unit_type: Mapped[str] = mapped_column(Text, default="dept")  # company|dept|team
    manager_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(Text, default="active")


class FeaturePermission(Base):
    """Fine-grained feature flags per role (tenant scoped)."""

    __tablename__ = "feature_permissions"
    __table_args__ = (UniqueConstraint("tenant_id", "role_code", "feature_code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    role_code: Mapped[str] = mapped_column(Text, nullable=False)
    feature_code: Mapped[str] = mapped_column(Text, nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, default=True)


class UserOrgMembership(Base):
    __tablename__ = "user_org_memberships"
    __table_args__ = (UniqueConstraint("user_id", "org_unit_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    org_unit_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("org_units.id"), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)


class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)  # charter|invoice|pda|claim
    trigger_on: Mapped[str] = mapped_column(Text, default="submit")  # submit|manual
    steps: Mapped[dict] = mapped_column(JSON, default=dict)  # [{name, role_code, action}]
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class WorkflowInstance(Base):
    __tablename__ = "workflow_instances"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    definition_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("workflow_definitions.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="running")  # running|approved|rejected|cancelled
    current_step: Mapped[int] = mapped_column(default=0)
    history: Mapped[dict] = mapped_column(JSON, default=dict)
    started_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class PlatformBranding(Base):
    """Developer product brand shown on public portal / login / favicon."""

    __tablename__ = "platform_branding"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    product_name: Mapped[str] = mapped_column(Text, default="VoyageOS")
    tagline: Mapped[str] = mapped_column(Text, default="Maritime commercial operating system")
    logo_url: Mapped[str] = mapped_column(Text, default="/branding/logo.svg")
    icon_url: Mapped[str] = mapped_column(Text, default="/branding/mark.svg")
    favicon_url: Mapped[str] = mapped_column(Text, default="/branding/mark.svg")
    primary_color: Mapped[str] = mapped_column(Text, default="#1A9B96")
    hero_title: Mapped[str] = mapped_column(Text, default="One OS for the commercial voyage lifecycle")
    hero_subtitle: Mapped[str] = mapped_column(
        Text,
        default="From estimate and fixture to operations, laytime, finance and twin — with SaaS control plane built in.",
    )
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
