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


class Charter(Base):
    __tablename__ = "charters"

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CoaLifting(Base):
    __tablename__ = "coa_liftings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    charter_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("charters.id"), nullable=False)
    period_label: Mapped[str] = mapped_column(Text, nullable=False)
    planned_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    actual_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    status: Mapped[str] = mapped_column(Text, default="planned")


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

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    voyage_no: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="planned")
    vessel_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vessels.id"))
    charter_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("charters.id"))
    cargo: Mapped[str | None] = mapped_column(Text)
    cp_date: Mapped[date | None] = mapped_column(Date)
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
    status: Mapped[str] = mapped_column(Text, default="draft")
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    results: Mapped[dict] = mapped_column(JSON, default=dict)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    claim_no: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(Text, default="demurrage")
    status: Mapped[str] = mapped_column(Text, default="open")
    voyage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("voyages.id"))
    laytime_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("laytime_calcs.id"))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    time_bar: Mapped[date | None] = mapped_column(Date)
    settlement_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    notes: Mapped[str | None] = mapped_column(Text)


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


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    invoice_no: Mapped[str] = mapped_column(Text, nullable=False)
    invoice_type: Mapped[str] = mapped_column(Text, default="freight")
    status: Mapped[str] = mapped_column(Text, default="draft")
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("counterparties.id"))
    voyage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("voyages.id"))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_date: Mapped[date | None] = mapped_column(Date)
    gl_posted: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("invoices.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reference: Mapped[str | None] = mapped_column(Text)


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
