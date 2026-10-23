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

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.pagination import envelope
from app.security import AuthContext, require_module
from app.services import cargo as cargo_svc
from app.services.recycle import soft_delete
from app.services.state_machine import CARGO_TRANSITIONS, transition
from app.services.tenant_guard import scoped_get

from app.models_cargo import Cargo
from app.models_charter_ext import CargoItineraryRow, CargoPortOption
from app.models_domain import Voyage

router = APIRouter(tags=["Cargo"])

# P11 IMOS Cargo detail 对齐 — 头部 / CP 条款 / Laycan 四字段 / 支付块
_CARGO_P11_FIELDS = (
    "cargo_name_id", "api_gravity", "specific_gravity",
    "cp_date", "cp_form", "option_pct", "option_type", "min_qty", "max_qty",
    "freight_type", "currency", "exchange_rate", "min_inv_qty",
    "freight_via", "demurrage_via", "cp_draft_m", "coordinator",
    "reference_no", "booking_no", "vc_in_id", "nominated_vessel_id", "voyage_no",
    "contract_link", "company_code", "department", "trade_area",
    "laycan_from_override", "laycan_to_override", "laycan_confirmed",
    "remittance_bank", "invoice_pct", "balance_pct",
    "payment_terms_code", "payment_terms_desc",
)


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
    # ── P11 IMOS Cargo detail 对齐 ──
    cargo_name_id: UUID | None = None
    api_gravity: float | None = None
    specific_gravity: float | None = None
    cp_date: date | None = None
    cp_form: str | None = None
    option_pct: float | None = None
    option_type: str | None = None  # MOLOO|MINLO|MOLOA...
    min_qty: float | None = None
    max_qty: float | None = None
    freight_type: str | None = None  # F|L|LS
    currency: str | None = None
    exchange_rate: float | None = None
    min_inv_qty: float | None = None
    freight_via: str | None = None
    demurrage_via: str | None = None
    cp_draft_m: float | None = None
    coordinator: str | None = None
    reference_no: str | None = None
    booking_no: str | None = None
    vc_in_id: str | None = None
    nominated_vessel_id: UUID | None = None
    voyage_no: str | None = None
    contract_link: str | None = None
    company_code: str | None = None
    department: str | None = None
    trade_area: str | None = None
    laycan_from_override: datetime | None = None
    laycan_to_override: datetime | None = None
    laycan_confirmed: bool | None = None
    remittance_bank: str | None = None
    invoice_pct: float | None = None
    balance_pct: float | None = None
    payment_terms_code: str | None = None
    payment_terms_desc: str | None = None


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
    # ── P11 IMOS Cargo detail 对齐 ──
    cargo_name_id: UUID | None = None
    api_gravity: float | None = None
    specific_gravity: float | None = None
    cp_date: date | None = None
    cp_form: str | None = None
    option_pct: float | None = None
    option_type: str | None = None
    min_qty: float | None = None
    max_qty: float | None = None
    freight_type: str | None = None
    currency: str | None = None
    exchange_rate: float | None = None
    min_inv_qty: float | None = None
    freight_via: str | None = None
    demurrage_via: str | None = None
    cp_draft_m: float | None = None
    coordinator: str | None = None
    reference_no: str | None = None
    booking_no: str | None = None
    vc_in_id: str | None = None
    nominated_vessel_id: UUID | None = None
    voyage_no: str | None = None
    contract_link: str | None = None
    company_code: str | None = None
    department: str | None = None
    trade_area: str | None = None
    laycan_from_override: datetime | None = None
    laycan_to_override: datetime | None = None
    laycan_confirmed: bool | None = None
    remittance_bank: str | None = None
    invoice_pct: float | None = None
    balance_pct: float | None = None
    payment_terms_code: str | None = None
    payment_terms_desc: str | None = None


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
            # P11 IMOS Cargo list：Laycan 本地 + GMT（override）并排显示
            "laycan_from_override": r.laycan_from_override.isoformat() if r.laycan_from_override else None,
            "laycan_to_override": r.laycan_to_override.isoformat() if r.laycan_to_override else None,
            "laycan_confirmed": bool(r.laycan_confirmed),
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
    # exclude_unset —— 只提交显式字段：显式 null 用于清空（IMOS 编辑器需要能清空支付块/附件字段），
    # 未提交的字段保持原值（与 CharterUpdate 的 PATCH 语义一致）。
    fields = body.model_dump(exclude_unset=True)
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


# —— P11: Cargo Itinerary / Options grids（IMOS Cargo detail 表格） ——


class CargoItineraryIn(BaseModel):
    seq: int = 0
    flag: str = "L"  # L=load | D=disch
    port_id: UUID | None = None
    port_name: str | None = None
    berth: str | None = None
    qty: float | None = None
    ld_rate: float | None = None
    ru: str | None = None
    terms: str | None = None
    incoterms: str | None = None
    port_exp: float | None = None
    oexp_per_t: float | None = None
    liner_exp: float | None = None
    draft: float | None = None
    unit: str | None = None
    salinity: float | None = None


class CargoItineraryPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    seq: int | None = None
    flag: str | None = None
    port_id: UUID | None = None
    port_name: str | None = None
    berth: str | None = None
    qty: float | None = None
    ld_rate: float | None = None
    ru: str | None = None
    terms: str | None = None
    incoterms: str | None = None
    port_exp: float | None = None
    oexp_per_t: float | None = None
    liner_exp: float | None = None
    draft: float | None = None
    unit: str | None = None
    salinity: float | None = None


