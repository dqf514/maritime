"""Field-level permissions API (字段级权限管理)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_field_perms import FieldPermission
from app.schemas_wave1 import CounterpartyIn, PortIn, VesselIn
from app.security import AuthContext, require_roles

router = APIRouter(prefix="/field-permissions", tags=["field-permissions"])

MODES = ("read", "write", "hidden")

# Registry of managed entities and their permission-relevant field names.
# Derived from the write schemas where cheap; invoice kept explicit (update-schema lives in the router).
ENTITY_FIELDS: dict[str, list[str]] = {
    "counterparty": sorted(CounterpartyIn.model_fields.keys()),
    "vessel": sorted(VesselIn.model_fields.keys()),
    "port": sorted(PortIn.model_fields.keys()),
    "invoice": [
        "amount",
        "tax_amount",
        "due_date",
        "invoice_type",
        "bill_by",
        "commission_basis",
    ],
}


class FieldPermIn(BaseModel):
    entity: str = Field(min_length=1, max_length=64)
    field: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=64)
    mode: str = Field(default="read")
    active: bool = True


class FieldPermPatch(BaseModel):
    mode: str | None = None
    active: bool | None = None
    field: str | None = None
    role: str | None = None
    entity: str | None = None


class FieldPermOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    entity: str
    field: str
    role: str
    mode: str
    active: bool
    created_at: datetime | None = None


def _validate_mode(mode: str) -> None:
    if mode not in MODES:
        raise HTTPException(422, detail={"code": "INVALID_FIELD_MODE", "message": f"mode must be one of {MODES}"})


def _validate_entity_field(entity: str, field: str) -> None:
    known = ENTITY_FIELDS.get(entity)
    if known is not None and field not in known:
        raise HTTPException(
            422,
            detail={"code": "UNKNOWN_ENTITY_FIELD", "message": f"{entity}.{field} is not a registered field"},
        )


def _validate_entity(entity: str) -> None:
    if entity not in ENTITY_FIELDS:
        raise HTTPException(
            422,
            detail={"code": "UNKNOWN_ENTITY", "message": f"unknown entity '{entity}'"},
        )


@router.get("/entities")
def list_entities(auth: AuthContext = Depends(require_roles("tenant_admin", "platform_admin"))):
    """Registered entities and their field names (for the permissions matrix)."""
    _ = auth
    return [{"entity": name, "fields": fields} for name, fields in ENTITY_FIELDS.items()]


@router.get("", response_model=list[FieldPermOut])
def list_rules(
    entity: str | None = Query(None),
    role: str | None = Query(None),
    auth: AuthContext = Depends(require_roles("tenant_admin", "platform_admin")),
    db: Session = Depends(get_db),
):
    stmt = select(FieldPermission).where(FieldPermission.tenant_id == auth.tenant_id)
    if entity:
        stmt = stmt.where(FieldPermission.entity == entity)
    if role:
        stmt = stmt.where(FieldPermission.role == role)
    rows = db.scalars(stmt.order_by(FieldPermission.entity, FieldPermission.field, FieldPermission.role)).all()
    return [FieldPermOut.model_validate(r) for r in rows]


@router.post("", response_model=FieldPermOut, status_code=201)
def create_rule(
    body: FieldPermIn,
    auth: AuthContext = Depends(require_roles("tenant_admin", "platform_admin")),
    db: Session = Depends(get_db),
):
    _validate_mode(body.mode)
    _validate_entity(body.entity)
    _validate_entity_field(body.entity, body.field)
    existing = db.scalar(
        select(FieldPermission).where(
            FieldPermission.tenant_id == auth.tenant_id,
            FieldPermission.entity == body.entity,
            FieldPermission.field == body.field,
            FieldPermission.role == body.role,
        )
    )
    if existing:
        raise HTTPException(
            409,
            detail={"code": "FIELD_PERM_EXISTS", "message": "rule already exists for tenant+entity+field+role"},
        )
    row = FieldPermission(tenant_id=auth.tenant_id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return FieldPermOut.model_validate(row)


@router.patch("/{rule_id}", response_model=FieldPermOut)
def update_rule(
    rule_id: UUID,
    body: FieldPermPatch,
    auth: AuthContext = Depends(require_roles("tenant_admin", "platform_admin")),
    db: Session = Depends(get_db),
):
    row = db.get(FieldPermission, rule_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Field permission not found")
    data = body.model_dump(exclude_unset=True)
    if "mode" in data and data["mode"] is not None:
        _validate_mode(data["mode"])
    new_entity = data.get("entity", row.entity)
    new_field = data.get("field", row.field)
    new_role = data.get("role", row.role)
    _validate_entity(new_entity)
    _validate_entity_field(new_entity, new_field)
    dup = db.scalar(
        select(FieldPermission).where(
            FieldPermission.tenant_id == auth.tenant_id,
            FieldPermission.entity == new_entity,
            FieldPermission.field == new_field,
            FieldPermission.role == new_role,
            FieldPermission.id != row.id,
        )
    )
    if dup:
        raise HTTPException(
            409,
            detail={"code": "FIELD_PERM_EXISTS", "message": "rule already exists for tenant+entity+field+role"},
        )
    for k, v in data.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return FieldPermOut.model_validate(row)


@router.delete("/{rule_id}")
def delete_rule(
    rule_id: UUID,
    auth: AuthContext = Depends(require_roles("tenant_admin", "platform_admin")),
    db: Session = Depends(get_db),
):
    row = db.get(FieldPermission, rule_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Field permission not found")
    db.delete(row)
    db.commit()
    return {"ok": True}
