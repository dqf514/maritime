"""P11 IMOS chartering parity — TC 交还船/定价梯/其他费用、fixture 航次测算、cargo 行程/港序选项。

六张子表全部挂在既有父实体上（TimeCharterContract / Charter / Cargo），
列名与 IMOS 截图表头逐列对齐。父表新增列写在各自 models_*.py，同一次
Alembic 迁移落地。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TimeCharterLayEvent(Base):
    """交船 / 还船事件行（IMOS TC detail 的 Delivery/Redelivery 表）。

    ``est_gmt`` = 合同估计时点；``proj_act_gmt`` = 预计/实际时点；
    Difference（小时，proj−est）由序列化器计算，不落库。
    """

    __tablename__ = "time_charter_lay_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    tc_contract_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("time_charter_contracts.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # delivery | redelivery
    port: Mapped[str | None] = mapped_column(Text)
    est_gmt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    proj_act_gmt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remarks: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TimeCharterPricingRow(Base):
    """定价梯行（Pricing 页签：Hire Rate / Rate Type / Lock / From-To / Duration / Period / TCL Ins）。"""

    __tablename__ = "time_charter_pricing_rows"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    tc_contract_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("time_charter_contracts.id"), nullable=False, index=True
    )
    hire_rate: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    rate_type: Mapped[str] = mapped_column(String(16), default="per_day")  # per_day|lumpsum|per_30_days
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    from_gmt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    to_gmt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_days: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    period_unit: Mapped[str] = mapped_column(String(16), default="Days")
    tcl_ins: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    comments: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TimeCharterOtherItem(Base):
    """其他费用行（BALLA/CABLE/VICTU/ALLOW/LASHS/ILOHC/INTHC …）。

    IMOS 的 Rate Type: Lumpsum / Monthly / Per 30 days / Per day；``comm`` = 佣金计提开关。
    """

    __tablename__ = "time_charter_other_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    tc_contract_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("time_charter_contracts.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(12), nullable=False)  # BALLA|CABLE|VICTU|...
    description: Mapped[str | None] = mapped_column(Text)
    rate_type: Mapped[str] = mapped_column(String(16), default="lumpsum")  # lumpsum|monthly|per_30_days|per_day
    rate: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    comm: Mapped[bool] = mapped_column(Boolean, default=False)
    from_gmt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    to_gmt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remarks: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CharterItineraryRow(Base):
    """Fixture 航次测算行（Port / Miles / Spd / SDays / XSD / F / Cargo / L-D Qty / L-D Rate / Terms / PDays / XPD / PortExp / LinerExp / OExp$/t / St）。

    序列化器附带 footer 聚合（miles / sdays / pdays / xpd / port_exp 合计）。
    """

    __tablename__ = "charter_itinerary_rows"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    charter_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("charters.id"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    port: Mapped[str | None] = mapped_column(Text)
    miles: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    speed: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    sea_days: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))  # SDays
    xsd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))  # extra steaming days
    flag: Mapped[str | None] = mapped_column(String(2))  # F=load D=disch Z=P ... (IMOS 站位标记)
    cargo: Mapped[str | None] = mapped_column(Text)
    ld_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    ld_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    terms: Mapped[str | None] = mapped_column(String(16))  # SHINC/SHEX ...
    port_days: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))  # PDays
    xpd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # extra port days cost
    port_exp: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    liner_exp: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    oexp_per_t: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    status: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CargoItineraryRow(Base):
    """Cargo Itinerary/Options 行（F|D / Port / Berth / Qty / L-D Rate / RU / Terms / Incoterms / PortExp / OExp$/t / LinerExp / Draft / Unit / Salinity）。"""

    __tablename__ = "cargo_itinerary_rows"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    cargo_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("cargoes.id"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    flag: Mapped[str] = mapped_column(String(2), default="L")  # L=load | D=disch
    port_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ports.id"))
    port_name: Mapped[str | None] = mapped_column(Text)  # 冗余显示名（港口主数据可空）
    berth: Mapped[str | None] = mapped_column(Text)
    qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    ld_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    ru: Mapped[str | None] = mapped_column(Text)  # RU = Rate Unit / remarks as per IMOS col
    terms: Mapped[str | None] = mapped_column(Text)
    incoterms: Mapped[str | None] = mapped_column(Text)
    port_exp: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    oexp_per_t: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    liner_exp: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    draft: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    unit: Mapped[str | None] = mapped_column(String(8))
    salinity: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CargoPortOption(Base):
    """Cargo Load/Discharge Options 子表（Port/Area / L-D Rate / RU / Terms / TT / PExp / Draft）。"""

    __tablename__ = "cargo_port_options"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    cargo_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("cargoes.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)  # load | disch
    seq: Mapped[int] = mapped_column(Integer, default=0)
    port_area: Mapped[str | None] = mapped_column(Text)
    ld_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    ru: Mapped[str | None] = mapped_column(Text)
    terms: Mapped[str | None] = mapped_column(Text)
    tt_days: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))  # TT
    pexp: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    draft: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
