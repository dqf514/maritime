"""Soft delete helpers — mark deleted_at / status and write recycle snapshot."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_recycle import RecycleBinItem

# Default status when restoring if payload has no usable prior status
DEFAULT_RESTORE_STATUS: dict[str, str] = {
    "vessel": "active",
    "user": "active",
    "api_key": "active",
    "org_unit": "active",
    "connector": "draft",
    "estimate": "draft",
    "charter": "draft",
    "voyage": "planned",
    "invoice": "draft",
    "claim": "open",
    "laytime": "draft",
}


def _now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def _jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(x) for x in obj]
    return str(obj)


def row_to_payload(row: Any) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for col in row.__table__.columns:
        data[col.name] = _jsonable(getattr(row, col.name, None))
    return sanitize_payload(data, entity=row)


# Columns never persisted into recycle snapshots
SENSITIVE_COLUMNS = {"password_hash", "key_hash", "secret_ref"}


def _secret_config_keys(connector_type: str | None) -> set[str]:
    if not connector_type:
        return set()
    from app.services.integration_adapters import CATALOG

    for entry in CATALOG:
        if entry.get("connector_type") == connector_type:
            return {f["key"] for f in entry.get("config_schema", []) if f.get("secret")}
    return set()


def sanitize_payload(data: dict[str, Any], *, entity: Any = None) -> dict[str, Any]:
    """Strip credentials from a recycle snapshot payload."""
    out = {k: v for k, v in data.items() if k not in SENSITIVE_COLUMNS}
    config = out.get("config")
    if isinstance(config, dict):
        declared = _secret_config_keys(getattr(entity, "connector_type", None))
        masked = dict(config)
        for key, value in masked.items():
            if key in declared or "secret" in key.lower():
                if value not in (None, ""):
                    masked[key] = "***"
        out["config"] = masked
    return out


def soft_delete(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: UUID | None,
    entity_type: str,
    row: Any,
    title: str,
) -> RecycleBinItem:
    """Mark row soft-deleted and enqueue recycle bin item."""
    payload = row_to_payload(row)
    entity_id = str(getattr(row, "id"))
    if hasattr(row, "deleted_at"):
        row.deleted_at = _now()
    if hasattr(row, "status"):
        row.status = "deleted"
    if hasattr(row, "updated_at"):
        row.updated_at = _now()

    item = RecycleBinItem(
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        title=title,
        payload=payload,
        deleted_by=user_id,
        deleted_at=_now(),
    )
    db.add(item)
    db.flush()
    return item


def restore_row(row: Any, entity_type: str, payload: dict[str, Any] | None) -> None:
    """Undo soft-delete on a live ORM row using recycle payload."""
    if hasattr(row, "deleted_at"):
        row.deleted_at = None
    if hasattr(row, "status"):
        prev = (payload or {}).get("status")
        if prev and prev != "deleted":
            row.status = str(prev)
        else:
            row.status = DEFAULT_RESTORE_STATUS.get(entity_type, "active")
    if hasattr(row, "updated_at"):
        row.updated_at = _now()


def list_recycle(db: Session, tenant_id: UUID, *, include_restored: bool = False) -> list[RecycleBinItem]:
    stmt = select(RecycleBinItem).where(
        RecycleBinItem.tenant_id == tenant_id,
        RecycleBinItem.purged_at.is_(None),
    )
    if not include_restored:
        stmt = stmt.where(RecycleBinItem.restored_at.is_(None))
    return list(db.scalars(stmt.order_by(RecycleBinItem.deleted_at.desc())).all())


def get_recycle_item(db: Session, tenant_id: UUID, item_id: UUID) -> RecycleBinItem | None:
    row = db.get(RecycleBinItem, item_id)
    if not row or row.tenant_id != tenant_id or row.purged_at is not None:
        return None
    return row


def item_public(row: RecycleBinItem) -> dict[str, Any]:
    payload = row.payload if isinstance(row.payload, dict) else {}
    return {
        "id": str(row.id),
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "title": row.title,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
        "restored_at": row.restored_at.isoformat() if row.restored_at else None,
        "payload": sanitize_payload(payload),
    }


_ = json
