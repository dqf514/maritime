"""Vessel detail extension models — 船舶管理补充表.

Covers the vessel-card gaps: contacts, preferred routes, port tugs,
bunker tanks, L/D performance, TCE targets, vetting records and loadline
zones. All rows are tenant-scoped and hung off ``vessels.id``; use
``app.services.tenant_guard`` for access (see ``routers/vessel_detail.py``).
"""

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
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class VesselContact(Base):
    """Vessel contact directory — captain / superintendent / agent / owner."""

    __tablename__ = "vessel_contacts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    vessel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vessels.id"), nullable=False)
    contact_role: Mapped[str] = mapped_column(Text, default="captain")  # captain|superintendent|agent|owner
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VesselRoute(Base):
    """Preferred trade route — typical speed / distance for estimates."""

    __tablename__ = "vessel_routes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    vessel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vessels.id"), nullable=False)
    route_name: Mapped[str] = mapped_column(Text, nullable=False)
    from_area: Mapped[str | None] = mapped_column(Text)
    to_area: Mapped[str | None] = mapped_column(Text)
    typical_speed: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    distance_nm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VesselTug(Base):
    """Tug info per port — 拖轮信息."""

    __tablename__ = "vessel_tugs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    vessel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vessels.id"), nullable=False)
    tug_name: Mapped[str] = mapped_column(Text, nullable=False)
    port_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ports.id"))
    power_hp: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VesselTank(Base):
    """Bunker / lube / water / ballast tank capacity card."""

    __tablename__ = "vessel_tanks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    vessel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vessels.id"), nullable=False)
    tank_name: Mapped[str] = mapped_column(Text, nullable=False)
    tank_type: Mapped[str] = mapped_column(Text, default="fuel")  # fuel|lube|water|ballast
    capacity_mt: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    max_fill_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))  # 0-100
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VesselPerformance(Base):
    """Loading / discharging performance per cargo type — 装卸货效率."""

    __tablename__ = "vessel_performance"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    vessel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vessels.id"), nullable=False)
    cargo_type: Mapped[str] = mapped_column(Text, nullable=False)
    load_rate_mt_hr: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    discharge_rate_mt_hr: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    stowage_factor: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))  # m3/MT
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VesselTceTarget(Base):
    """Monthly TCE target — 月度 TCE 目标."""

    __tablename__ = "vessel_tce_targets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    vessel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vessels.id"), nullable=False)
    year_month: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    target_tce_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VesselVetting(Base):
    """Vetting record — SIRE / CDI / PSC 检查记录."""

    __tablename__ = "vessel_vettings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    vessel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vessels.id"), nullable=False)
    vetting_type: Mapped[str] = mapped_column(Text, default="sire")  # sire|cdi|psc
    vetting_date: Mapped[date | None] = mapped_column(Date)
    result: Mapped[str] = mapped_column(Text, default="pass")  # pass|conditional|fail
    expiry_date: Mapped[date | None] = mapped_column(Date)
    inspector: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LoadlineZone(Base):
    """Loadline zone draft limits — 载重线区带吃水限制."""

    __tablename__ = "loadline_zones"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    vessel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vessels.id"), nullable=False)
    zone_name: Mapped[str] = mapped_column(Text, default="summer")  # summer|tropical|winter|winter_north_atlantic
    max_draft_m: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VesselPortConsumption(Base):
    """In-port consumption matrix — 停泊工况油耗（IMOS In Port Consumption Table）.

    IMOS 按「燃油牌号 x 工况」铺成一张矩阵：同一船在同一港，装货/卸货/停泊开着辅机
    的油耗并不相同，用两个标量（``consumption_sea`` / ``consumption_port``）无法表达，
    估算的港口使费与 TCE 会系统性偏高。每行 = 一个燃油牌号。
    """

    __tablename__ = "vessel_port_consumptions"
    __table_args__ = (UniqueConstraint("vessel_id", "fuel_grade"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    vessel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vessels.id"), nullable=False)
    inactive: Mapped[bool] = mapped_column(Boolean, default=False)
    fuel_grade: Mapped[str] = mapped_column(Text, nullable=False)  # VLF / LSG / MGO ...
    unit: Mapped[str] = mapped_column(Text, default="MT")
    gas_flag: Mapped[str | None] = mapped_column(Text)  # IMOS 的 G 列，L=liquid / G=gas
    capacity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))  # 该牌号舱容 MT
    margin: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))  # 安全裕度 MT
    # —— 工况日耗（MT/day）——
    loading: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    discharge: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    idle_on: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))  # 停泊·辅机开启
    idle_off: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))  # 停泊·辅机关闭
    heat: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    heat_plus: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    heat_plus_plus: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    igs: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))  # 惰气系统
    clean: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))  # 洗舱
    manoeuvring: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    auxiliary: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    cooling: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    boiler: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    incinerator: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # 软删除列必须存在：services/recycle.soft_delete 靠它隐藏行，缺了会"删除成功但列表还在"。
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VesselSpeedConsumption(Base):
    """Speed / consumption curve — 航速油耗曲线（IMOS Speed Consumption Table）.

    一行 = 一个航速点。``basis`` 区分 Eco Owner（船东经济航速）与 Warranted Owner
    （船东保证航速）——两者在同一航速下的油耗承诺不同，租家索赔时要分别举证。
    各燃油的日耗放在 ``fuel_consumption`` JSON（键 = 牌号），避免每加一种油就加一列。
    """

    __tablename__ = "vessel_speed_consumptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    vessel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vessels.id"), nullable=False)
    speed: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))  # 节
    ballast_laden: Mapped[str | None] = mapped_column(Text)  # B=压载 / L=满载
    engine_load: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))  # MCR 百分比
    fuel_consumption: Mapped[dict | None] = mapped_column(JSON)  # {"VLF": 18.00, "LSG": 0.10}
    basis: Mapped[str | None] = mapped_column(Text)  # eco_owner / warranted_owner
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # 同 VesselPortConsumption —— 软删除列缺失会让 recycle.soft_delete 静默失效。
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
