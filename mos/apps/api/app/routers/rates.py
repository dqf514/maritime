"""Phase 4 rate tables — 运价/费率表、费率行、定价模板路由。

Mounted at ``/api/v1/rates``. All access is tenant-scoped via
``scoped_get`` / ``scoped_query`` (services.tenant_guard).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_rates import RATE_TABLE_KINDS, RATE_UNITS, PricingTemplate, RateTable, RateTableRow
from app.pagination import envelope, paginate
from app.security import AuthContext, require_module
from app.services.recycle import soft_delete
from app.services.tenant_guard import scoped_get, scoped_query
from app.services.rates import (
    list_rate_rows,
    resolve_pricing,
    resolve_rate_row,
    upsert_rate_row,
    validate_rate_table,
)

router = APIRouter(prefix="/rates", tags=["Rate Tables"])


# —— schemas ——


class RateTableIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    kind: str
    currency: str = "USD"
    valid_from: date | None = None
    valid_to: date | None = None
    description: str | None = None
    is_active: bool = True


class RateTablePatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    kind: str | None = None
    currency: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    description: str | None = None
    is_active: bool | None = None


class RateRowIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dims: dict = Field(default_factory=dict)
    value: float
    unit: str | None = None
    priority: int = 0
    notes: str | None = None


class RateRowPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dims: dict | None = None
    value: float | None = None
    unit: str | None = None
    priority: int | None = None
    notes: str | None = None


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dims: dict = Field(default_factory=dict)
    as_of: date | None = None


class PricingTemplateIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str | None = None
    rate_table_refs: dict = Field(default_factory=dict)
    rules: dict = Field(default_factory=dict)
    is_active: bool = True


class PricingTemplatePatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    description: str | None = None
    rate_table_refs: dict | None = None
    rules: dict | None = None
    is_active: bool | None = None


def _table_out(r: RateTable) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "name": r.name,
        "kind": r.kind,
        "currency": r.currency,
        "valid_from": r.valid_from.isoformat() if r.valid_from else None,
        "valid_to": r.valid_to.isoformat() if r.valid_to else None,
        "description": r.description,
        "is_active": r.is_active,
    }


def _template_out(r: PricingTemplate) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "name": r.name,
        "description": r.description,
        "rate_table_refs": {k: str(v) for k, v in (r.rate_table_refs or {}).items()},
        "rules": r.rules or {},
        "is_active": r.is_active,
    }


def _check_kind(kind: str) -> None:
    if kind not in RATE_TABLE_KINDS:
        raise HTTPException(422, detail={"code": "INVALID_RATE_TABLE_KIND", "kind": kind, "allowed": list(RATE_TABLE_KINDS)})


def _check_unit(unit: str | None) -> None:
    if unit is not None and unit not in RATE_UNITS:
        raise HTTPException(422, detail={"code": "INVALID_RATE_UNIT", "unit": unit, "allowed": list(RATE_UNITS)})


# —— rate tables ——


@router.get("/tables")
def list_tables(
    kind: str | None = Query(None),
    active: bool | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    stmt = scoped_query(db, RateTable, auth.tenant_id).where(RateTable.tenant_id == auth.tenant_id)
    if kind:
        stmt = stmt.where(RateTable.kind == kind)
    if active is not None:
        stmt = stmt.where(RateTable.is_active == active)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(RateTable.name.ilike(like))
    stmt = stmt.order_by(RateTable.name)
    rows, total = paginate(db, stmt, limit, offset)
    return envelope([_table_out(r) for r in rows], total, limit, offset)


@router.post("/tables")
def create_table(
    body: RateTableIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _check_kind(body.kind)
    row = RateTable(
        tenant_id=auth.tenant_id,
        name=body.name,
        kind=body.kind,
        currency=(body.currency or "USD").upper(),
        valid_from=body.valid_from,
        valid_to=body.valid_to,
        description=body.description,
        is_active=body.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _table_out(row)


@router.get("/tables/{table_id}")
def get_table(
    table_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, RateTable, table_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, "Rate table not found")
    out = _table_out(row)
    out["row_count"] = len(
        db.scalars(
            scoped_query(db, RateTableRow, auth.tenant_id).where(RateTableRow.rate_table_id == table_id)
        ).all()
    )
    return out


@router.patch("/tables/{table_id}")
def update_table(
    table_id: UUID,
    body: RateTablePatch,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, RateTable, table_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, "Rate table not found")
    data = body.model_dump(exclude_unset=True)
    if "kind" in data and data["kind"] is not None:
        _check_kind(data["kind"])
    if "currency" in data and data["currency"]:
        data["currency"] = str(data["currency"]).upper()
    for k, v in data.items():
        setattr(row, k, v)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _table_out(row)


@router.delete("/tables/{table_id}")
def delete_table(
    table_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, RateTable, table_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, "Rate table not found")
    soft_delete(db, tenant_id=auth.tenant_id, user_id=auth.user_id, entity_type="rate_table", row=row, title=row.name)
    db.commit()
    return {"ok": True, "recycled": True}


# —— rate rows ——


@router.get("/tables/{table_id}/rows")
def list_rows(
    table_id: UUID,
    dim: list[str] = Query(default=[]),  # "load_port=CNSHA" filters
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    if scoped_get(db, RateTable, table_id, auth.tenant_id) is None:
        raise HTTPException(404, "Rate table not found")
    dim_filters: dict[str, str] = {}
    for item in dim:
        if "=" in item:
            k, _, v = item.partition("=")
            dim_filters[k.strip()] = v.strip()
    return list_rate_rows(db, auth.tenant_id, table_id, dim_filters=dim_filters, limit=limit, offset=offset)


@router.post("/tables/{table_id}/rows")
def add_row(
    table_id: UUID,
    body: RateRowIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    if scoped_get(db, RateTable, table_id, auth.tenant_id) is None:
        raise HTTPException(404, "Rate table not found")
    _check_unit(body.unit)
    row = upsert_rate_row(
        db,
        auth.tenant_id,
        table_id,
        body.dims,
        body.value,
        unit=body.unit,
        priority=body.priority,
        notes=body.notes,
    )
    return {"id": str(row.id), "dims": row.dims, "value": float(row.value), "unit": row.unit, "priority": row.priority, "notes": row.notes}


@router.patch("/tables/{table_id}/rows/{row_id}")
def update_row(
    table_id: UUID,
    row_id: UUID,
    body: RateRowPatch,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, RateTableRow, row_id, auth.tenant_id)
    if row is None or row.rate_table_id != table_id:
        raise HTTPException(404, "Rate row not found")
    if scoped_get(db, RateTable, table_id, auth.tenant_id) is None:
        raise HTTPException(404, "Rate table not found")
    data = body.model_dump(exclude_unset=True)
    if "unit" in data:
        _check_unit(data["unit"])
    if "dims" in data and data["dims"] is not None:
        row.dims = {str(k): v for k, v in data["dims"].items() if v is not None}
    if "value" in data and data["value"] is not None:
        row.value = data["value"]
    for k in ("unit", "priority", "notes"):
        if k in data:
            setattr(row, k, data[k])
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "dims": row.dims, "value": float(row.value), "unit": row.unit, "priority": row.priority, "notes": row.notes}


@router.delete("/tables/{table_id}/rows/{row_id}")
def delete_row(
    table_id: UUID,
    row_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, RateTableRow, row_id, auth.tenant_id)
    if row is None or row.rate_table_id != table_id:
        raise HTTPException(404, "Rate row not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


# —— lookup ——


@router.post("/tables/{table_id}/resolve")
def resolve_table(
    table_id: UUID,
    body: ResolveIn,
    auth: AuthContext = Depends(require_module("estimate")),
    db: Session = Depends(get_db),
):
    """Best-match rate lookup for ``dims`` (specificity cascade)."""
    if scoped_get(db, RateTable, table_id, auth.tenant_id) is None:
        raise HTTPException(404, "Rate table not found")
    row = resolve_rate_row(db, auth.tenant_id, table_id, body.dims, as_of=body.as_of)
    if row is None:
        return {"matched": False, "value": None, "unit": None, "dims": None}
    return {
        "matched": True,
        "value": float(row.value),
        "unit": row.unit,
        "dims": row.dims,
        "priority": row.priority,
        "row_id": str(row.id),
    }


@router.get("/tables/{table_id}/validate")
def validate_table(
    table_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    """Gap/conflict audit — echoes the issues list (empty list = healthy)."""
    if scoped_get(db, RateTable, table_id, auth.tenant_id) is None:
        raise HTTPException(404, "Rate table not found")
    return {"table_id": str(table_id), "issues": validate_rate_table(db, auth.tenant_id, table_id)}


# —— pricing templates ——


@router.get("/templates")
def list_templates(
    active: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    stmt = scoped_query(db, PricingTemplate, auth.tenant_id).where(PricingTemplate.tenant_id == auth.tenant_id)
    if active is not None:
        stmt = stmt.where(PricingTemplate.is_active == active)
    stmt = stmt.order_by(PricingTemplate.name)
    rows, total = paginate(db, stmt, limit, offset)
    return envelope([_template_out(r) for r in rows], total, limit, offset)


@router.post("/templates")
def create_template(
    body: PricingTemplateIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    # referenced tables must exist in this tenant — reject foreign/unknown ids
    refs = {str(k): str(v) for k, v in (body.rate_table_refs or {}).items()}
    for role, raw in refs.items():
        try:
            tid = UUID(raw)
        except ValueError:
            raise HTTPException(422, detail={"code": "INVALID_RATE_TABLE_REF", "role": role, "value": raw})
        if scoped_get(db, RateTable, tid, auth.tenant_id) is None:
            raise HTTPException(404, f"Rate table for role '{role}' not found")
    row = PricingTemplate(
        tenant_id=auth.tenant_id,
        name=body.name,
        description=body.description,
        rate_table_refs=refs,
        rules=body.rules or {},
        is_active=body.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _template_out(row)


@router.get("/templates/{template_id}")
def get_template(
    template_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, PricingTemplate, template_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, "Pricing template not found")
    return _template_out(row)


@router.patch("/templates/{template_id}")
def update_template(
    template_id: UUID,
    body: PricingTemplatePatch,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, PricingTemplate, template_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, "Pricing template not found")
    data = body.model_dump(exclude_unset=True)
    if "rate_table_refs" in data and data["rate_table_refs"] is not None:
        refs = {str(k): str(v) for k, v in data["rate_table_refs"].items()}
        for role, raw in refs.items():
            try:
                tid = UUID(raw)
            except ValueError:
                raise HTTPException(422, detail={"code": "INVALID_RATE_TABLE_REF", "role": role, "value": raw})
            if scoped_get(db, RateTable, tid, auth.tenant_id) is None:
                raise HTTPException(404, f"Rate table for role '{role}' not found")
        data["rate_table_refs"] = refs
    for k, v in data.items():
        setattr(row, k, v)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _template_out(row)


@router.post("/templates/{template_id}/resolve")
def resolve_template(
    template_id: UUID,
    body: dict[str, Any],
    auth: AuthContext = Depends(require_module("estimate")),
    db: Session = Depends(get_db),
):
    """Resolve every referenced table for an estimate context.

    Body is the context dict: lookup dims (load_port/disch_port/route/
    cargo_type/...) plus optional ``cargo_qty`` / ``demurrage_days`` /
    ``as_of``.
    """
    ctx = {k: v for k, v in (body or {}).items() if k != "as_of"}
    as_of = body.get("as_of") if isinstance(body, dict) else None
    if isinstance(as_of, str):
        try:
            as_of = date.fromisoformat(as_of)
        except ValueError:
            raise HTTPException(422, detail={"code": "INVALID_AS_OF", "as_of": as_of})
    try:
        return resolve_pricing(db, auth.tenant_id, template_id, ctx, as_of=as_of)
    except LookupError:
        raise HTTPException(404, "Pricing template not found")
