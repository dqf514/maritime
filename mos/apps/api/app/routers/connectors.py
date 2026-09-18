from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_wave1 import ConnectorInstance
from app.schemas_wave1 import ConnectorIn, ConnectorOut
from app.security import AuthContext, require_module
from app.services import office_hub as office_hub
from app.services.graph_client import graph_mode_resolved
from app.services.ms_config import resolve_ms_config
from app.services.integration_adapters import (
    OFFICE_TYPES,
    catalog_public,
    sync_adapter,
    test_adapter,
)
from app.services.recycle import soft_delete

router = APIRouter(prefix="/settings/connectors", tags=["Integration Hub"])


@router.get("/catalog")
def connector_catalog(
    locale: str | None = None,
    auth: AuthContext = Depends(require_module("integration")),
):
    _ = auth
    loc = locale or getattr(auth.user, "locale", None) or "en"
    return catalog_public(loc)


@router.get("", response_model=list[ConnectorOut])
def list_connectors(
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(ConnectorInstance).where(
            ConnectorInstance.tenant_id == auth.tenant_id,
            ConnectorInstance.status != "deleted",
        )
    ).all()
    return [ConnectorOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("", response_model=ConnectorOut)
def create_connector(
    body: ConnectorIn,
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    row = ConnectorInstance(
        tenant_id=auth.tenant_id,
        status="draft",
        last_health={},
        **body.model_dump(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ConnectorOut.model_validate(row, from_attributes=True)


class ConnectorPatch(BaseModel):
    connector_type: str | None = None
    instance_name: str | None = None
    endpoint: str | None = None
    secret_ref: str | None = None
    config: dict | None = None
    status: str | None = None


@router.patch("/{connector_id}", response_model=ConnectorOut)
def update_connector(
    connector_id: UUID,
    body: ConnectorPatch,
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    row = db.get(ConnectorInstance, connector_id)
    if not row or row.tenant_id != auth.tenant_id or row.status == "deleted":
        raise HTTPException(404, "Connector not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        if k == "status" and v == "deleted":
            continue
        setattr(row, k, v)
    row.updated_at = datetime.now().astimezone()
    db.commit()
    db.refresh(row)
    return ConnectorOut.model_validate(row, from_attributes=True)


@router.delete("/{connector_id}")
def delete_connector(
    connector_id: UUID,
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    row = db.get(ConnectorInstance, connector_id)
    if not row or row.tenant_id != auth.tenant_id or row.status == "deleted":
        raise HTTPException(404, "Connector not found")
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="connector",
        row=row,
        title=row.instance_name,
    )
    db.commit()
    return {"ok": True, "recycled": True}


@router.post("/{connector_id}/test", response_model=ConnectorOut)
def test_connector(
    connector_id: UUID,
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    row = db.get(ConnectorInstance, connector_id)
    if not row or row.tenant_id != auth.tenant_id or row.status == "deleted":
        raise HTTPException(404, "Connector not found")
    office_health = None
    if row.connector_type in OFFICE_TYPES:
        mode = graph_mode_resolved(resolve_ms_config(db, auth.tenant_id))
        try:
            client = office_hub.get_graph_client(db, auth.tenant_id)
            office_health = {**client.health(), "graph_mode": mode}
        except Exception as exc:  # noqa: BLE001
            office_health = {"ok": False, "error": str(exc), "graph_mode": mode}
    health = test_adapter(row, office_health=office_health)
    row.last_health = health
    row.status = "active" if health.get("ok") else "error"
    row.updated_at = datetime.now().astimezone()
    db.commit()
    db.refresh(row)
    return ConnectorOut.model_validate(row, from_attributes=True)


@router.post("/{connector_id}/sync")
def sync_connector(
    connector_id: UUID,
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    row = db.get(ConnectorInstance, connector_id)
    if not row or row.tenant_id != auth.tenant_id or row.status == "deleted":
        raise HTTPException(404, "Connector not found")
    summary = sync_adapter(db, row, tenant_id=auth.tenant_id)
    row.last_health = {**(row.last_health or {}), "last_sync": summary}
    if summary.get("ok"):
        row.status = "active"
    row.updated_at = datetime.now().astimezone()
    db.commit()
    return summary
