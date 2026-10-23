"""Time-charter (TCI/TCO) contract and hire-statement models."""

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
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base


class TimeCharterContract(Base):
    """Time-charter contract (TCI in / TCO out).

    Extends the generic Charter with TC-specific lifecycle fields.
    `charter_id` points to the parent Charter row that holds the commercial
    fixture (hire_per_day, delivery/redelivery ports, commission, etc.).
    """

    __tablename__ = "time_charter_contracts"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False
    )
    charter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("charters.id"), nullable=False
    )
    contract_type: Mapped[str] = mapped_column(
        String(8), nullable=False
    )  # tci | tco
    vessel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vessels.id"), nullable=False
    )
    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("counterparties.id"), nullable=False
    )
    delivery_port: Mapped[str | None] = mapped_column(Text)
    delivery_date: Mapped[date | None] = mapped_column(Date)
    redelivery_port: Mapped[str | None] = mapped_column(Text)
    redelivery_date: Mapped[date | None] = mapped_column(Date)
    hire_rate: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False
    )  # daily hire
    hire_currency: Mapped[str] = mapped_column(String(3), default="USD")
    payment_frequency: Mapped[str] = mapped_column(
        String(16), default="monthly"
    )  # monthly | semi_monthly
    cancel_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        String(16), default="draft"
    )  # draft | active | completed | cancelled
    # Phase 5 TC depth — bareboat / sub-TC / profit share / commission
    contract_style: Mapped[str] = mapped_column(
        String(16), default="time_charter"
    )  # time_charter | bareboat
    parent_contract_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("time_charter_contracts.id")
    )  # sub-TC chain (head fixture re-let out)
    profit_share_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2)
    )  # owner's share of excess when no tiered rules
    profit_share_threshold: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2)
    )  # TCE threshold before profit share kicks in
    address_comm_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    brokerage_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    # 指数联动定价 — index-linked hire components (same spec as
    # Estimate.inputs["unpriced_components"], see services/unpriced_components.py).
    # Additive: null/empty → hire statements behave exactly as before.
    hire_components: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # ── P11 IMOS TC detail 对齐 — 头部标识 / 期限 / 交还船 / 右栏 ──
    tc_code: Mapped[str | None] = mapped_column(Text, index=True)  # VESSEL-I#### / -O####，租户内唯一
    beneficiary: Mapped[str | None] = mapped_column(Text)
    date_fixed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fixed_by: Mapped[str | None] = mapped_column(Text)
    company_code: Mapped[str | None] = mapped_column(String(16))
    department: Mapped[str | None] = mapped_column(Text)
    trade_area: Mapped[str | None] = mapped_column(String(32))
    ref_no: Mapped[str | None] = mapped_column(Text)
    payment_terms: Mapped[str | None] = mapped_column(Text)
    contract_form: Mapped[str | None] = mapped_column(Text)  # TRIP TC / TCT / Bareboat ...
    laycan_from_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    laycan_to_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Duration block（Min/Max -Days +Days E/L Redel.）
    duration_min_days: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    duration_max_days: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    duration_minus_days: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    duration_plus_days: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    el_redel_min: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    el_redel_max: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_basis: Mapped[str | None] = mapped_column(String(32))  # Custom / Laycan / ...
    use_local_time: Mapped[bool] = mapped_column(Boolean, default=False)
    # 计费与账务（IMOS header 右列）
    billing_period: Mapped[str | None] = mapped_column(String(32))  # EVERY 15 DAYS / MONTHLY ...
    billing_schedule: Mapped[str | None] = mapped_column(String(32))  # IN ADVANCE / IN ARREARS
    rebillable_admin_fee_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 6), default=Decimal("1"))
    ref_contract: Mapped[str | None] = mapped_column(Text)
    chtr_specialist: Mapped[str | None] = mapped_column(Text)
    conf_date_gmt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    intercompany: Mapped[bool] = mapped_column(Boolean, default=False)
    ic_company: Mapped[str | None] = mapped_column(Text)
    ic_adj_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    # 右栏 Summary
    next_open_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner_comm_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    owner_comm_pay_to: Mapped[str | None] = mapped_column(Text)
    valuation_id: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)
    notes_to_operations: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProfitShareRule(Base):
    """Tiered profit-share rule（利润分成阶梯）.

    ``tier_from`` / ``tier_to`` bound the TCE band (null ``tier_to`` = unlimited);
    ``share_pct`` is the owner's share of the excess inside the band;
    ``basis`` records what the excess is measured on: tce|revenue|profit.
    """

    __tablename__ = "profit_share_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    tc_contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("time_charter_contracts.id"), nullable=False, index=True
    )
    tier_from: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tier_to: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    share_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    basis: Mapped[str] = mapped_column(String(16), default="tce")  # tce|revenue|profit
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BrokerRule(Base):
    """Broker / address commission rule per TC contract (经纪/地址佣金规则)."""

    __tablename__ = "broker_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    tc_contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("time_charter_contracts.id"), nullable=False, index=True
    )
    broker_party_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("counterparties.id"), nullable=False
    )
    commission_type: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # brokerage|address
    commission_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    applies_to: Mapped[str] = mapped_column(
        String(16), default="all"
    )  # hire|off_hire|all
    # ── P11 IMOS Broker grid 列 ──
    payment_method: Mapped[str] = mapped_column(
        String(24), default="pay_directly"
    )  # pay_directly|deduct_from_hire
    m_method: Mapped[int] = mapped_column(Integer, default=0)  # IMOS "M" 列（计佣口径）
    from_gmt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    to_gmt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remarks: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class HireBillingSchedule(Base):
    """Planned hire billing per period (应收租金计划)."""

    __tablename__ = "hire_billing_schedules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    tc_contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("time_charter_contracts.id"), nullable=False, index=True
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="draft"
    )  # draft|invoiced|paid|overdue
    hire_statement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("hire_statements.id")
    )
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoices.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class HirePaymentSchedule(Base):
    """Planned hire payments (应付租金计划)."""

    __tablename__ = "hire_payment_schedules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    tc_contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("time_charter_contracts.id"), nullable=False, index=True
    )
    billing_schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("hire_billing_schedules.id")
    )
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(
        String(16), default="scheduled"
    )  # scheduled|paid|late|cancelled
    payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class HireStatement(Base):
    """Periodic hire statement (invoice equivalent for TC contracts).

    Each statement covers a billing period and itemises gross hire,
    off-hire deductions, bunker adjustments and other corrections.
    """

    __tablename__ = "hire_statements"
    __table_args__ = (
        UniqueConstraint("tenant_id", "statement_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("time_charter_contracts.id"), nullable=False
    )
    statement_number: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    hire_days: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=0
    )
    off_hire_days: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=0
    )
    gross_hire: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=0
    )
    off_hire_deduction: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=0
    )
    bunker_adjustment: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=0
    )
    other_adjustments: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=0
    )
    net_hire: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=0
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(
        String(16), default="draft"
    )  # draft | sent | approved | paid | void
    breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class HireSurvey(Base):
    """On/Off-hire survey（交船/还船检验，D13）。

    关键在交还船时点的船况与存油（bunker last word），与还船油价差结算、
    off-hire 扣减联动。``kind``: on_hire = 交船检验, off_hire = 还船检验。
    """

    __tablename__ = "hire_surveys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    charter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("charters.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # on_hire|off_hire
    surveyed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    port_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ports.id"))
    bunker_fo: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    bunker_do: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
