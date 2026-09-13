"""Recycle bin APIs — list / restore / purge soft-deleted records."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ApiKey, User
from app.models_domain import Charter, Claim, Estimate, Invoice, LaytimeCalc, Voyage
from app.models_saas import OrgUnit
from app.models_wave1 import ConnectorInstance, Counterparty, Port, Vessel
from app.security import AuthContext, get_current_auth
from app.services.recycle import get_recycle_item, item_public, list_recycle, restore_row

router = APIRouter(prefix="/recycle-bin", tags=["Recycle Bin"])


def _now():
    return datetime.now(timezone.utc).astimezone()


# entity_type -> (Model, tenant-scoped?)
ENTITY_LOOKUP: dict[str, tuple[type, bool]] = {
    "vessel": (Vessel, True),
    "port": (Port, False),
    "counterparty": (Counterparty, True),
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
}


@router.get("")
def recycle_list(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)):
    rows = list_recycle(db, auth.tenant_id)
    return [item_public(r) for r in rows]


@router.post("/{item_id}/restore")
def recycle_restore(
    item_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    if "tenant_admin" not in auth.roles and "platform_admin" not in auth.roles:
        raise HTTPException(403, detail={"code": "ADMIN_REQUIRED"})
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
    db.commit()
    return {"ok": True, "id": str(item.id), "entity_type": et, "entity_id": eid}


@router.delete("/{item_id}")
def recycle_purge(
    item_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """Permanent purge — remove recycle entry (source row stays soft-deleted / orphaned)."""
    if "tenant_admin" not in auth.roles and "platform_admin" not in auth.roles:
        raise HTTPException(403, detail={"code": "ADMIN_REQUIRED"})
    item = get_recycle_item(db, auth.tenant_id, item_id)
    if not item:
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    item.purged_at = _now()
    db.commit()
    return {"ok": True, "purged": True}
