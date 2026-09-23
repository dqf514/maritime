"""Market data integration service.

Provides provider-agnostic market data ingestion and querying.
Includes demo data seeding for bunker prices, freight indices, and port costs.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.models_domain import MarketQuote

DEMO_SYMBOLS = {
    "BUNKER_VLSFO_SIN": ("VLSFO Singapore", "bunker"),
    "BUNKER_VLSFO_ROT": ("VLSFO Rotterdam", "bunker"),
    "BUNKER_VLSFO_FUJ": ("VLSFO Fujairah", "bunker"),
    "BUNKER_MGO_SIN": ("MGO Singapore", "bunker"),
    "BUNKER_MGO_ROT": ("MGO Rotterdam", "bunker"),
    "BDI": ("Baltic Dry Index", "index"),
    "BCI": ("Baltic Capesize Index", "index"),
    "BPI": ("Baltic Panamax Index", "index"),
    "BSI": ("Baltic Supramax Index", "index"),
    "BHSI": ("Baltic Handysize Index", "index"),
    "TCE_C5_PAC": ("TCE C5 Pacific", "tce"),
    "TCE_C8_ATL": ("TCE C8 Atlantic", "tce"),
    "TCE_P60A": ("TCE P60A Transatlantic", "tce"),
}

DEMO_BUNKER_PRICES = {
    "BUNKER_VLSFO_SIN": 580,
    "BUNKER_VLSFO_ROT": 560,
    "BUNKER_VLSFO_FUJ": 570,
    "BUNKER_MGO_SIN": 780,
    "BUNKER_MGO_ROT": 760,
}

DEMO_INDICES = {
    "BDI": 2150,
    "BCI": 3200,
    "BPI": 1800,
    "BSI": 1400,
    "BHSI": 950,
}

DEMO_TCE = {
    "TCE_C5_PAC": 28500,
    "TCE_C8_ATL": 31000,
    "TCE_P60A": 22000,
}


def seed_demo_data(db: Session, tenant_id: UUID) -> int:
    """Seed 30 days of demo market data for a tenant."""
    today = date.today()
    count = 0
    for day_offset in range(30):
        d = today - timedelta(days=day_offset)
        for symbol, (desc_label, cat) in DEMO_SYMBOLS.items():
            existing = db.scalars(
                select(MarketQuote).where(
                    MarketQuote.tenant_id == tenant_id,
                    MarketQuote.symbol == symbol,
                    MarketQuote.quote_date == d,
                )
            ).first()
            if existing:
                continue
            if cat == "bunker":
                base = DEMO_BUNKER_PRICES.get(symbol, 500)
                value = Decimal(str(round(base + (day_offset - 15) * 2.5, 2)))
            elif cat == "index":
                base = DEMO_INDICES.get(symbol, 1500)
                value = Decimal(str(round(base + (day_offset - 15) * 15, 2)))
            else:
                base = DEMO_TCE.get(symbol, 20000)
                value = Decimal(str(round(base + (day_offset - 15) * 200, 2)))
            q = MarketQuote(
                tenant_id=tenant_id,
                symbol=symbol,
                quote_date=d,
                value=value,
                source="demo",
            )
            db.add(q)
            count += 1
    db.commit()
    return count


def get_latest_quotes(db: Session, tenant_id: UUID, category: str | None = None) -> list[dict]:
    """Get the latest quote for each symbol, optionally filtered by category."""
    symbols = DEMO_SYMBOLS.keys()
    if category:
        symbols = [s for s, (_, c) in DEMO_SYMBOLS.items() if c == category]

    results = []
    for symbol in symbols:
        row = db.scalars(
            select(MarketQuote)
            .where(
                MarketQuote.tenant_id == tenant_id,
                MarketQuote.symbol == symbol,
            )
            .order_by(desc(MarketQuote.quote_date))
        ).first()
        if row:
            label, cat = DEMO_SYMBOLS.get(symbol, (symbol, "other"))
            results.append({
                "symbol": symbol,
                "label": label,
                "category": cat,
                "value": float(row.value),
                "date": row.quote_date.isoformat(),
                "source": row.source,
            })
    return results


def get_history(
    db: Session, tenant_id: UUID, symbol: str, days: int = 30
) -> list[dict]:
    """Get historical quotes for a symbol."""
    since = date.today() - timedelta(days=days)
    rows = db.scalars(
        select(MarketQuote)
        .where(
            MarketQuote.tenant_id == tenant_id,
            MarketQuote.symbol == symbol,
            MarketQuote.quote_date >= since,
        )
        .order_by(MarketQuote.quote_date)
    ).all()
    return [
        {"date": r.quote_date.isoformat(), "value": float(r.value), "source": r.source}
        for r in rows
    ]


def get_bunker_comparison(db: Session, tenant_id: UUID) -> list[dict]:
    """Compare latest bunker prices across ports."""
    bunker_symbols = [s for s, (_, c) in DEMO_SYMBOLS.items() if c == "bunker"]
    results = []
    for symbol in bunker_symbols:
        row = db.scalars(
            select(MarketQuote)
            .where(
                MarketQuote.tenant_id == tenant_id,
                MarketQuote.symbol == symbol,
            )
            .order_by(desc(MarketQuote.quote_date))
        ).first()
        if row:
            label, _ = DEMO_SYMBOLS.get(symbol, (symbol, "other"))
            results.append({
                "symbol": symbol,
                "port": label.replace("VLSFO ", "").replace("MGO ", ""),
                "fuel_type": "VLSFO" if "VLSFO" in symbol else "MGO",
                "price_usd": float(row.value),
                "date": row.quote_date.isoformat(),
            })
    return sorted(results, key=lambda x: x["price_usd"])
