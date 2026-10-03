"""Phase 6 COA routes — COA 合同 CRUD、分单、运力分摊与燃油中性盈亏.

Path map (all under ``/api/v1``):
  GET    /coa/contracts                  — list + pagination + filters
  POST   /coa/contracts                  — create (COA-YYYY-NNNNN doc number)
  GET    /coa/contracts/{id}             — detail
  PATCH  /coa/contracts/{id}             — update
  DELETE /coa/contracts/{id}             — soft delete (recycle bin)
  POST   /coa/contracts/{id}/transition  — state machine (COA_CONTRACT_TRANSITIONS)
  GET    /coa/contracts/{id}/itineraries — itinerary list
  POST   /coa/contracts/{id}/itineraries — add itinerary (qty sum ≤ total_qty)
  PATCH  /coa/itineraries/{id}           — update itinerary
  DELETE /coa/itineraries/{id}           — remove itinerary
  POST   /coa/{id}/allocate              — allocate lifting → itinerary seq
  GET    /coa/{id}/allocation            — allocation summary
  GET    /coa/{id}/pnl                   — fuel-neutral P&L

Route order: literal ``/coa/contracts/...`` paths are registered before the
parametric ``/coa/{coa_id}/...`` group.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_coa import COA_QTY_UNITS, COA_RATE_BASES, CoaContract, CoaItinerary
from app.models_domain import Charter
from app.pagination import envelope, paginate
from app.security import AuthContext, require_module
from app.services import coa as coa_svc
from app.services.doc_numbering import next_doc_number
from app.services.recycle import soft_delete
from app.services.state_machine import COA_CONTRACT_TRANSITIONS, transition
from app.services.tenant_guard import scoped_get, scoped_query

router = APIRouter(tags=["COA"])


class CoaContractIn(BaseModel):
    charter_id: UUID
    total_qty: Decimal = Field(gt=0)
    qty_unit: str = "mt"
    period_from: date
    period_to: date
    rate_basis: str = "per_voyage"
    rate: Decimal
    currency: str = "USD"
    cargo_spec: str | None = None


class CoaContractPatch(BaseModel):
    total_qty: Decimal | None = Field(default=None, gt=0)
    qty_unit: str | None = None
    period_from: date | None = None
    period_to: date | None = None
    rate_basis: str | None = None
    rate: Decimal | None = None
    currency: str | None = None
    cargo_spec: str | None = None


class CoaItineraryIn(BaseModel):
    seq: int = Field(ge=1)
    load_port_id: UUID | None = None
    disch_port_id: UUID | None = None
    qty: Decimal = Field(gt=0)
    notes: str | None = None


class CoaItineraryPatch(BaseModel):
    load_port_id: UUID | None = None
    disch_port_id: UUID | None = None
    qty: Decimal | None = Field(default=None, gt=0)
    notes: str | None = None


class AllocateIn(BaseModel):
    lifting_id: UUID
    itinerary_seq: int = Field(ge=1)


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def _contract_public(row: CoaContract) -> dict:
    return {
        "id": str(row.id),
        "coa_no": row.coa_no,
        "charter_id": str(row.charter_id),
        "total_qty": _f(row.total_qty),
        "qty_unit": row.qty_unit,
        "period_from": row.period_from.isoformat(),
        "period_to": row.period_to.isoformat(),
        "rate_basis": row.rate_basis,
        "rate": _f(row.rate),
        "currency": row.currency,
        "cargo_spec": row.cargo_spec,
        "status": row.status,
    }


def _itinerary_public(row: CoaItinerary) -> dict:
    return {
        "id": str(row.id),
        "coa_contract_id": str(row.coa_contract_id),
        "seq": row.seq,
        "load_port_id": str(row.load_port_id) if row.load_port_id else None,
        "disch_port_id": str(row.disch_port_id) if row.disch_port_id else None,
        "qty": _f(row.qty),
        "allocated_qty": _f(row.allocated_qty),
        "notes": row.notes,
    }


def _get_contract(db: Session, contract_id: UUID, tenant_id: UUID) -> CoaContract:
    row = scoped_get(db, CoaContract, contract_id, tenant_id)
    if row is None:
        raise HTTPException(404, "COA contract not found")
    return row


def _get_itinerary(db: Session, itinerary_id: UUID, tenant_id: UUID) -> CoaItinerary:
    row = scoped_get(db, CoaItinerary, itinerary_id, tenant_id)
    if row is None:
        raise HTTPException(404, "Itinerary not found")
    return row


def _validate_contract_fields(db: Session, tenant_id: UUID, body: CoaContractIn | CoaContractPatch, *, partial: bool) -> None:
    qty_unit = body.qty_unit
    if qty_unit is not None and qty_unit not in COA_QTY_UNITS:
        raise HTTPException(422, detail={"code": "COA_QTY_UNIT_UNKNOWN", "message": qty_unit})
    rate_basis = body.rate_basis
    if rate_basis is not None and rate_basis not in COA_RATE_BASES:
        raise HTTPException(422, detail={"code": "COA_RATE_BASIS_UNKNOWN", "message": rate_basis})
    p_from = getattr(body, "period_from", None)
    p_to = getattr(body, "period_to", None)
    if p_from is not None and p_to is not None and p_to < p_from:
        raise HTTPException(422, detail={"code": "COA_PERIOD_INVALID", "message": "period_to before period_from"})
    if not partial:
        assert isinstance(body, CoaContractIn)
        if scoped_get(db, Charter, body.charter_id, tenant_id) is None:
            raise HTTPException(404, "Charter not found")


def _itinerary_qty_sum(db: Session, tenant_id: UUID, coa_contract_id: UUID, *, exclude_id: UUID | None = None) -> Decimal:
    stmt = select(CoaItinerary).where(
        CoaItinerary.tenant_id == tenant_id,
        CoaItinerary.coa_contract_id == coa_contract_id,
    )
    rows = db.scalars(stmt).all()
    return sum((it.qty for it in rows if it.id != exclude_id), Decimal("0"))


# ── CoaContract CRUD ─────────────────────────────────────────────────────────


@router.get("/coa/contracts")
def list_coa_contracts(
    status: str | None = Query(None),
    charter_id: UUID | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    q = scoped_query(db, CoaContract, auth.tenant_id)
    if status:
        q = q.where(CoaContract.status == status)
    if charter_id:
        q = q.where(CoaContract.charter_id == charter_id)
    rows, total = paginate(db, q.order_by(CoaContract.coa_no), limit, offset)
    return envelope([_contract_public(r) for r in rows], total, limit, offset)


@router.post("/coa/contracts", status_code=201)
def create_coa_contract(
    body: CoaContractIn,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    _validate_contract_fields(db, auth.tenant_id, body, partial=False)
    row = CoaContract(
        tenant_id=auth.tenant_id,
        coa_no=next_doc_number(db, auth.tenant_id, CoaContract, CoaContract.coa_no, "COA"),
        charter_id=body.charter_id,
        total_qty=body.total_qty,
        qty_unit=body.qty_unit,
        period_from=body.period_from,
        period_to=body.period_to,
        rate_basis=body.rate_basis,
        rate=body.rate,
        currency=body.currency,
        cargo_spec=body.cargo_spec,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _contract_public(row)


@router.get("/coa/contracts/{contract_id}")
def get_coa_contract(
    contract_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    return _contract_public(_get_contract(db, contract_id, auth.tenant_id))


@router.patch("/coa/contracts/{contract_id}")
def update_coa_contract(
    contract_id: UUID,
    body: CoaContractPatch,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    row = _get_contract(db, contract_id, auth.tenant_id)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if fields:
        merged = CoaContractPatch(
            total_qty=fields.get("total_qty", row.total_qty),
            qty_unit=fields.get("qty_unit", row.qty_unit),
            period_from=fields.get("period_from", row.period_from),
            period_to=fields.get("period_to", row.period_to),
            rate_basis=fields.get("rate_basis", row.rate_basis),
            rate=fields.get("rate", row.rate),
            currency=fields.get("currency", row.currency),
            cargo_spec=fields.get("cargo_spec", row.cargo_spec),
        )
        _validate_contract_fields(db, auth.tenant_id, merged, partial=True)
        for k, v in fields.items():
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return _contract_public(row)


@router.delete("/coa/contracts/{contract_id}")
def delete_coa_contract(
    contract_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    row = _get_contract(db, contract_id, auth.tenant_id)
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="coa_contract",
        row=row,
        title=row.coa_no,
    )
    db.commit()
    return {"ok": True, "recycled": True}


@router.post("/coa/contracts/{contract_id}/transition")
def transition_coa_contract(
    contract_id: UUID,
    target: str,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    row = _get_contract(db, contract_id, auth.tenant_id)
    row.status = transition("coa_contract", row.status, target, COA_CONTRACT_TRANSITIONS)
    db.commit()
    return {"id": str(row.id), "status": row.status}


# ── Itineraries ──────────────────────────────────────────────────────────────


@router.get("/coa/contracts/{contract_id}/itineraries")
def list_itineraries(
    contract_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    contract = _get_contract(db, contract_id, auth.tenant_id)
    rows = db.scalars(
        scoped_query(db, CoaItinerary, auth.tenant_id)
        .where(CoaItinerary.coa_contract_id == contract.id)
        .order_by(CoaItinerary.seq)
    ).all()
    return [_itinerary_public(r) for r in rows]


@router.post("/coa/contracts/{contract_id}/itineraries", status_code=201)
def add_itinerary(
    contract_id: UUID,
    body: CoaItineraryIn,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    contract = _get_contract(db, contract_id, auth.tenant_id)
    if contract.status not in ("draft", "active"):
        raise HTTPException(422, detail={"code": "COA_NOT_EDITABLE", "message": f"contract is {contract.status}"})
    dup = db.scalar(
        select(CoaItinerary).where(
            CoaItinerary.coa_contract_id == contract.id,
            CoaItinerary.seq == body.seq,
        )
    )
    if dup is not None:
        raise HTTPException(422, detail={"code": "COA_SEQ_DUPLICATE", "message": f"seq {body.seq} already exists"})
    total = _itinerary_qty_sum(db, auth.tenant_id, contract.id) + body.qty
    if total > contract.total_qty:
        raise HTTPException(
            422,
            detail={
                "code": "COA_ITINERARY_SUM_EXCEEDED",
                "message": f"itinerary qty sum {total} exceeds contracted {contract.total_qty}",
            },
        )
    row = CoaItinerary(
        tenant_id=auth.tenant_id,
        coa_contract_id=contract.id,
        seq=body.seq,
        load_port_id=body.load_port_id,
        disch_port_id=body.disch_port_id,
        qty=body.qty,
        notes=body.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _itinerary_public(row)


@router.patch("/coa/itineraries/{itinerary_id}")
def update_itinerary(
    itinerary_id: UUID,
    body: CoaItineraryPatch,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    row = _get_itinerary(db, itinerary_id, auth.tenant_id)
    contract = _get_contract(db, row.coa_contract_id, auth.tenant_id)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if "qty" in fields:
        allocated = row.allocated_qty or Decimal("0")
        if fields["qty"] < allocated:
            raise HTTPException(
                422,
                detail={
                    "code": "COA_QTY_BELOW_ALLOCATED",
                    "message": f"qty {fields['qty']} below allocated {allocated}",
                },
            )
        total = _itinerary_qty_sum(db, auth.tenant_id, contract.id, exclude_id=row.id) + fields["qty"]
        if total > contract.total_qty:
            raise HTTPException(
                422,
                detail={
                    "code": "COA_ITINERARY_SUM_EXCEEDED",
                    "message": f"itinerary qty sum {total} exceeds contracted {contract.total_qty}",
                },
            )
    for k, v in fields.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return _itinerary_public(row)


@router.delete("/coa/itineraries/{itinerary_id}")
def delete_itinerary(
    itinerary_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    row = _get_itinerary(db, itinerary_id, auth.tenant_id)
    allocated = row.allocated_qty or Decimal("0")
    if allocated > 0:
        raise HTTPException(
            422,
            detail={"code": "COA_ITINERARY_ALLOCATED", "message": f"itinerary has allocated qty {allocated}"},
        )
    db.delete(row)
    db.commit()
    return {"ok": True}


# ── Allocation / P&L (spec paths: /coa/{id}/...) ─────────────────────────────


@router.post("/coa/{coa_id}/allocate")
def allocate_lifting(
    coa_id: UUID,
    body: AllocateIn,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    alloc = coa_svc.allocate_lifting(db, auth.tenant_id, coa_id, body.lifting_id, body.itinerary_seq)
    return {
        "id": str(alloc.id),
        "coa_contract_id": str(alloc.coa_contract_id),
        "itinerary_id": str(alloc.itinerary_id),
        "lifting_id": str(alloc.lifting_id),
        "qty": _f(alloc.qty),
    }


@router.get("/coa/{coa_id}/allocation")
def allocation_summary(
    coa_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    return coa_svc.allocation_summary(db, auth.tenant_id, coa_id)


@router.get("/coa/{coa_id}/pnl")
def fuel_neutral_pnl(
    coa_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    return coa_svc.fuel_neutral_pnl(db, auth.tenant_id, coa_id)
