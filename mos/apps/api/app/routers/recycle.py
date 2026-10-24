"""Recycle bin APIs — list / restore / purge soft-deleted records."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ApiKey, User
from app.models_ai import AIConversation
from app.models_cargo import Cargo, CargoGroup, CargoName, CargoNameProperty
from app.models_coa import CoaContract
from app.models_domain import (
    BunkerOption,
    BunkerOrder,
    BunkerRequirement,
    Charter,
    CharterOffer,
    Claim,
    DqIssue,
    Estimate,
    Invoice,
    LaytimeCalc,
    MasterContract,
    OffHireEvent,
    PortCall,
    PortDisbursement,
    Voyage,
)
from app.models_office import WebhookEndpoint
from app.models_rates import PricingTemplate, RateTable
from app.models_saas import OrgUnit
from app.models_shipshore import ShipReport, ShipTerminal
from app.models_task import Task
from app.models_time_charter import TimeCharterContract
from app.models_trading import Trade
from app.models_vessel_ext import VesselPortConsumption, VesselSpeedConsumption
from app.models_voyage_ext import VoyageInstruction, VoyageNote
from app.models_wave1 import (
    Company,
    ConnectorInstance,
    Counterparty,
    CounterpartyContact,
    CounterpartyProperty,
    EmailAccount,
    Port,
    PortAlias,
    PortBerth,
    Vessel,
)
from app.security import AuthContext, get_current_auth
from app.services.recycle import get_recycle_item, item_public, list_recycle, restore_row
from app.services.timeutil import utcnow_naive

router = APIRouter(prefix="/recycle-bin", tags=["Recycle Bin"])


def _now():
    return utcnow_naive()


# entity_type -> (Model, tenant-scoped?)
ENTITY_LOOKUP: dict[str, tuple[type, bool]] = {
    "vessel": (Vessel, True),
    "port": (Port, False),
    "counterparty": (Counterparty, True),
    # —— master data 子表（IMOS Data Center parity）——
    # port_berth / port_alias 随父级 ports 为全局参照数据，故 tenant_scoped=False。
    "counterparty_property": (CounterpartyProperty, True),
    "cargo_group": (CargoGroup, True),
    "cargo_name": (CargoName, True),
    "cargo_name_property": (CargoNameProperty, True),
    "port_berth": (PortBerth, False),
    "port_alias": (PortAlias, False),
    "vessel_port_consumption": (VesselPortConsumption, True),
    "vessel_speed_consumption": (VesselSpeedConsumption, True),
    "user": (User, True),
    "api_key": (ApiKey, True),
    "org_unit": (OrgUnit, True),
    "connector": (ConnectorInstance, True),
    "estimate": (Estimate, True),
    "charter": (Charter, True),
    "voyage": (Voyage, True),
    "invoice": (Invoice, True),
    "claim": (Claim, True),
    "laytime": (LaytimeCalc, True),
    "cargo": (Cargo, True),
    "port_call": (PortCall, True),
    "off_hire_event": (OffHireEvent, True),
    "bunker_order": (BunkerOrder, True),
    "bunker_requirement": (BunkerRequirement, True),
    "bunker_option": (BunkerOption, True),
    # —— 以下类型此前缺失：记录会进回收站，但「恢复」必然 400 UNSUPPORTED_TYPE ——
    "ai_conversation": (AIConversation, True),
    "charter_offer": (CharterOffer, True),
    "coa_contract": (CoaContract, True),
    "company": (Company, True),
    "counterparty_contact": (CounterpartyContact, True),
    "dq_issue": (DqIssue, True),
    "email_account": (EmailAccount, True),
    "master_contract": (MasterContract, True),
    "port_disbursement": (PortDisbursement, True),
    "pricing_template": (PricingTemplate, True),
    "rate_table": (RateTable, True),
    "ship_report": (ShipReport, True),
    "ship_terminal": (ShipTerminal, True),
    "task": (Task, True),
    "tc_contract": (TimeCharterContract, True),
    "time_charter_contract": (TimeCharterContract, True),
    "trade": (Trade, True),
    "webhook_endpoint": (WebhookEndpoint, True),
    "voyage_notes": (VoyageNote, True),
    "voyage_instructions": (VoyageInstruction, True),
}


def _require_admin(auth: AuthContext) -> None:
    if "tenant_admin" not in auth.roles and "platform_admin" not in auth.roles:
        raise HTTPException(403, detail={"code": "ADMIN_REQUIRED"})


@router.get("")
def recycle_list(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)):
    _require_admin(auth)
    rows = list_recycle(db, auth.tenant_id)
    flags = _source_flags(db, auth.tenant_id, rows)
    out = []
    for r in rows:
        item = item_public(r)
        item.update(flags.get((r.entity_type, r.entity_id), {"restorable": True, "source_missing": False}))
        out.append(item)
    return out


def _source_flags(db: Session, tenant_id: UUID, rows) -> dict[tuple[str, str], dict]:
    """标记每条回收站条目是否可恢复 / 源记录是否已被物理删除。

    「彻底删除」目前只删回收站条目、源行仍是软删（见整改建议 P1-4），但运维脚本
    会物理删源行 —— 回收站里因此留下**悬空条目**，点「恢复」只会得到一句 "Failed"。
    这里在列表接口就给出可恢复性，前端据此禁用按钮并说明原因。
    """
    ids_by_type: dict[str, list[UUID]] = {}
    for r in rows:
        if r.entity_type not in ENTITY_LOOKUP:
            continue
        try:
            ids_by_type.setdefault(r.entity_type, []).append(UUID(r.entity_id))
        except (ValueError, AttributeError, TypeError):
            continue

    flags: dict[tuple[str, str], dict] = {}
    for et, ids in ids_by_type.items():
        model, tenant_scoped = ENTITY_LOOKUP[et]
        stmt = select(model.id).where(model.id.in_(ids))
        if tenant_scoped and "tenant_id" in model.__table__.columns:
            stmt = stmt.where(model.tenant_id == tenant_id)
        found = set(db.scalars(stmt).all())
        for i in ids:
            flags[(et, str(i))] = {"restorable": True, "source_missing": i not in found}

    for r in rows:
        if r.entity_type not in ENTITY_LOOKUP:
            flags[(r.entity_type, r.entity_id)] = {"restorable": False, "source_missing": False}
    return flags


@router.post("/{item_id}/restore")
def recycle_restore(
    item_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    _require_admin(auth)
    item = get_recycle_item(db, auth.tenant_id, item_id)
    if not item or item.restored_at:
        raise HTTPException(404, detail={"code": "NOT_FOUND"})

    et = item.entity_type
    eid = item.entity_id
    meta = ENTITY_LOOKUP.get(et)
    if not meta:
        raise HTTPException(400, detail={"code": "UNSUPPORTED_TYPE", "entity_type": et})

    model, tenant_scoped = meta
    row = db.get(model, UUID(eid))
    if not row:
        raise HTTPException(404, detail={"code": "SOURCE_MISSING"})
    if tenant_scoped and getattr(row, "tenant_id", None) != auth.tenant_id:
        raise HTTPException(404, detail={"code": "SOURCE_MISSING"})

    restore_row(row, et, item.payload if isinstance(item.payload, dict) else {})
    item.restored_at = _now()
    try:
        db.commit()
    except IntegrityError as exc:
        # P0-24：还原会撞上数据库唯一约束（例如同名对手方已经重新建过档）
        # → 409，不是 500。
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "RESTORE_CONFLICT",
                "message": (
                    f"Cannot restore {et}: it conflicts with an existing record "
                    f"(e.g. a duplicate name). Remove or rename the existing one first."
                ),
                "entity_type": et,
                "entity_id": eid,
            },
        ) from exc
    return {"ok": True, "id": str(item.id), "entity_type": et, "entity_id": eid}


@router.delete("/{item_id}")
def recycle_purge(
    item_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """Permanent purge — remove recycle entry (source row stays soft-deleted / orphaned)."""
    _require_admin(auth)
    item = get_recycle_item(db, auth.tenant_id, item_id)
    if not item:
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    item.purged_at = _now()
    db.commit()
    return {"ok": True, "purged": True}
