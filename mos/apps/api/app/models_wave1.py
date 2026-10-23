"""Wave 1 domain models: masterdata, email, AI hub, connectors, notifications."""

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
    Uuid,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), default="USD")
    tax_no: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Vessel(Base):
    __tablename__ = "vessels"
    __table_args__ = (UniqueConstraint("tenant_id", "imo"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    imo: Mapped[str | None] = mapped_column(Text)
    mmsi: Mapped[str | None] = mapped_column(Text)
    flag: Mapped[str | None] = mapped_column(Text)
    vessel_type: Mapped[str | None] = mapped_column(Text)
    dwt: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    speed_knots: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    consumption_sea: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    consumption_port: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    # —— DWT / draft tab（载重吨/吃水表）——
    summer_dwt: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    tropical_dwt: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    winter_dwt: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    summer_draft: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    tropical_draft: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    winter_draft: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    lightship: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    deadweight_scale: Mapped[list | None] = mapped_column(JSON)  # 吃水-载重吨曲线 [{draft_m, deadweight_mt}]
    # —— vessel type detail（船型明细）——
    hull_type: Mapped[str | None] = mapped_column(Text)
    build_year: Mapped[int | None] = mapped_column(Integer)
    build_yard: Mapped[str | None] = mapped_column(Text)
    flag_state: Mapped[str | None] = mapped_column(Text)
    ism_manager: Mapped[str | None] = mapped_column(Text)
    isps_manager: Mapped[str | None] = mapped_column(Text)
    # —— consumption detail（航速/油耗明细，MT/day）——
    sea_speed_25: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    sea_speed_75: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    sea_speed_100: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    port_working: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    port_idle: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    port_maneuvering: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    ifo_mdo_ratio: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    # —— capacity / commercial aids（舱容与营运参数）——
    max_lift_qty: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    stowage_factor: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))  # m3/MT
    design_speed: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    tank_capacity_total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # —— IMOS identity / commercial（短码、权属、航线、船东、日租金、速航/压载航速）——
    # vessel_code 是租约/航次里反复引用的 6 位短码（如 ACKATH），必须租户内唯一，
    # 否则 TC Code（VESSEL-I0001）这类编码无从生成。
    vessel_code: Mapped[str | None] = mapped_column(Text)
    type_code: Mapped[str | None] = mapped_column(Text)  # IMOS Type Code，如 B=散货船
    ownership: Mapped[str | None] = mapped_column(Text)  # tc / own / unspecified
    trade_area: Mapped[str | None] = mapped_column(Text)
    class_society: Mapped[str | None] = mapped_column(Text)
    vessel_owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("counterparties.id"))
    daily_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))  # USD/day 运营成本
    speed_laden: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))  # 满载航速
    speed_ballast: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))  # 压载航速
    # —— IMOS dimensions（TPC / 积载因数口径下的舱容 / 型宽修正）——
    tpc: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))  # tonnes per centimetre
    capacity_bale_ft3: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    capacity_grain_ft3: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    deck_capacity_m3: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    vessel_type_corr: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    scrubber: Mapped[str | None] = mapped_column(Text)  # none / open_loop / hybrid / closed_loop
    # —— IMOS Variables and Safety Margins（常数与气象安全裕度，喂给载重/吃水校核）——
    constants_sea: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    constants_lakes: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    fresh_water: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    constants_others: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    beaufort: Mapped[str | None] = mapped_column(Text)  # CALM / MODERATE / ...
    sea_state: Mapped[str | None] = mapped_column(Text)
    sea_swell: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active")
    # —— IMOS 对齐的业务分组（Track 2）：船舶按经营性质归组，而非按管理处室 ——
    # mother_vessel 母船/租入船队 | ship_management 船管 | tugs_barges 拖轮驳船 |
    # flf 灵便重吊(Fleetline) | other 其他。默认母船队，避免存量数据失焦。
    fleet_group: Mapped[str] = mapped_column(Text, default="mother_vessel")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Port(Base):
    __tablename__ = "ports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    unlocode: Mapped[str | None] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text, default="UTC")
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    holidays: Mapped[list | None] = mapped_column(JSON)  # 港口节假日 ["YYYY-MM-DD"]，供 laytime SHINC/SHEX 扣除
    is_eu: Mapped[bool] = mapped_column(Boolean, default=False)  # EU/EEA port — drives EU ETS eu_share inference
    # —— IMOS port classification（港口分类与地理归属）——
    port_type: Mapped[str | None] = mapped_column(Text)  # standard_port / river / terminal / lightering ...
    parent_country: Mapped[str | None] = mapped_column(Text)  # 属地与主权国分离（如直布罗陀/英国）
    port_operator: Mapped[str | None] = mapped_column(Text)
    port_no: Mapped[int | None] = mapped_column(Integer)
    port_area: Mapped[str | None] = mapped_column(Text)
    region_code: Mapped[str | None] = mapped_column(Text)  # EURO / ASIA / USEC ...
    loadline_zone: Mapped[str | None] = mapped_column(Text)  # IMO 载重线区域
    # —— IMOS dual timezone（IMOS 把 STD / DST 分列显示，比单个 tz 字符串更贴合配载计算）——
    std_gmt_offset: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    dst_gmt_offset: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    external_ref: Mapped[str | None] = mapped_column(Text)
    alerts: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)
    fuel_zone_default: Mapped[str | None] = mapped_column(Text)  # 默认燃油区（ECA）
    supported_scrubbers: Mapped[str | None] = mapped_column(Text)
    # —— IMOS compliance flags（排放/合规开关族；is_eu 只覆盖其中一项，故并列保留）——
    # server_default 与 alembic 迁移保持一致：存量港口行必须能在加 NOT NULL 列时拿到默认值。
    inactive: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    bunkering_port: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    single_berth: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    port_range: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    hide_passing_point: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    projection_port: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    lightering_port: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    use_high_sulfur_fuel: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    eu_ets_port: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    sts_exclusion: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # Port of Call Exclusion (STS)
    outermost_region: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    fuel_eu: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    uk_ets_port: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    uk_ets_ni: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # UK ETS Northern Ireland
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PortBerth(Base):
    """港口泊位字典（IMOS Port 详情页 Berth 子表）。港口本身是全局参照数据，泊位/别名随之全局。"""

    __tablename__ = "port_berths"
    __table_args__ = (UniqueConstraint("port_id", "short_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    port_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ports.id"), nullable=False)
    short_name: Mapped[str] = mapped_column(Text, nullable=False)  # QUAY / BERTH-3 ...
    full_name: Mapped[str | None] = mapped_column(Text)
    inactive: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PortAlias(Base):
    """港口别名/历史名，供 CP、代理报文、NOA 里的异写匹配到同一港口。"""

    __tablename__ = "port_aliases"
    __table_args__ = (UniqueConstraint("port_id", "alias"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    port_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ports.id"), nullable=False)
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Counterparty(Base):
    __tablename__ = "counterparties"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, default="other")
    country: Mapped[str | None] = mapped_column(Text)
    credit_rating: Mapped[str | None] = mapped_column(Text)
    sanctions_status: Mapped[str] = mapped_column(Text, default="clear")
    address: Mapped[str | None] = mapped_column(Text)
    tax_id: Mapped[str | None] = mapped_column(Text)
    swift_code: Mapped[str | None] = mapped_column(Text)
    registration_no: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    # —— IMOS identity keys（一家对手方常有三套编号：Short Name / Company No. / Ref No.）——
    # type 是历史单值字段，保留以免破坏存量筛选；address_types 是 IMOS 的多角色集合，
    # 一家公司可同时是 Agents + Brokers + Owners + Charterers + Misc。
    address_types: Mapped[list | None] = mapped_column(JSON)
    short_name: Mapped[str | None] = mapped_column(Text)
    company_no: Mapped[str | None] = mapped_column(Text)
    ref_no: Mapped[str | None] = mapped_column(Text)
    cross_ref: Mapped[str | None] = mapped_column(Text)
    reference_code: Mapped[str | None] = mapped_column(Text)
    veslink_id: Mapped[str | None] = mapped_column(Text)  # 对接 IMOS/Veslink 的外部主键
    # —— IMOS contact block（IMOS 把 Fax / Telex / Department 也做成一等字段）——
    fax: Mapped[str | None] = mapped_column(Text)
    telex: Mapped[str | None] = mapped_column(Text)
    department: Mapped[str | None] = mapped_column(Text)
    main_contact: Mapped[str | None] = mapped_column(Text)
    # —— IMOS credit block（授信条款/额度/评级日期，credit_rating 已有故不重复）——
    currency: Mapped[str | None] = mapped_column(Text)
    credit_term: Mapped[int | None] = mapped_column(Integer)  # 账期天数
    credit_line: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    rating_date: Mapped[date | None] = mapped_column(Date)
    demurrage_tb_days: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))  # Dem TB Days
    vat_no: Mapped[str | None] = mapped_column(Text)
    # —— IMOS GL linkage（对手方直接绑定 AP/AR/IC 科目，出账不再靠人工选科目）——
    ap_account: Mapped[str | None] = mapped_column(Text)
    ar_account: Mapped[str | None] = mapped_column(Text)
    ic_account: Mapped[str | None] = mapped_column(Text)
    default_account: Mapped[str | None] = mapped_column(Text)
    # —— IMOS lifecycle（Active/Inactive，与 sanctions_status 正交）——
    # server_default 与迁移一致：存量行加 NOT NULL 列时需要服务端默认值。
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CounterpartyProperty(Base):
    """对手方自定义 Title/Value 属性（IMOS Address Book 的 Properties 子表）。"""

    __tablename__ = "counterparty_properties"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("counterparties.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CounterpartyContact(Base):
    __tablename__ = "counterparty_contacts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    counterparty_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("counterparties.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    mobile: Mapped[str | None] = mapped_column(Text)
    department: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class ExchangeRate(Base):
    __tablename__ = "exchange_rates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tenants.id"))
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiProvider(Base):
    __tablename__ = "ai_providers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    provider_type: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text)
    model_default: Mapped[str | None] = mapped_column(Text)
    secret_ref: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiSkillBinding(Base):
    __tablename__ = "ai_skill_bindings"
    __table_args__ = (UniqueConstraint("tenant_id", "skill_code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    skill_code: Mapped[str] = mapped_column(Text, nullable=False)
    primary_provider_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ai_providers.id"))
    fallback_provider_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ai_providers.id"))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class ConnectorInstance(Base):
    __tablename__ = "connector_instances"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    connector_type: Mapped[str] = mapped_column(Text, nullable=False)
    instance_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="draft")
    endpoint: Mapped[str | None] = mapped_column(Text)
    secret_ref: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    last_health: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EmailAccount(Base):
    __tablename__ = "email_accounts"
    __table_args__ = (UniqueConstraint("tenant_id", "email"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(Text, default="active")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EmailThread(Base):
    __tablename__ = "email_threads"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("email_accounts.id"))
    subject_norm: Mapped[str | None] = mapped_column(Text)
    thread_key: Mapped[str | None] = mapped_column(Text)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EmailMessage(Base):
    __tablename__ = "email_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("email_accounts.id"))
    thread_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("email_threads.id"))
    message_id: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(Text, default="inbound")
    from_email: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parse_status: Mapped[str] = mapped_column(Text, default="pending")
    parse_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    parse_result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    level: Mapped[str] = mapped_column(Text, default="info")
    href: Mapped[str | None] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(Text)
    size: Mapped[int | None] = mapped_column(Integer)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
