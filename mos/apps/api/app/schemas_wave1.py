from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class CompanyIn(BaseModel):
    name: str
    code: str
    base_currency: str = "USD"
    tax_no: str | None = None


class CompanyOut(CompanyIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str


class VesselIn(BaseModel):
    name: str
    imo: str | None = None
    mmsi: str | None = None
    flag: str | None = None
    vessel_type: str | None = None
    dwt: Decimal | None = None
    speed_knots: Decimal | None = None
    consumption_sea: Decimal | None = None
    consumption_port: Decimal | None = None
    status: str = "active"


class VesselOut(VesselIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class PortIn(BaseModel):
    name: str
    unlocode: str | None = None
    country: str | None = None
    timezone: str = "UTC"
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    holidays: list[str] | None = None  # 港口节假日 ["YYYY-MM-DD"]
    is_eu: bool = False  # EU/EEA port — EU ETS eu_share inference


class PortOut(PortIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class CounterpartyIn(BaseModel):
    name: str
    type: str = "other"
    country: str | None = None
    credit_rating: str | None = None
    sanctions_status: str = "clear"


class CounterpartyOut(CounterpartyIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


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
    email: EmailStr
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
