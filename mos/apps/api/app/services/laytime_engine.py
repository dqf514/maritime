"""Laytime calculator (fixed allowance + exclusions)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


def _hours(start: datetime, end: datetime) -> Decimal:
    return Decimal(str((end - start).total_seconds() / 3600.0))


def compute_laytime(inputs: dict[str, Any]) -> dict[str, Any]:
    """
    allowed_hours: fixed or qty/rate.
    used_hours = working - excluded.
    demurrage if used > allowed; despatch if reverse and used < allowed.
    """
    qty = Decimal(str(inputs.get("cargo_qty") or 0))
    load_rate = Decimal(str(inputs.get("load_rate_per_day") or 0))
    fixed = inputs.get("allowed_hours")
    if fixed is not None:
        allowed = Decimal(str(fixed))
    elif load_rate > 0:
        allowed = (qty / load_rate * Decimal("24")).quantize(Decimal("0.01"))
    else:
        allowed = Decimal("0")

    turn_time = Decimal(str(inputs.get("turn_time_hours") or 0))
    allowed = allowed + turn_time

    events = inputs.get("events") or []
    used = Decimal("0")
    for ev in events:
        if ev.get("excluded"):
            continue
        s = ev["start"] if isinstance(ev["start"], datetime) else datetime.fromisoformat(str(ev["start"]))
        e = ev["end"] if isinstance(ev["end"], datetime) else datetime.fromisoformat(str(ev["end"]))
        used += _hours(s, e)

    terms = (inputs.get("terms") or "SHINC").upper()
    dem_rate = Decimal(str(inputs.get("demurrage_rate_per_day") or 0))
    des_rate = Decimal(str(inputs.get("despatch_rate_per_day") or (dem_rate / 2 if dem_rate else 0)))

    balance = used - allowed
    amount = Decimal("0")
    kind = "on_time"
    if balance > 0:
        kind = "demurrage"
        amount = (balance / Decimal("24") * dem_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    elif balance < 0 and inputs.get("despatch_allowed", True):
        kind = "despatch"
        amount = ((-balance) / Decimal("24") * des_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "terms": terms,
        "allowed_hours": float(allowed),
        "used_hours": float(used.quantize(Decimal("0.01"))),
        "balance_hours": float(balance.quantize(Decimal("0.01"))),
        "result_type": kind,
        "amount": float(amount),
        "currency": inputs.get("currency") or "USD",
    }
