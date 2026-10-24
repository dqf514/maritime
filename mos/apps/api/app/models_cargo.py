"""Phase 3 货盘 (cargo) 主档 — 商业货盘实体, 供集中排程 (scheduling) 使用."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
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


class Cargo(Base):
    __tablename__ = "cargoes"
    __table_args__ = (UniqueConstraint("tenant_id", "cargo_no"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    cargo_no: Mapped[str] = mapped_column(Text, nullable=False)  # 单号 doc number CGO-YYYY-NNNNN
    cargo_type: Mapped[str | None] = mapped_column(String(32))  # bulk|liquid|dry
    commodity: Mapped[str | None] = mapped_column(Text)
    qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    qty_unit: Mapped[str | None] = mapped_column(String(8))  # mt|bbl
    load_port_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ports.id"))
    disch_port_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ports.id"))
    laycan_from: Mapped[date | None] = mapped_column(Date)
    laycan_to: Mapped[date | None] = mapped_column(Date)
    charterer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("counterparties.id"))
    freight_basis: Mapped[str | None] = mapped_column(String(16))  # per_mt|lumpsum|worldscale
    freight_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|booked|nominated|fixed|confirmed|completed|cancelled
    voyage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("voyages.id"))
    charter_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("charters.id"))
    coa_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # COA reference (no dedicated table)
    # ── P11 IMOS Cargo detail 对齐 — 头部 / CP 条款 / 支付块 ──
    cargo_name_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("cargo_names.id"))
    api_gravity: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    specific_gravity: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    cp_date: Mapped[date | None] = mapped_column(Date)
    cp_form: Mapped[str | None] = mapped_column(String(32))  # GENCON/NYPE/...
    option_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    option_type: Mapped[str | None] = mapped_column(String(16))  # MOLOO|MINLO|MOLOA...
    min_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    max_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    freight_type: Mapped[str | None] = mapped_column(String(2))  # F|L|LS
    currency: Mapped[str | None] = mapped_column(String(3), default="USD")
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 6), default=Decimal("1"))
    min_inv_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    freight_via: Mapped[str | None] = mapped_column(Text)
    demurrage_via: Mapped[str | None] = mapped_column(Text)
    cp_draft_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    coordinator: Mapped[str | None] = mapped_column(Text)
    reference_no: Mapped[str | None] = mapped_column(Text)
    booking_no: Mapped[str | None] = mapped_column(Text)
    vc_in_id: Mapped[str | None] = mapped_column(Text)
    nominated_vessel_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vessels.id"))
    voyage_no: Mapped[str | None] = mapped_column(Text)
    contract_link: Mapped[str | None] = mapped_column(Text)
    company_code: Mapped[str | None] = mapped_column(String(16))
    department: Mapped[str | None] = mapped_column(Text)
    trade_area: Mapped[str | None] = mapped_column(String(32))
    # Laycan 四字段（Local / Override × From / To）+ Confirmed
    laycan_from_override: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    laycan_to_override: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    laycan_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    # 支付块
    remittance_bank: Mapped[str | None] = mapped_column(Text)
    invoice_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    balance_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    payment_terms_code: Mapped[str | None] = mapped_column(String(16))
    payment_terms_desc: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CargoGroup(Base):
    """Commodity group — 货种分组（AGRI BULK / COAL / CEMENT / CONTAINER / FERTILIZER ...）."""

    __tablename__ = "cargo_groups"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CargoName(Base):
    """Commodity master — 货名主档（IMOS Data Center > Cargo Names）.

    ``Cargo.commodity`` 只是个自由文本，同一票货在不同航次里会被写成
    "STEAM COAL" / "Steam Coal" / "COAL"，积载因数与危险品属性无处落地。
    货名主档把监管属性（IMO/IBC/IMSBC/UN/Class）与积载因数双口径
    （m3/MT 与 ft3/MT）固化下来，估算、配载、SOF 才能引用同一份事实。
    """

    __tablename__ = "cargo_names"
    __table_args__ = (UniqueConstraint("tenant_id", "short_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    short_name: Mapped[str] = mapped_column(Text, nullable=False)  # RSM / SBM / STEAM COAL
    full_name: Mapped[str | None] = mapped_column(Text)
    cargo_group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("cargo_groups.id"))
    cargo_class: Mapped[str | None] = mapped_column(Text)
    # —— 危险品/固体散货监管属性（IMSBC + IMDG）——
    imo_name: Mapped[str | None] = mapped_column(Text)
    ibc_code: Mapped[str | None] = mapped_column(Text)
    imsbc_code: Mapped[str | None] = mapped_column(Text)
    un_number: Mapped[str | None] = mapped_column(Text)
    imdg_class: Mapped[str | None] = mapped_column(Text)
    dangerous: Mapped[bool] = mapped_column(Boolean, default=False)
    special_handling: Mapped[bool] = mapped_column(Boolean, default=False)
    pre_clearance_us_ca: Mapped[bool] = mapped_column(Boolean, default=False)
    # —— 积载因数双口径 + 物性 ——
    stow_factor_m3_mt: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    stow_factor_ft3_mt: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    api_gravity: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))  # API / SG
    # —— 计价口径 ——
    product_code: Mapped[str | None] = mapped_column(Text)
    default_cp_unit: Mapped[str | None] = mapped_column(Text)  # MT / M3 / FEU ...
    capacity_basis: Mapped[str | None] = mapped_column(Text)  # unspecified / bale / grain / deck
    bill_by: Mapped[str | None] = mapped_column(Text)  # bl_qty / coa_qty ...
    inactive: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CargoNameProperty(Base):
    """Tenant-specific Title/Value attributes on a commodity — 货名自定义属性."""

    __tablename__ = "cargo_name_properties"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    cargo_name_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("cargo_names.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
