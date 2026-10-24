from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# 主数据「键 / 名字」的长度上限（P0-22）。
# 这些列在 DB 里都是 Text（SQLite/PG 都不限长），所以列宽给不出硬约束 ——
# 这里按常见的 VARCHAR(255) 兜底：主数据名字超过 255 字符一定是垃圾行，
# 选择器、导出列宽和唯一约束都读不动。
# 真正有列宽的列（String(64) 等）按列宽单独写 max_length。
_NAME_MAX_LEN = 255

# 键字段类型：非空 + 长度封顶（去空白与空串判定由 _reject_empty 负责）
MasterDataName = Annotated[str, Field(max_length=_NAME_MAX_LEN)]
# 同上，但允许缺省（PATCH / Update body）
OptionalMasterDataName = Annotated[str, Field(max_length=_NAME_MAX_LEN)] | None


def _reject_null(field: str):
    """为单个键字段生成 "可缺省、不可显式置空" 的校验器。

    用于 ``*Patch`` body：键字段（name / short_name / title …）是 NOT NULL，
    PATCH 里必须可缺省（``exclude_unset`` 会跳过），但显式传 null 要 422 而不是
    让 SQLAlchemy 撞 NOT NULL 抛 500。
    """

    def check(cls, v):
        if v is None:
            raise ValueError(f"{field} must not be null")
        return v

    return field_validator(field)(check)


def _reject_empty(field: str):
    """为键字段生成「非空」校验器（P0-22）。

    主数据（对手方 / 船舶 / 港口 / 货物品名）允许空名字等于没有主数据：
    列表里出现一行无名记录、开票时选对手方出现空白选项、导出时客户看到空列。
    这里统一拒绝 ``""`` / ``"   "`` / 显式 null，并把首尾空白**剥掉**再落库
    （" ACME " 与 "ACME " 是同一家公司，留着空格只会让去重和匹配失效）。

    ``*Update`` / ``*Patch`` 里该字段可缺省（路由 ``exclude_unset`` 会跳过），
    显式传 null 或空串 → 422。
    """

    def check(cls, v):
        if v is None:
            raise ValueError(f"{field} must not be empty")
        v = str(v).strip()
        if not v:
            raise ValueError(f"{field} must not be empty")
        return v

    return field_validator(field)(check)


class CompanyIn(BaseModel):
    name: MasterDataName
    code: str
    base_currency: str = "USD"
    tax_no: str | None = None

    _name_not_empty = _reject_empty("name")


