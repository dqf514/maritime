"""i18n languages, UI message catalogs, maritime terminology."""

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


class Language(Base):
    __tablename__ = "languages"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)  # en, zh-CN
    name: Mapped[str] = mapped_column(Text, nullable=False)
    native_name: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(default=100)


class UiMessage(Base):
    """Platform UI string catalog (key × locale)."""

    __tablename__ = "ui_messages"
    __table_args__ = (UniqueConstraint("msg_key", "locale"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    msg_key: Mapped[str] = mapped_column(Text, nullable=False)
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    namespace: Mapped[str] = mapped_column(Text, default="app")  # app|nav|error|email|pdf
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TerminologyTerm(Base):
    """Core maritime terminology (platform catalog)."""

    __tablename__ = "terminology_terms"
    __table_args__ = (UniqueConstraint("term_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    term_key: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, default="general")
    en: Mapped[str] = mapped_column(Text, nullable=False)
    zh_cn: Mapped[str] = mapped_column(Text, nullable=False)
    definition_en: Mapped[str | None] = mapped_column(Text)
    definition_zh_cn: Mapped[str | None] = mapped_column(Text)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(Text, default="approved")  # draft|approved|deprecated
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantTerminologyOverride(Base):
    __tablename__ = "tenant_terminology_overrides"
    __table_args__ = (UniqueConstraint("tenant_id", "term_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    term_key: Mapped[str] = mapped_column(Text, nullable=False)
    locale: Mapped[str] = mapped_column(String(16), default="en")
    label: Mapped[str] = mapped_column(Text, nullable=False)
    definition: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="approved")  # pending|approved
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantI18nSettings(Base):
    __tablename__ = "tenant_i18n_settings"
    __table_args__ = (UniqueConstraint("tenant_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    default_locale: Mapped[str] = mapped_column(String(16), default="en")
    allowed_locales: Mapped[list] = mapped_column(JSON, default=lambda: ["en", "zh-CN"])
    allow_user_override: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
