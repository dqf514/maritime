"""Centralized scheduling routes (Phase 3) — 集中排程.

Path map (all under ``/api/v1``):
  GET    /scheduling/blocks               — list blocks (vessel / date range / type)
  POST   /scheduling/blocks               — create block (overlaps flagged hard_conflict)
  PATCH  /scheduling/blocks/{id}          — update metadata (timing via move/resize)
  DELETE /scheduling/blocks/{id}          — delete block
  POST   /scheduling/blocks/{id}/move     — move window (409 SCHEDULE_CONFLICT on clash)
  POST   /scheduling/blocks/{id}/resize   — resize window (409 SCHEDULE_CONFLICT on clash)
  GET    /scheduling/conflicts            — overlapping blocks
  GET    /scheduling/open-positions       — vessel availability gaps
  GET    /scheduling/cargo-book           — open cargo + laycan
  GET    /scheduling/berth-windows        — port berth slots
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.pagination import envelope
from app.security import AuthContext, require_module
from app.services import scheduling as sched
from app.services.tenant_guard import scoped_get

from app.models_domain import ScheduleBlock

router = APIRouter(tags=["Scheduling"])


class BlockIn(BaseModel):
    vessel_id: UUID
    title: str
    start_at: datetime
    end_at: datetime
    block_type: str = "voyage"
    voyage_id: UUID | None = None
    meta: dict | None = None


class BlockPatch(BaseModel):
    title: str | None = None
    block_type: str | None = None
    voyage_id: UUID | None = None
    meta: dict | None = None


class WindowIn(BaseModel):
    start_at: datetime
    end_at: datetime


class ResizeIn(BaseModel):
    start_at: datetime | None = None
    end_at: datetime | None = None


def _get_block(db: Session, block_id: UUID, tenant_id: UUID) -> ScheduleBlock:
    row = scoped_get(db, ScheduleBlock, block_id, tenant_id)
    if row is None:
        raise HTTPException(404, "Schedule block not found")
    return row


@router.get("/scheduling/blocks")
def list_blocks(
    vessel_id: UUID | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    block_type: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    rows, total = sched.list_blocks(
        db,
        auth.tenant_id,
        vessel_id=vessel_id,
        date_from=date_from,
        date_to=date_to,
        block_type=block_type,
        limit=limit,
        offset=offset,
    )
    return envelope([sched.block_public(r) for r in rows], total, limit, offset)


@router.post("/scheduling/blocks")
def create_block(
    body: BlockIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = sched.create_block(
        db,
        auth.tenant_id,
        vessel_id=body.vessel_id,
        title=body.title,
        start_at=body.start_at,
        end_at=body.end_at,
        block_type=body.block_type,
        voyage_id=body.voyage_id,
        meta=body.meta,
    )
    return sched.block_public(row)


@router.patch("/scheduling/blocks/{block_id}")
def update_block(
    block_id: UUID,
    body: BlockPatch,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = _get_block(db, block_id, auth.tenant_id)
    fields = body.model_dump(exclude_unset=True)
    row = sched.update_block(db, auth.tenant_id, row, **fields)
    return sched.block_public(row)


@router.delete("/scheduling/blocks/{block_id}")
def delete_block(
    block_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    _get_block(db, block_id, auth.tenant_id)
    return sched.delete_block(db, block_id)


@router.post("/scheduling/blocks/{block_id}/move")
def move_block(
    block_id: UUID,
    body: WindowIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    _get_block(db, block_id, auth.tenant_id)
    row = sched.move_block(db, block_id, body.start_at, body.end_at)
    return sched.block_public(row)


@router.post("/scheduling/blocks/{block_id}/resize")
def resize_block(
    block_id: UUID,
    body: ResizeIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    _get_block(db, block_id, auth.tenant_id)
    row = sched.resize_block(db, block_id, body.start_at, body.end_at)
    return sched.block_public(row)


@router.get("/scheduling/conflicts")
def scheduling_conflicts(
    vessel_id: UUID | None = Query(None),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    items = sched.detect_conflicts(db, auth.tenant_id, vessel_id)
    return {"items": items, "total": len(items)}


@router.get("/scheduling/open-positions")
def scheduling_open_positions(
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    items = sched.open_positions(db, auth.tenant_id, date_from, date_to)
    return {"items": items, "total": len(items)}


@router.get("/scheduling/cargo-book")
def scheduling_cargo_book(
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    return sched.cargo_book(db, auth.tenant_id)


@router.get("/scheduling/berth-windows")
def scheduling_berth_windows(
    port_id: UUID | None = Query(None),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    items = sched.berth_windows(db, auth.tenant_id, port_id)
    return {"items": items, "total": len(items)}
