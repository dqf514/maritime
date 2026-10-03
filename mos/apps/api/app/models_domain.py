"""Wave 2–8 domain models (modular monolith)."""

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


class Estimate(Base):
    __tablename__ = "estimates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, default="voyage")  # voyage | tct
    vessel_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vessels.id"))
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("counterparties.id"))
    version: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(Text, default="draft")
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    results: Mapped[dict] = mapped_column(JSON, default=dict)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("estimates.id"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EstimateTemplate(Base):
    """估算模板：可复用 inputs（船舶/货种/航线锚点），from-template 一键起估算。"""

    __tablename__ = "estimate_templates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    template_name: Mapped[str] = mapped_column(Text, nullable=False)
    vessel_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vessels.id"))
    cargo_type: Mapped[str | None] = mapped_column(String(32))
    route_name: Mapped[str | None] = mapped_column(String(128))
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Charter(Base):
    __tablename__ = "charters"
    __table_args__ = (UniqueConstraint("tenant_id", "charter_no"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    charter_no: Mapped[str] = mapped_column(Text, nullable=False)
    charter_type: Mapped[str] = mapped_column(Text, default="voyage")
    status: Mapped[str] = mapped_column(Text, default="draft")
    vessel_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vessels.id"))
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("counterparties.id"))
    estimate_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("estimates.id"))
    laycan_from: Mapped[date | None] = mapped_column(Date)
    laycan_to: Mapped[date | None] = mapped_column(Date)
    commission_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    freight_terms: Mapped[dict] = mapped_column(JSON, default=dict)
    clauses: Mapped[dict] = mapped_column(JSON, default=dict)
    sanctions_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    # P0 commercial terms (DDS CP fixture fields)
    demurrage_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    despatch_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    laytime_terms: Mapped[str | None] = mapped_column(String(32))  # SHINC/SHEX/SSHEX ...
    cp_form: Mapped[str | None] = mapped_column(String(32))  # GENCON/NYPE/SHELLTIME ...
    freight_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    freight_basis: Mapped[str | None] = mapped_column(String(16))  # per_mt/lumpsum/worldscale
    cargo_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    load_rate_pd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))  # mt per day
    disch_rate_pd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    address_comm_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    brokerage_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    hire_per_day: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    hire_cycle_days: Mapped[int | None] = mapped_column()
    delivery_port_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    redelivery_port_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redelivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ets_responsibility: Mapped[str | None] = mapped_column(String(16))  # owner/charterer
    # 合同方向与成交类型（VC In vs VC Out；head/relet 转租）
    charter_direction: Mapped[str] = mapped_column(String(8), default="out")  # in|out
    master_contract_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("master_contracts.id"))
    fixture_type: Mapped[str] = mapped_column(String(16), default="voyage_fixture")  # head|relet|voyage_fixture
    # 租约页签：敞口/计价基准/转分账/规划期/收支/自定义属性
    exposure_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    pricing_basis: Mapped[str | None] = mapped_column(String(32))
    rebill_settings: Mapped[dict | None] = mapped_column(JSON)
    planning_periods: Mapped[dict | None] = mapped_column(JSON)
    rev_exp: Mapped[dict | None] = mapped_column(JSON)
    properties: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MasterContract(Base):
    """主合同（COA / 期租 / 光租框架）：航次成交可挂靠 master_contract_id。"""

    __tablename__ = "master_contracts"
    __table_args__ = (UniqueConstraint("tenant_id", "contract_no"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    contract_no: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    counterparty_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("counterparties.id"), nullable=False)
    contract_type: Mapped[str] = mapped_column(String(32), default="voyage_coa")  # voyage_coa|time_charter|bareboat
    total_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|active|completed|cancelled
    clauses: Mapped[dict | None] = mapped_column(JSON)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CargoBrokerRule(Base):
    """Cargo broker 佣金规则（brokerage / address），按租约逐条约定。"""

    __tablename__ = "cargo_broker_rules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    charter_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("charters.id"), nullable=False)
    broker_party_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("counterparties.id"), nullable=False)
    commission_type: Mapped[str] = mapped_column(String(16), nullable=False)  # brokerage|address
    commission_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    applies_to: Mapped[str] = mapped_column(String(16), default="all")  # freight|demurrage|all
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OffHireEvent(Base):
    """Off-hire window during a time charter; closed events deduct from billable hire."""

    __tablename__ = "off_hire_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    voyage_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("voyages.id"), nullable=False)
    charter_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("charters.id"))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str | None] = mapped_column(String(32))  # breakdown|dry_dock|detention|strike|deficiency|other
    deduct_hire: Mapped[bool] = mapped_column(Boolean, default=True)
    hire_deduction: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))  # explicit deduction amount
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|closed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CoaLifting(Base):
    __tablename__ = "coa_liftings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    charter_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("charters.id"), nullable=False)
    period_label: Mapped[str] = mapped_column(Text, nullable=False)
    planned_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    actual_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    status: Mapped[str] = mapped_column(Text, default="planned")  # planned|nominated|fixed|completed|withdrawn
    voyage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("voyages.id"))
    laycan_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    laycan_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CharterAmendment(Base):
    """Change order for a charter whose key terms are locked (active/completed)."""

    __tablename__ = "charter_amendments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    charter_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("charters.id"), nullable=False)
    seq: Mapped[int] = mapped_column(default=1)
    changes: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), default="proposed")  # proposed|approved|rejected
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScheduleBlock(Base):
    __tablename__ = "schedule_blocks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    vessel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vessels.id"), nullable=False)
    block_type: Mapped[str] = mapped_column(Text, default="voyage")  # voyage|repair|offhire
    title: Mapped[str] = mapped_column(Text, nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    voyage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("voyages.id"))
    hard_conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class Voyage(Base):
    __tablename__ = "voyages"
    __table_args__ = (UniqueConstraint("tenant_id", "voyage_no"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    voyage_no: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="planned")
    vessel_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vessels.id"))
    charter_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("charters.id"))
    cargo: Mapped[str | None] = mapped_column(Text)
    cp_date: Mapped[date | None] = mapped_column(Date)
    tc_contract_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("time_charter_contracts.id"))
    tc_seq: Mapped[int | None] = mapped_column()  # consecutive voyage sequence under TC contract
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PortCall(Base):
    __tablename__ = "port_calls"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    voyage_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("voyages.id"), nullable=False)
    port_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ports.id"))
    seq: Mapped[int] = mapped_column(default=1)
    purpose: Mapped[str] = mapped_column(Text, default="load")  # load|discharge|bunker|transit
    eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    etd: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ata: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    atd: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    nor_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    eosp_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bl_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    agent: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text, default="UTC")