class CompanyOut(CompanyIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str


class VesselIn(BaseModel):
    """Vessel create/update body.

    Field set mirrors the ORM column set 1:1 — IMOS exposes every one of these on
    its Vessel record, and ``routers/field_perms.py`` + ``routers/imports.py`` both
    derive their catalogs from ``model_fields``, so keeping In == ORM columns is what
    makes the new fields manageable and importable without extra wiring.
    """

    name: MasterDataName
    imo: str | None = None
    mmsi: str | None = None
    flag: str | None = None
    vessel_type: str | None = None
    dwt: Decimal | None = None
    speed_knots: Decimal | None = None
    consumption_sea: Decimal | None = None
    consumption_port: Decimal | None = None
    status: str = "active"

    # P0-22：空名字的船在列表/开票选择器/导出里都是一个无名幽灵行
    _name_not_empty = _reject_empty("name")
    # IMOS 对齐业务分组：mother_vessel | ship_management | tugs_barges | flf | other
    fleet_group: str = "mother_vessel"
    # —— DWT / draft tab（载重吨/吃水表）——
    summer_dwt: Decimal | None = None
    tropical_dwt: Decimal | None = None
    winter_dwt: Decimal | None = None
    summer_draft: Decimal | None = None
    tropical_draft: Decimal | None = None
    winter_draft: Decimal | None = None
    lightship: Decimal | None = None
    deadweight_scale: list[dict] | None = None  # [{draft_m, deadweight_mt}]
    # —— vessel type detail（船型明细）——
    hull_type: str | None = None
    build_year: int | None = None
    build_yard: str | None = None
    flag_state: str | None = None
    ism_manager: str | None = None
    isps_manager: str | None = None
    # —— consumption detail（航速/油耗明细，MT/day）——
    sea_speed_25: Decimal | None = None
    sea_speed_75: Decimal | None = None
    sea_speed_100: Decimal | None = None
    port_working: Decimal | None = None
    port_idle: Decimal | None = None
    port_maneuvering: Decimal | None = None
    ifo_mdo_ratio: Decimal | None = None
    # —— capacity / commercial aids（舱容与营运参数）——
    max_lift_qty: Decimal | None = None
    stowage_factor: Decimal | None = None
    design_speed: Decimal | None = None
    tank_capacity_total: Decimal | None = None
    # —— IMOS identity / commercial（短码、权属、航线、船东、日租金、速航/压载航速）——
    vessel_code: str | None = None
    type_code: str | None = None
    ownership: str | None = None
    trade_area: str | None = None
    class_society: str | None = None
    vessel_owner_id: UUID | None = None
    daily_cost: Decimal | None = None
    speed_laden: Decimal | None = None
    speed_ballast: Decimal | None = None
    # —— IMOS dimensions（TPC / 积载因数口径下的舱容 / 型宽修正）——
    tpc: Decimal | None = None
    capacity_bale_ft3: Decimal | None = None
    capacity_grain_ft3: Decimal | None = None
    deck_capacity_m3: Decimal | None = None
    vessel_type_corr: Decimal | None = None
    scrubber: str | None = None
    # —— IMOS Variables and Safety Margins（常数与气象安全裕度）——
    constants_sea: Decimal | None = None
    constants_lakes: Decimal | None = None
    fresh_water: Decimal | None = None
    constants_others: Decimal | None = None
    beaufort: str | None = None
    sea_state: str | None = None
    sea_swell: str | None = None


class VesselUpdate(VesselIn):
    """PATCH body for vessels — carries the optimistic-lock token.

    ``expected_updated_at`` is excluded from ``model_dump()`` (Field exclude)
    so it can never land in the ORM via ``**body.model_dump()`` / setattr loops.
    """

    name: OptionalMasterDataName = None  # PATCH 可缺省（路由 exclude_unset），显式 null 拒绝
    _name_not_null = _reject_null("name")

    expected_updated_at: str | None = Field(default=None, exclude=True)


class VesselOut(VesselIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


# IMOS 港口合规开关族 —— 全部 NOT NULL，但老库行由后加列填充，读出可能是 None。
_PORT_BOOL_FIELDS = (
    "is_eu",  # EU/EEA port — EU ETS eu_share inference
    "inactive",
    "bunkering_port",
    "single_berth",
    "port_range",
    "hide_passing_point",
    "projection_port",
    "lightering_port",
    "use_high_sulfur_fuel",
    "eu_ets_port",
    "sts_exclusion",  # Port of Call Exclusion (STS)
    "outermost_region",
    "fuel_eu",
    "uk_ets_port",
    "uk_ets_ni",  # UK ETS Northern Ireland
)


class PortIn(BaseModel):
    name: MasterDataName
    unlocode: str | None = None
    country: str | None = None
    timezone: str = "UTC"
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    holidays: list[str] | None = None  # 港口节假日 ["YYYY-MM-DD"]
    is_eu: bool = False  # EU/EEA port — EU ETS eu_share inference

    # P0-22：空港口名会让航线/挂港列表出现无名行
    _name_not_empty = _reject_empty("name")
    # —— IMOS port classification（港口分类与地理归属）——
    port_type: str | None = None
    parent_country: str | None = None  # 属地与主权国分离（如直布罗陀/英国）
    port_operator: str | None = None
    port_no: int | None = None
    port_area: str | None = None
    region_code: str | None = None  # EURO / ASIA / USEC ...
    loadline_zone: str | None = None
    # —— IMOS dual timezone（STD / DST 分列，比单个 tz 字符串更贴合配载计算）——
    std_gmt_offset: Decimal | None = None
    dst_gmt_offset: Decimal | None = None
    external_ref: str | None = None
    alerts: str | None = None
    remarks: str | None = None
    fuel_zone_default: str | None = None
    supported_scrubbers: str | None = None
    # —— IMOS compliance flags（排放/合规开关族）——
    inactive: bool = False
    bunkering_port: bool = False
    single_berth: bool = False
    port_range: bool = False
    hide_passing_point: bool = False
    projection_port: bool = False
    lightering_port: bool = False
    use_high_sulfur_fuel: bool = False
    eu_ets_port: bool = False
    sts_exclusion: bool = False
    outermost_region: bool = False
    fuel_eu: bool = False
    uk_ets_port: bool = False
    uk_ets_ni: bool = False

    @field_validator(*_PORT_BOOL_FIELDS, mode="before")
    @classmethod
    def _none_is_false(cls, v):
        # 老库行的布尔列可能为 NULL（列是后加的），读取时归一为 False
        return False if v is None else v


class PortOut(PortIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime | None = None


class PortUpdate(PortIn):
    """PATCH body for ports — 同 VesselUpdate/CounterpartyUpdate，name 可缺省。"""

    name: OptionalMasterDataName = None  # PATCH 可缺省（路由 exclude_unset），显式 null 拒绝
    _name_not_null = _reject_null("name")


class CounterpartyIn(BaseModel):
    """Counterparty create/update body — mirrors the ORM column set 1:1 (see VesselIn).

    ``type`` stays a single value for backward-compatible filtering; ``address_types``
    is IMOS's multi-role set (Agents + Brokers + Charterers + Owners + Company Info + Misc).
    """

    name: MasterDataName
    type: str = "other"
    country: str | None = None
    credit_rating: str | None = None
    sanctions_status: str = "clear"
    address: str | None = None
    # P0-22：空名字的对手方在开票/账龄/导出里都无法辨认
    _name_not_empty = _reject_empty("name")
    tax_id: str | None = None
    swift_code: str | None = None
    registration_no: str | None = None
    website: str | None = None
    phone: str | None = None
    email: str | None = None
    notes: str | None = None
    # —— IMOS identity keys（一家对手方常有三套编号：Short Name / Company No. / Ref No.）——
    address_types: list[str] | None = None
    short_name: str | None = None
    company_no: str | None = None
    ref_no: str | None = None
    cross_ref: str | None = None
    reference_code: str | None = None
    veslink_id: str | None = None  # 对接 IMOS/Veslink 的外部主键
    # —— IMOS contact block ——
    fax: str | None = None
    telex: str | None = None
    department: str | None = None
    main_contact: str | None = None
    # —— IMOS credit block（授信条款/额度/评级日期）——
    currency: str | None = None
    credit_term: int | None = None  # 账期天数
    credit_line: Decimal | None = None
    rating_date: date | None = None
    demurrage_tb_days: Decimal | None = None  # Dem TB Days
    vat_no: str | None = None
    # —— IMOS GL linkage（对手方直接绑定 AP/AR/IC 科目）——
    ap_account: str | None = None
    ar_account: str | None = None
    ic_account: str | None = None
    default_account: str | None = None
    # —— IMOS lifecycle（Active/Inactive，与 sanctions_status 正交）——
    status: str = "active"


class CounterpartyUpdate(CounterpartyIn):
    """PATCH body for counterparties — carries the optimistic-lock token."""

    name: OptionalMasterDataName = None  # PATCH 可缺省（路由 exclude_unset），显式 null 拒绝
    _name_not_null = _reject_null("name")

    expected_updated_at: str | None = Field(default=None, exclude=True)


class CounterpartyOut(CounterpartyIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CounterpartyContactIn(BaseModel):
    name: MasterDataName
    title: str | None = None
    email: str | None = None
    phone: str | None = None
    mobile: str | None = None
    department: str | None = None
    is_primary: bool = False
    notes: str | None = None

    # P0-22：无名联系人无法辨认（询价/催款邮件里只有一个空收件人）
    _name_not_empty = _reject_empty("name")


class CounterpartyContactOut(CounterpartyContactIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    counterparty_id: UUID


# ── IMOS Data Center 子表 —— 港口泊位/别名、货物品名、对手方属性、船舶油耗矩阵 ──
# 统一 from_attributes + In 与 ORM 列一一对应：field_perms / imports 的字段目录由
# model_fields 派生，这样新增子资源不额外接线就自带权限与导入模板。


class PortBerthIn(BaseModel):
    """港口泊位（IMOS Port 详情页 Berth 子表）。港口是全局参照数据，泊位随之全局。"""

    short_name: MasterDataName
    full_name: str | None = None
    inactive: bool = False

    # P0-22：空泊位号 = 没有泊位（选泊位时出现一个空白选项）
    _short_name_not_empty = _reject_empty("short_name")


class PortBerthOut(PortBerthIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    port_id: UUID
    created_at: datetime | None = None


class PortAliasIn(BaseModel):
    """港口别名/历史名 —— CP、代理报文、NOA 里的异写匹配到同一港口。"""

    alias: MasterDataName

    # P0-22：空别名匹配不到任何港口，却会在别名表里留下一行
    _alias_not_empty = _reject_empty("alias")


class PortAliasOut(PortAliasIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    port_id: UUID
    created_at: datetime | None = None


class CargoGroupIn(BaseModel):
    """商品大类 —— AGRI BULK / COAL / CEMENT / CONTAINER / Fertilizer ..."""

    name: MasterDataName
    description: str | None = None

    # P0-22：空大类名 = 没有品名归属（货物品名挂在一个无名分组下）
    _name_not_empty = _reject_empty("name")


class CargoGroupOut(CargoGroupIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CargoNameIn(BaseModel):
    """货物品名主数据（IMOS Data Center > Cargo Names）—— 见 models_cargo.CargoName。"""

    short_name: MasterDataName
    full_name: str | None = None
    cargo_group_id: UUID | None = None
    cargo_class: str | None = None
    # P0-22：空短名 = 没有品名
    _short_name_not_empty = _reject_empty("short_name")
    # —— 危险品属性（IMSBC + IMDG）——
    imo_name: str | None = None
    ibc_code: str | None = None
    imsbc_code: str | None = None
    un_number: str | None = None
    imdg_class: str | None = None
    dangerous: bool = False
    special_handling: bool = False
    pre_clearance_us_ca: bool = False
    # —— 积载双口径 + API ——
    stow_factor_m3_mt: Decimal | None = None
    stow_factor_ft3_mt: Decimal | None = None
    api_gravity: Decimal | None = None
    # —— 商务 ——
    product_code: str | None = None
    default_cp_unit: str | None = None
    capacity_basis: str | None = None
    bill_by: str | None = None
    inactive: bool = False
    description: str | None = None


class CargoNameOut(CargoNameIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TitleValueIn(BaseModel):
    """Title/Value 子表通用 body —— 对手方属性与品名属性结构相同。"""

    title: MasterDataName
    value: str | None = None

    # P0-22：空标题的属性行在详情页/导出里都是一行空白
    _title_not_empty = _reject_empty("title")


class CounterpartyPropertyOut(TitleValueIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    counterparty_id: UUID
    created_at: datetime | None = None


class CargoNamePropertyOut(TitleValueIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    cargo_name_id: UUID
    created_at: datetime | None = None


class VesselPortConsumptionIn(BaseModel):
    """In-port consumption matrix（IMOS In Port Consumption Table），按燃料牌号一行。"""

    fuel_grade: MasterDataName
    unit: str = "MT"
    inactive: bool = False
    gas_flag: str | None = None
    capacity: Decimal | None = None  # 日耗罐容 MT
    margin: Decimal | None = None  # 安全裕度 MT
    loading: Decimal | None = None
    discharge: Decimal | None = None
    idle_on: Decimal | None = None  # 停泊发电机开
    idle_off: Decimal | None = None  # 停泊发电机关
    heat: Decimal | None = None
    heat_plus: Decimal | None = None
    heat_plus_plus: Decimal | None = None
    igs: Decimal | None = None  # 惰气系统
    clean: Decimal | None = None  # 洗舱
    manoeuvring: Decimal | None = None
    auxiliary: Decimal | None = None
    cooling: Decimal | None = None
    boiler: Decimal | None = None
    incinerator: Decimal | None = None

    # P0-22：空燃油牌号 = 这一行油耗没有归属（VLSFO / LSG / MGO …）
    _fuel_grade_not_empty = _reject_empty("fuel_grade")


class VesselPortConsumptionOut(VesselPortConsumptionIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    vessel_id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


class VesselSpeedConsumptionIn(BaseModel):
    """Speed / consumption curve（IMOS Speed Consumption Table），一行一个航速。"""

    speed: Decimal | None = None
    ballast_laden: str | None = None  # B=压载 / L=满载
    engine_load: Decimal | None = None  # MCR 百分比
    fuel_consumption: dict[str, float] | None = None  # {"VLF": 18.00, "LSG": 0.10}
    basis: str | None = None  # eco_owner / warranted_owner


class VesselSpeedConsumptionOut(VesselSpeedConsumptionIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    vessel_id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── PATCH bodies ──
# 与 create body 分开：子表 UI 是按格提交的，PATCH 只带改过的字段，所以 create 里
# 那些 NOT NULL 键（short_name / title / fuel_grade…）在 Patch 里必须可缺省。
# 缺省 = 不写（路由用 exclude_unset 跳过）；显式传 null 拒绝，避免写成违反 NOT NULL。
# 校验器工厂 _reject_null 定义在本文件顶部。


class CargoGroupPatch(CargoGroupIn):
    name: OptionalMasterDataName = None

    _name_not_null = _reject_null("name")


class CargoNamePatch(CargoNameIn):
    short_name: OptionalMasterDataName = None

    _short_name_not_null = _reject_null("short_name")


class PortBerthPatch(PortBerthIn):
    short_name: OptionalMasterDataName = None

    _short_name_not_null = _reject_null("short_name")


class PortAliasPatch(PortAliasIn):
    alias: OptionalMasterDataName = None

    _alias_not_null = _reject_null("alias")


class VesselPortConsumptionPatch(VesselPortConsumptionIn):
    fuel_grade: OptionalMasterDataName = None

    _fuel_grade_not_null = _reject_null("fuel_grade")


class TitleValuePatch(TitleValueIn):
    title: OptionalMasterDataName = None

    _title_not_null = _reject_null("title")


class ExchangeRateIn(BaseModel):
    base_currency: str
    quote_currency: str
    rate: Decimal
    rate_date: date
    source: str | None = "manual"


class ExchangeRateOut(ExchangeRateIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class AiProviderIn(BaseModel):
    name: str
    provider_type: str
    base_url: str | None = None
    model_default: str | None = None
    secret_ref: str | None = None
    config: dict = Field(default_factory=dict)


class AiProviderOut(AiProviderIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str


class AiSkillBindingIn(BaseModel):
    skill_code: str
    primary_provider_id: UUID | None = None
    fallback_provider_id: UUID | None = None
    params: dict = Field(default_factory=dict)
    enabled: bool = True


class AiSkillBindingOut(AiSkillBindingIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class ConnectorIn(BaseModel):
    connector_type: str
    instance_name: str
    endpoint: str | None = None
    secret_ref: str | None = None
    config: dict = Field(default_factory=dict)


class ConnectorOut(ConnectorIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    last_health: dict = Field(default_factory=dict)


class EmailAccountIn(BaseModel):
    provider: str
    # Optional for Microsoft 365 accounts — resolved from Graph /me at creation
    email: EmailStr | None = None
    display_name: str | None = None
    config: dict = Field(default_factory=dict)


class EmailAccountOut(EmailAccountIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    last_sync_at: datetime | None = None


class EmailMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    subject: str | None
    from_email: str | None
    parse_status: str
    parse_confidence: float | None = None
    parse_result: dict = Field(default_factory=dict)
    sent_at: datetime | None = None


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    body: str | None
    level: str
    href: str | None
    read_at: datetime | None
    created_at: datetime


class SkillCatalogItem(BaseModel):
    skill_code: str
    module: str
    description: str