def _itin_public(r: CargoItineraryRow) -> dict:
    return {
        "id": str(r.id),
        "cargo_id": str(r.cargo_id),
        "seq": r.seq,
        "flag": r.flag,
        "port_id": str(r.port_id) if r.port_id else None,
        "port_name": r.port_name,
        "berth": r.berth,
        "qty": float(r.qty) if r.qty is not None else None,
        "ld_rate": float(r.ld_rate) if r.ld_rate is not None else None,
        "ru": r.ru,
        "terms": r.terms,
        "incoterms": r.incoterms,
        "port_exp": float(r.port_exp) if r.port_exp is not None else None,
        "oexp_per_t": float(r.oexp_per_t) if r.oexp_per_t is not None else None,
        "liner_exp": float(r.liner_exp) if r.liner_exp is not None else None,
        "draft": float(r.draft) if r.draft is not None else None,
        "unit": r.unit,
        "salinity": float(r.salinity) if r.salinity is not None else None,
    }


@router.get("/cargo/{cargo_id}/itinerary")
def list_cargo_itinerary(
    cargo_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    _get_cargo(db, cargo_id, auth.tenant_id)
    rows = db.scalars(
        select(CargoItineraryRow)
        .where(
            CargoItineraryRow.tenant_id == auth.tenant_id,
            CargoItineraryRow.cargo_id == cargo_id,
        )
        .order_by(CargoItineraryRow.seq, CargoItineraryRow.created_at)
    ).all()
    return [_itin_public(r) for r in rows]


@router.post("/cargo/{cargo_id}/itinerary", status_code=201)
def add_cargo_itinerary(
    cargo_id: UUID,
    body: CargoItineraryIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    _get_cargo(db, cargo_id, auth.tenant_id)
    row = CargoItineraryRow(
        tenant_id=auth.tenant_id,
        cargo_id=cargo_id,
        **body.model_dump(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _itin_public(row)


@router.patch("/cargo/{cargo_id}/itinerary/{row_id}")
def update_cargo_itinerary(
    cargo_id: UUID,
    row_id: UUID,
    body: CargoItineraryPatch,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    _get_cargo(db, cargo_id, auth.tenant_id)
    row = scoped_get(db, CargoItineraryRow, row_id, auth.tenant_id)
    if not row or row.cargo_id != cargo_id:
        raise HTTPException(404, "Itinerary row not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _itin_public(row)


@router.delete("/cargo/{cargo_id}/itinerary/{row_id}")
def delete_cargo_itinerary(
    cargo_id: UUID,
    row_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    _get_cargo(db, cargo_id, auth.tenant_id)
    row = scoped_get(db, CargoItineraryRow, row_id, auth.tenant_id)
    if not row or row.cargo_id != cargo_id:
        raise HTTPException(404, "Itinerary row not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


class CargoOptionIn(BaseModel):
    kind: str  # load | disch
    seq: int = 0
    port_area: str | None = None
    ld_rate: float | None = None
    ru: str | None = None
    terms: str | None = None
    tt_days: float | None = None
    pexp: float | None = None
    draft: float | None = None


class CargoOptionPatch(BaseModel):
    kind: str | None = None
    seq: int | None = None
    port_area: str | None = None
    ld_rate: float | None = None
    ru: str | None = None
    terms: str | None = None
    tt_days: float | None = None
    pexp: float | None = None
    draft: float | None = None


def _opt_public(r: CargoPortOption) -> dict:
    return {
        "id": str(r.id),
        "cargo_id": str(r.cargo_id),
        "kind": r.kind,
        "seq": r.seq,
        "port_area": r.port_area,
        "ld_rate": float(r.ld_rate) if r.ld_rate is not None else None,
        "ru": r.ru,
        "terms": r.terms,
        "tt_days": float(r.tt_days) if r.tt_days is not None else None,
        "pexp": float(r.pexp) if r.pexp is not None else None,
        "draft": float(r.draft) if r.draft is not None else None,
    }


@router.get("/cargo/{cargo_id}/options")
def list_cargo_options(
    cargo_id: UUID,
    kind: str | None = Query(None, pattern="^(load|disch)$"),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    _get_cargo(db, cargo_id, auth.tenant_id)
    q = select(CargoPortOption).where(
        CargoPortOption.tenant_id == auth.tenant_id,
        CargoPortOption.cargo_id == cargo_id,
    )
    if kind:
        q = q.where(CargoPortOption.kind == kind)
    rows = db.scalars(q.order_by(CargoPortOption.kind, CargoPortOption.seq)).all()
    return [_opt_public(r) for r in rows]


@router.post("/cargo/{cargo_id}/options", status_code=201)
def add_cargo_option(
    cargo_id: UUID,
    body: CargoOptionIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    _get_cargo(db, cargo_id, auth.tenant_id)
    if body.kind not in ("load", "disch"):
        raise HTTPException(422, "kind must be load or disch")
    row = CargoPortOption(
        tenant_id=auth.tenant_id,
        cargo_id=cargo_id,
        **body.model_dump(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _opt_public(row)


@router.patch("/cargo/{cargo_id}/options/{row_id}")
def update_cargo_option(
    cargo_id: UUID,
    row_id: UUID,
    body: CargoOptionPatch,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    _get_cargo(db, cargo_id, auth.tenant_id)
    row = scoped_get(db, CargoPortOption, row_id, auth.tenant_id)
    if not row or row.cargo_id != cargo_id:
        raise HTTPException(404, "Option row not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _opt_public(row)


@router.delete("/cargo/{cargo_id}/options/{row_id}")
def delete_cargo_option(
    cargo_id: UUID,
    row_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    _get_cargo(db, cargo_id, auth.tenant_id)
    row = scoped_get(db, CargoPortOption, row_id, auth.tenant_id)
    if not row or row.cargo_id != cargo_id:
        raise HTTPException(404, "Option row not found")
    db.delete(row)
    db.commit()
    return {"ok": True}