class NoonReport(Base):
    __tablename__ = "noon_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    voyage_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("voyages.id"), nullable=False)
    report_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    lon: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    speed: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    rob_fo: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    rob_do: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    eta_next: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remarks: Mapped[str | None] = mapped_column(Text)
    eta_deviation_hours: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    # weather observations (weather-routing reserve; all nullable)
    wind_bf: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))  # Beaufort scale
    sea_state: Mapped[str | None] = mapped_column(String(32))
    current_kn: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))  # current speed, kn (+fair / -adverse)


class SofEvent(Base):
    __tablename__ = "sof_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    port_call_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("port_calls.id"), nullable=False)
    event_code: Mapped[str] = mapped_column(Text, nullable=False)  # NOR|COMMENCED|COMPLETED|...
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    local_tz: Mapped[str] = mapped_column(Text, default="UTC")
    remarks: Mapped[str | None] = mapped_column(Text)


class LaytimeCalc(Base):
    __tablename__ = "laytime_calcs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    voyage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("voyages.id"))
    port_call_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("port_calls.id"))
    booking_reference: Mapped[str | None] = mapped_column(String(64))  # booking 订舱单号（from-booking）
    status: Mapped[str] = mapped_column(Text, default="draft")
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    results: Mapped[dict] = mapped_column(JSON, default=dict)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LaytimeType(Base):
    """装卸时间条款类型字典（SHINC/SHEX/SHEXUU/WWDSHEX...），laytime_terms 的取值来源。"""

    __tablename__ = "laytime_types"
    __table_args__ = (UniqueConstraint("code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(32), nullable=False)  # SHINC, SHEX, SHEXUU, WWDSHEX, etc.
    label_en: Mapped[str] = mapped_column(Text, nullable=False)
    label_zh: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)


class DemurrageOnAccount(Base):
    """预付/暂付滞期费 (demurrage on account)：结算时冲抵应付滞期。"""

    __tablename__ = "demurrage_on_account"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    laytime_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("laytime_calcs.id"), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    payment_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|paid|applied
    applied_to_settlement: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DemurrageRootCause(Base):
    """滞期根因归集：延误原因 × 责任方 × 小时数，用于责任分摊与索赔支持。"""

    __tablename__ = "demurrage_root_causes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    laytime_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("laytime_calcs.id"), nullable=False, index=True)
    cause: Mapped[str] = mapped_column(String(32), nullable=False)  # port_congestion|weather|cargo_delay|documentation|other
    delay_hours: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    responsible_party: Mapped[str] = mapped_column(String(16), nullable=False)  # owner|charterer|port|agent|other
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LaytimeDelay(Base):
    """装卸时间延误明细：可标记为条款除外（不计 laytime）并记录成本影响。"""

    __tablename__ = "laytime_delays"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    laytime_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("laytime_calcs.id"), nullable=False, index=True)
    delay_type: Mapped[str] = mapped_column(String(32), nullable=False)  # weather|port_congestion|cargo|documentation|breakdown|other
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_hours: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    excluded_from_laytime: Mapped[bool] = mapped_column(Boolean, default=False)
    cost_impact: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    claim_no: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(Text, default="demurrage")
    subtype: Mapped[str | None] = mapped_column(String(32))  # claim_taxonomy CLAIM_SUBTYPES 子类
    status: Mapped[str] = mapped_column(Text, default="open")
    voyage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("voyages.id"))
    laytime_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("laytime_calcs.id"))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    time_bar: Mapped[date | None] = mapped_column(Date)
    settlement_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    deductions: Mapped[list | None] = mapped_column(JSON)  # [{reason, amount}]
    notes: Mapped[str | None] = mapped_column(Text)
    # 对方联系人（索赔通讯对象，D 闭环：counterparty_contacts 可被业务引用）
    contact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("counterparty_contacts.id"))


