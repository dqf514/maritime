"""Lightering & Barging CRUD（过驳/驳运，最小可用）。

Endpoints (all under /api/v1):
- /lightering-ops  — LighteringOp 列表/新建/详情/更新/删除
- /barge-ops      — BargeOp 列表/新建/详情/更新/删除
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_lightering import BargeOp, LighteringOp
from app.security import AuthContext, require_module
from app.services.doc_numbering import next_doc_number
from app.services.tenant_guard import scoped_get, scoped_query

router = APIRouter()  # 由 main.py 以 /api/v1 挂载


class LighteringOpIn(BaseModel):
    op_no: str | None = None
    lightering_type: str = Field(..., description="reverse_lightering|fso|stS")
    vessel_id: UUID
    location: str | None = None
    qty_lightered: float | None = None
    status: str = "planned"  # planned|in_progress|completed|cancelled
    notes: str | None = None


class LighteringOpOut(BaseModel):
    id: str
    op_no: str
    lightering_type: str
    vessel_id: str
    location: str | None
    qty_lightered: float | None
    status: str
    notes: str | None


class BargeOpIn(BaseModel):
    op_no: str | None = None
    barge_name: str
    barge_type: str | None = None
    operation_type: str = Field(..., description="bunkering|lightering|transport")
    vessel_id: UUID | None = None
    port_id: UUID | None = None
    qty: float | None = None
    status: str = "planned"
    notes: str | None = None


class BargeOpOut(BaseModel):
    id: str
    op_no: str
    barge_name: str
    barge_type: str | None
    operation_type: str
    vessel_id: str | None
    port_id: str | None
    qty: float | None
    status: str
    notes: str | None


def _lightering_out(row: LighteringOp) -> LighteringOpOut:
    return LighteringOpOut(
        id=str(row.id),
        op_no=row.op_no,
        lightering_type=row.lightering_type,
        vessel_id=str(row.vessel_id),
        location=row.location,
        qty_lightered=float(row.qty_lightered) if row.qty_lightered is not None else None,
        status=row.status,
        notes=row.notes,
    )


def _barge_out(row: BargeOp) -> BargeOpOut:
    return BargeOpOut(
        id=str(row.id),
        op_no=row.op_no,
        barge_name=row.barge_name,
        barge_type=row.barge_type,
        operation_type=row.operation_type,
        vessel_id=str(row.vessel_id) if row.vessel_id else None,
        port_id=str(row.port_id) if row.port_id else None,
        qty=float(row.qty) if row.qty is not None else None,
        status=row.status,
        notes=row.notes,
    )


# ── Lightering operations ──


@router.get("/lightering-ops", response_model=list[LighteringOpOut])
def list_lightering_ops(
    status: str | None = Query(None),
    vessel_id: UUID | None = Query(None),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    stmt = scoped_query(db, LighteringOp, auth.tenant_id)
    if status:
        stmt = stmt.where(LighteringOp.status == status)
    if vessel_id:
        stmt = stmt.where(LighteringOp.vessel_id == vessel_id)
    rows = db.scalars(stmt.order_by(LighteringOp.op_no)).all()
    return [_lightering_out(r) for r in rows]


@router.post("/lightering-ops", response_model=LighteringOpOut, status_code=201)
def create_lightering_op(
    body: LighteringOpIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    op_no = body.op_no or next_doc_number(db, auth.tenant_id, LighteringOp, LighteringOp.op_no, "LGT")
    row = LighteringOp(
        tenant_id=auth.tenant_id,
        op_no=op_no,
        lightering_type=body.lightering_type,
        vessel_id=body.vessel_id,
        location=body.location,
        qty_lightered=Decimal(str(body.qty_lightered)) if body.qty_lightered is not None else None,
        status=body.status,
        notes=body.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _lightering_out(row)


@router.get("/lightering-ops/{op_id}", response_model=LighteringOpOut)
def get_lightering_op(
    op_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, LighteringOp, op_id, auth.tenant_id)
    if not row:
        raise HTTPException(404, detail={"code": "LIGHTERING_OP_NOT_FOUND", "message": "Lightering op not found"})
    return _lightering_out(row)


@router.patch("/lightering-ops/{op_id}", response_model=LighteringOpOut)
def update_lightering_op(
    op_id: UUID,
    body: LighteringOpIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, LighteringOp, op_id, auth.tenant_id)
    if not row:
        raise HTTPException(404, detail={"code": "LIGHTERING_OP_NOT_FOUND", "message": "Lightering op not found"})
    if body.op_no:
        row.op_no = body.op_no
    row.lightering_type = body.lightering_type
    row.vessel_id = body.vessel_id
    row.location = body.location
    row.qty_lightered = Decimal(str(body.qty_lightered)) if body.qty_lightered is not None else None
    row.status = body.status
    row.notes = body.notes
    db.commit()
    db.refresh(row)
    return _lightering_out(row)


@router.delete("/lightering-ops/{op_id}")
def delete_lightering_op(
    op_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, LighteringOp, op_id, auth.tenant_id)
    if not row:
        raise HTTPException(404, detail={"code": "LIGHTERING_OP_NOT_FOUND", "message": "Lightering op not found"})
    db.delete(row)
    db.commit()
    return {"ok": True}


# ── Barge operations ──


@router.get("/barge-ops", response_model=list[BargeOpOut])
def list_barge_ops(
    status: str | None = Query(None),
    operation_type: str | None = Query(None),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    stmt = scoped_query(db, BargeOp, auth.tenant_id)
    if status:
        stmt = stmt.where(BargeOp.status == status)
    if operation_type:
        stmt = stmt.where(BargeOp.operation_type == operation_type)
    rows = db.scalars(stmt.order_by(BargeOp.op_no)).all()
    return [_barge_out(r) for r in rows]


@router.post("/barge-ops", response_model=BargeOpOut, status_code=201)
def create_barge_op(
    body: BargeOpIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    op_no = body.op_no or next_doc_number(db, auth.tenant_id, BargeOp, BargeOp.op_no, "BRG")
    row = BargeOp(
        tenant_id=auth.tenant_id,
        op_no=op_no,
        barge_name=body.barge_name,
        barge_type=body.barge_type,
        operation_type=body.operation_type,
        vessel_id=body.vessel_id,
        port_id=body.port_id,
        qty=Decimal(str(body.qty)) if body.qty is not None else None,
        status=body.status,
        notes=body.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _barge_out(row)


@router.get("/barge-ops/{op_id}", response_model=BargeOpOut)
def get_barge_op(
    op_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, BargeOp, op_id, auth.tenant_id)
    if not row:
        raise HTTPException(404, detail={"code": "BARGE_OP_NOT_FOUND", "message": "Barge op not found"})
    return _barge_out(row)


@router.patch("/barge-ops/{op_id}", response_model=BargeOpOut)
def update_barge_op(
    op_id: UUID,
    body: BargeOpIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, BargeOp, op_id, auth.tenant_id)
    if not row:
        raise HTTPException(404, detail={"code": "BARGE_OP_NOT_FOUND", "message": "Barge op not found"})
    if body.op_no:
        row.op_no = body.op_no
    row.barge_name = body.barge_name
    row.barge_type = body.barge_type
    row.operation_type = body.operation_type
    row.vessel_id = body.vessel_id
    row.port_id = body.port_id
    row.qty = Decimal(str(body.qty)) if body.qty is not None else None
    row.status = body.status
    row.notes = body.notes
    db.commit()
    db.refresh(row)
    return _barge_out(row)


@router.delete("/barge-ops/{op_id}")
def delete_barge_op(
    op_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, BargeOp, op_id, auth.tenant_id)
    if not row:
        raise HTTPException(404, detail={"code": "BARGE_OP_NOT_FOUND", "message": "Barge op not found"})
    db.delete(row)
    db.commit()
    return {"ok": True}
