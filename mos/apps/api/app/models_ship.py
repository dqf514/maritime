"""Ship management domain — technical fleet for owners / managers.

Integrates with commercial Vessel masterdata; external PMS adapters sync via
Integration Hub connectors (pms.*) and /ship/integrations/* endpoints.
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
    Uuid,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ShipTechnicalProfile(Base):
    """Extended technical card linked 1:1 to commercial Vessel."""

    __tablename__ = "ship_technical_profiles"
    __table_args__ = (UniqueConstraint("vessel_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    vessel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vessels.id"), nullable=False)
    management_mode: Mapped[str] = mapped_column(Text, default="in_house")  # in_house|external_pms|hybrid
    class_society: Mapped[str | None] = mapped_column(Text)
    built_year: Mapped[int | None] = mapped_column(Integer)
    yard: Mapped[str | None] = mapped_column(Text)
    engine_maker: Mapped[str | None] = mapped_column(Text)
    engine_type: Mapped[str | None] = mapped_column(Text)
    next_drydock: Mapped[date | None] = mapped_column(Date)
    next_special_survey: Mapped[date | None] = mapped_column(Date)
    technical_status: Mapped[str] = mapped_column(Text, default="in_service")  # in_service|repair|drydock|laid_up
    superintendent: Mapped[str | None] = mapped_column(Text)
    external_pms_id: Mapped[str | None] = mapped_column(Text)
    external_system: Mapped[str | None] = mapped_column(Text)  # spectec|abs_ns|shipnet|custom
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShipCertificate(Base):
    __tablename__ = "ship_certificates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    vessel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vessels.id"), nullable=False)
    cert_code: Mapped[str] = mapped_column(Text, nullable=False)
    cert_name: Mapped[str] = mapped_column(Text, nullable=False)
    issued_on: Mapped[date | None] = mapped_column(Date)
    expires_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, default="valid")  # valid|expiring|expired|pending
    issuing_body: Mapped[str | None] = mapped_column(Text)
    external_ref: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class ShipWorkOrder(Base):
    """Planned maintenance / defect / survey job."""

    __tablename__ = "ship_work_orders"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    vessel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vessels.id"), nullable=False)
    wo_no: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, default="pms")  # pms|defect|survey|drydock|safety
    priority: Mapped[str] = mapped_column(Text, default="medium")  # low|medium|high|critical
    status: Mapped[str] = mapped_column(Text, default="open")  # open|in_progress|done|deferred|cancelled
    due_on: Mapped[date | None] = mapped_column(Date)
    completed_on: Mapped[date | None] = mapped_column(Date)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    assignee: Mapped[str | None] = mapped_column(Text)
    external_ref: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, default="voyageos")  # voyageos|external_pms (stored enum value kept for DB compatibility)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShipCrewMember(Base):
    __tablename__ = "ship_crew_members"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    vessel_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vessels.id"))
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    rank: Mapped[str] = mapped_column(Text, nullable=False)
    nationality: Mapped[str | None] = mapped_column(Text)
    contract_end: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, default="onboard")  # onboard|leave|joining|signed_off
    external_ref: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class ShipDefect(Base):
    __tablename__ = "ship_defects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    vessel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vessels.id"), nullable=False)
    defect_no: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, default="minor")  # minor|major|critical
    status: Mapped[str] = mapped_column(Text, default="open")
    found_on: Mapped[date | None] = mapped_column(Date)
    due_on: Mapped[date | None] = mapped_column(Date)
    linked_wo_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ship_work_orders.id"))
    external_ref: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class ShipSparePart(Base):
    __tablename__ = "ship_spare_parts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    vessel_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vessels.id"))
    part_no: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    qty_on_hand: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    min_qty: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    unit: Mapped[str] = mapped_column(Text, default="pcs")
    location: Mapped[str | None] = mapped_column(Text)
    external_ref: Mapped[str | None] = mapped_column(Text)


class ShipWoSpare(Base):
    """Spare-part consumption registered against a work order."""

    __tablename__ = "ship_wo_spares"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    wo_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ship_work_orders.id"), nullable=False)
    part_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ship_spare_parts.id"), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExternalPmsSyncLog(Base):
    """Audit trail for external ship-management system sync."""

    __tablename__ = "external_pms_sync_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    connector_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("connector_instances.id"))
    direction: Mapped[str] = mapped_column(Text, default="inbound")  # inbound|outbound|pull
    entity_type: Mapped[str] = mapped_column(Text, default="work_order")
    status: Mapped[str] = mapped_column(Text, default="ok")
    message: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
