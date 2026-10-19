"""Cargo routes (Phase 3) — 货盘 CRUD / 状态流转 / 货盘簿.

Path map (all under ``/api/v1``):
  GET    /cargo                  — list + pagination + filters
  POST   /cargo                  — create (CGO-YYYY-NNNNN doc number)
  GET    /cargo/book             — open cargo grouped by laycan month
  GET    /cargo-book             — cargo book rows for /cargo page (enriched names)
  GET    /cargo/{id}             — detail
  PATCH  /cargo/{id}             — update
  DELETE /cargo/{id}             — soft delete (recycle bin)
  POST   /cargo/{id}/transition  — state machine (CARGO_TRANSITIONS)
  POST   /cargo/{id}/allocate    — link to voyage

Route order matters: ``/cargo/book`` is registered before ``/cargo/{cargo_id}``.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.pagination import envelope
from app.security import AuthContext, require_module
from app.services import cargo as cargo_svc
from app.services.recycle import soft_delete
from app.services.state_machine import CARGO_TRANSITIONS, transition
from app.services.tenant_guard import scoped_get

from app.models_cargo import Cargo
from app.models_domain import Voyage

router = APIRouter(tags=["Cargo"])


class CargoIn(BaseModel):
    cargo_type: str | None = None
    commodity: str | None = None
    qty: float | None = None
    qty_unit: str | None = None
    load_port_id: UUID | None = None
    disch_port_id: UUID | None = None
    laycan_from: date | None = None
    laycan_to: date | None = None
    charterer_id: UUID | None = None
    freight_basis: str | None = None
    freight_rate: float | None = None
    voyage_id: UUID | None = None
    charter_id: UUID | None = None
    coa_id: UUID | None = None
    notes: str | None = None


class CargoPatch(BaseModel):
    cargo_type: str | None = None
    commodity: str | None = None
    qty: float | None = None
    qty_unit: str | None = None
    load_port_id: UUID | None = None
    disch_port_id: UUID | None = None
    laycan_from: date | None = None
    laycan_to: date | None = None
    charterer_id: UUID | None = None
    freight_basis: str | None = None
    freight_rate: float | None = None
    voyage_id: UUID | None = None
    charter_id: UUID | None = None
    coa_id: UUID | None = None
    notes: str | None = None


class AllocateIn(BaseModel):
    voyage_id: UUID


def _get_cargo(db: Session, cargo_id: UUID, tenant_id: UUID) -> Cargo:
    row = scoped_get(db, Cargo, cargo_id, tenant_id)
    if row is None:
        raise HTTPException(404, "Cargo not found")
    return row


@router.get("/cargo")
def list_cargo(
    status: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    charterer_id: UUID | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    rows, total = cargo_svc.list_cargo(
        db,
        auth.tenant_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        charterer_id=charterer_id,
        limit=limit,
        offset=offset,
    )
    return envelope([cargo_svc.cargo_public(r) for r in rows], total, limit, offset)


@router.post("/cargo")
def create_cargo(body: CargoIn, auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    row = cargo_svc.create_cargo(db, auth.tenant_id, **body.model_dump())
    return cargo_svc.cargo_public(row)


@router.get("/cargo/book")
def cargo_book(auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    """货盘簿 — open cargo grouped by laycan month (must precede /cargo/{cargo_id})."""
    return cargo_svc.cargo_book_summary(db, auth.tenant_id)


@router.get("/cargo-book")
def cargo_book_rows(
    status: str | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """货物台账列表（/cargo 页面契约）——富化港口/船名/对手方显示名。

    页面调的是 /api/v1/cargo-book（此前 404）；行结构按 CargoBookRow 对齐。
    """
    from sqlalchemy import select

    from app.models_wave1 import Counterparty, Port, Vessel

    rows, total = cargo_svc.list_cargo(db, auth.tenant_id, status=status, limit=limit, offset=offset)
    if not rows:
        return envelope([], total, limit, offset)

    port_ids = {r.load_port_id for r in rows if r.load_port_id} | {r.disch_port_id for r in rows if r.disch_port_id}
    cp_ids = {r.charterer_id for r in rows if r.charterer_id}
    voyage_ids = {r.voyage_id for r in rows if r.voyage_id}

    ports = {str(p.id): p.name for p in db.scalars(select(Port).where(Port.id.in_(port_ids)))} if port_ids else {}
    cps = {str(c.id): c.name for c in db.scalars(select(Counterparty).where(Counterparty.id.in_(cp_ids)))} if cp_ids else {}
    vessels: dict[str, str] = {}
    if voyage_ids:
        for vid, vname in db.execute(
            select(Voyage.id, Vessel.name).outerjoin(Vessel, Voyage.vessel_id == Vessel.id).where(Voyage.id.in_(voyage_ids))
        ):
            vessels[str(vid)] = vname or None  # type: ignore[assignment]

    items = [
        {
            "id": str(r.id),
            "cargo_ref": r.cargo_no,
            "charter_id": str(r.charter_id) if r.charter_id else None,
            "voyage_id": str(r.voyage_id) if r.voyage_id else None,
            "vessel_name": vessels.get(str(r.voyage_id)) if r.voyage_id else None,
            "cargo_type": r.cargo_type or "",
            "cargo_qty": float(r.qty) if r.qty is not None else 0.0,
            "load_port": ports.get(str(r.load_port_id), "") if r.load_port_id else "",
            "discharge_port": ports.get(str(r.disch_port_id), "") if r.disch_port_id else "",
            "laycan_from": r.laycan_from.isoformat() if r.laycan_from else None,
            "laycan_to": r.laycan_to.isoformat() if r.laycan_to else None,
            "etd": None,
            "eta": None,
            "status": r.status,
            "counterparty": cps.get(str(r.charterer_id)) if r.charterer_id else None,
        }
        for r in rows
    ]
    return envelope(items, total, limit, offset)


@router.get("/cargo/{cargo_id}")
def get_cargo(
    cargo_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    return cargo_svc.cargo_public(_get_cargo(db, cargo_id, auth.tenant_id))


@router.patch("/cargo/{cargo_id}")
def update_cargo(
    cargo_id: UUID,
    body: CargoPatch,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = _get_cargo(db, cargo_id, auth.tenant_id)
    # model_dump() keeps explicit nulls as "don't care" for PATCH semantics:
    # update_cargo ignores None values (see services.cargo.update_cargo).
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    row = cargo_svc.update_cargo(db, row, **fields)
    return cargo_svc.cargo_public(row)


@router.delete("/cargo/{cargo_id}")
def delete_cargo(
    cargo_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = _get_cargo(db, cargo_id, auth.tenant_id)
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="cargo",
        row=row,
        title=row.cargo_no,
    )
    db.commit()
    return {"ok": True, "recycled": True}


@router.post("/cargo/{cargo_id}/transition")
def cargo_transition(
    cargo_id: UUID,
    target: str,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = _get_cargo(db, cargo_id, auth.tenant_id)
    row.status = transition("cargo", row.status, target, CARGO_TRANSITIONS)
    db.commit()
    return {"id": str(row.id), "status": row.status}


@router.post("/cargo/{cargo_id}/allocate")
def allocate_cargo(
    cargo_id: UUID,
    body: AllocateIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    _get_cargo(db, cargo_id, auth.tenant_id)  # tenant check before the service writes
    row = cargo_svc.allocate_to_voyage(db, cargo_id, body.voyage_id)
    return cargo_svc.cargo_public(row)
