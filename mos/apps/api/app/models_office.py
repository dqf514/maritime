"""Office / Microsoft 365 ecosystem models — Teams, SharePoint, OneDrive, Mail, Webhooks."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class OfficeTenantLink(Base):
    """Per-tenant Microsoft 365 / Office ecosystem binding."""

    __tablename__ = "office_tenant_links"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(Text, default="draft")  # draft|connected|error|disabled
    # Graph scopes granted / requested
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    # Cached tokens (server-only), Fernet-encrypted at rest via ops_crypto (v1: prefix)
    access_token: Mapped[str | None] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    graph_tenant_id: Mapped[str | None] = mapped_column(Text)  # Entra tenant GUID
    connected_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    # Feature toggles
    mail_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    files_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    teams_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sharepoint_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    calendar_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Defaults: SharePoint site / drive / Teams channel
    defaults: Mapped[dict] = mapped_column(JSON, default=dict)
    last_health: Mapped[dict] = mapped_column(JSON, default=dict)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class OfficeResourceLink(Base):
    """Maps a MariOS entity to an Office resource (file, folder, chat, channel, list item)."""

    __tablename__ = "office_resource_links"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)  # charter|voyage|estimate|invoice|claim|document|...
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(Text, default="microsoft")  # microsoft
    resource_kind: Mapped[str] = mapped_column(Text, nullable=False)  # drive_item|sharepoint_list|teams_channel|mail|calendar|folder
    resource_id: Mapped[str] = mapped_column(Text, nullable=False)
    web_url: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OfficeSyncJob(Base):
    """Inbound/outbound sync job between MariOS and M365."""

    __tablename__ = "office_sync_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(Text, default="inbound")  # inbound|outbound|bidirectional
    channel: Mapped[str] = mapped_column(Text, nullable=False)  # mail|onedrive|sharepoint|teams
    status: Mapped[str] = mapped_column(Text, default="queued")  # queued|running|done|failed
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebhookEndpoint(Base):
    """Outbound webhooks for partners / Power Automate / Teams Workflows."""

    __tablename__ = "webhook_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    secret: Mapped[str] = mapped_column(Text, nullable=False)
    events: Mapped[list] = mapped_column(JSON, default=list)  # ["charter.activated","invoice.issued",...]
    status: Mapped[str] = mapped_column(Text, default="active")
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_delivery: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("webhook_endpoints.id"), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    event: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(Text, default="pending")  # pending|delivered|failed
    response_code: Mapped[int | None] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OfficeAddonInstall(Base):
    """Tracks Office / Teams add-in installations for a tenant."""

    __tablename__ = "office_addon_installs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    addon_id: Mapped[str] = mapped_column(String(64), nullable=False)  # outlook|teams|excel|word|powerpoint
    version: Mapped[str] = mapped_column(Text, default="1.0.0")
    status: Mapped[str] = mapped_column(Text, default="available")  # available|installed|disabled
    install_meta: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
