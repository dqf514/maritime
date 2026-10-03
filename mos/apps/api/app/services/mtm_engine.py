"""Phase 7 MtM / 持仓净额引擎 — 逐日盯市与纸货-实货净头寸.

口径（确定性、Decimal）：

- 盯市 :func:`calculate_mtm` —
  ``market_price`` 取 ``MarketQuote``（index_symbol，估值日或之前最近一条；
  同租户优先于全局行情）。``book_price`` = 加权腿定价（无腿/无定价时用交易价）。
  ``unrealized_pnl = (market − book) × qty × side``（buy=+, sell=−）。
  ``realized_pnl`` = 各腿 ``settlement_amount`` 合计（视为已入账有符号现金）。
  无行情或无 index_symbol 时按 book 价平价盯市（unrealized = 0）。
  结果 upsert 到 ``mtm_results``（trade_id + valuation_date + snapshot_type）。

- 组合盯市 :func:`portfolio_mtm` — 租户下所有未删除且非 cancelled 交易批量盯市，
  返回逐笔 + 合计（按 kind / route 分组）。

- 持仓净额 :func:`position_netting` — 按 route 抵消买卖：
  paper（ffa|swap|option|paper）与 physical 分列，buy 记 +qty，sell 记 −qty。
  仅统计在手持仓（draft|confirmed；settled/cancelled 不再持有敞口）。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models_domain import MarketQuote
from app.models_trading import MtMResult, Trade, TradeLeg

PAPER_KINDS = ("ffa", "swap", "option", "paper")
OPEN_STATUSES = ("draft", "confirmed")
MARKABLE_STATUSES = ("draft", "confirmed", "settled")

ZERO = Decimal("0")
PENNY = Decimal("0.01")


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def _q(v: Decimal) -> Decimal:
    return v.quantize(PENNY)


def _side_sign(buy_sell: str) -> Decimal:
    return Decimal("1") if buy_sell == "buy" else Decimal("-1")


def market_price_for(
    db: Session, tenant_id: UUID | None, symbol: str | None, valuation_date: date
) -> Decimal | None:
    """估值日（含）之前最近一条行情；同租户行情优先于全局（tenant_id IS NULL）。"""
    if not symbol:
        return None
    stmt = select(MarketQuote).where(
        MarketQuote.symbol == symbol,
        MarketQuote.quote_date <= valuation_date,
    )
    if tenant_id is not None:
        stmt = stmt.where(or_(MarketQuote.tenant_id == tenant_id, MarketQuote.tenant_id.is_(None)))
    rows = db.scalars(stmt.order_by(MarketQuote.quote_date.desc())).all()
    return Decimal(str(rows[0].value)) if rows else None


def _book_price(trade: Trade, legs: list[TradeLeg]) -> Decimal:
    """账面价 = 腿固定价加权（qty 加权）；无腿或腿无定价时用交易价。"""
    priced = [lg for lg in legs if lg.fixed_price is not None]
    total_qty = sum((Decimal(str(lg.qty or 0)) for lg in priced), ZERO)
    if not priced or total_qty <= ZERO:
        return Decimal(str(trade.price))
    weighted = sum((Decimal(str(lg.fixed_price)) * Decimal(str(lg.qty or 0)) for lg in priced), ZERO)
    return weighted / total_qty


def calculate_mtm(
    db: Session,
    trade_id: UUID,
    valuation_date: date,
    *,
    snapshot_type: str = "daily",
    tenant_id: UUID | None = None,
) -> MtMResult:
    """单笔交易盯市；upsert 到 ``mtm_results`` 并返回结果行（不 commit）。"""
    trade = db.get(Trade, trade_id)
    if trade is None or trade.deleted_at is not None:
        raise ValueError(f"trade {trade_id} not found")
    if tenant_id is not None and trade.tenant_id != tenant_id:
        raise ValueError(f"trade {trade_id} not found")
    if trade.status == "cancelled":
        raise ValueError(f"trade {trade_id} is cancelled")

    legs = db.scalars(select(TradeLeg).where(TradeLeg.trade_id == trade.id).order_by(TradeLeg.leg_no)).all()
    book_price = _book_price(trade, list(legs))
    market_price = market_price_for(db, trade.tenant_id, trade.index_symbol, valuation_date)
    if market_price is None:
        market_price = book_price  # 无行情：平价盯市

    qty = Decimal(str(trade.qty or 0))
    unrealized = _q((market_price - book_price) * qty * _side_sign(trade.buy_sell))
    realized = _q(sum((Decimal(str(lg.settlement_amount or 0)) for lg in legs), ZERO))

    row = db.scalar(
        select(MtMResult).where(
            MtMResult.trade_id == trade.id,
            MtMResult.valuation_date == valuation_date,
            MtMResult.snapshot_type == snapshot_type,
        )
    )
    if row is None:
        row = MtMResult(
            tenant_id=trade.tenant_id,
            trade_id=trade.id,
            valuation_date=valuation_date,
            snapshot_type=snapshot_type,
            market_price=market_price,
            book_price=book_price,
            unrealized_pnl=unrealized,
            realized_pnl=realized,
        )
        db.add(row)
    else:
        row.market_price = market_price
        row.book_price = book_price
        row.unrealized_pnl = unrealized
        row.realized_pnl = realized
    db.flush()
    return row


def portfolio_mtm(
    db: Session,
    tenant_id: UUID,
    valuation_date: date,
    *,
    snapshot_type: str = "daily",
    persist: bool = True,
) -> dict:
    """租户全量盯市：逐笔 + 合计（按 kind / route 分组）。

    ``persist=True`` 时 upsert 快照到 ``mtm_results``（mtm/run 端点）；
    ``persist=False`` 纯计算不落库（mtm/summary 端点）。
    """
    trades = db.scalars(
        select(Trade).where(
            Trade.tenant_id == tenant_id,
            Trade.deleted_at.is_(None),
            Trade.status.in_(MARKABLE_STATUSES),
        ).order_by(Trade.trade_no)
    ).all()
    rows: list[dict] = []
    totals = {"unrealized_pnl": ZERO, "realized_pnl": ZERO}
    by_kind: dict[str, dict[str, Decimal]] = {}
    by_route: dict[str, dict[str, Decimal]] = {}
    for t in trades:
        if persist:
            res = calculate_mtm(
                db, t.id, valuation_date, snapshot_type=snapshot_type, tenant_id=tenant_id
            )
            book_price = Decimal(str(res.book_price))
            market_price = Decimal(str(res.market_price))
            unrealized = Decimal(str(res.unrealized_pnl))
            realized = Decimal(str(res.realized_pnl))
        else:
            legs = db.scalars(select(TradeLeg).where(TradeLeg.trade_id == t.id)).all()
            book_price = _book_price(t, list(legs))
            market_price = market_price_for(db, tenant_id, t.index_symbol, valuation_date)
            if market_price is None:
                market_price = book_price
            qty = Decimal(str(t.qty or 0))
            unrealized = _q((market_price - book_price) * qty * _side_sign(t.buy_sell))
            realized = _q(sum((Decimal(str(lg.settlement_amount or 0)) for lg in legs), ZERO))
        pub = {
            "trade_id": str(t.id),
            "trade_no": t.trade_no,
            "kind": t.kind,
            "route": t.route,
            "buy_sell": t.buy_sell,
            "qty": _f(t.qty),
            "valuation_date": valuation_date.isoformat(),
            "snapshot_type": snapshot_type,
            "market_price": _f(market_price),
            "book_price": _f(book_price),
            "unrealized_pnl": _f(unrealized),
            "realized_pnl": _f(realized),
        }
        rows.append(pub)
        totals["unrealized_pnl"] += unrealized
        totals["realized_pnl"] += realized
        for bucket, label in (
            (by_kind, t.kind or "unspecified"),
            (by_route, t.route or "unmapped"),
        ):
            slot = bucket.setdefault(label, {"unrealized_pnl": ZERO, "realized_pnl": ZERO, "trades": 0})
            slot["unrealized_pnl"] += unrealized
            slot["realized_pnl"] += realized
            slot["trades"] += 1

    def _bucket_out(bucket: dict[str, dict[str, Decimal]]) -> dict[str, dict]:
        return {
            k: {
                "unrealized_pnl": _f(v["unrealized_pnl"]),
                "realized_pnl": _f(v["realized_pnl"]),
                "trades": v["trades"],
            }
            for k, v in sorted(bucket.items())
        }

    return {
        "valuation_date": valuation_date.isoformat(),
        "snapshot_type": snapshot_type,
        "trades": rows,
        "totals": {
            "unrealized_pnl": _f(totals["unrealized_pnl"]),
            "realized_pnl": _f(totals["realized_pnl"]),
            "trades": len(rows),
        },
        "by_kind": _bucket_out(by_kind),
        "by_route": _bucket_out(by_route),
    }


def position_netting(
    db: Session,
    tenant_id: UUID,
    route: str | None = None,
    period: tuple[date, date] | None = None,
) -> dict:
    """纸货/实货净头寸：按 route 抵消买卖（buy +, sell −）。

    ``period`` 为 (from, to)：筛选与之重叠的交易期间；``route`` 精确匹配。
    仅统计在手持仓（draft|confirmed）。
    """
    stmt = select(Trade).where(
        Trade.tenant_id == tenant_id,
        Trade.deleted_at.is_(None),
        Trade.status.in_(OPEN_STATUSES),
    )
    if route:
        stmt = stmt.where(Trade.route == route)
    if period:
        p_from, p_to = period
        stmt = stmt.where(
            or_(
                Trade.period_from.is_(None),  # 无期间的交易不过滤（常青头寸）
                Trade.period_to.is_(None),
                (Trade.period_from <= p_to) & (Trade.period_to >= p_from),
            )
        )
    trades = db.scalars(stmt.order_by(Trade.trade_no)).all()

    buckets: dict[str, dict[str, Decimal]] = {}
    for t in trades:
        label = t.route or "unmapped"
        slot = buckets.setdefault(
            label,
            {
                "paper_buy": ZERO, "paper_sell": ZERO, "paper_net": ZERO,
                "physical_buy": ZERO, "physical_sell": ZERO, "physical_net": ZERO,
                "net_qty": ZERO,
                "trades": 0,
            },
        )
        qty = Decimal(str(t.qty or 0))
        is_paper = t.kind in PAPER_KINDS
        if t.buy_sell == "buy":
            slot["paper_buy" if is_paper else "physical_buy"] += qty
        else:
            slot["paper_sell" if is_paper else "physical_sell"] += qty
        slot["trades"] += 1

    routes = []
    for label in sorted(buckets):
        s = buckets[label]
        s["paper_net"] = s["paper_buy"] - s["paper_sell"]
        s["physical_net"] = s["physical_buy"] - s["physical_sell"]
        s["net_qty"] = s["paper_net"] + s["physical_net"]
        routes.append(
            {
                "route": label,
                "paper_buy": _f(s["paper_buy"]),
                "paper_sell": _f(s["paper_sell"]),
                "paper_net": _f(s["paper_net"]),
                "physical_buy": _f(s["physical_buy"]),
                "physical_sell": _f(s["physical_sell"]),
                "physical_net": _f(s["physical_net"]),
                "net_qty": _f(s["net_qty"]),
                "trades": s["trades"],
            }
        )

    tot = {
        "paper_net": sum((Decimal(str(r["paper_net"])) for r in routes), ZERO),
        "physical_net": sum((Decimal(str(r["physical_net"])) for r in routes), ZERO),
        "net_qty": sum((Decimal(str(r["net_qty"])) for r in routes), ZERO),
        "trades": sum(r["trades"] for r in routes),
    }
    return {
        "route": route,
        "period": {"from": period[0].isoformat(), "to": period[1].isoformat()} if period else None,
        "routes": routes,
        "totals": {
            "paper_net": _f(tot["paper_net"]),
            "physical_net": _f(tot["physical_net"]),
            "net_qty": _f(tot["net_qty"]),
            "trades": tot["trades"],
        },
    }


def exposure_by_route_period(
    db: Session,
    tenant_id: UUID,
    valuation_date: date,
    *,
    route: str | None = None,
) -> dict:
    """风险敞口：按 route（× 期间）列示净头寸、名义敞口与盯市盈亏。

    名义敞口 net_notional = net_qty × market_price（无行情用 book 价）。
    """
    stmt = select(Trade).where(
        Trade.tenant_id == tenant_id,
        Trade.deleted_at.is_(None),
        Trade.status.in_(OPEN_STATUSES),
    )
    if route:
        stmt = stmt.where(Trade.route == route)
    trades = db.scalars(stmt.order_by(Trade.trade_no)).all()

    groups: dict[tuple[str, str], dict] = {}
    for t in trades:
        label = t.route or "unmapped"
        period_label = (
            f"{t.period_from.isoformat()}/{t.period_to.isoformat()}"
            if t.period_from and t.period_to
            else "open"
        )
        key = (label, period_label)
        slot = groups.setdefault(
            key,
            {"net_qty": ZERO, "gross_qty": ZERO, "notional": ZERO, "mtm_pnl": ZERO, "trades": 0},
        )
        sign = _side_sign(t.buy_sell)
        qty = Decimal(str(t.qty or 0))
        market = market_price_for(db, tenant_id, t.index_symbol, valuation_date)
        mark = market if market is not None else Decimal(str(t.price or 0))
        slot["net_qty"] += sign * qty
        slot["gross_qty"] += qty
        slot["notional"] += sign * qty * mark
        slot["trades"] += 1
        # 盯市盈亏（未实现）：(mark − book) × qty × side
        book = Decimal(str(t.price or 0))
        slot["mtm_pnl"] += (mark - book) * qty * sign

    rows = [
        {
            "route": route_label,
            "period": period_label,
            "net_qty": _f(s["net_qty"]),
            "gross_qty": _f(s["gross_qty"]),
            "net_notional": _q(s["notional"]),
            "unrealized_pnl": _q(s["mtm_pnl"]),
            "trades": s["trades"],
        }
        for (route_label, period_label), s in sorted(groups.items())
    ]
    totals = {
        "net_qty": _f(sum((Decimal(str(r["net_qty"])) for r in rows), ZERO)),
        "gross_qty": _f(sum((Decimal(str(r["gross_qty"])) for r in rows), ZERO)),
        "net_notional": _f(sum((Decimal(str(r["net_notional"])) for r in rows), ZERO)),
        "unrealized_pnl": _f(sum((Decimal(str(r["unrealized_pnl"])) for r in rows), ZERO)),
        "trades": sum(r["trades"] for r in rows),
    }
    return {"valuation_date": valuation_date.isoformat(), "rows": rows, "totals": totals}
