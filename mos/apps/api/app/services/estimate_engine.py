"""Voyage estimate / TCE engine (DDS §11)."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any


TWOPLACES = Decimal("0.01")
FOUR = Decimal("0.0001")


def _d(v: Any) -> Decimal:
    if v is None:
        return Decimal("0")
    return Decimal(str(v))


def compute_estimate(inputs: dict[str, Any]) -> dict[str, Any]:
    """
    TCE = (total_revenue - voyage_cost) / total_days
    voyage_cost excludes hire / opportunity hire.

    Freight modes:
    - lump_sum_freight > 0 → lump sum
    - ws_flat + ws_pct → Worldscale: cargo_qty * ws_flat * (ws_pct/100)
    - else cargo_qty * freight_rate
    """
    cargo_qty = _d(inputs.get("cargo_qty") or 0)
    freight_rate = _d(inputs.get("freight_rate") or 0)
    lump_sum = _d(inputs.get("lump_sum_freight") or 0)
    commission_pct = _d(inputs.get("commission_pct") or 0)
    ws_flat = _d(inputs.get("ws_flat") or 0)
    ws_pct = _d(inputs.get("ws_pct") or 0)

    freight_basis = "rate"
    if lump_sum > 0:
        gross_freight = lump_sum
        freight_basis = "lump_sum"
    elif ws_flat > 0 and ws_pct > 0:
        # Worldscale: flat rate × WS% × cargo quantity (simplified commercial form)
        gross_freight = cargo_qty * ws_flat * (ws_pct / Decimal("100"))
        freight_basis = "worldscale"
    else:
        gross_freight = cargo_qty * freight_rate

    commission = (gross_freight * commission_pct / Decimal("100")).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    net_freight = gross_freight - commission

    demurrage = _d(inputs.get("demurrage_income") or 0)
    other_income = _d(inputs.get("other_income") or 0)
    total_revenue = net_freight + demurrage + other_income

    sea_days = _d(inputs.get("sea_days") or 0)
    port_days = _d(inputs.get("port_days") or 0)
    # optional ECA / waiting days fold into sea/port for duration
    eca_days = _d(inputs.get("eca_days") or 0)
    waiting_days = _d(inputs.get("waiting_days") or 0)
    total_days = sea_days + port_days + eca_days + waiting_days
    if total_days <= 0:
        total_days = Decimal("1")

    bunker_sea_tpd = _d(inputs.get("bunker_sea_tpd") or 0)
    bunker_port_tpd = _d(inputs.get("bunker_port_tpd") or 0)
    bunker_price = _d(inputs.get("bunker_price") or 0)
    bunker_eca_tpd = _d(inputs.get("bunker_eca_tpd") or bunker_sea_tpd)
    bunker_cost = (
        (bunker_sea_tpd * sea_days)
        + (bunker_port_tpd * (port_days + waiting_days))
        + (bunker_eca_tpd * eca_days)
    ) * bunker_price

    port_costs = _d(inputs.get("port_costs") or 0)
    canal_costs = _d(inputs.get("canal_costs") or 0)
    other_costs = _d(inputs.get("other_costs") or 0)
    eca_extra_cost = _d(inputs.get("eca_extra_cost") or 0)
    voyage_cost = bunker_cost + port_costs + canal_costs + other_costs + eca_extra_cost

    hire_per_day = _d(inputs.get("hire_per_day") or 0)
    hire_cost = hire_per_day * total_days  # reported separately, not in voyage_cost for TCE

    tce = ((total_revenue - voyage_cost) / total_days).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    net_result = (total_revenue - voyage_cost - hire_cost).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

    return {
        "gross_freight": float(gross_freight.quantize(TWOPLACES)),
        "commission": float(commission),
        "net_freight": float(net_freight.quantize(TWOPLACES)),
        "total_revenue": float(total_revenue.quantize(TWOPLACES)),
        "bunker_cost": float(bunker_cost.quantize(TWOPLACES)),
        "voyage_cost": float(voyage_cost.quantize(TWOPLACES)),
        "hire_cost": float(hire_cost.quantize(TWOPLACES)),
        "total_days": float(total_days.quantize(FOUR)),
        "tce": float(tce),
        "net_result": float(net_result),
        "freight_basis": freight_basis,
        "currency": inputs.get("currency") or "USD",
    }


def sensitivity(base_inputs: dict[str, Any], field: str, deltas: list[float]) -> list[dict[str, Any]]:
    rows = []
    for d in deltas:
        inp = dict(base_inputs)
        inp[field] = float(_d(base_inputs.get(field) or 0) * (Decimal("1") + Decimal(str(d))))
        out = compute_estimate(inp)
        rows.append({"field": field, "delta_pct": d, "tce": out["tce"], "result": out})
    return rows
