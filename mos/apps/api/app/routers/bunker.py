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

from app.models_domain import BunkerOrder, MarketQuote, Voyage
from app.models_finance_ext import BunkerInquiry
from app.services.recycle import soft_delete
from app.services.state_machine import BUNKER_TRANSITIONS, transition

from app.routers._finance_common import _alive

from app.models_domain import NoonReport
from app.models_wave1 import Counterparty, Vessel
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


