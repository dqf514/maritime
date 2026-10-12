"""Voyage estimate / TCE engine (DDS §11)."""

from __future__ import annotations

from datetime import date, datetime
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

# Explicit freight_basis input vocabulary (Track C1). Aliases accept the charter
# master-data spellings (per_mt / lumpsum / worldscale) and the engine's legacy
# output names. Normalized canonical values: per_mt | lump_sum | worldscale | ws_differential.
_FREIGHT_BASIS_ALIASES: dict[str, str] = {
    "rate": "per_mt",
    "per_mt": "per_mt",
    "per-mt": "per_mt",
    "permt": "per_mt",
    "lump": "lump_sum",
    "lump_sum": "lump_sum",
    "lump-sum": "lump_sum",
    "lumpsum": "lump_sum",
    "worldscale": "worldscale",
    "ws": "worldscale",
    "ws_differential": "ws_differential",
    "ws-differential": "ws_differential",
    "wsdifferential": "ws_differential",
    "ws_diff": "ws_differential",
    "ws_differentials": "ws_differential",
}

# Differential add-on bases: per_mt × cargo_qty (mt), per_measure × cargo_measure,
# lump = flat amount (negative amounts allowed — commercial rebates).
_DIFF_BASIS_ALIASES: dict[str, str] = {
    "per_mt": "per_mt",
    "per-mt": "per_mt",
    "permt": "per_mt",
    "mt": "per_mt",
    "per_measure": "per_measure",
    "per-measure": "per_measure",
    "permeasure": "per_measure",
    "measure": "per_measure",
    "lump": "lump",
    "lump_sum": "lump",
    "lump-sum": "lump",
    "lumpsum": "lump",
    "flat": "lump",
}

# Output vocabulary for freight_basis (legacy keys preserved: rate/lump_sum/worldscale).
_BASIS_OUTPUT = {
    "per_mt": "rate",
    "lump_sum": "lump_sum",
    "worldscale": "worldscale",
    "ws_differential": "ws_differential",
}


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


def _rate_table_dims(inputs: dict[str, Any]) -> dict[str, Any]:
    """Lookup dims drawn from estimate inputs (rows only care about their own keys)."""
    keys = ("load_port", "disch_port", "from_port", "to_port", "route", "cargo_type", "vessel_class")
    return {k: inputs[k] for k in keys if inputs.get(k)}


