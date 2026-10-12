"""Phase 5 — Market data endpoints.

Two routers live here:

- ``router`` (prefix ``/market-data``) — quote latest/history/bunker comparison.
- ``positions_router`` (no prefix) — bare ``/market-positions`` for the trading
  board. The frontend calls ``GET /api/v1/market-positions`` directly, so this
  one cannot sit under the ``/market-data`` prefix.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_domain import MarketQuote
from app.models_trading import Trade, TradeLeg
from app.security import AuthContext, require_module
from app.services import market_data as mkt
from app.services.mtm_engine import OPEN_STATUSES, market_price_for
from app.services.tenant_guard import scoped_query

router = APIRouter(prefix="/market-data", tags=["Market Data"])
# 无 prefix：注册到 /api/v1 下即为 /api/v1/market-positions
positions_router = APIRouter(tags=["Market Data"])

ZERO = Decimal("0")
PENNY = Decimal("0.01")
# 无历史行情时的兜底波动率（见 _volatility 注释）
DEFAULT_VOL = Decimal("0.05")
Z_95 = Decimal("1.65")


@router.get("/latest")
def latest_quotes(
    category: str | None = Query(None, description="bunker|index|tce"),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    return mkt.get_latest_quotes(db, auth.tenant_id, category)


@router.get("/history/{symbol}")
def history(
    symbol: str,
    days: int = Query(30, ge=1, le=365),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    return mkt.get_history(db, auth.tenant_id, symbol, days)


@router.get("/bunker-comparison")
def bunker_comparison(
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    return mkt.get_bunker_comparison(db, auth.tenant_id)


@router.post("/seed-demo", status_code=201)
def seed_demo(
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    count = mkt.seed_demo_data(db, auth.tenant_id)
    return {"seeded": count}


# ── Market positions (trading board) ─────────────────────────────────────────


def _q(v: Decimal) -> Decimal:
    return v.quantize(PENNY)


def _f(v: Decimal | None) -> float:
    return float(v) if v is not None else 0.0


def _volatility(db: Session, tenant_id: UUID, symbol: str | None) -> Decimal:
    """Simple 95% parametric VaR vol.

    ``services.market_data`` has no volatility/stddev helper. Compute a cheap
    population stddev of period-over-period returns over recent MarketQuote
    history (tenant rows + global); when history is too thin (< 3 points or
    degenerate) fall back to a fixed 5% rate. Deterministic either way.
    """
    if not symbol:
        return DEFAULT_VOL
    rows = db.scalars(
        select(MarketQuote)
        .where(
            (MarketQuote.tenant_id == tenant_id) | (MarketQuote.tenant_id.is_(None)),
            MarketQuote.symbol == symbol,
        )
        .order_by(MarketQuote.quote_date.desc())
        .limit(30)
    ).all()
    values = [Decimal(str(r.value)) for r in rows]
    if len(values) < 3:
        return DEFAULT_VOL
    values = list(reversed(values))  # chronological
    rets = []
    for prev, cur in zip(values, values[1:]):
        if prev != 0:
            rets.append(float(cur / prev - 1))
    if len(rets) < 2:
        return DEFAULT_VOL
    try:
        sd = statistics.pstdev(rets)
    except statistics.StatisticsError:
        return DEFAULT_VOL
    if sd <= 0:
        return DEFAULT_VOL
    return Decimal(str(sd))


def _entry_price(trade: Trade, legs: list[TradeLeg]) -> Decimal:
    """腿固定价 qty 加权；无腿/无腿定价时用交易价（与 mtm_engine._book_price 同口径）。"""
    priced = [lg for lg in legs if lg.fixed_price is not None]
    total_qty = sum((Decimal(str(lg.qty or 0)) for lg in priced), ZERO)
    if not priced or total_qty <= ZERO:
        return Decimal(str(trade.price or 0))
    weighted = sum((Decimal(str(lg.fixed_price)) * Decimal(str(lg.qty or 0)) for lg in priced), ZERO)
    return weighted / total_qty


def _period_label(trade: Trade, leg: TradeLeg | None) -> str:
    p_from = (leg.period_from if leg else None) or trade.period_from
    p_to = (leg.period_to if leg else None) or trade.period_to
    if p_from and p_to:
        return f"{p_from.isoformat()}..{p_to.isoformat()}"
    if p_from:
        return p_from.isoformat()
    return ""


def _market_positions_items(db: Session, tenant_id: UUID, valuation_date: date) -> list[dict]:
    """Open trade-leg positions netted by (route, period).

    ``long_qty`` = sum of buy leg qty, ``short_qty`` = sum of sell leg qty,
    ``net_qty`` = long − short. ``avg_price`` is the volume-weighted entry price
    of the legs (trade.price when a leg has no fixed_price). ``market_price`` is
    the latest MarketQuote on-or-before ``valuation_date`` for the group's
    index symbol (tenant rows preferred over global), else ``avg_price``.
    ``unrealized_pnl = (market − avg) × net_qty`` — long profits when price
    rises. ``commodity`` is blank: Trade has no commodity column.
    """
    trades = list(
        db.scalars(
            scoped_query(db, Trade, tenant_id).where(Trade.status.in_(OPEN_STATUSES))
        ).all()
    )
    legs_by_trade: dict[UUID, list[TradeLeg]] = defaultdict(list)
    if trades:
        for lg in db.scalars(
            select(TradeLeg)
            .where(TradeLeg.tenant_id == tenant_id, TradeLeg.trade_id.in_([t.id for t in trades]))
            .order_by(TradeLeg.leg_no)
        ).all():
            legs_by_trade[lg.trade_id].append(lg)

    # key: (route, period) → accumulators
    groups: dict[tuple[str, str], dict] = {}
    for t in trades:
        legs = legs_by_trade.get(t.id) or [None]  # type: ignore[list-item]
        route = t.route or "unmapped"
        for lg in legs:
            qty = Decimal(str((lg.qty if lg is not None else t.qty) or 0))
            if qty == 0:
                continue
            price = Decimal(str(lg.fixed_price)) if (lg is not None and lg.fixed_price is not None) else Decimal(str(t.price or 0))
            symbol = (lg.index_symbol if lg is not None else None) or t.index_symbol
            key = (route, _period_label(t, lg))
            slot = groups.setdefault(
                key,
                {
                    "long_qty": ZERO,
                    "short_qty": ZERO,
                    "notional": ZERO,
                    "volume": ZERO,
                    "symbols": [],
                },
            )
            if t.buy_sell == "buy":
                slot["long_qty"] += qty
            else:
                slot["short_qty"] += qty
            slot["notional"] += price * qty
            slot["volume"] += qty
            if symbol and symbol not in slot["symbols"]:
                slot["symbols"].append(symbol)

    items = []
    for (route, period), s in sorted(groups.items()):
        long_qty = s["long_qty"]
        short_qty = s["short_qty"]
        net_qty = long_qty - short_qty
        volume = s["volume"]
        # 先量化再参与 PnL，保证展示值与计算值一致（确定性）
        avg_price = _q((s["notional"] / volume) if volume > 0 else ZERO)

        market_price = None
        for symbol in s["symbols"]:
            market_price = market_price_for(db, tenant_id, symbol, valuation_date)
            if market_price is not None:
                break
        if market_price is None:
            market_price = avg_price  # 无行情：按账面价平价
        else:
            market_price = _q(market_price)

        unrealized = _q((market_price - avg_price) * net_qty)
        vol = _volatility(db, tenant_id, s["symbols"][0] if s["symbols"] else None)
        exposure = abs(market_price * net_qty)
        var_95 = _q(Z_95 * exposure * vol)

        items.append(
            {
                "id": f"{route}-{period}",
                "route": route,
                # Trade 无 commodity 列 — 留空（前端可按 route 映射）
                "commodity": "",
                "period": period,
                "long_qty": _f(long_qty),
                "short_qty": _f(short_qty),
                "net_qty": _f(net_qty),
                "avg_price": _f(avg_price),
                "market_price": _f(market_price),
                "unrealized_pnl": _f(unrealized),
                "var_95": _f(var_95),
            }
        )
    return items


@positions_router.get("/market-positions")
def market_positions(
    as_of: date | None = Query(None, description="valuation date; default today"),
    auth: AuthContext = Depends(require_module("risk")),
    db: Session = Depends(get_db),
):
    """Trading-board positions: open (draft|confirmed) trade legs netted by route+period."""
    valuation = as_of or date.today()
    return {"items": _market_positions_items(db, auth.tenant_id, valuation)}
