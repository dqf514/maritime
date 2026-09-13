"""Identity & verification — platform / tenant / user layered auth."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    Uuid,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PlatformIdentitySettings(Base):
    """Singleton-ish platform IdP & email channel metadata (secrets stay in env)."""

    __tablename__ = "platform_identity_settings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Non-secret OAuth app metadata
    microsoft_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    google_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    email_password_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    magic_link_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Redirect / branding for IdP consents
    oauth_redirect_base: Mapped[str | None] = mapped_column(Text)  # e.g. https://api.voyageos.com
    web_app_base: Mapped[str | None] = mapped_column(Text)  # e.g. https://app.voyageos.com
    # Email channel
    email_channel: Mapped[str] = mapped_column(Text, default="console")  # console|smtp|sendgrid|graph
    email_from: Mapped[str] = mapped_column(Text, default="noreply@voyageos.local")
    email_from_name: Mapped[str] = mapped_column(Text, default="VoyageOS")
    # Default policy template applied to new tenants
    default_require_email_verify: Mapped[bool] = mapped_column(Boolean, default=True)
    default_invite_only: Mapped[bool] = mapped_column(Boolean, default=False)
    default_allowed_domains: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantAuthPolicy(Base):
    """Tenant-admin controlled login & verification policy."""

    __tablename__ = "tenant_auth_policies"
    __table_args__ = (UniqueConstraint("tenant_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    password_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    microsoft_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    google_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    magic_link_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    require_email_verify: Mapped[bool] = mapped_column(Boolean, default=False)
    invite_only: Mapped[bool] = mapped_column(Boolean, default=False)
    allowed_domains: Mapped[list] = mapped_column(JSON, default=list)  # empty = any
    session_hours: Mapped[int] = mapped_column(default=12)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserIdentity(Base):
    """Linked external identity (Microsoft / Google / …)."""

    __tablename__ = "user_identities"
    __table_args__ = (UniqueConstraint("provider", "subject"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)  # microsoft|google|email
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthChallenge(Base):
    """Email verify / invite / magic-link / password-reset tokens."""

    __tablename__ = "auth_challenges"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tenants.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)  # email_verify|invite|magic_link|password_reset|oauth_state
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutboundMailLog(Base):
    """Audit of verification / invite emails (console channel stores body for demo)."""

    __tablename__ = "outbound_mail_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tenants.id"))
    to_email: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, default="console")
    status: Mapped[str] = mapped_column(Text, default="sent")
    body_preview: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
