"""租户可复制/自定义的参考数据（国家、时区、货币、船型、油种等）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ReferenceDataset(Base):
    """数据源目录（系统级定义）。"""

    __tablename__ = "reference_datasets"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    name_zh: Mapped[str] = mapped_column(Text, nullable=False)
    description_en: Mapped[str | None] = mapped_column(Text)
    description_zh: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    editable: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantReferenceConfig(Base):
    """租户对某数据源使用系统包还是本地副本。"""

    __tablename__ = "tenant_reference_configs"
    __table_args__ = (UniqueConstraint("tenant_id", "dataset_code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    dataset_code: Mapped[str] = mapped_column(String(64), ForeignKey("reference_datasets.code"), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="system")  # system | local
    cloned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReferenceItem(Base):
    """参考条目：scope_key=system 为内置；否则为租户 UUID 字符串（本地副本/自定义）。"""

    __tablename__ = "reference_items"
    __table_args__ = (UniqueConstraint("scope_key", "dataset_code", "code", name="uq_ref_item_scope_code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dataset_code: Mapped[str] = mapped_column(String(64), ForeignKey("reference_datasets.code"), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False, default="system", index=True)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    label_en: Mapped[str] = mapped_column(Text, nullable=False)
    label_zh: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(32), default="system")  # system | cloned | custom
    origin_code: Mapped[str | None] = mapped_column(String(128))
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PortDistance(Base):
    """Port-to-port distance lookup (nautical miles)."""

    __tablename__ = "port_distances"
    __table_args__ = (
        UniqueConstraint("from_port_unlocode", "to_port_unlocode", "route_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    from_port_unlocode: Mapped[str] = mapped_column(String(5), nullable=False, index=True)
    to_port_unlocode: Mapped[str] = mapped_column(String(5), nullable=False, index=True)
    distance_nm: Mapped[Decimal] = mapped_column(Numeric(10, 1), nullable=False)
    route_type: Mapped[str] = mapped_column(String(16), default="standard")  # standard|canal|cape
    canal_transit: Mapped[str | None] = mapped_column(String(16))  # suez|panama|kiel
    canal_toll: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    transit_days: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))  # at typical speed
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), default="manual")  # manual|import|calculated


class WorldscaleRate(Base):
    """Worldscale flat rate for a port pair (annual publication)."""

    __tablename__ = "worldscale_rates"
    __table_args__ = (
        UniqueConstraint("from_port_unlocode", "to_port_unlocode", "year"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    from_port_unlocode: Mapped[str] = mapped_column(String(5), nullable=False, index=True)
    to_port_unlocode: Mapped[str] = mapped_column(String(5), nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    flat_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)  # WS 100 = $/mt
    cargo_type: Mapped[str | None] = mapped_column(String(32))  # clean/dirty/dry
    vessel_class: Mapped[str | None] = mapped_column(String(32))
    notes: Mapped[str | None] = mapped_column(Text)


class PortHoliday(Base):
    """Port holiday calendar entry.

    Used for laytime calculation — holidays are non-working days.
    """

    __tablename__ = "port_holidays"
    __table_args__ = (
        UniqueConstraint("port_unlocode", "holiday_date", name="uq_port_holiday_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    port_unlocode: Mapped[str] = mapped_column(String(5), nullable=False, index=True)
    country: Mapped[str] = mapped_column(String(3), nullable=False, index=True)  # ISO 3166-1 alpha-3
    holiday_date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    holiday_name: Mapped[str] = mapped_column(String(128), nullable=False)
    holiday_type: Mapped[str] = mapped_column(String(16), default="public")  # public | religious | local | custom
    recurring: Mapped[bool] = mapped_column(Boolean, default=False)  # applies every year
    notes: Mapped[str | None] = mapped_column(Text)


class PortRate(Base):
    """Port rate reference — baseline costs for port disbursement estimation.

    All amounts in USD unless noted.
    """

    __tablename__ = "port_rates"
    __table_args__ = (
        UniqueConstraint("port_unlocode", "rate_type", "vessel_size_band", name="uq_port_rate"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    port_unlocode: Mapped[str] = mapped_column(String(5), nullable=False, index=True)
    rate_type: Mapped[str] = mapped_column(String(32), nullable=False)  # port_dues | pilotage | towage | mooring | wharfage | light_due
    vessel_size_band: Mapped[str] = mapped_column(String(16), default="medium")  # small | medium | large | xl
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    basis: Mapped[str] = mapped_column(String(32), default="per_call")  # per_call | per_day | per_gt | per_dwt
    effective_from: Mapped[str | None] = mapped_column(String(10))  # YYYY-MM-DD
    effective_to: Mapped[str | None] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(32), default="manual")  # manual | import | agent_quote
    notes: Mapped[str | None] = mapped_column(Text)


class PortRestriction(Base):
    """Port physical and operational restrictions."""

    __tablename__ = "port_restrictions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    port_unlocode: Mapped[str] = mapped_column(String(5), nullable=False, index=True)
    max_draft_m: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))  # max draft in meters
    max_loa_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))  # max LOA in meters
    max_beam_m: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))  # max beam in meters
    max_dwt: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))  # max deadweight
    berth_types: Mapped[dict | None] = mapped_column(JSON)  # ["bulk", "tanker", "container", "general"]
    cargo_types: Mapped[dict | None] = mapped_column(JSON)  # allowed cargo types
    working_hours: Mapped[str | None] = mapped_column(String(32))  # "0800-1700" | "24h"
    night_work_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    sunday_work_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_pilot: Mapped[bool] = mapped_column(Boolean, default=True)
    ice_class_required: Mapped[str | None] = mapped_column(String(16))  # ice class notation
    other_restrictions: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FuelZone(Base):
    """Fuel zone / emissions zone definition.

    Supports ECA, EU ETS, FuelEU Maritime zones with GeoJSON boundaries.
    """

    __tablename__ = "fuel_zones"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    zone_name: Mapped[str] = mapped_column(String(128), nullable=False)
    zone_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # eca | non_eca | eu_ets | fueleu | cii
    geometry: Mapped[dict | None] = mapped_column(JSON)  # GeoJSON Polygon/MultiPolygon
    fuel_requirements: Mapped[dict | None] = mapped_column(JSON)  # {"sulfur_max": 0.1, "fuel_type": "MGO"}
    eu_ets_factor: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))  # EUR/tCO2 allowance price
    fueleu_limit: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))  # gCO2e/MJ intensity limit
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    effective_from: Mapped[str | None] = mapped_column(String(10))  # YYYY-MM-DD
    effective_to: Mapped[str | None] = mapped_column(String(10))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