def _as_of(inputs: dict[str, Any]) -> date | None:
    raw = inputs.get("rate_as_of")
    if not raw:
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _resolve_rate_table_inputs(inputs: dict[str, Any], db: Any, tenant_id: Any) -> dict[str, Decimal]:
    """Resolve Phase 4 rate-table inputs into concrete amounts/rates.

    Optional override inputs (all omitted from legacy gold fixtures):

    - ``freight_rate_table_id`` — per-mt freight rate via ``resolve_rate``
      (dims: load_port/disch_port/cargo_type/...). Used when no direct
      ``freight_rate`` is provided; a direct rate wins (backward compat).
    - ``demurrage_rate_table_id`` — per-day demurrage rate ×
      ``demurrage_days`` → ``demurrage_income`` (only when the latter is
      not provided directly).
    - ``surcharge_rate_table_id`` — per-mt surcharge × ``cargo_qty`` →
      ``surcharge_income`` (added to revenue; no legacy direct equivalent).

    Returns only the keys that resolved, e.g.
    ``{"freight_rate": Decimal("12.5"), "surcharge_income": Decimal("...")}``.
    """
    from app.services.rates import resolve_rate  # local import: engine stays import-light

    out: dict[str, Decimal] = {}
    as_of = _as_of(inputs)
    dims = _rate_table_dims(inputs)

    freight_tid = inputs.get("freight_rate_table_id")
    if freight_tid:
        val = resolve_rate(db, tenant_id, freight_tid, dims, as_of=as_of)
        if val is not None and not _d(inputs.get("freight_rate") or 0):
            out["freight_rate"] = val

    dem_tid = inputs.get("demurrage_rate_table_id")
    if dem_tid and not _d(inputs.get("demurrage_income") or 0) and inputs.get("demurrage_days") is not None:
        val = resolve_rate(db, tenant_id, dem_tid, dims, as_of=as_of)
        if val is not None:
            out["demurrage_income"] = (val * _d(inputs.get("demurrage_days"))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

    sur_tid = inputs.get("surcharge_rate_table_id")
    if sur_tid:
        val = resolve_rate(db, tenant_id, sur_tid, dims, as_of=as_of)
        if val is not None and inputs.get("cargo_qty") is not None:
            out["surcharge_income"] = (val * _d(inputs.get("cargo_qty"))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
    return out


def _parse_differentials(inputs: dict[str, Any]) -> tuple[Decimal, list[dict[str, Any]]]:
    """Parse additive freight differentials (WS + differentials, Track C1).

    ``differentials``: list of ``{basis, amount, label?}`` where basis is
    ``per_mt`` (× cargo_qty mt), ``per_measure`` (× cargo_measure) or ``lump``
    (flat). Parsed defensively but strictly: malformed entries raise ValueError
    so API layers can surface 422. Returns (total, rows) — rows only carry
    ``label`` when provided. Absent/empty input → (0, []) so legacy results stay
    byte-identical.
    """
    raw = inputs.get("differentials")
    if not raw:
        return Decimal("0"), []
    if isinstance(raw, (str, bytes, dict)) or not isinstance(raw, (list, tuple)):
        raise ValueError(
            f"differentials must be a list of {{basis, amount, label?}} objects, got {type(raw).__name__}"
        )
    cargo_qty = _d(inputs.get("cargo_qty") or 0)
    if inputs.get("legs") and not _d(inputs.get("cargo_qty") or 0):
        _, _, leg_cargo = _apply_legs(inputs)
        cargo_qty = leg_cargo
    cargo_measure_raw = inputs.get("cargo_measure")
    total = Decimal("0")
    rows: list[dict[str, Any]] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"differentials[{i}] must be an object with basis/amount, got {type(entry).__name__}")
        basis_raw = str(entry.get("basis") or "").strip().lower()
        basis = _DIFF_BASIS_ALIASES.get(basis_raw)
        if not basis:
            raise ValueError(
                f"differentials[{i}].basis must be per_mt|per_measure|lump, got {entry.get('basis')!r}"
            )
        amount_raw = entry.get("amount")
        if amount_raw is None or (isinstance(amount_raw, str) and not amount_raw.strip()):
            raise ValueError(f"differentials[{i}].amount is required")
        amount = _d(amount_raw)
        if basis == "per_mt":
            value = amount * cargo_qty
        elif basis == "per_measure":
            if cargo_measure_raw is None:
                raise ValueError(
                    f"differentials[{i}].basis=per_measure requires a cargo_measure input"
                )
            value = amount * _d(cargo_measure_raw)
        else:  # lump — flat add-on (negative = rebate)
            value = amount
        value = value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        total += value
        row: dict[str, Any] = {"basis": basis, "amount": float(amount), "value": float(value)}
        if entry.get("label") is not None:
            row["label"] = str(entry.get("label"))
        rows.append(row)
    return total, rows


def compute_estimate(inputs: dict[str, Any], *, db: Any = None, tenant_id: Any = None) -> dict[str, Any]:
    """
    TCE = (total_revenue - voyage_cost) / total_days
    voyage_cost excludes hire / opportunity hire; brokerage and EU ETS
    emissions cost are included. Address commission is deducted from freight revenue.

    Freight modes (Track C1: Per MT / Lump Sum / WS + Differentials):
    - explicit ``freight_basis`` input selects the mode (aliases accepted, see
      ``_FREIGHT_BASIS_ALIASES``): per_mt / lump_sum / worldscale / ws_differential.
    - without an explicit basis, legacy auto-detect (byte-identical):
      lump_sum_freight > 0 → lump sum; ws_flat + ws_pct (or ws_rate_pct) →
      Worldscale: cargo_qty * ws_flat * (ws_pct/100); else cargo_qty * freight_rate.
    - ``differentials: [{basis: per_mt|per_measure|lump, amount, label?}]`` are
      additive freight add-ons: per_mt × cargo_qty, per_measure × cargo_measure,
      lump = flat amount (negative = rebate). Added to gross freight before
      commissions. When applied on top of a Worldscale base the output
      ``freight_basis`` becomes ``ws_differential``.
    - Explicit modes validate their required inputs (ValueError → 422); the
      legacy auto path never raises on missing freight inputs.

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
    - Phase 4 rate tables (require db + tenant_id kwargs, see
      _resolve_rate_table_inputs): freight_rate_table_id fills freight_rate
      when no direct rate is given; demurrage_rate_table_id × demurrage_days
      fills demurrage_income; surcharge_rate_table_id × cargo_qty adds
      surcharge_income to revenue. Direct values win when provided
      (backward compatibility) — the rate table is the optional fill-in.
    - scale_table (比例运费表, services/freight_terms.py): tiered per-mt rates
      {qty_from, qty_to, rate} selected by scale_qty (default cargo_qty). Fills
      freight_rate when no direct rate is given (fill-in, same precedence as
      rate tables). Per-mt only — a lump_sum/worldscale mode together with a
      scale_table raises ValueError. Provenance keys ``scale_table_rate`` /
      ``scale_qty`` are added to results only when the table is present.
    - extra_freight_terms: [{term, basis: per_mt|per_lump|pct_of_freight, rate,
      applies_when?}] additive surcharges appended to gross freight (after
      differentials, before commissions). pct_of_freight multiplies the freight
      base (gross after differentials, before extras — terms do not compound).
      applies_when is an optional predicate dict over the estimate inputs
      (exact key/value match; ``*_min``/``*_max`` numeric bounds). Absent/empty
      → legacy output byte-identical; present → result keys
      ``extra_freight_terms`` / ``extra_freight_total``.
    - unpriced_components (指数联动定价, services/unpriced_components.py):
      index-linked hire elements [{name, formula: rolling_index|range|level|
      offset, index_name?, observations?, base_value?, offset_value?, floor?,
      cap?, window_days?, factor?, basis: per_day|per_lump}] resolved against
      inline observations or a tenant-scoped MarketQuote series. The resolved
      total is folded into hire_cost as extra hire lines (hire is excluded from
      voyage_cost / TCE, so TCE is unchanged and net_result absorbs it).
      Absent/empty → legacy output byte-identical; present → result keys
      ``unpriced_components`` / ``unpriced_components_total``.
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
    # ws_rate_pct is an accepted alias for ws_pct (Track C1 input vocabulary)
    ws_pct_raw = inputs.get("ws_pct")
    if ws_pct_raw is None or (isinstance(ws_pct_raw, str) and not ws_pct_raw.strip()):
        ws_pct_raw = inputs.get("ws_rate_pct")
        if isinstance(ws_pct_raw, str) and not ws_pct_raw.strip():
            ws_pct_raw = None
    ws_pct = _d(ws_pct_raw)
    ws_pct_provided = ws_pct_raw is not None

    # Phase 4 rate tables (optional; no-op without *_rate_table_id keys)
    rate_table_hits: dict[str, Decimal] = {}
    if db is not None and tenant_id is not None:
        rate_table_hits = _resolve_rate_table_inputs(inputs, db, tenant_id)
    if "freight_rate" in rate_table_hits:
        freight_rate = rate_table_hits["freight_rate"]

    # Scale table (比例运费表) — optional fill-in for freight_rate (direct wins).
    scale_qty = _d(inputs.get("scale_qty") if inputs.get("scale_qty") is not None else cargo_qty)
    scale_rate: Decimal | None = None
    if inputs.get("scale_table"):
        from app.services.freight_terms import apply_scale_table  # local: engine stays import-light

        scale_rate = apply_scale_table(scale_qty, inputs["scale_table"])
        if not _d(inputs.get("freight_rate") or 0) and "freight_rate" not in rate_table_hits:
            freight_rate = scale_rate

    # Freight mode selection: explicit freight_basis input wins; otherwise legacy
    # auto-detect (byte-identical when no new inputs are present).
    basis_raw = inputs.get("freight_basis")
    explicit_basis: str | None = None
    if basis_raw is not None and str(basis_raw).strip() != "":
        key = str(basis_raw).strip().lower()
        explicit_basis = _FREIGHT_BASIS_ALIASES.get(key)
        if explicit_basis is None:
            raise ValueError(
                f"freight_basis must be per_mt|lump_sum|worldscale|ws_differential, got {basis_raw!r}"
            )

    if explicit_basis is not None:
        mode = explicit_basis
        if mode == "per_mt":
            if freight_rate <= 0:
                raise ValueError(
                    "freight_basis=per_mt requires freight_rate > 0 "
                    f"(or freight_rate_table_id resolvable), got {inputs.get('freight_rate')!r}"
                )
        elif mode == "lump_sum":
            if lump_sum <= 0:
                # pricing_engine convention: freight_rate carries the lump amount
                # when lump_sum_freight is absent
                lump_sum = freight_rate
            if lump_sum <= 0:
                raise ValueError(
                    "freight_basis=lump_sum requires lump_sum_freight > 0 "
                    f"(or freight_rate as the lump amount), got {inputs.get('lump_sum_freight')!r}"
                )
        else:  # worldscale | ws_differential
            if ws_flat <= 0:
                raise ValueError(
                    f"freight_basis={mode} requires ws_flat > 0, got {inputs.get('ws_flat')!r}"
                )
            if not ws_pct_provided:
                raise ValueError(
                    f"freight_basis={mode} requires ws_pct (or ws_rate_pct), got none"
                )
            if ws_pct < 0:
                raise ValueError(
                    f"freight_basis={mode} requires ws_pct (or ws_rate_pct) >= 0, got {ws_pct}"
                )
    else:
        # legacy auto-detect
        if lump_sum > 0:
            mode = "lump_sum"
        elif ws_flat > 0 and ws_pct > 0:
            mode = "worldscale"
        else:
            mode = "per_mt"

    if scale_rate is not None and mode != "per_mt":
        raise ValueError(
            "scale_table is per-mt only: it cannot price freight_basis="
            f"{_BASIS_OUTPUT[mode]!r} freight; remove scale_table or switch to per_mt"
        )

    if mode == "lump_sum":
        base_freight = lump_sum
    elif mode in ("worldscale", "ws_differential"):
        # Worldscale: flat rate × WS% × cargo quantity (simplified commercial form)
        base_freight = cargo_qty * ws_flat * (ws_pct / Decimal("100"))
    else:  # per_mt
        base_freight = cargo_qty * freight_rate

    # Freight differentials (additive add-ons; absent → no-op, legacy unchanged)
    differentials_total, differential_rows = _parse_differentials(inputs)
    if differentials_total or differential_rows:
        if mode in ("worldscale", "ws_differential"):
            mode = "ws_differential"
        gross_freight = base_freight + differentials_total
    else:
        gross_freight = base_freight

    # Extra freight terms (additive surcharges; absent → no-op, legacy unchanged).
    # pct_of_freight multiplies the freight base (gross after differentials,
    # before extras) — terms do not compound each other.
    extra_terms_total, extra_term_rows = (Decimal("0"), [])
    if inputs.get("extra_freight_terms"):
        from app.services.freight_terms import parse_extra_freight_terms  # local import

        extra_terms_total, extra_term_rows = parse_extra_freight_terms(inputs, gross_freight)
        if extra_term_rows:
            gross_freight = gross_freight + extra_terms_total

    freight_basis = _BASIS_OUTPUT[mode]

    address_commission = (gross_freight * address_comm_pct / Decimal("100")).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    brokerage = (gross_freight * brokerage_pct / Decimal("100")).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    commission = address_commission  # legacy output key
    net_freight = gross_freight - address_commission

    demurrage = rate_table_hits.get("demurrage_income", _d(inputs.get("demurrage_income") or 0))
    other_income = _d(inputs.get("other_income") or 0)
    surcharge_income = rate_table_hits.get("surcharge_income", Decimal("0"))
    total_revenue = net_freight + demurrage + other_income + surcharge_income

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

    # Unpriced (index-linked) components — extra hire lines; absent → no-op.
    unpriced_total = Decimal("0")
    unpriced_rows: list[dict[str, Any]] = []
    if inputs.get("unpriced_components"):
        from app.services.unpriced_components import evaluate_unpriced_components  # local import

        unpriced_total, unpriced_rows = evaluate_unpriced_components(
            inputs["unpriced_components"],
            days=total_days,
            db=db,
            tenant_id=tenant_id,
            default_pricing_date=_as_of(inputs),
        )
        hire_cost = hire_cost + unpriced_total

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

    # rate-table provenance — only present when a table actually contributed,
    # so legacy results stay byte-identical.
    if differential_rows:
        result["differentials"] = differential_rows
        result["differentials_total"] = float(differentials_total.quantize(TWOPLACES))
    if extra_term_rows:
        result["extra_freight_terms"] = extra_term_rows
        result["extra_freight_total"] = float(extra_terms_total.quantize(TWOPLACES))
    if unpriced_rows:
        result["unpriced_components"] = unpriced_rows
        result["unpriced_components_total"] = float(unpriced_total.quantize(TWOPLACES))
    if scale_rate is not None:
        result["scale_table_rate"] = float(scale_rate.quantize(FOUR, rounding=ROUND_HALF_UP))
        result["scale_qty"] = float(scale_qty.quantize(THREE, rounding=ROUND_HALF_UP))
    if rate_table_hits:
        result["surcharge_income"] = float(surcharge_income.quantize(TWOPLACES))
        result["rate_table_rates"] = {
            "freight_rate": float(rate_table_hits["freight_rate"]) if "freight_rate" in rate_table_hits else None,
            "demurrage_income": float(rate_table_hits["demurrage_income"]) if "demurrage_income" in rate_table_hits else None,
            "surcharge_income": float(rate_table_hits["surcharge_income"]) if "surcharge_income" in rate_table_hits else None,
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
    *,
    db: Any = None,
    tenant_id: Any = None,
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
        out = compute_estimate(inp, db=db, tenant_id=tenant_id)
        row = {"field": field, "mode": mode, "tce": out["tce"], "result": out}
        row["delta_abs" if mode == "abs" else "delta_pct"] = d
        rows.append(row)
    return rows
