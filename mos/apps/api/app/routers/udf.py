"""C4-P3 数据字典 / UDF 管理 — user-defined field definitions CRUD.

Scope note (values): UDF **values** are NOT stored in a per-record JSON column.
They live in the side table ``udf_values`` and are already exposed via the
legacy config routes (``GET/PUT /api/v1/config/udf/{entity_type}/...``).
This router therefore covers **definitions** only (dictionary management),
plus the entity registry. See plan item C4-P3.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_config import UdfDefinition, UdfValue
from app.security import AuthContext, require_module
from app.services.tenant_guard import scoped_get, scoped_query

router = APIRouter(prefix="/udf", tags=["udf"])

# Canonical field types accepted by the dictionary API (plan C4-P3).
FIELD_TYPES = ("text", "number", "date", "select")
# Legacy types still present in older rows / the /config/udf routes.
_TYPE_ALIASES = {"string": "text", "boolean": "text"}

# field_key slug: lowercase letter, then lowercase alnum / underscore.
_FIELD_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# Entities that may host UDFs (数据字典可扩展对象). Mirrors the core domain
# entity names used across masterdata / operations / finance.
UDF_ENTITIES: dict[str, str] = {
    "vessel": "Vessel",
    "voyage": "Voyage",
    "charter": "Charter",
    "estimate": "Estimate",
    "cargo": "Cargo",
    "counterparty": "Counterparty",
    "port": "Port",
    "invoice": "Invoice",
    "claim": "Claim",
    "laytime": "Laytime",
    "bunker": "Bunker",
    "coa": "COA",
}


def _normalize_type(raw: str) -> str:
    t = (raw or "").strip().lower()
    t = _TYPE_ALIASES.get(t, t)
    if t not in FIELD_TYPES:
        raise HTTPException(
            422,
            detail={
                "code": "INVALID_FIELD_TYPE",
                "message": f"field_type must be one of {FIELD_TYPES}",
            },
        )
    return t


def _validate_entity(entity: str) -> None:
    if entity not in UDF_ENTITIES:
        raise HTTPException(
            422,
            detail={"code": "UNKNOWN_ENTITY", "message": f"unknown entity '{entity}'"},
        )


def _validate_field_key(field_key: str) -> None:
    if not _FIELD_KEY_RE.match(field_key or ""):
        raise HTTPException(
            422,
            detail={
                "code": "INVALID_FIELD_KEY",
                "message": "field_key must match ^[a-z][a-z0-9_]{0,63}$ (slug format)",
            },
        )


def _to_options(raw: Any) -> dict | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return {"choices": list(raw)}
    raise HTTPException(
        422,
        detail={"code": "INVALID_OPTIONS", "message": "options must be a list or object"},
    )


class UdfDefinitionIn(BaseModel):
    entity: str = Field(min_length=1, max_length=64)
    field_key: str = Field(min_length=1, max_length=64)
    label_en: str | None = Field(default=None, max_length=128)
    label_zh: str | None = Field(default=None, max_length=128)
    field_type: str = "text"
    options: list[str] | dict | None = None
    required: bool = False
    active: bool = True
    sort_order: int = 0

    @field_validator("field_key")
    @classmethod
    def _slug_key(cls, v: str) -> str:
        if not _FIELD_KEY_RE.match(v or ""):
            raise ValueError("field_key must match ^[a-z][a-z0-9_]{0,63}$ (slug format)")
        return v


class UdfDefinitionPatch(BaseModel):
    label_en: str | None = Field(default=None, max_length=128)
    label_zh: str | None = Field(default=None, max_length=128)
    field_type: str | None = None
    options: list[str] | dict | None = None
    required: bool | None = None
    active: bool | None = None
    sort_order: int | None = None


class UdfDefinitionOut(BaseModel):
    id: str
    entity: str
    field_key: str
    label_en: str | None
    label_zh: str | None
    field_type: str
    options: dict | list | None
    required: bool
    active: bool
    sort_order: int
    created_at: str | None = None


def _display_label(d: UdfDefinition) -> str:
    return d.label_en or d.label_zh or d.field_label or d.field_key


def _to_out(d: UdfDefinition) -> UdfDefinitionOut:
    return UdfDefinitionOut(
        id=str(d.id),
        entity=d.entity_type,
        field_key=d.field_key,
        label_en=d.label_en,
        label_zh=d.label_zh,
        field_type=_TYPE_ALIASES.get(d.field_type, d.field_type),
        options=d.options_json,
        required=bool(d.required),
        active=bool(d.active) if d.active is not None else True,
        sort_order=int(d.sort_order or 0),
        created_at=d.created_at.isoformat() if d.created_at else None,
    )


@router.get("/entities")
def list_entities(auth: AuthContext = Depends(require_module("admin"))):
    """Entity registry (数据字典支持的业务对象)."""
    _ = auth
    return [{"entity": name, "label": label} for name, label in UDF_ENTITIES.items()]


@router.get("", response_model=list[UdfDefinitionOut])
def list_definitions(
    entity: str | None = Query(None),
    include_inactive: bool = Query(False),
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    """List UDF definitions for the current tenant.

    Returns active definitions by default; pass ``include_inactive=true``
    (admin dictionary view) to also see disabled ones. Filter by ``entity``.
    """
    if entity is not None:
        _validate_entity(entity)
    stmt = scoped_query(db, UdfDefinition, auth.tenant_id)
    if entity:
        stmt = stmt.where(UdfDefinition.entity_type == entity)
    if not include_inactive:
        stmt = stmt.where(UdfDefinition.active.is_(True))
    rows = db.scalars(
        stmt.order_by(UdfDefinition.entity_type, UdfDefinition.sort_order, UdfDefinition.field_key)
    ).all()
    return [_to_out(r) for r in rows]


@router.post("", response_model=UdfDefinitionOut, status_code=201)
def create_definition(
    body: UdfDefinitionIn,
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    """Create a UDF definition. Duplicate entity+field_key → 409."""
    _validate_entity(body.entity)
    _validate_field_key(body.field_key)  # also enforced by pydantic; keeps 422 code
    field_type = _normalize_type(body.field_type)
    if field_type == "select" and not body.options:
        raise HTTPException(
            422,
            detail={"code": "OPTIONS_REQUIRED", "message": "select fields require options"},
        )
    options = _to_options(body.options)

    existing = db.scalar(
        select(UdfDefinition).where(
            UdfDefinition.tenant_id == auth.tenant_id,
            UdfDefinition.entity_type == body.entity,
            UdfDefinition.field_key == body.field_key,
        )
    )
    if existing:
        raise HTTPException(
            409,
            detail={
                "code": "UDF_EXISTS",
                "message": f"UDF '{body.field_key}' already exists on entity '{body.entity}'",
            },
        )

    label = body.label_en or body.label_zh or body.field_key
    row = UdfDefinition(
        tenant_id=auth.tenant_id,
        entity_type=body.entity,
        field_key=body.field_key,
        field_label=label,
        label_en=body.label_en,
        label_zh=body.label_zh,
        field_type=field_type,
        options_json=options,
        required=body.required,
        active=body.active,
        sort_order=body.sort_order,
        created_by=auth.user_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.patch("/{definition_id}", response_model=UdfDefinitionOut)
def update_definition(
    definition_id: UUID,
    body: UdfDefinitionPatch,
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    """Update a UDF definition (labels / type / options / required / active / sort)."""
    row = scoped_get(db, UdfDefinition, definition_id, auth.tenant_id)
    if not row:
        raise HTTPException(404, "UDF definition not found")

    data = body.model_dump(exclude_unset=True)
    if "field_type" in data and data["field_type"] is not None:
        data["field_type"] = _normalize_type(data["field_type"])
    if "options" in data:
        data["options"] = _to_options(data["options"])
        # map API name → column name
        data["options_json"] = data.pop("options")
    if data.get("field_type") == "select" and not data.get("options_json", row.options_json):
        raise HTTPException(
            422,
            detail={"code": "OPTIONS_REQUIRED", "message": "select fields require options"},
        )

    if "label_en" in data or "label_zh" in data:
        label_en = data.get("label_en", row.label_en)
        label_zh = data.get("label_zh", row.label_zh)
        row.field_label = label_en or label_zh or row.field_key

    for k, v in data.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.delete("/{definition_id}")
def delete_definition(
    definition_id: UUID,
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    """Hard-delete a UDF definition and its stored values.

    UdfDefinition has no ``deleted_at`` / ``status`` column (unlike recycle-bin
    entities), so this follows the hard-delete convention used by sibling
    config tables (see field_perms / config flags). Values cascade via the
    explicit ``UdfValue`` cleanup.
    """
    row = scoped_get(db, UdfDefinition, definition_id, auth.tenant_id)
    if not row:
        raise HTTPException(404, "UDF definition not found")
    db.execute(delete(UdfValue).where(UdfValue.definition_id == row.id))
    db.delete(row)
    db.commit()
    return {"ok": True}