class ClaimAction(Base):
    """索赔动作记录：negotiate|litigate|arbitrate|settle|write_off，跟踪处置过程与结果。"""

    __tablename__ = "claim_actions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    claim_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("claims.id"), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(16), nullable=False)  # negotiate|litigate|arbitrate|settle|write_off
    action_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PortDisbursement(Base):
    __tablename__ = "port_disbursements"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    voyage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("voyages.id"))
    port_call_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("port_calls.id"))
    status: Mapped[str] = mapped_column(Text, default="draft")
    pda_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    fda_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    lines: Mapped[dict] = mapped_column(JSON, default=dict)
    variance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))


class BunkerOrder(Base):
    __tablename__ = "bunker_orders"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    order_no: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="planned")
    vessel_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vessels.id"))
    voyage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("voyages.id"))
    grade: Mapped[str] = mapped_column(Text, default="VLSFO")
    qty_ordered: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    qty_delivered: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    rob_before: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    rob_after: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    consumption: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    # BDN (Bunker Delivery Note) captured fields
    bdn_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    density_kg_m3: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    sulphur_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    bdn_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supplier: Mapped[str | None] = mapped_column(String(128))
    barge: Mapped[str | None] = mapped_column(String(128))
    # 供油方=对手方（闭环修复：BunkerIn.counterparty_id 此前只校验不落库）
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("counterparties.id"))


class BunkerRequirement(Base):
    """加油需求 (bunker requirement)：draft→approved→tendering→ordered→fulfilled。

    采购链起点：需求 → 招标 (tender) → 供应商报价 (BunkerOption) → 选定 →
    转 BunkerOrder 执行。
    """

    __tablename__ = "bunker_requirements"
    __table_args__ = (UniqueConstraint("tenant_id", "requirement_no"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    requirement_no: Mapped[str] = mapped_column(Text, nullable=False)
    vessel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vessels.id"), nullable=False)
    voyage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("voyages.id"))
    fuel_type: Mapped[str] = mapped_column(String(32), default="VLSFO")
    qty_required: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    port_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ports.id"))
    window_from: Mapped[date | None] = mapped_column(Date)
    window_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|approved|tendering|ordered|fulfilled|cancelled
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BunkerOption(Base):
    """供应商报价选项 (bunker option)：offered|selected|rejected。"""

    __tablename__ = "bunker_options"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    requirement_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("bunker_requirements.id"), nullable=False, index=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("counterparties.id"), nullable=False)
    port_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ports.id"), nullable=False)
    fuel_type: Mapped[str] = mapped_column(String(32), default="VLSFO")
    qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    price_per_mt: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    delivery_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="offered")  # offered|selected|rejected
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BunkerCapCollar(Base):
    """燃油价格上限/下限保护 (cap/collar)：指数价夹紧到 [collar, cap] 区间。"""

    __tablename__ = "bunker_cap_collar"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    charter_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("charters.id"))
    fuel_type: Mapped[str] = mapped_column(String(32), nullable=False)
    cap_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    collar_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    index_symbol: Mapped[str | None] = mapped_column(String(32))
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FuelConsumptionCategory(Base):
    """分场景油耗定额 (sea/port_working/port_idle/maneuvering/cargo_heating/ballast)。"""

    __tablename__ = "fuel_consumption_categories"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    vessel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vessels.id"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)  # sea|port_working|port_idle|maneuvering|cargo_heating|ballast
    fuel_type: Mapped[str] = mapped_column(String(32), default="VLSFO")
    consumption_per_day: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("tenant_id", "invoice_no"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    invoice_no: Mapped[str] = mapped_column(Text, nullable=False)
    invoice_type: Mapped[str] = mapped_column(Text, default="freight")
    status: Mapped[str] = mapped_column(Text, default="draft")
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("counterparties.id"))
    voyage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("voyages.id"))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    base_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))  # amount in tenant base currency
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    credit_note_of_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # red-flush source invoice
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_date: Mapped[date | None] = mapped_column(Date)
    gl_posted: Mapped[bool] = mapped_column(Boolean, default=False)
    mirror_of_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("invoices.id"))
    bill_by: Mapped[str | None] = mapped_column(String(16))  # cp_qty | bl_qty
    commission_basis: Mapped[str | None] = mapped_column(String(16))  # net | gross
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("invoices.id"), nullable=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("payment_batches.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reference: Mapped[str | None] = mapped_column(Text)


class PaymentBatch(Base):
    __tablename__ = "payment_batches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    batch_number: Mapped[str] = mapped_column(Text, nullable=False)
    batch_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="draft")  # draft|processing|completed|reversed
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    payment_count: Mapped[int] = mapped_column(default=0)
    bank_charge_mode: Mapped[str | None] = mapped_column(String(16))  # shared|sender|receiver
    approval_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class EmissionRecord(Base):
    __tablename__ = "emission_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    voyage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("voyages.id"))
    vessel_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vessels.id"))
    fo_mt: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0)
    do_mt: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0)
    co2_mt: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0)
    cii_rating: Mapped[str | None] = mapped_column(Text)
    period: Mapped[str | None] = mapped_column(Text)


