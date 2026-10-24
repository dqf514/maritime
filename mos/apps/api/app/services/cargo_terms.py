"""Cargo CP terms — billable quantity basis, MOL tolerance window, overage pricing.

Pure helpers shared by the commercial/COA routers and tests. Deliberately kept
out of ``services/estimate_engine.compute_estimate`` so the TCE gold fixtures
(``fixtures/calc/tce``) stay byte-identical: the engine already supports an
optional ``cargo_tolerance_pct`` input that emits ``cargo_qty_min`` /
``cargo_qty_max``; overage billing is a settlement-time concern priced here
against a billed quantity (e.g. B/L qty) rather than a voyage-economics input.

Terms vocabulary (aligns with COA_BILL_BY / cargo qty_unit conventions):
  bill_by       — weight (mt) | measure (m3/cbm) | volume (bbl)
  tolerance_pct — ±pct MOL window around the contracted quantity
  overage_pct   — % rate uplift applied to quantity above the tolerance max
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from app.services.money import CENT

# bill_by: weight → mt, measure → m3/cbm, volume → bbl (see models_coa.COA_BILL_BY)
BILL_BY_VALUES = ("weight", "measure", "volume")


THREE = Decimal("0.001")

# validation ranges (mirrored by the Pydantic schemas)
TOLERANCE_PCT_MIN, TOLERANCE_PCT_MAX = Decimal("0"), Decimal("50")
OVERAGE_PCT_MIN, OVERAGE_PCT_MAX = Decimal("0"), Decimal("100")


def _d(v, default: str = "0") -> Decimal:
    if v is None:
        return Decimal(default)
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def quantity_bounds(
    qty: Decimal | float | int | str | None,
    tolerance_pct: Decimal | float | int | str | None,
) -> tuple[Decimal | None, Decimal | None]:
    """(qty_min, qty_max) = qty × (1 ∓ tolerance_pct/100); None tolerance → (qty, qty).

    tolerance_pct 必须落在本模块声明的区间内（TOLERANCE_PCT_MIN..MAX）——
    以前负公差会算出「下界 > 上界」的反向区间（P2-B17）。
    """
    if qty is None:
        return None, None
    q = _d(qty)
    if q < 0:
        raise ValueError(f"qty must be >= 0, got {qty!r}")
    if tolerance_pct is None:
        return q, q
    tol_pct = _d(tolerance_pct)
    if tol_pct < TOLERANCE_PCT_MIN or tol_pct > TOLERANCE_PCT_MAX:
        raise ValueError(
            f"tolerance_pct must be between {TOLERANCE_PCT_MIN} and {TOLERANCE_PCT_MAX}, got {tol_pct}"
        )
    tol = tol_pct / Decimal("100")
    return (
        (q * (Decimal("1") - tol)).quantize(THREE, rounding=ROUND_HALF_UP),
        (q * (Decimal("1") + tol)).quantize(THREE, rounding=ROUND_HALF_UP),
    )


def freight_with_overage(
    *,
    contract_qty: Decimal | float | int | str | None,
    billed_qty: Decimal | float | int | str,
    freight_rate: Decimal | float | int | str,
    tolerance_pct: Decimal | float | int | str | None = None,
    overage_pct: Decimal | float | int | str | None = None,
) -> dict:
    """Billable freight under the CP cargo terms (per-unit rate basis).

    - Tolerance window bounds the contracted-rate quantity:
      ``qty_max = contract_qty × (1 + tolerance_pct/100)`` (contract_qty when no
      tolerance). Quantity up to ``qty_max`` bills at ``freight_rate``.
    - Any billed quantity above ``qty_max`` ("overage") bills at
      ``freight_rate × (1 + overage_pct/100)`` — the same rate when
      ``overage_pct`` is absent/zero.
    - Short shipments bill on the billed quantity (no minimum-freight clause
      here — that lives in the CP clauses document, not the rate path).
    """
    billed = _d(billed_qty)
    if billed < 0:
        raise ValueError(f"billed_qty must be >= 0, got {billed_qty!r}")
    rate = _d(freight_rate)
    if rate < 0:
        raise ValueError(f"freight_rate must be >= 0, got {freight_rate!r}")

    qty_min, qty_max = quantity_bounds(contract_qty, tolerance_pct)
    if qty_max is None:
        # no contracted quantity → everything bills at the contract rate
        qty_max = billed
        qty_min = billed

    at_contract = billed if billed <= qty_max else qty_max
    over_qty = billed - at_contract
    over_rate_pct = _d(overage_pct) if overage_pct is not None else Decimal("0")
    if over_rate_pct < OVERAGE_PCT_MIN or over_rate_pct > OVERAGE_PCT_MAX:
        raise ValueError(
            f"overage_pct must be between {OVERAGE_PCT_MIN} and {OVERAGE_PCT_MAX}, got {over_rate_pct}"
        )

    contract_freight = (at_contract * rate).quantize(CENT, rounding=ROUND_HALF_UP)
    # 超量部分按**量化后**的费率计价 —— 报的 overage_rate 与实际算的钱必须是
    # 同一个数（以前报 1.51 却按 1.5035 算，100 单位差 0.10）（P2-B16）。
    over_rate = (rate * (Decimal("1") + over_rate_pct / Decimal("100"))).quantize(
        CENT, rounding=ROUND_HALF_UP
    )
    overage_freight = (over_qty * over_rate).quantize(CENT, rounding=ROUND_HALF_UP)

    return {
        "billable_basis_note": "per-unit freight_rate; bill_by selects the qty unit (weight|measure|volume)",
        "contract_qty": float(_d(contract_qty)) if contract_qty is not None else None,
        "billed_qty": float(billed),
        "tolerance_pct": float(_d(tolerance_pct)) if tolerance_pct is not None else None,
        "overage_pct": float(over_rate_pct),
        "qty_min": float(qty_min) if qty_min is not None else None,
        "qty_max": float(qty_max) if qty_max is not None else None,
        "qty_at_contract_rate": float(at_contract.quantize(THREE, rounding=ROUND_HALF_UP)),
        "qty_at_overage_rate": float(over_qty.quantize(THREE, rounding=ROUND_HALF_UP)),
        "freight_rate": float(rate),
        "overage_rate": float(over_rate),
        "contract_freight": float(contract_freight),
        "overage_freight": float(overage_freight),
        "total_freight": float((contract_freight + overage_freight).quantize(CENT, rounding=ROUND_HALF_UP)),
    }


# ── pricing-tab auto scoring: cargo parcel ↔ itinerary leg matching ────────────


def score_cargo_vs_leg(
    *,
    cargo_load_port_id,
    cargo_disch_port_id,
    cargo_qty,
    cargo_laycan_from: date | None = None,
    cargo_laycan_to: date | None = None,
    leg_load_port_id=None,
    leg_disch_port_id=None,
    leg_qty=None,
    period_from: date | None = None,
    period_to: date | None = None,
    tolerance_pct=None,
) -> dict:
    """Deterministic 0–100 match score of one cargo parcel against one leg.

    Breakdown (sums to 100 when fully matched):
      load port equal (both set)      25
      disch port equal (both set)     25
      qty fit  30 × min(qty)/max(qty) 30  (0 when either qty missing/non-positive)
      laycan ∩ contract period        20
    ``tolerance_pct`` (when set) only annotates ``within_tolerance`` — it does
    not change the score, so ranking stays stable across contracts.
    """
    breakdown: dict[str, float] = {}

    load_match = (
        cargo_load_port_id is not None
        and leg_load_port_id is not None
        and cargo_load_port_id == leg_load_port_id
    )
    disch_match = (
        cargo_disch_port_id is not None
        and leg_disch_port_id is not None
        and cargo_disch_port_id == leg_disch_port_id
    )
    breakdown["load_port"] = 25.0 if load_match else 0.0
    breakdown["disch_port"] = 25.0 if disch_match else 0.0

    cq = _d(cargo_qty) if cargo_qty is not None else None
    lq = _d(leg_qty) if leg_qty is not None else None
    qty_score = 0.0
    within_tolerance: bool | None = None
    if cq is not None and lq is not None and cq > 0 and lq > 0:
        qty_score = float(
            (Decimal("30") * (cq if cq < lq else lq) / (cq if cq > lq else lq)).quantize(
                CENT, rounding=ROUND_HALF_UP
            )
        )
        if tolerance_pct is not None:
            tol = _d(tolerance_pct) / Decimal("100")
            within_tolerance = abs(cq - lq) <= lq * tol
    breakdown["qty_fit"] = qty_score

    laycan_score = 0.0
    if cargo_laycan_from is not None and cargo_laycan_to is not None and period_from is not None and period_to is not None:
        overlaps = cargo_laycan_from <= period_to and cargo_laycan_to >= period_from
        laycan_score = 20.0 if overlaps else 0.0
    breakdown["laycan_window"] = laycan_score

    # 评分求和走 Decimal + 显式 HALF_UP：裸 round() 是二进制银行家舍入
    # （round(2.675, 2) == 2.67）（P2-B19）
    score = (
        Decimal(str(breakdown["load_port"]))
        + Decimal(str(breakdown["disch_port"]))
        + Decimal(str(qty_score))
        + Decimal(str(laycan_score))
    ).quantize(CENT, rounding=ROUND_HALF_UP)

    return {
        "score": float(score),
        "breakdown": breakdown,
        "within_tolerance": within_tolerance,
    }


def score_cargoes_to_legs(
    cargoes: list[dict],
    legs: list[dict],
    *,
    tolerance_pct=None,
    period_from: date | None = None,
    period_to: date | None = None,
    top_n: int = 3,
) -> list[dict]:
    """Score every cargo against every leg; return per-leg matches sorted by score.

    ``cargoes`` / ``legs`` are plain dicts (see routers for field names) so the
    helper stays ORM-free and unit-testable.
    """
    out: list[dict] = []
    for leg in legs:
        matches = []
        for cargo in cargoes:
            scored = score_cargo_vs_leg(
                cargo_load_port_id=cargo.get("load_port_id"),
                cargo_disch_port_id=cargo.get("disch_port_id"),
                cargo_qty=cargo.get("qty"),
                cargo_laycan_from=cargo.get("laycan_from"),
                cargo_laycan_to=cargo.get("laycan_to"),
                leg_load_port_id=leg.get("load_port_id"),
                leg_disch_port_id=leg.get("disch_port_id"),
                leg_qty=leg.get("qty"),
                period_from=period_from,
                period_to=period_to,
                tolerance_pct=tolerance_pct,
            )
            matches.append(
                {
                    "cargo_id": cargo.get("id"),
                    "cargo_no": cargo.get("cargo_no"),
                    "score": scored["score"],
                    "breakdown": scored["breakdown"],
                    "within_tolerance": scored["within_tolerance"],
                }
            )
        matches.sort(key=lambda m: (-m["score"], m.get("cargo_no") or ""))
        out.append(
            {
                "itinerary_id": leg.get("id"),
                "seq": leg.get("seq"),
                "load_port_id": leg.get("load_port_id"),
                "disch_port_id": leg.get("disch_port_id"),
                "qty": leg.get("qty"),
                "matches": matches[:top_n],
            }
        )
    return out
