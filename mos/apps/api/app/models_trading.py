"""Phase 7 Trading & Risk models — FFA/掉期/期权/实货纸货交易与逐日盯市.

Trades may be paper (``kind`` in ffa|swap|option|paper) or physical; legs carry
period slices (monthly settlements) so multi-period instruments mark per leg.
``MtMResult`` stores valuation snapshots (daily|weekly|monthly) keyed by
``(trade_id, valuation_date, snapshot_type)`` — one row per run.

Multi-tenant: every table carries ``tenant_id``; the trade header uses the
``deleted_at`` soft-delete convention (see ``app.services.tenant_guard``).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

TRADE_KINDS = ("ffa", "swap", "option", "physical", "paper")
TRADE_SIDES = ("buy", "sell")
TRADE_STATUSES = ("draft", "confirmed", "settled", "cancelled")
MTM_SNAPSHOT_TYPES = ("daily", "weekly", "monthly")


class Trade(Base):
    """交易头：FFA / 掉期 / 期权 / 实货 / 纸货。``index_symbol`` 挂 MarketQuote。"""

    __tablename__ = "trades"
    __table_args__ = (UniqueConstraint("tenant_id", "trade_no"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    trade_no: Mapped[str] = mapped_column(Text, nullable=False)  # doc number TRD-YYYY-NNNNN
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # ffa|swap|option|physical|paper
    buy_sell: Mapped[str] = mapped_column(String(4), nullable=False)  # buy|sell
    route: Mapped[str | None] = mapped_column(String(64))  # route / index label for position netting
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    qty_unit: Mapped[str | None] = mapped_column(String(8))  # mt|bbl|t|day
    price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)  # booked / fixed price
    price_unit: Mapped[str | None] = mapped_column(String(16))  # per_mt|per_day|per_t|lumpsum
    index_symbol: Mapped[str | None] = mapped_column(String(64))  # link to MarketQuote.symbol
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("counterparties.id"))
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)  # draft|confirmed|settled|cancelled
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    settlement_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TradeLeg(Base):
    """交易分腿：跨期工具按月/期切分；``settlement_amount`` 为该腿已结算金额。"""

    __tablename__ = "trade_legs"
    __table_args__ = (UniqueConstraint("trade_id", "leg_no"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    trade_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("trades.id"), nullable=False, index=True)
    leg_no: Mapped[int] = mapped_column(Integer, nullable=False)
    period_from: Mapped[date] = mapped_column(Date, nullable=False)
    period_to: Mapped[date] = mapped_column(Date, nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    fixed_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    index_symbol: Mapped[str | None] = mapped_column(String(64))
    settlement_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))


class MtMResult(Base):
    """盯市快照：unrealized = (market − book) × qty × side；realized 来自已结算腿。"""

    __tablename__ = "mtm_results"
    __table_args__ = (UniqueConstraint("trade_id", "valuation_date", "snapshot_type"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    trade_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("trades.id"), nullable=False, index=True)
    valuation_date: Mapped[date] = mapped_column(Date, nullable=False)
    market_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    book_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    snapshot_type: Mapped[str] = mapped_column(String(8), default="daily", nullable=False)  # daily|weekly|monthly
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
