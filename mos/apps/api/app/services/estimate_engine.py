"""Voyage estimate / TCE engine (DDS §11)."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any


TWOPLACES = Decimal("0.01")
FOUR = Decimal("0.0001")
THREE = Decimal("0.001")


def _d(v: Any) -> Decimal:
    if v is None:
        return Decimal("0")
    return Decimal(str(v))


DEFAULT_CO2_FACTOR = Decimal("3.114")  # mt CO2 per mt fuel (IMO default)


def _apply_legs(inputs: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal]:
    """Derive (sea_days, port_days, leg_cargo_qty) from a multi-leg itinerary.

    Each leg: {from_port?, to_port?, distance_nm, speed_kn, port_days?, cargo_qty?}.
    distance_nm and speed_kn must be > 0; API layers surface ValueError as 422.
    """
    sea_days = Decimal("0")
    port_days = Decimal("0")
    leg_cargo = Decimal("0")
    for i, leg in enumerate(inputs["legs"]):
        distance = _d(leg.get("distance_nm") or 0)
        speed = _d(leg.get("speed_kn") or 0)
        if distance <= 0:
            raise ValueError(f"legs[{i}].distance_nm must be > 0, got {leg.get('distance_nm')!r}")
        if speed <= 0:
            raise ValueError(f"legs[{i}].speed_kn must be > 0, got {leg.get('speed_kn')!r}")
        sea_days += distance / (speed * Decimal("24"))
        port_days += _d(leg.get("port_days") or 0)
        leg_cargo += _d(leg.get("cargo_qty") or 0)
    return sea_days, port_days, leg_cargo


def compute_estimate(inputs: dict[str, Any]) -> dict[str, Any]:
    """
    TCE = (total_revenue - voyage_cost) / total_days
    voyage_cost excludes hire / opportunity hire; brokerage and EU ETS
    emissions cost are included. Address commission is deducted from freight revenue.

    Freight modes:
    - lump_sum_freight > 0 → lump sum
    - ws_flat + ws_pct → Worldscale: cargo_qty * ws_flat * (ws_pct/100)
    - else cargo_qty * freight_rate

    Optional inputs:
    - legs: multi-leg itinerary; overrides sea_days/port_days (Σ distance/speed/24,
      Σ leg port_days) and sums leg cargo_qty when top-level cargo_qty is absent.
    - bunker_prices + bunker_grade / bunker_eca_grade: per-grade pricing; sea
      consumption is priced at bunker_grade, port/ECA consumption at
      bunker_eca_grade. Falls back to the single bunker_price when absent.
    - eu_ets_share (0-1), ets_price, co2_factor (default 3.114):
      emissions_cost = total fuel mt × co2_factor × eu_ets_share × ets_price.
    - cargo_tolerance_pct (e.g. 10 = ±10% MOL): results carry
      cargo_qty_min / cargo_qty_max around cargo_qty.
    - stowage_factor (m3/mt) + hold_capacity_m3, vessel_deadweight (mt):
      capacity cross-checks. Overflows are reported in results["warnings"]
      (non-blocking — an estimate may intentionally explore an over-capacity
      cargo; the chartering desk decides). The key is omitted when empty so
      legacy results stay byte-identical.
    """
    legs = inputs.get("legs") or []
    leg_sea_days = leg_port_days = leg_cargo = None
    if legs:
        leg_sea_days, leg_port_days, leg_cargo = _apply_legs(inputs)

    cargo_qty = _d(inputs.get("cargo_qty") or 0)
    if legs and not cargo_qty:
        cargo_qty = leg_cargo
    freight_rate = _d(inputs.get("freight_rate") or 0)
    lump_sum = _d(inputs.get("lump_sum_freight") or 0)
    # address commission is deducted from freight revenue; legacy commission_pct
    # is treated as address commission for backward compatibility.
    address_comm_pct = _d(inputs.get("address_comm_pct") or inputs.get("commission_pct") or 0)
    # brokerage is a voyage cost, not a revenue deduction
    brokerage_pct = _d(inputs.get("brokerage_pct") or 0)
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

    address_commission = (gross_freight * address_comm_pct / Decimal("100")).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    brokerage = (gross_freight * brokerage_pct / Decimal("100")).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    commission = address_commission  # legacy output key
    net_freight = gross_freight - address_commission

    demurrage = _d(inputs.get("demurrage_income") or 0)
    other_income = _d(inputs.get("other_income") or 0)
    total_revenue = net_freight + demurrage + other_income

    sea_days = _d(inputs.get("sea_days") or 0)
    port_days = _d(inputs.get("port_days") or 0)
    if legs:
        sea_days = leg_sea_days
        port_days = leg_port_days
    # optional ECA / waiting days fold into sea/port for duration
    eca_days = _d(inputs.get("eca_days") or 0)
    waiting_days = _d(inputs.get("waiting_days") or 0)
    total_days = sea_days + port_days + eca_days + waiting_days
    if total_days <= 0:
        raise ValueError(
            "total_days must be > 0: "
            f"sea_days={sea_days}, port_days={port_days}, eca_days={eca_days}, "
            f"waiting_days={waiting_days}. A zero/negative voyage duration would "
            "make TCE meaningless; API layers must return this as a 422 validation "
            "error, not silently assume 1 day."
        )

    bunker_sea_tpd = _d(inputs.get("bunker_sea_tpd") or 0)
    bunker_port_tpd = _d(inputs.get("bunker_port_tpd") or 0)
    bunker_price = _d(inputs.get("bunker_price") or 0)
    bunker_eca_tpd = _d(inputs.get("bunker_eca_tpd") or bunker_sea_tpd)
    sea_fuel_mt = bunker_sea_tpd * sea_days
    port_fuel_mt = bunker_port_tpd * (port_days + waiting_days)
    eca_fuel_mt = bunker_eca_tpd * eca_days
    total_fuel_mt = sea_fuel_mt + port_fuel_mt + eca_fuel_mt

    bunker_prices = inputs.get("bunker_prices") or {}
    if bunker_prices:
        # per-grade pricing: sea leg burns bunker_grade, port/ECA burn the ECA grade
        def _grade_price(grade: Any) -> Decimal:
            if grade and grade in bunker_prices:
                return _d(bunker_prices[grade])
            return bunker_price  # legacy single-price fallback

        sea_price = _grade_price(inputs.get("bunker_grade"))
        eca_price = _grade_price(inputs.get("bunker_eca_grade"))
        bunker_cost = sea_fuel_mt * sea_price + (port_fuel_mt + eca_fuel_mt) * eca_price
    else:
        bunker_cost = total_fuel_mt * bunker_price

    # EU ETS: CO2 = total fuel × emission factor; priced over the EU leg share
    co2_factor = _d(inputs.get("co2_factor") or DEFAULT_CO2_FACTOR)
    eu_ets_share = _d(inputs.get("eu_ets_share") or 0)
    ets_price = _d(inputs.get("ets_price") or 0)
    co2_mt = total_fuel_mt * co2_factor
    emissions_cost = (co2_mt * eu_ets_share * ets_price).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

    port_costs = _d(inputs.get("port_costs") or 0)
    canal_costs = _d(inputs.get("canal_costs") or 0)
    other_costs = _d(inputs.get("other_costs") or 0)
    eca_extra_cost = _d(inputs.get("eca_extra_cost") or 0)
    voyage_cost = bunker_cost + port_costs + canal_costs + other_costs + eca_extra_cost + brokerage + emissions_cost

    hire_per_day = _d(inputs.get("hire_per_day") or 0)
    hire_cost = hire_per_day * total_days  # reported separately, not in voyage_cost for TCE

    tce = ((total_revenue - voyage_cost) / total_days).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    net_result = (total_revenue - voyage_cost - hire_cost).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

    result: dict[str, Any] = {
        "gross_freight": float(gross_freight.quantize(TWOPLACES)),
        "commission": float(commission),
        "address_commission": float(address_commission),
        "brokerage": float(brokerage),
        "net_freight": float(net_freight.quantize(TWOPLACES)),
        "total_revenue": float(total_revenue.quantize(TWOPLACES)),
        "bunker_cost": float(bunker_cost.quantize(TWOPLACES)),
        "fuel_mt": float(total_fuel_mt.quantize(FOUR)),
        "co2_mt": float(co2_mt.quantize(FOUR)),
        "emissions_cost": float(emissions_cost),
        "voyage_cost": float(voyage_cost.quantize(TWOPLACES)),
        "hire_cost": float(hire_cost.quantize(TWOPLACES)),
        "sea_days": float(sea_days.quantize(FOUR)),
        "port_days": float(port_days.quantize(FOUR)),
        "total_days": float(total_days.quantize(FOUR)),
        "tce": float(tce),
        "net_result": float(net_result),
        "freight_basis": freight_basis,
        "currency": inputs.get("currency") or "USD",
    }

    # cargo quantity tolerance (±pct MOL, "more or less" owner's/charterer's option)
    tolerance_pct = inputs.get("cargo_tolerance_pct")
    if tolerance_pct is not None:
        tol = _d(tolerance_pct) / Decimal("100")
        result["cargo_qty_min"] = float((cargo_qty * (Decimal("1") - tol)).quantize(THREE, rounding=ROUND_HALF_UP))
        result["cargo_qty_max"] = float((cargo_qty * (Decimal("1") + tol)).quantize(THREE, rounding=ROUND_HALF_UP))

    # capacity cross-checks: warnings only, never block the calculation
    warnings: list[dict[str, str]] = []
    stowage_factor = inputs.get("stowage_factor")
    hold_capacity = inputs.get("hold_capacity_m3")
    if stowage_factor and hold_capacity:
        required_m3 = cargo_qty * _d(stowage_factor)
        if required_m3 > _d(hold_capacity):
            warnings.append(
                {
                    "code": "STOWAGE_OVERFLOW",
                    "message": (
                        f"cargo {cargo_qty} mt × stowage factor {_d(stowage_factor)} m3/mt "
                        f"= {required_m3} m3 exceeds hold capacity {hold_capacity} m3"
                    ),
                }
            )
    deadweight = inputs.get("vessel_deadweight")
    if deadweight and cargo_qty > _d(deadweight):
        warnings.append(
            {
                "code": "DEADWEIGHT_EXCEEDED",
                "message": f"cargo {cargo_qty} mt exceeds vessel deadweight {deadweight} mt",
            }
        )
    if warnings:
        result["warnings"] = warnings
    return result


def sensitivity(
    base_inputs: dict[str, Any],
    field: str,
    deltas: list[float],
    mode: str = "pct",
) -> list[dict[str, Any]]:
    """Perturb `field` and recompute TCE.

    mode="pct": multiplicative perturbation, value * (1 + delta) — delta is a
    fraction (0.05 = +5%). mode="abs": additive perturbation, value + delta in
    the field's own unit (e.g. bunker_price +25 USD/MT).
    """
    if mode not in ("pct", "abs"):
        raise ValueError(f"Unknown sensitivity mode '{mode}': expected 'pct' or 'abs'")
    base_value = _d(base_inputs.get(field) or 0)
    rows = []
    for d in deltas:
        inp = dict(base_inputs)
        if mode == "abs":
            inp[field] = float(base_value + Decimal(str(d)))
        else:
            inp[field] = float(base_value * (Decimal("1") + Decimal(str(d))))
        out = compute_estimate(inp)
        row = {"field": field, "mode": mode, "tce": out["tce"], "result": out}
        row["delta_abs" if mode == "abs" else "delta_pct"] = d
        rows.append(row)
    return rows
