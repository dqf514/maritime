from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_wave1 import ConnectorInstance
from app.schemas_wave1 import ConnectorIn, ConnectorOut
from app.security import AuthContext, require_module_role
from app.services.audit import audit
from app.services import office_hub as office_hub
from app.services.graph_client import graph_mode_resolved
from app.services.ms_config import resolve_ms_config
from app.services.integration_adapters import (
    OFFICE_TYPES,
    SECRET_MASK,
    catalog_public,
    decrypt_config_secrets,
    encrypt_config_secrets,
    mask_config_secrets,
    sync_adapter,
    test_adapter,
)
from app.services.recycle import soft_delete
from app.services.timeutil import utcnow_naive

router = APIRouter(prefix="/settings/connectors", tags=["Integration Hub"])


def _connector_out(row: ConnectorInstance) -> ConnectorOut:
    """连接器响应 —— **密钥字段脱敏**（P0-19）。

    ``ConnectorOut`` 继承 ``ConnectorIn``，``config`` 整块被原样回吐：目录里
    标了 ``secret=True`` 的 ``password`` / ``api_key`` / ``auth_header`` /
    ``inbound_secret`` 于是**任何登录用户**（含 viewer）都能读到管理员配的
    凭据。这里把密钥值换成 ``***``；前端编辑框回传 ``***`` 时服务端保留原值
    （见 :func:`_merge_config`），所以编辑流程不受影响。
    """
    return ConnectorOut(
        id=row.id,
        connector_type=row.connector_type,
        instance_name=row.instance_name,
        endpoint=row.endpoint,
        secret_ref=SECRET_MASK if row.secret_ref else None,
        config=mask_config_secrets(row.connector_type, row.config),
        status=row.status,
        last_health=row.last_health or {},
    )


def _merge_config(
    existing: dict | None,
    incoming: dict | None,
    connector_type: str | None,
) -> dict:
    """合并配置并加密落库。

    - 回传的 ``***`` 表示「保持原值不变」（前端编辑框只回显掩码）；
    - 其余值按目录的 ``secret=True`` 标记加密（``v1:`` 前缀，兼容历史明文）。
    """
    old = dict(existing or {})
    new = dict(incoming or {})
    merged: dict = {}
    for key, value in new.items():
        if value == SECRET_MASK and key in old:
            merged[key] = old[key]
        else:
            merged[key] = value
    # 保留本次未提交的旧键（避免 PATCH 丢字段）
    for key, value in old.items():
        merged.setdefault(key, value)
    return encrypt_config_secrets(connector_type, merged)


@router.get("/catalog")
def connector_catalog(
    locale: str | None = None,
    auth: AuthContext = Depends(require_module_role("integration")),
):
    _ = auth
    loc = locale or getattr(auth.user, "locale", None) or "en"
    return catalog_public(loc)


@router.get("", response_model=list[ConnectorOut])
def list_connectors(
    auth: AuthContext = Depends(require_module_role("integration")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(ConnectorInstance).where(
            ConnectorInstance.tenant_id == auth.tenant_id,
            ConnectorInstance.status != "deleted",
        )
    ).all()
    return [_connector_out(r) for r in rows]


@router.post("", response_model=ConnectorOut)
def create_connector(
    body: ConnectorIn,
    auth: AuthContext = Depends(require_module_role("integration")),
    db: Session = Depends(get_db),
):
    data = body.model_dump()
    # P0-19：密钥字段**加密落库**（不再明文存 password / api_key …）
    data["config"] = encrypt_config_secrets(body.connector_type, data.get("config") or {})
    row = ConnectorInstance(
        tenant_id=auth.tenant_id,
        status="draft",
        last_health={},
        **data,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(
        db,
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        action="connector.created",
        entity_type="connector",
        entity_id=row.id,
        detail={"connector_type": row.connector_type, "instance_name": row.instance_name},
    )
    return _connector_out(row)


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
    auth: AuthContext = Depends(require_module_role("integration")),
    db: Session = Depends(get_db),
):
    row = db.get(ConnectorInstance, connector_id)
    if not row or row.tenant_id != auth.tenant_id or row.status == "deleted":
        raise HTTPException(404, "Connector not found")
    data = body.model_dump(exclude_unset=True)
    if "config" in data:
        # P0-19：合并（``***`` = 保持原值）+ 加密落库
        data["config"] = _merge_config(row.config, data["config"], row.connector_type)
    if data.get("secret_ref") == SECRET_MASK:
        # 掩码回传 = 「保持原值」—— 与 config 同一口径。
        # 否则前端把只读回显的 "***" 原样写回去，连接器凭据当场报废。
        data["secret_ref"] = row.secret_ref
    for k, v in data.items():
        if k == "status" and v == "deleted":
            continue
        setattr(row, k, v)
    row.updated_at = utcnow_naive()
    db.commit()
    db.refresh(row)
    audit(
        db,
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        action="connector.updated",
        entity_type="connector",
        entity_id=row.id,
        detail={"connector_type": row.connector_type, "instance_name": row.instance_name},
    )
    return _connector_out(row)


@router.delete("/{connector_id}")
def delete_connector(
    connector_id: UUID,
    auth: AuthContext = Depends(require_module_role("integration")),
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
    auth: AuthContext = Depends(require_module_role("integration")),
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
    row.updated_at = utcnow_naive()
    db.commit()
    db.refresh(row)
    return _connector_out(row)


@router.post("/{connector_id}/sync")
def sync_connector(
    connector_id: UUID,
    auth: AuthContext = Depends(require_module_role("integration")),
    db: Session = Depends(get_db),
):
    row = db.get(ConnectorInstance, connector_id)
    if not row or row.tenant_id != auth.tenant_id or row.status == "deleted":
        raise HTTPException(404, "Connector not found")
    summary = sync_adapter(db, row, tenant_id=auth.tenant_id)
    row.last_health = {**(row.last_health or {}), "last_sync": summary}
    if summary.get("ok"):
        row.status = "active"
    row.updated_at = utcnow_naive()
    db.commit()
    return summary
