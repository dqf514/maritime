"""Phase 7 Trading & Risk routes — FFA/掉期/期权/实货纸货交易、盯市与敞口.

Path map (all under ``/api/v1/trading``):
  GET    /trading/trades                — list + pagination + filters (kind/status/route/date)
  POST   /trading/trades                — create (TRD-YYYY-NNNNN, optional legs)
  GET    /trading/trades/{id}           — detail with legs
  PATCH  /trading/trades/{id}           — update
  DELETE /trading/trades/{id}           — soft delete (recycle bin)
  POST   /trading/trades/{id}/transition — state machine (TRADE_TRANSITIONS)
  POST   /trading/trades/{id}/legs      — replace legs
  GET    /trading/positions             — net paper/physical positions
  POST   /trading/mtm/run?date=X        — run MtM for all trades
  GET    /trading/mtm/summary?date=X    — MtM portfolio summary
  GET    /trading/exposure              — risk exposure by route/period

All ORM access is tenant-scoped (``scoped_get`` / ``scoped_query``).
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
from app.models_trading import TRADE_KINDS, TRADE_SIDES, Trade, TradeLeg
from app.models_wave1 import Counterparty
from app.pagination import envelope, paginate
from app.security import AuthContext, require_module
from app.services import mtm_engine
from app.services.doc_numbering import next_doc_number
from app.services.recycle import soft_delete
from app.services.state_machine import TRADE_TRANSITIONS, transition
from app.services.tenant_guard import scoped_get, scoped_query

router = APIRouter(prefix="/trading", tags=["Trading"])


class TradeLegIn(BaseModel):
    leg_no: int = Field(ge=1)
    period_from: date
    period_to: date
    qty: Decimal = Field(gt=0)
    fixed_price: Decimal | None = None
    index_symbol: str | None = None
    settlement_amount: Decimal | None = None


class TradeIn(BaseModel):
    kind: str
    buy_sell: str
    route: str | None = None
    period_from: date | None = None
    period_to: date | None = None
    qty: Decimal = Field(gt=0)
    qty_unit: str | None = None
    price: Decimal
    price_unit: str | None = None
    index_symbol: str | None = None
    counterparty_id: UUID | None = None
    trade_date: date | None = None
    settlement_date: date | None = None
    notes: str | None = None
    legs: list[TradeLegIn] = Field(default_factory=list)


class TradePatch(BaseModel):
    route: str | None = None
    period_from: date | None = None
    period_to: date | None = None
    qty: Decimal | None = Field(default=None, gt=0)
    qty_unit: str | None = None
    price: Decimal | None = None
    price_unit: str | None = None
    index_symbol: str | None = None
    counterparty_id: UUID | None = None
    settlement_date: date | None = None
    notes: str | None = None


class LegsIn(BaseModel):
    legs: list[TradeLegIn] = Field(default_factory=list)


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def _validate_trade_fields(
    db: Session, tenant_id: UUID, body: TradeIn | TradePatch | TradeLegIn, *, kind: str | None = None
) -> None:
    k = getattr(body, "kind", None) or kind
    if k is not None and k not in TRADE_KINDS:
        raise HTTPException(422, detail={"code": "TRADE_KIND_UNKNOWN", "message": k})
    side = getattr(body, "buy_sell", None)
    if side is not None and side not in TRADE_SIDES:
        raise HTTPException(422, detail={"code": "TRADE_SIDE_UNKNOWN", "message": side})
    p_from = getattr(body, "period_from", None)
    p_to = getattr(body, "period_to", None)
    if p_from is not None and p_to is not None and p_to < p_from:
        raise HTTPException(422, detail={"code": "TRADE_PERIOD_INVALID", "message": "period_to before period_from"})
    cp = getattr(body, "counterparty_id", None)
    if cp is not None and scoped_get(db, Counterparty, cp, tenant_id) is None:
        raise HTTPException(404, "Counterparty not found")


def _leg_public(row: TradeLeg) -> dict:
    return {
        "id": str(row.id),
        "trade_id": str(row.trade_id),
        "leg_no": row.leg_no,
        "period_from": row.period_from.isoformat(),
        "period_to": row.period_to.isoformat(),
        "qty": _f(row.qty),
        "fixed_price": _f(row.fixed_price) if row.fixed_price is not None else None,
        "index_symbol": row.index_symbol,
        "settlement_amount": _f(row.settlement_amount) if row.settlement_amount is not None else None,
    }


def _trade_public(row: Trade, legs: list[TradeLeg] | None = None) -> dict:
    out = {
        "id": str(row.id),
        "trade_no": row.trade_no,
        "kind": row.kind,
        "buy_sell": row.buy_sell,
        "route": row.route,
        "period_from": row.period_from.isoformat() if row.period_from else None,
        "period_to": row.period_to.isoformat() if row.period_to else None,
        "qty": _f(row.qty),
        "qty_unit": row.qty_unit,
        "price": _f(row.price),
        "price_unit": row.price_unit,
        "index_symbol": row.index_symbol,
        "counterparty_id": str(row.counterparty_id) if row.counterparty_id else None,
        "status": row.status,
        "trade_date": row.trade_date.isoformat(),
        "settlement_date": row.settlement_date.isoformat() if row.settlement_date else None,
        "notes": row.notes,
    }
    if legs is not None:
        out["legs"] = [_leg_public(lg) for lg in legs]
    return out


def _get_trade(db: Session, trade_id: UUID, tenant_id: UUID) -> Trade:
    row = scoped_get(db, Trade, trade_id, tenant_id)
    if row is None:
        raise HTTPException(404, "Trade not found")
    return row


def _legs_of(db: Session, trade_id: UUID, tenant_id: UUID) -> list[TradeLeg]:
    return list(
        db.scalars(
            select(TradeLeg)
            .where(TradeLeg.tenant_id == tenant_id, TradeLeg.trade_id == trade_id)
            .order_by(TradeLeg.leg_no)
        ).all()
    )


def _validate_legs(db: Session, trade: Trade, legs: list[TradeLegIn]) -> None:
    seen: set[int] = set()
    total = Decimal("0")
    for lg in legs:
        if lg.leg_no in seen:
            raise HTTPException(422, detail={"code": "TRADE_LEG_NO_DUPLICATE", "message": f"leg_no {lg.leg_no}"})
        seen.add(lg.leg_no)
        _validate_trade_fields(db, trade.tenant_id, lg, kind=trade.kind)
        if trade.period_from is not None and lg.period_from < trade.period_from:
            raise HTTPException(422, detail={"code": "TRADE_LEG_PERIOD", "message": f"leg {lg.leg_no} before trade period"})
        if trade.period_to is not None and lg.period_to > trade.period_to:
            raise HTTPException(422, detail={"code": "TRADE_LEG_PERIOD", "message": f"leg {lg.leg_no} after trade period"})
        total += lg.qty
    if legs and trade.qty is not None and total > Decimal(str(trade.qty)):
        raise HTTPException(
            422,
            detail={"code": "TRADE_LEG_QTY_EXCEEDED", "message": f"leg qty sum {total} exceeds trade qty {trade.qty}"},
        )


# ── Trades ───────────────────────────────────────────────────────────────────


@router.get("/trades")
def list_trades(
    kind: str | None = Query(None),
    status: str | None = Query(None),
    route: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    index_symbol: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("risk")),
    db: Session = Depends(get_db),
):
    q = scoped_query(db, Trade, auth.tenant_id)
    if kind:
        q = q.where(Trade.kind == kind)
    if status:
        q = q.where(Trade.status == status)
    if route:
        q = q.where(Trade.route == route)
    if index_symbol:
        q = q.where(Trade.index_symbol == index_symbol)
    if date_from:
        q = q.where(Trade.trade_date >= date_from)
    if date_to:
        q = q.where(Trade.trade_date <= date_to)
    rows, total = paginate(db, q.order_by(Trade.trade_no), limit, offset)
    return envelope([_trade_public(r) for r in rows], total, limit, offset)


@router.post("/trades", status_code=201)
def create_trade(
    body: TradeIn,
    auth: AuthContext = Depends(require_module("risk")),
    db: Session = Depends(get_db),
):
    _validate_trade_fields(db, auth.tenant_id, body)
    row = Trade(
        tenant_id=auth.tenant_id,
        trade_no=next_doc_number(db, auth.tenant_id, Trade, Trade.trade_no, "TRD"),
        kind=body.kind,
        buy_sell=body.buy_sell,
        route=body.route,
        period_from=body.period_from,
        period_to=body.period_to,
        qty=body.qty,
        qty_unit=body.qty_unit,
        price=body.price,
        price_unit=body.price_unit,
        index_symbol=body.index_symbol,
        counterparty_id=body.counterparty_id,
        trade_date=body.trade_date or date.today(),
        settlement_date=body.settlement_date,
        notes=body.notes,
    )
    db.add(row)
    db.flush()
    if body.legs:
        _validate_legs(db, row, body.legs)
        for lg in body.legs:
            db.add(
                TradeLeg(
                    tenant_id=auth.tenant_id,
                    trade_id=row.id,
                    leg_no=lg.leg_no,
                    period_from=lg.period_from,
                    period_to=lg.period_to,
                    qty=lg.qty,
                    fixed_price=lg.fixed_price,
                    index_symbol=lg.index_symbol,
                    settlement_amount=lg.settlement_amount,
                )
            )
    db.commit()
    db.refresh(row)
    return _trade_public(row, _legs_of(db, row.id, auth.tenant_id))


@router.get("/trades/{trade_id}")
def get_trade(
    trade_id: UUID,
    auth: AuthContext = Depends(require_module("risk")),
    db: Session = Depends(get_db),
):
    row = _get_trade(db, trade_id, auth.tenant_id)
    return _trade_public(row, _legs_of(db, row.id, auth.tenant_id))


@router.patch("/trades/{trade_id}")
def update_trade(
    trade_id: UUID,
    body: TradePatch,
    auth: AuthContext = Depends(require_module("risk")),
    db: Session = Depends(get_db),
):
    row = _get_trade(db, trade_id, auth.tenant_id)
    if row.status in ("settled", "cancelled"):
        raise HTTPException(422, detail={"code": "TRADE_LOCKED", "message": f"trade is {row.status}"})
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if fields:
        _validate_trade_fields(db, auth.tenant_id, body, kind=row.kind)
        p_from = fields.get("period_from", row.period_from)
        p_to = fields.get("period_to", row.period_to)
        if p_from is not None and p_to is not None and p_to < p_from:
            raise HTTPException(422, detail={"code": "TRADE_PERIOD_INVALID", "message": "period_to before period_from"})
        for k, v in fields.items():
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return _trade_public(row, _legs_of(db, row.id, auth.tenant_id))


@router.delete("/trades/{trade_id}")
def delete_trade(
    trade_id: UUID,
    auth: AuthContext = Depends(require_module("risk")),
    db: Session = Depends(get_db),
):
    row = _get_trade(db, trade_id, auth.tenant_id)
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="trade",
        row=row,
        title=row.trade_no,
    )
    db.commit()
    return {"ok": True, "recycled": True}


@router.post("/trades/{trade_id}/transition")
def transition_trade(
    trade_id: UUID,
    target: str,
    auth: AuthContext = Depends(require_module("risk")),
    db: Session = Depends(get_db),
):
    row = _get_trade(db, trade_id, auth.tenant_id)
    row.status = transition("trade", row.status, target, TRADE_TRANSITIONS)
    db.commit()
    return {"id": str(row.id), "status": row.status}


@router.post("/trades/{trade_id}/legs")
def replace_legs(
    trade_id: UUID,
    body: LegsIn,
    auth: AuthContext = Depends(require_module("risk")),
    db: Session = Depends(get_db),
):
    row = _get_trade(db, trade_id, auth.tenant_id)
    _validate_legs(db, row, body.legs)
    for old in _legs_of(db, row.id, auth.tenant_id):
        db.delete(old)
    for lg in body.legs:
        db.add(
            TradeLeg(
                tenant_id=auth.tenant_id,
                trade_id=row.id,
                leg_no=lg.leg_no,
                period_from=lg.period_from,
                period_to=lg.period_to,
                qty=lg.qty,
                fixed_price=lg.fixed_price,
                index_symbol=lg.index_symbol,
                settlement_amount=lg.settlement_amount,
            )
        )
    db.commit()
    return _trade_public(row, _legs_of(db, row.id, auth.tenant_id))


# ── Positions / MtM / exposure ───────────────────────────────────────────────


@router.get("/positions")
def net_positions(
    route: str | None = Query(None),
    period_from: date | None = Query(None),
    period_to: date | None = Query(None),
    auth: AuthContext = Depends(require_module("risk")),
    db: Session = Depends(get_db),
):
    if (period_from is None) != (period_to is None):
        raise HTTPException(422, detail={"code": "PERIOD_INCOMPLETE", "message": "provide period_from and period_to"})
    period = (period_from, period_to) if period_from and period_to else None
    return mtm_engine.position_netting(db, auth.tenant_id, route=route, period=period)


@router.post("/mtm/run")
def run_mtm(
    valuation_date: date | None = Query(None, alias="date"),
    snapshot_type: str = Query("daily"),
    auth: AuthContext = Depends(require_module("risk")),
    db: Session = Depends(get_db),
):
    if snapshot_type not in ("daily", "weekly", "monthly"):
        raise HTTPException(422, detail={"code": "MTM_SNAPSHOT_UNKNOWN", "message": snapshot_type})
    vd = valuation_date or date.today()
    result = mtm_engine.portfolio_mtm(db, auth.tenant_id, vd, snapshot_type=snapshot_type)
    db.commit()
    return result


@router.get("/mtm/summary")
def mtm_summary(
    valuation_date: date | None = Query(None, alias="date"),
    snapshot_type: str = Query("daily"),
    auth: AuthContext = Depends(require_module("risk")),
    db: Session = Depends(get_db),
):
    vd = valuation_date or date.today()
    # 只读汇总：纯计算不落库（mtm/run 负责持久化快照）
    return mtm_engine.portfolio_mtm(db, auth.tenant_id, vd, snapshot_type=snapshot_type, persist=False)


@router.get("/exposure")
def risk_exposure(
    valuation_date: date | None = Query(None, alias="date"),
    route: str | None = Query(None),
    auth: AuthContext = Depends(require_module("risk")),
    db: Session = Depends(get_db),
):
    vd = valuation_date or date.today()
    return mtm_engine.exposure_by_route_period(db, auth.tenant_id, vd, route=route)
