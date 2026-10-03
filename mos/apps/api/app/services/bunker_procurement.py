"""Bunker procurement helpers — requirement numbering + cap/collar price clamping.

Cap/collar (上下限保护)：租约约定燃油采购价上限 (cap) 与下限 (collar)，
指数价结算时夹紧到 [collar, cap] 区间：
- price > cap  → 按 cap 成交（买方保护）
- price < collar → 按 collar 成交（卖方保护）
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import BunkerCapCollar


def next_requirement_no(prefix: str = "BREQ") -> str:
    """Bunker requirement doc number: BREQ-YYYYMMDD-XXXXX (house style)."""
    return f"{prefix}-{datetime.now().strftime('%Y%m%d')}-{str(uuid4())[:5].upper()}"


def apply_cap_collar(
    price: Decimal | float | str,
    cap_price: Decimal | float | str | None = None,
    collar_price: Decimal | float | str | None = None,
) -> Decimal:
    """Clamp ``price`` into the [collar_price, cap_price] band (2dp)."""
    p = Decimal(str(price)).quantize(Decimal("0.01"))
    collar = Decimal(str(collar_price)).quantize(Decimal("0.01")) if collar_price is not None else None
    cap = Decimal(str(cap_price)).quantize(Decimal("0.01")) if cap_price is not None else None
    if collar is not None and cap is not None and collar > cap:
        raise ValueError("collar_price must be <= cap_price")
    if collar is not None and p < collar:
        p = collar
    if cap is not None and p > cap:
        p = cap
    return p


def find_cap_collar(
    db: Session,
    tenant_id: UUID,
    fuel_type: str,
    on_date: date | None = None,
    charter_id: UUID | None = None,
) -> BunkerCapCollar | None:
    """Most specific effective cap/collar row for a fuel type.

    Preference: charter-specific rows over fleet-wide rows; newest effective_from wins.
    """
    on = on_date or date.today()
    rows = db.scalars(
        select(BunkerCapCollar).where(
            BunkerCapCollar.tenant_id == tenant_id,
            BunkerCapCollar.fuel_type == fuel_type,
            BunkerCapCollar.effective_from <= on,
        )
    ).all()
    candidates = [
        r
        for r in rows
        if (r.effective_to is None or r.effective_to >= on)
        and (r.charter_id is None or (charter_id is not None and r.charter_id == charter_id))
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r.charter_id is not None, r.effective_from), reverse=True)
    return candidates[0]


def resolve_cap_collar_price(
    db: Session,
    tenant_id: UUID,
    fuel_type: str,
    price: Decimal | float | str,
    on_date: date | None = None,
    charter_id: UUID | None = None,
) -> dict:
    """Clamp ``price`` with the effective cap/collar row (if any).

    Returns the clamped price plus the band that was applied.
    """
    row = find_cap_collar(db, tenant_id, fuel_type, on_date=on_date, charter_id=charter_id)
    if row is None:
        return {
            "price": float(Decimal(str(price)).quantize(Decimal("0.01"))),
            "clamped_price": float(Decimal(str(price)).quantize(Decimal("0.01"))),
            "cap_price": None,
            "collar_price": None,
            "cap_collar_id": None,
            "clamped": False,
        }
    clamped = apply_cap_collar(price, cap_price=row.cap_price, collar_price=row.collar_price)
    raw = Decimal(str(price)).quantize(Decimal("0.01"))
    return {
        "price": float(raw),
        "clamped_price": float(clamped),
        "cap_price": float(row.cap_price) if row.cap_price is not None else None,
        "collar_price": float(row.collar_price) if row.collar_price is not None else None,
        "cap_collar_id": str(row.id),
        "clamped": clamped != raw,
    }