class VoyageAccrual(Base):
    """Period accruals for voyage revenue/cost (freight, hire, bunker, port, commission)."""

    __tablename__ = "voyage_accruals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    voyage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("voyages.id"))
    period_ym: Mapped[str] = mapped_column(Text, nullable=False)  # YYYY-MM
    line_type: Mapped[str] = mapped_column(Text, default="freight")  # freight|hire|bunker|port|commission|other
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(Text, default="draft")  # draft|posted|reversed
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MarketQuote(Base):
    __tablename__ = "market_quotes"
    __table_args__ = (UniqueConstraint("tenant_id", "symbol", "quote_date"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tenants.id"))
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    quote_date: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    source: Mapped[str | None] = mapped_column(Text)


class DqIssue(Base):
    __tablename__ = "dq_issues"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    rule_code: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, default="warn")
    status: Mapped[str] = mapped_column(Text, default="open")
    message: Mapped[str] = mapped_column(Text, nullable=False)


class Pool(Base):
    __tablename__ = "pools"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(Text, default="active")


class PoolVessel(Base):
    __tablename__ = "pool_vessels"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    pool_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("pools.id"), nullable=False)
    vessel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vessels.id"), nullable=False)
    points: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=1)
    joined_on: Mapped[date] = mapped_column(Date, nullable=False)
    left_on: Mapped[date | None] = mapped_column(Date)


class PoolPeriod(Base):
    __tablename__ = "pool_periods"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    pool_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("pools.id"), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="open")
    total_pool_result: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    distribution: Mapped[dict] = mapped_column(JSON, default=dict)


class RiskPosition(Base):
    __tablename__ = "risk_positions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, default="long")
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    mark_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    var_1d: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    limit_breach: Mapped[bool] = mapped_column(Boolean, default=False)


class BerthWindow(Base):
    __tablename__ = "berth_windows"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    port_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ports.id"))
    berth_name: Mapped[str] = mapped_column(Text, nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    voyage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("voyages.id"))
    status: Mapped[str] = mapped_column(Text, default="reserved")


class TwinAlert(Base):
    __tablename__ = "twin_alerts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    level: Mapped[str] = mapped_column(Text, default="info")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    href: Mapped[str | None] = mapped_column(Text)
    vessel_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vessels.id"))
    voyage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("voyages.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    doc_type: Mapped[str] = mapped_column(Text, default="file")
    storage_uri: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PortalMessage(Base):
    __tablename__ = "portal_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    counterparty_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("counterparties.id"), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CharterOffer(Base):
    """租船报价追踪（Phase 长尾 / D2）：offer/counter 生命周期 + fix 转 CP。

    status: offer | firm | declined | expired | fixed
    fixed 后 charter_id 指向生成的租约（一键转 CP）。
    """

    __tablename__ = "charter_offers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("counterparties.id"))
    vessel_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vessels.id"))
    charterer_name: Mapped[str | None] = mapped_column(Text)
    cargo: Mapped[str | None] = mapped_column(Text)
    laycan_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    laycan_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    demurrage_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(Text, default="offer")  # offer|firm|declined|expired|fixed
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    charter_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("charters.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
