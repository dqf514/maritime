"""燃油采购与加油路由。"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.pagination import envelope, paginate
from app.security import AuthContext, require_module

from app.models_domain import (
    BunkerCapCollar,
    BunkerOption,
    BunkerOrder,
    BunkerRequirement,
    Charter,
    FuelConsumptionCategory,
    MarketQuote,
    Voyage,
)
from app.models_finance_ext import BunkerInquiry
from app.services.bunker_procurement import next_requirement_no
from app.services.recycle import soft_delete
from app.services.state_machine import BUNKER_REQUIREMENT_TRANSITIONS, BUNKER_TRANSITIONS, transition

from app.routers._finance_common import _alive

from app.models_domain import NoonReport
from app.models_wave1 import Counterparty, Port, Vessel
from app.services.sanctions import assert_not_sanctioned
from app.services.tenant_guard import scoped_get

router = APIRouter()


# —— Bunker ——
class BunkerIn(BaseModel):
    vessel_id: UUID | None = None
    voyage_id: UUID | None = None
    grade: str = "VLSFO"
    qty_ordered: float
    unit_price: float | None = None  # required unless index_symbol is given
    rob_before: float | None = None
    counterparty_id: UUID | None = None
    supplier: str | None = None
    index_symbol: str | None = None  # e.g. SIN380 — price = latest quote + differential
    price_differential: float = 0


def _latest_quote(db: Session, tenant_id: UUID, symbol: str) -> MarketQuote | None:
    return db.scalars(
        select(MarketQuote)
        .where(
            MarketQuote.symbol == symbol,
            (MarketQuote.tenant_id == tenant_id) | (MarketQuote.tenant_id.is_(None)),
        )
        .order_by(MarketQuote.quote_date.desc())
        .limit(1)
    ).first()


@router.post("/bunker-orders")
def create_bunker(body: BunkerIn, auth: AuthContext = Depends(require_module("bunker")), db: Session = Depends(get_db)):
    if body.counterparty_id:
        party = db.get(Counterparty, body.counterparty_id)
        if not party or party.tenant_id != auth.tenant_id or party.deleted_at:
            raise HTTPException(404, "Counterparty not found")
        assert_not_sanctioned(db, auth.tenant_id, party.id)
    if body.vessel_id is not None and scoped_get(db, Vessel, body.vessel_id, auth.tenant_id) is None:
        raise HTTPException(404, "Vessel not found")
    if body.voyage_id is not None and scoped_get(db, Voyage, body.voyage_id, auth.tenant_id) is None:
        raise HTTPException(404, "Voyage not found")
    index_quote: MarketQuote | None = None
    unit_price = body.unit_price
    if body.index_symbol:
        # Index-linked pricing: unit price = latest market quote + differential (e.g. SIN380+12).
        index_quote = _latest_quote(db, auth.tenant_id, body.index_symbol)
        if index_quote is None:
            raise HTTPException(
                status_code=422,
                detail={"code": "NO_INDEX_QUOTE", "message": f"No market quote available for index '{body.index_symbol}'"},
            )
        unit_price = float(
            (Decimal(str(index_quote.value)) + Decimal(str(body.price_differential))).quantize(Decimal("0.01"))
        )
    if unit_price is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "UNIT_PRICE_REQUIRED", "message": "unit_price is required unless index_symbol is given"},
        )
    row = BunkerOrder(
        tenant_id=auth.tenant_id,
        order_no=f"BNK-{datetime.now().strftime('%Y%m%d')}-{str(uuid4())[:5].upper()}",
        vessel_id=body.vessel_id,
        voyage_id=body.voyage_id,
        grade=body.grade,
        qty_ordered=body.qty_ordered,
        unit_price=unit_price,
        rob_before=body.rob_before,
        counterparty_id=body.counterparty_id,
    )
    if body.supplier is not None:
        row.supplier = body.supplier
    db.add(row)
    db.flush()
    pricing_meta: dict | None = None
    if index_quote is not None:
        # Audit trail of the index pricing source (BunkerOrder has no meta column).
        pricing_meta = {
            "source": "index",
            "index_symbol": body.index_symbol,
            "quote_date": index_quote.quote_date.isoformat(),
            "quote_value": float(index_quote.value),
            "price_differential": body.price_differential,
        }
        db.add(
            BunkerInquiry(
                tenant_id=auth.tenant_id,
                order_id=row.id,
                supplier=f"INDEX:{body.index_symbol}",
                quoted_price=Decimal(str(unit_price)),
                status="accepted",
                meta=pricing_meta,
            )
        )
    db.commit()
    return {
        "id": str(row.id),
        "order_no": row.order_no,
        "status": row.status,
        "unit_price": float(row.unit_price or 0),
        "pricing": pricing_meta,
    }


@router.post("/bunker-orders/{order_id}/transition")
def bunker_transition(
    order_id: UUID,
    target: str,
    qty_delivered: float | None = None,
    consumption: float | None = None,
    bdn_qty: float | None = None,
    density_kg_m3: float | None = None,
    sulphur_pct: float | None = None,
    bdn_date: date | None = None,
    supplier: str | None = None,
    barge: str | None = None,
    auth: AuthContext = Depends(require_module("bunker")),
    db: Session = Depends(get_db),
):
    row = db.get(BunkerOrder, order_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Bunker order not found")
    row.status = transition("bunker_order", row.status, target, BUNKER_TRANSITIONS)
    if bdn_qty is not None and qty_delivered is None:
        qty_delivered = bdn_qty
    if qty_delivered is not None:
        row.qty_delivered = Decimal(str(qty_delivered))
    if consumption is not None:
        row.consumption = Decimal(str(consumption))
    warnings: list[dict] = []
    if target == "delivered":
        before = Decimal(str(row.rob_before or 0))
        delivered = Decimal(str(row.qty_delivered or row.qty_ordered or 0))
        cons = Decimal(str(row.consumption or 0))
        row.rob_after = before + delivered - cons
        if bdn_qty is not None:
            bdn = Decimal(str(bdn_qty))
            ordered = Decimal(str(row.qty_ordered or 0))
            if ordered > 0 and abs(bdn - ordered) / ordered > Decimal("0.02"):
                warnings.append(
                    {
                        "code": "BDN_QTY_DEVIATION",
                        "message": f"BDN qty {float(bdn)} deviates >2% from ordered qty {float(ordered)}",
                    }
                )
            # ROB conservation: rob_after should equal rob_before + BDN qty − consumption (0.5% tolerance)
            expected = before + bdn - cons
            if expected > 0 and abs(Decimal(str(row.rob_after)) - expected) / expected > Decimal("0.005"):
                warnings.append(
                    {
                        "code": "ROB_CONSERVATION",
                        "message": f"rob_after {float(row.rob_after)} != rob_before + bdn_qty − consumption ({float(expected)}) beyond 0.5%",
                    }
                )
    for name, value in (
        ("bdn_qty", bdn_qty),
        ("density_kg_m3", density_kg_m3),
        ("sulphur_pct", sulphur_pct),
        ("bdn_date", bdn_date),
        ("supplier", supplier),
        ("barge", barge),
    ):
        if value is not None:
            setattr(row, name, value)
    db.commit()
    return {
        "id": str(row.id),
        "status": row.status,
        "rob_before": float(row.rob_before or 0),
        "rob_after": float(row.rob_after or 0),
        "qty_delivered": float(row.qty_delivered or 0),
        "warnings": warnings,
    }


@router.get("/bunker-orders")
def list_bunker(auth: AuthContext = Depends(require_module("bunker")), db: Session = Depends(get_db)):
    rows = db.scalars(select(BunkerOrder).where(BunkerOrder.tenant_id == auth.tenant_id)).all()
    return [
        {
            "id": str(r.id),
            "order_no": r.order_no,
            "status": r.status,
            "vessel_id": str(r.vessel_id) if r.vessel_id else None,
            "voyage_id": str(r.voyage_id) if r.voyage_id else None,
            "grade": r.grade,
            "qty_ordered": float(r.qty_ordered or 0),
            "qty_delivered": float(r.qty_delivered or 0) if r.qty_delivered is not None else None,
            "unit_price": float(r.unit_price or 0),
            "rob_before": float(r.rob_before or 0) if r.rob_before is not None else None,
            "rob_after": float(r.rob_after or 0) if r.rob_after is not None else None,
            "consumption": float(r.consumption or 0) if r.consumption is not None else None,
            "currency": r.currency,
            "amount": float(r.qty_ordered or 0) * float(r.unit_price or 0),
            "supplier": r.supplier,
            "counterparty_id": str(r.counterparty_id) if r.counterparty_id else None,
        }
        for r in rows
    ]


class BunkerUpdate(BaseModel):
    grade: str | None = None
    qty_ordered: float | None = None
    unit_price: float | None = None
    rob_before: float | None = None
    vessel_id: UUID | None = None
    voyage_id: UUID | None = None
    supplier: str | None = None
    counterparty_id: UUID | None = None


@router.patch("/bunker-orders/{order_id}")
def update_bunker(
    order_id: UUID,
    body: BunkerUpdate,
    auth: AuthContext = Depends(require_module("bunker")),
    db: Session = Depends(get_db),
):
    row = db.get(BunkerOrder, order_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Bunker order not found")
    if body.grade is not None:
        row.grade = body.grade
    if body.qty_ordered is not None:
        row.qty_ordered = body.qty_ordered
    if body.unit_price is not None:
        row.unit_price = body.unit_price
    if body.rob_before is not None:
        row.rob_before = body.rob_before
    if body.vessel_id is not None:
        if scoped_get(db, Vessel, body.vessel_id, auth.tenant_id) is None:
            raise HTTPException(404, "Vessel not found")
        row.vessel_id = body.vessel_id
    if body.voyage_id is not None:
        if scoped_get(db, Voyage, body.voyage_id, auth.tenant_id) is None:
            raise HTTPException(404, "Voyage not found")
        row.voyage_id = body.voyage_id
    if body.supplier is not None:
        row.supplier = body.supplier
    if body.counterparty_id is not None:
        party = db.get(Counterparty, body.counterparty_id)
        if not party or party.tenant_id != auth.tenant_id or party.deleted_at:
            raise HTTPException(404, "Counterparty not found")
        row.counterparty_id = body.counterparty_id
    db.commit()
    return {"id": str(row.id), "order_no": row.order_no, "status": row.status}


class BunkerInquiryIn(BaseModel):
    supplier: str
    quoted_price: float


@router.post("/bunker-orders/{order_id}/inquiries")
def create_bunker_inquiry(
    order_id: UUID,
    body: BunkerInquiryIn,
    auth: AuthContext = Depends(require_module("bunker")),
    db: Session = Depends(get_db),
):
    order = db.get(BunkerOrder, order_id)
    if not order or order.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Bunker order not found")
    if body.quoted_price <= 0:
        raise HTTPException(422, detail={"code": "INVALID_PRICE", "message": "quoted_price must be > 0"})
    row = BunkerInquiry(
        tenant_id=auth.tenant_id,
        order_id=order.id,
        supplier=body.supplier,
        quoted_price=Decimal(str(body.quoted_price)).quantize(Decimal("0.01")),
        status="quoted",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "order_id": str(order.id), "status": row.status, "quoted_price": float(row.quoted_price)}


@router.get("/bunker-orders/{order_id}/inquiries")
def list_bunker_inquiries(order_id: UUID, auth: AuthContext = Depends(require_module("bunker")), db: Session = Depends(get_db)):
    """All supplier quotes for a bunker order (含 INDEX: 定价审计行), newest first."""
    order = db.get(BunkerOrder, order_id)
    if not order or order.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Bunker order not found")
    rows = db.scalars(
        select(BunkerInquiry)
        .where(BunkerInquiry.order_id == order.id)
        .order_by(BunkerInquiry.quoted_at.desc())
    ).all()
    return [
        {
            "id": str(r.id),
            "order_id": str(r.order_id),
            "supplier": r.supplier,
            "quoted_price": float(r.quoted_price or 0),
            "status": r.status,
            "quoted_at": r.quoted_at.isoformat() if r.quoted_at else None,
            "meta": r.meta or {},
        }
        for r in rows
    ]


@router.post("/bunker-inquiries/{inquiry_id}/accept")
def accept_bunker_inquiry(
    inquiry_id: UUID,
    auth: AuthContext = Depends(require_module("bunker")),
    db: Session = Depends(get_db),
):
    """Accept one supplier quote: writes price + supplier back to the order and
    rejects the order's remaining quotes."""
    row = db.get(BunkerInquiry, inquiry_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Bunker inquiry not found")
    if row.status != "quoted":
        raise HTTPException(
            status_code=409,
            detail={"code": "INVALID_STATE", "message": f"Cannot accept an inquiry in status {row.status}"},
        )
    order = db.get(BunkerOrder, row.order_id)
    if not order or order.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Bunker order not found")
    row.status = "accepted"
    order.unit_price = row.quoted_price
    if row.supplier:
        order.supplier = row.supplier
    others = db.scalars(
        select(BunkerInquiry).where(
            BunkerInquiry.order_id == order.id,
            BunkerInquiry.id != row.id,
            BunkerInquiry.status == "quoted",
        )
    ).all()
    for other in others:
        other.status = "rejected"
    db.commit()
    return {
        "id": str(row.id),
        "status": row.status,
        "order_id": str(order.id),
        "unit_price": float(order.unit_price or 0),
        "supplier": order.supplier,
    }


@router.get("/voyages/{voyage_id}/bunker-allocation")
def bunker_allocation(voyage_id: UUID, auth: AuthContext = Depends(require_module("bunker")), db: Session = Depends(get_db)):
    """Estimated bunker cost allocation for a voyage.

    简化口径: consumption = sum of positive ROB (FO+DO) drops between
    consecutive noon reports; unit cost = quantity-weighted average price of
    the voyage's delivered bunker orders. Allocation = consumption × weighted
    price. ROB increases (bunkering between reports) are ignored.
    """
    voyage = db.get(Voyage, voyage_id)
    if not voyage or voyage.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Voyage not found")
    noons = db.scalars(
        select(NoonReport)
        .where(NoonReport.tenant_id == auth.tenant_id, NoonReport.voyage_id == voyage.id)
        .order_by(NoonReport.report_at.asc())
    ).all()
    consumption = Decimal("0")
    prev_rob: Decimal | None = None
    for n in noons:
        rob = Decimal(str(n.rob_fo or 0)) + Decimal(str(n.rob_do or 0))
        if prev_rob is not None and rob < prev_rob:
            consumption += prev_rob - rob
        prev_rob = rob
    orders = db.scalars(
        select(BunkerOrder).where(
            BunkerOrder.tenant_id == auth.tenant_id,
            BunkerOrder.voyage_id == voyage.id,
            BunkerOrder.status.in_(["delivered", "closed"]),
        )
    ).all()
    total_qty = Decimal("0")
    total_value = Decimal("0")
    for o in orders:
        qty = Decimal(str(o.qty_delivered or 0))
        if qty > 0:
            total_qty += qty
            total_value += qty * Decimal(str(o.unit_price or 0))
    wavg = (total_value / total_qty).quantize(Decimal("0.01")) if total_qty > 0 else None
    allocated = (consumption * wavg).quantize(Decimal("0.01")) if wavg is not None else None
    return {
        "voyage_id": str(voyage.id),
        "voyage_no": voyage.voyage_no,
        "consumption_mt": float(consumption.quantize(Decimal("0.001"))),
        "weighted_avg_price": float(wavg) if wavg is not None else None,
        "allocated_amount": float(allocated) if allocated is not None else None,
        "currency": "USD",
        "noon_reports": len(noons),
        "delivered_orders": len(orders),
        "basis": "noon ROB(FO+DO) drops x qty-weighted price of delivered bunker orders (simplified)",
    }


# —— Bunker requirement & procurement chain (需求→招标→报价→选定) ——

BUNKER_REQUIREMENT_STATUSES = ("draft", "approved", "tendering", "ordered", "fulfilled", "cancelled")
CONSUMPTION_CATEGORIES = ("sea", "port_working", "port_idle", "maneuvering", "cargo_heating", "ballast")


class BunkerRequirementIn(BaseModel):
    vessel_id: UUID
    voyage_id: UUID | None = None
    fuel_type: str = "VLSFO"
    qty_required: float
    port_id: UUID | None = None
    window_from: date | None = None
    window_to: date | None = None
    notes: str | None = None


def _requirement_payload(r: BunkerRequirement) -> dict:
    return {
        "id": str(r.id),
        "requirement_no": r.requirement_no,
        "status": r.status,
        "vessel_id": str(r.vessel_id),
        "voyage_id": str(r.voyage_id) if r.voyage_id else None,
        "fuel_type": r.fuel_type,
        "qty_required": float(r.qty_required or 0),
        "port_id": str(r.port_id) if r.port_id else None,
        "window_from": r.window_from.isoformat() if r.window_from else None,
        "window_to": r.window_to.isoformat() if r.window_to else None,
        "notes": r.notes,
    }


def _option_payload(o: BunkerOption) -> dict:
    return {
        "id": str(o.id),
        "requirement_id": str(o.requirement_id),
        "supplier_id": str(o.supplier_id),
        "port_id": str(o.port_id),
        "fuel_type": o.fuel_type,
        "qty": float(o.qty or 0),
        "price_per_mt": float(o.price_per_mt or 0),
        "amount": float(o.qty or 0) * float(o.price_per_mt or 0),
        "delivery_date": o.delivery_date.isoformat() if o.delivery_date else None,
        "status": o.status,
        "notes": o.notes,
    }


def _check_vessel(db: Session, tenant_id: UUID, vessel_id: UUID) -> None:
    if scoped_get(db, Vessel, vessel_id, tenant_id) is None:
        raise HTTPException(404, "Vessel not found")


def _check_voyage(db: Session, tenant_id: UUID, voyage_id: UUID) -> None:
    if scoped_get(db, Voyage, voyage_id, tenant_id) is None:
        raise HTTPException(404, "Voyage not found")


@router.post("/bunker/requirements")
def create_bunker_requirement(
    body: BunkerRequirementIn,
    auth: AuthContext = Depends(require_module("bunker")),
    db: Session = Depends(get_db),
):
    if body.qty_required <= 0:
        raise HTTPException(422, detail={"code": "INVALID_QTY", "message": "qty_required must be > 0"})
    _check_vessel(db, auth.tenant_id, body.vessel_id)
    if body.voyage_id is not None:
        _check_voyage(db, auth.tenant_id, body.voyage_id)
    if body.port_id is not None:
        _port = db.get(Port, body.port_id)
        if not _port or _port.deleted_at:
            raise HTTPException(404, "Port not found")
    if body.window_from and body.window_to and body.window_to < body.window_from:
        raise HTTPException(422, detail={"code": "INVALID_WINDOW", "message": "window_to must be >= window_from"})
    row = BunkerRequirement(
        tenant_id=auth.tenant_id,
        requirement_no=next_requirement_no(),
        vessel_id=body.vessel_id,
        voyage_id=body.voyage_id,
        fuel_type=body.fuel_type,
        qty_required=Decimal(str(body.qty_required)).quantize(Decimal("0.001")),
        port_id=body.port_id,
        window_from=body.window_from,
        window_to=body.window_to,
        status="draft",
        notes=body.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _requirement_payload(row)


@router.get("/bunker/requirements")
def list_bunker_requirements(
    status: str | None = Query(None),
    vessel_id: UUID | None = Query(None),
    voyage_id: UUID | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("bunker")),
    db: Session = Depends(get_db),
):
    q = select(BunkerRequirement).where(BunkerRequirement.tenant_id == auth.tenant_id)
    if status is not None:
        q = q.where(BunkerRequirement.status == status)
    if vessel_id is not None:
        q = q.where(BunkerRequirement.vessel_id == vessel_id)
    if voyage_id is not None:
        q = q.where(BunkerRequirement.voyage_id == voyage_id)
    rows, total = paginate(db, q.order_by(BunkerRequirement.id), limit, offset)
    return envelope([_requirement_payload(r) for r in rows], total, limit, offset)


@router.post("/bunker/requirements/{requirement_id}/tender")
def tender_bunker_requirement(
    requirement_id: UUID,
    auth: AuthContext = Depends(require_module("bunker")),
    db: Session = Depends(get_db),
):
    """Open tendering on a requirement (draft|approved → tendering)."""
    row = db.get(BunkerRequirement, requirement_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Bunker requirement not found")
    row.status = transition("bunker_requirement", row.status, "tendering", BUNKER_REQUIREMENT_TRANSITIONS)
    db.commit()
    return _requirement_payload(row)


@router.post("/bunker/requirements/{requirement_id}/transition")
def transition_bunker_requirement(
    requirement_id: UUID,
    target: str,
    auth: AuthContext = Depends(require_module("bunker")),
    db: Session = Depends(get_db),
):
    """Generic requirement lifecycle move (approved/ordered/fulfilled/cancelled/...)."""
    if target not in BUNKER_REQUIREMENT_STATUSES:
        raise HTTPException(422, detail={"code": "INVALID_STATUS", "message": f"Unknown status '{target}'"})
    row = db.get(BunkerRequirement, requirement_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Bunker requirement not found")
    row.status = transition("bunker_requirement", row.status, target, BUNKER_REQUIREMENT_TRANSITIONS)
    db.commit()
    return _requirement_payload(row)


class BunkerOptionIn(BaseModel):
    requirement_id: UUID
    supplier_id: UUID
    port_id: UUID | None = None
    fuel_type: str | None = None
    qty: float | None = None
    price_per_mt: float
    delivery_date: date | None = None
    notes: str | None = None


@router.post("/bunker/options")
def create_bunker_option(
    body: BunkerOptionIn,
    auth: AuthContext = Depends(require_module("bunker")),
    db: Session = Depends(get_db),
):
    if body.price_per_mt <= 0:
        raise HTTPException(422, detail={"code": "INVALID_PRICE", "message": "price_per_mt must be > 0"})
    req = db.get(BunkerRequirement, body.requirement_id)
    if not req or req.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Bunker requirement not found")
    if req.status in ("fulfilled", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail={"code": "INVALID_STATE", "message": f"Cannot add options to a {req.status} requirement"},
        )
    party = db.get(Counterparty, body.supplier_id)
    if not party or party.tenant_id != auth.tenant_id or party.deleted_at:
        raise HTTPException(404, "Supplier not found")
    assert_not_sanctioned(db, auth.tenant_id, party.id)
    port_id = body.port_id or req.port_id
    if port_id is None:
        raise HTTPException(422, detail={"code": "PORT_REQUIRED", "message": "port_id is required (option or requirement)"})
    _port = db.get(Port, port_id)
    if not _port or _port.deleted_at:
        raise HTTPException(404, "Port not found")
    qty = body.qty if body.qty is not None else float(req.qty_required or 0)
    if qty <= 0:
        raise HTTPException(422, detail={"code": "INVALID_QTY", "message": "qty must be > 0"})
    row = BunkerOption(
        tenant_id=auth.tenant_id,
        requirement_id=req.id,
        supplier_id=body.supplier_id,
        port_id=port_id,
        fuel_type=body.fuel_type or req.fuel_type,
        qty=Decimal(str(qty)).quantize(Decimal("0.001")),
        price_per_mt=Decimal(str(body.price_per_mt)).quantize(Decimal("0.01")),
        delivery_date=body.delivery_date,
        status="offered",
        notes=body.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _option_payload(row)


@router.get("/bunker/options")
def list_bunker_options(
    requirement_id: UUID | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("bunker")),
    db: Session = Depends(get_db),
):
    q = select(BunkerOption).where(BunkerOption.tenant_id == auth.tenant_id)
    if requirement_id is not None:
        q = q.where(BunkerOption.requirement_id == requirement_id)
    if status is not None:
        q = q.where(BunkerOption.status == status)
    rows, total = paginate(db, q.order_by(BunkerOption.id), limit, offset)
    return envelope([_option_payload(o) for o in rows], total, limit, offset)


@router.post("/bunker/options/{option_id}/select")
def select_bunker_option(
    option_id: UUID,
    auth: AuthContext = Depends(require_module("bunker")),
    db: Session = Depends(get_db),
):
    """Select a supplier option: siblings become rejected, requirement → ordered."""
    opt = db.get(BunkerOption, option_id)
    if not opt or opt.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Bunker option not found")
    if opt.status != "offered":
        raise HTTPException(
            status_code=409,
            detail={"code": "INVALID_STATE", "message": f"Cannot select an option in status {opt.status}"},
        )
    req = db.get(BunkerRequirement, opt.requirement_id)
    if not req or req.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Bunker requirement not found")
    if req.status not in ("draft", "approved", "tendering"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INVALID_STATE",
                "message": f"Cannot select an option for a requirement in status {req.status}",
            },
        )
    opt.status = "selected"
    others = db.scalars(
        select(BunkerOption).where(
            BunkerOption.requirement_id == req.id,
            BunkerOption.id != opt.id,
            BunkerOption.status == "offered",
        )
    ).all()
    for other in others:
        other.status = "rejected"
    req.status = transition("bunker_requirement", req.status, "ordered", BUNKER_REQUIREMENT_TRANSITIONS)
    db.commit()
    return {
        "id": str(opt.id),
        "status": opt.status,
        "requirement_id": str(req.id),
        "requirement_status": req.status,
        "supplier_id": str(opt.supplier_id),
        "price_per_mt": float(opt.price_per_mt or 0),
        "rejected_options": len(others),
    }


# —— Bunker cap/collar (价格上下限保护) ——


class BunkerCapCollarIn(BaseModel):
    charter_id: UUID | None = None
    fuel_type: str
    cap_price: float | None = None
    collar_price: float | None = None
    index_symbol: str | None = None
    effective_from: date
    effective_to: date | None = None


@router.post("/bunker/cap-collar")
def create_bunker_cap_collar(
    body: BunkerCapCollarIn,
    auth: AuthContext = Depends(require_module("bunker")),
    db: Session = Depends(get_db),
):
    if body.cap_price is None and body.collar_price is None:
        raise HTTPException(
            422,
            detail={"code": "CAP_OR_COLLAR_REQUIRED", "message": "At least one of cap_price / collar_price is required"},
        )
    if body.cap_price is not None and body.cap_price <= 0:
        raise HTTPException(422, detail={"code": "INVALID_CAP", "message": "cap_price must be > 0"})
    if body.collar_price is not None and body.collar_price <= 0:
        raise HTTPException(422, detail={"code": "INVALID_COLLAR", "message": "collar_price must be > 0"})
    if body.cap_price is not None and body.collar_price is not None and body.collar_price > body.cap_price:
        raise HTTPException(
            422,
            detail={"code": "COLLAR_ABOVE_CAP", "message": "collar_price must be <= cap_price"},
        )
    if body.effective_to is not None and body.effective_to < body.effective_from:
        raise HTTPException(
            422,
            detail={"code": "INVALID_PERIOD", "message": "effective_to must be >= effective_from"},
        )
    if body.charter_id is not None and scoped_get(db, Charter, body.charter_id, auth.tenant_id) is None:
        raise HTTPException(404, "Charter not found")
    row = BunkerCapCollar(
        tenant_id=auth.tenant_id,
        charter_id=body.charter_id,
        fuel_type=body.fuel_type,
        cap_price=Decimal(str(body.cap_price)).quantize(Decimal("0.01")) if body.cap_price is not None else None,
        collar_price=Decimal(str(body.collar_price)).quantize(Decimal("0.01")) if body.collar_price is not None else None,
        index_symbol=body.index_symbol,
        effective_from=body.effective_from,
        effective_to=body.effective_to,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _cap_collar_payload(row)


@router.get("/bunker/cap-collar")
def list_bunker_cap_collar(
    fuel_type: str | None = Query(None),
    charter_id: UUID | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("bunker")),
    db: Session = Depends(get_db),
):
    q = select(BunkerCapCollar).where(BunkerCapCollar.tenant_id == auth.tenant_id)
    if fuel_type is not None:
        q = q.where(BunkerCapCollar.fuel_type == fuel_type)
    if charter_id is not None:
        q = q.where(BunkerCapCollar.charter_id == charter_id)
    rows, total = paginate(db, q.order_by(BunkerCapCollar.id), limit, offset)
    return envelope([_cap_collar_payload(r) for r in rows], total, limit, offset)


def _cap_collar_payload(r: BunkerCapCollar) -> dict:
    return {
        "id": str(r.id),
        "charter_id": str(r.charter_id) if r.charter_id else None,
        "fuel_type": r.fuel_type,
        "cap_price": float(r.cap_price) if r.cap_price is not None else None,
        "collar_price": float(r.collar_price) if r.collar_price is not None else None,
        "index_symbol": r.index_symbol,
        "effective_from": r.effective_from.isoformat() if r.effective_from else None,
        "effective_to": r.effective_to.isoformat() if r.effective_to else None,
    }


# —— Fuel consumption categories (分场景油耗定额) ——


class ConsumptionCategoryIn(BaseModel):
    vessel_id: UUID
    category: str
    fuel_type: str = "VLSFO"
    consumption_per_day: float
    notes: str | None = None


@router.post("/bunker/consumption-categories")
def create_consumption_category(
    body: ConsumptionCategoryIn,
    auth: AuthContext = Depends(require_module("bunker")),
    db: Session = Depends(get_db),
):
    if body.category not in CONSUMPTION_CATEGORIES:
        raise HTTPException(
            422,
            detail={"code": "INVALID_CATEGORY", "message": f"category must be one of {list(CONSUMPTION_CATEGORIES)}"},
        )
    if body.consumption_per_day < 0:
        raise HTTPException(422, detail={"code": "INVALID_CONSUMPTION", "message": "consumption_per_day must be >= 0"})
    _check_vessel(db, auth.tenant_id, body.vessel_id)
    row = FuelConsumptionCategory(
        tenant_id=auth.tenant_id,
        vessel_id=body.vessel_id,
        category=body.category,
        fuel_type=body.fuel_type,
        consumption_per_day=Decimal(str(body.consumption_per_day)).quantize(Decimal("0.001")),
        notes=body.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _consumption_payload(row)


@router.get("/bunker/consumption-categories")
def list_consumption_categories(
    vessel_id: UUID | None = Query(None),
    category: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("bunker")),
    db: Session = Depends(get_db),
):
    q = select(FuelConsumptionCategory).where(FuelConsumptionCategory.tenant_id == auth.tenant_id)
    if vessel_id is not None:
        q = q.where(FuelConsumptionCategory.vessel_id == vessel_id)
    if category is not None:
        q = q.where(FuelConsumptionCategory.category == category)
    rows, total = paginate(db, q.order_by(FuelConsumptionCategory.id), limit, offset)
    return envelope([_consumption_payload(r) for r in rows], total, limit, offset)


def _consumption_payload(r: FuelConsumptionCategory) -> dict:
    return {
        "id": str(r.id),
        "vessel_id": str(r.vessel_id),
        "category": r.category,
        "fuel_type": r.fuel_type,
        "consumption_per_day": float(r.consumption_per_day or 0),
        "notes": r.notes,
    }


