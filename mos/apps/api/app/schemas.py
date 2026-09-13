from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginIn(BaseModel):
    email: EmailStr
    password: str
    tenant_code: str = "demo"


class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str | None
    locale: str | None
    roles: list[str] = []
    email_verified: bool = False


class TenantOut(BaseModel):
    id: UUID
    name: str
    code: str
    status: str
    default_locale: str
    default_timezone: str
    profile_tier: str


class MeOut(BaseModel):
    user: UserOut
    tenant: TenantOut
    licensed_modules: list[str]


class LicenseOut(BaseModel):
    module_code: str
    status: str
    is_core: bool = False


class SelfCheckResultOut(BaseModel):
    check_id: str
    severity: str
    status: str
    message: str | None = None


class SelfCheckRunOut(BaseModel):
    id: UUID
    status: str
    score: int | None
    started_at: datetime
    finished_at: datetime | None
    results: list[SelfCheckResultOut] = []


class BackupJobOut(BaseModel):
    id: UUID
    status: str
    trigger: str
    storage_path: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
    error: str | None = None


class MigrationJobCreate(BaseModel):
    note: str | None = None


class MigrationSourceIn(BaseModel):
    source_type: str
    config: dict = Field(default_factory=dict)


class MigrationProposalOut(BaseModel):
    id: UUID
    entity_type: str
    action: str
    confidence: float
    payload: dict
    status: str


class MigrationJobOut(BaseModel):
    id: UUID
    status: str
    summary: dict
    created_at: datetime


class SearchHit(BaseModel):
    id: str
    title: str
    keywords: list[str] = []
    module: str
    href: str | None = None
    action: str | None = None


class ApiKeyCreate(BaseModel):
    name: str
    scopes: list[str] = ["read"]


class ApiKeyOut(BaseModel):
    id: UUID
    name: str
    key_prefix: str
    scopes: list[str]
    status: str
    raw_key: str | None = None
