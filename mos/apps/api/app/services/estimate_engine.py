"""Voyage estimate / TCE engine (DDS §11)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from app.services.observability import traced
from app.services.money import CENT



FOUR = Decimal("0.0001")
THREE = Decimal("0.001")


def _d(v: Any) -> Decimal:
    if v is None:
        return Decimal("0")
    return Decimal(str(v))


def _num(v: Any, field: str) -> Decimal:
    """Decimal coercion that reports bad input as ValueError (→ API 422)."""
    try:
        return Decimal(str(v))
    except Exception as exc:  # noqa: BLE001 - decimal.InvalidOperation & co
        raise ValueError(f"{field} must be a number, got {v!r}") from exc


# 已知百分数字段 → 合法区间。``EstimateIn.inputs`` 是自由 dict（API 层无单位
# 约束），越界值以前会一路算进金额里（P1-B26/B27/B28），这里在引擎入口统一
# 拦截，抛 ValueError → API 层转 422。
_PERCENT_RANGE: dict[str, tuple[Decimal, Decimal]] = {
    "address_comm_pct": (Decimal("0"), Decimal("100")),
    "commission_pct": (Decimal("0"), Decimal("100")),
    "brokerage_pct": (Decimal("0"), Decimal("100")),
    "cargo_tolerance_pct": (Decimal("0"), Decimal("100")),
    "eu_ets_share_pct": (Decimal("0"), Decimal("100")),
    # Worldscale 可以超过 100%（WS 150 合法），只挡负数与离谱值
    "ws_pct": (Decimal("0"), Decimal("1000")),
    "ws_rate_pct": (Decimal("0"), Decimal("1000")),
}

# 收入类输入：不允许负数（负数收入没有文档化的符号约定，见 P2-B22）
_INCOME_FIELDS = ("demurrage_income", "other_income", "surcharge_income")

# 金额类输入：同样必须 >= 0。
# ``freight_rate`` 以前可以为负 → 负运费直接变成负收入（实测 −100 → −100,000）。
# ``hire_per_day`` 为负更是没有任何商业含义（除非刻意记亏损）。这里按"输入体检"
# 的口径统一拦掉；**负金额的合法场景**（商业返利/折扣）走 ``differentials`` /
# ``other_costs`` / ``extra_freight_terms`` 这些显式允许负值的结构，不受影响。
_AMOUNT_FIELDS = (
    "freight_rate",
    "lump_sum_freight",
    "ws_flat",
    "hire_per_day",
    "bunker_price",
    "eca_extra_cost",
    "canal_costs",
    "demurrage_rate",
)


def _validate_inputs(inputs: dict[str, Any]) -> None:
    """引擎入口的输入体检：百分数区间 + 收入非负。"""
    for name, (lo, hi) in _PERCENT_RANGE.items():
        raw = inputs.get(name)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            continue
        val = _num(raw, name)
        if val < lo or val > hi:
            raise ValueError(f"{name} must be between {lo} and {hi}, got {val}")
    # eu_ets_share 是 0–1 的**份额**（不是百分数）；>1 说明按百分数填了，
    # 以前会算成 100 倍的排放成本，现在明确报错并指向 eu_ets_share_pct。
    raw = inputs.get("eu_ets_share")
    if raw is not None and not (isinstance(raw, str) and not raw.strip()):
        val = _num(raw, "eu_ets_share")
        if val < 0 or val > 1:
            raise ValueError(
                "eu_ets_share must be between 0 and 1 (a share/ratio). "
                f"For a percentage use eu_ets_share_pct (0-100), got {val}"
            )
    for name in _INCOME_FIELDS:
        raw = inputs.get(name)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            continue
        val = _num(raw, name)
        if val < 0:
            raise ValueError(f"{name} must be >= 0, got {val}")
    for name in _AMOUNT_FIELDS:
        raw = inputs.get(name)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            continue
        val = _num(raw, name)
        if val < 0:
            raise ValueError(f"{name} must be >= 0, got {val}")


DEFAULT_CO2_FACTOR = Decimal("3.114")  # mt CO2 per mt fuel (IMO default)


def validate_estimate_inputs(inputs: dict[str, Any]) -> None:
    """公开版输入体检 —— API 层（存稿前）也可以调用。

    ``EstimateIn.inputs`` 是自由 dict，Pydantic 没法直接挂 ``ge/le``；
    这里复用引擎同一套区间规则，越界值在**写入**时就被拒（422），
    而不是等到算的时候才炸。
    """
    _validate_inputs(inputs or {})

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

# 一次性（flat）加价 —— 多货种继承顶层 differentials 时只能落到一个 parcel
_LUMP_BASIS_KEYS = frozenset({"lump", "lump_sum", "lump-sum", "lumpsum", "flat"})

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

    A table id that cannot be resolved into a rate raises ValueError instead
    of silently pricing that line at 0 (P1-B11) — a 250/MT surcharge on
    20,000 MT is 5,000,000 of revenue that must not disappear quietly.

    Returns only the keys that resolved, e.g.
    ``{"freight_rate": Decimal("12.5"), "surcharge_income": Decimal("...")}``.
    """
    from app.services.rates import resolve_rate  # local import: engine stays import-light

    out: dict[str, Decimal] = {}
    as_of = _as_of(inputs)
    dims = _rate_table_dims(inputs)

    freight_tid = inputs.get("freight_rate_table_id")
    if freight_tid and not _d(inputs.get("freight_rate") or 0):
        val = resolve_rate(db, tenant_id, freight_tid, dims, as_of=as_of)
        if val is None:
            raise ValueError(
                f"freight_rate_table_id {freight_tid} did not resolve to a rate for dims {dims or '{}'}"
            )
        out["freight_rate"] = val

    dem_tid = inputs.get("demurrage_rate_table_id")
    if dem_tid and not _d(inputs.get("demurrage_income") or 0) and inputs.get("demurrage_days") is not None:
        val = resolve_rate(db, tenant_id, dem_tid, dims, as_of=as_of)
        if val is None:
            raise ValueError(
                f"demurrage_rate_table_id {dem_tid} did not resolve to a rate for dims {dims or '{}'}"
            )
        out["demurrage_income"] = (val * _d(inputs.get("demurrage_days"))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    sur_tid = inputs.get("surcharge_rate_table_id")
    if sur_tid:
        val = resolve_rate(db, tenant_id, sur_tid, dims, as_of=as_of)
        if val is None:
            raise ValueError(
                f"surcharge_rate_table_id {sur_tid} did not resolve to a rate for dims {dims or '{}'}"
            )
        if inputs.get("cargo_qty") is None:
            raise ValueError(
                f"surcharge_rate_table_id {sur_tid} needs cargo_qty to price the surcharge"
            )
        out["surcharge_income"] = (val * _d(inputs.get("cargo_qty"))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    return out


def _parse_diff_list(
    raw: Any,
    *,
    cargo_qty: Decimal,
    cargo_measure_raw: Any,
    label: str = "differentials",
) -> tuple[Decimal, list[dict[str, Any]]]:
    """Parse a differentials list against an explicit cargo context.

    Shared by the top-level (legacy) path and per-cargo entries in
    multi-cargo estimates. Same strict validation → ValueError/422 contract.
    """
    if not raw:
        return Decimal("0"), []
    if isinstance(raw, (str, bytes, dict)) or not isinstance(raw, (list, tuple)):
        raise ValueError(
            f"{label} must be a list of {{basis, amount, label?}} objects, got {type(raw).__name__}"
        )
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
        amount = _num(amount_raw, f"differentials[{i}].amount")
        if basis == "per_mt":
            value = amount * cargo_qty
        elif basis == "per_measure":
            if cargo_measure_raw is None:
                raise ValueError(
                    f"differentials[{i}].basis=per_measure requires a cargo_measure input"
                )
            value = amount * _num(cargo_measure_raw, f"differentials[{i}] cargo_measure")
        else:  # lump — flat add-on (negative = rebate)
            value = amount
        # 先求和后量化（P2-B13）：逐行量化再求和会把每行的半分误差
        # 累积到总额上（3 × 0.005 → 0.03 而非 0.02），行数越多偏得越多。
        total += value
        row: dict[str, Any] = {"basis": basis, "amount": float(amount), "value": float(value.quantize(CENT, rounding=ROUND_HALF_UP))}
        if entry.get("label") is not None:
            row["label"] = str(entry.get("label"))
        rows.append(row)
    return total.quantize(CENT, rounding=ROUND_HALF_UP), rows


def _parse_differentials(inputs: dict[str, Any]) -> tuple[Decimal, list[dict[str, Any]]]:
    """Parse additive freight differentials (WS + differentials, Track C1).

    ``differentials``: list of ``{basis, amount, label?}`` where basis is
    ``per_mt`` (× cargo_qty mt), ``per_measure`` (× cargo_measure) or ``lump``
    (flat). Cargo context derives from top-level cargo_qty (or summed leg
    cargo_qty). Absent/empty input → (0, []) so legacy results stay
    byte-identical. See ``_parse_diff_list`` for the shared validation core.
    """
    raw = inputs.get("differentials")
    if not raw:
        return Decimal("0"), []
    cargo_qty = _d(inputs.get("cargo_qty") or 0)
    if inputs.get("legs") and not _d(inputs.get("cargo_qty") or 0):
        _, _, leg_cargo = _apply_legs(inputs)
        cargo_qty = leg_cargo
    return _parse_diff_list(raw, cargo_qty=cargo_qty, cargo_measure_raw=inputs.get("cargo_measure"))


@traced("estimate")
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
    - cargoes (multi-cargo / parcells, IMOS parity): list of parcel objects
      ``[{qty, cargo_type?, load_port?, disch_port?, measure?, freight_basis?,
      freight_rate?, lump_sum_freight?, ws_flat?, ws_pct?, differentials?}]``.
      Each parcel is priced on its own basis (own freight_basis or the
      top-level default, else legacy auto-detect); missing per-cargo pricing
      fields inherit the top-level inputs — including ``differentials`` and
      ``cargo_measure`` (a flat ``lump`` differential is charged once, to the
      first parcel that inherits it). Shared voyage cost, commissions,
      ETS and TCE math are unchanged — parcels only aggregate the revenue
      side. ``cargo_qty`` falls back to the parcel total when absent.
      Results add ``cargoes`` (per-parcel breakdown), ``cargo_count`` and
      ``parcel_qty_total``; ``freight_basis`` reports ``"multi"`` when
      parcels mix bases. Absent → legacy single-cargo path byte-identical.
      scale_table is rejected with cargoes (per-parcel freight_rate instead).
    - legs: multi-leg itinerary; **adds** to the top-level sea_days/port_days
      (Σ distance/speed/24, Σ leg port_days) — top-level days are the extra
      days beyond the legs (they used to be discarded) — and sums leg
      cargo_qty when top-level cargo_qty is absent.
    - bunker_prices + bunker_grade / bunker_eca_grade: per-grade pricing; sea
      consumption is priced at bunker_grade, port/ECA consumption at
      bunker_eca_grade. A missing grade falls back to the sea grade, then to a
      single-priced list, then to bunker_price — never to a silent 0.
    - eu_ets_share_pct (0-100, percent) / eu_ets_share (0-1, legacy ratio),
      ets_price, co2_factor (default 3.114):
      emissions_cost = total fuel mt × co2_factor × share × ets_price.
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
    - Vessel-master enrichment (services/estimate_enrich.py): when db +
      tenant_id are given and inputs carry ``vessel_id``, missing leg speeds,
      sea/port bunker tpd, eu_ets_share (port-pair average), ets_price
      (market EUA quote → constant fallback) and eca_days (ECA endpoint
      share × sea_days) are filled from the vessel/fuel-zone/market master
      data. Explicit inputs always win; provenance is reported as
      ``results["inputs_enriched"]``. No vessel_id → byte-identical.
    """
    # 输入体检（百分数区间 / 收入非负）—— 越界值以前会一路算进金额里。
    _validate_inputs(inputs)

    # Track 1 — vessel-master / fuel-zone / market enrichment. Gated on db +
    # tenant_id + vessel_id so gold fixtures and pure-arithmetic callers are
    # untouched; fills only missing keys, caller's dict is never mutated.
    enriched_prov: dict[str, str] = {}
    if db is not None and tenant_id is not None and inputs.get("vessel_id"):
        from app.services.estimate_enrich import enrich_estimate_inputs

        inputs, enriched_prov = enrich_estimate_inputs(inputs, db, tenant_id)

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
    # 显式 0 与「未提供」必须区分（`or` 会把 0 当缺失 → 凭空收 5% 佣金）。
    if inputs.get("address_comm_pct") is not None:
        address_comm_pct = _num(inputs["address_comm_pct"], "address_comm_pct")
    else:
        address_comm_pct = _d(inputs.get("commission_pct") or 0)
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

    # Freight mode selection: explicit freight_basis input wins (also serves as
    # the default basis for multi-cargo parcels); otherwise legacy auto-detect.
    basis_raw = inputs.get("freight_basis")
    explicit_basis: str | None = None
    if basis_raw is not None and str(basis_raw).strip() != "":
        key = str(basis_raw).strip().lower()
        explicit_basis = _FREIGHT_BASIS_ALIASES.get(key)
        if explicit_basis is None:
            raise ValueError(
                f"freight_basis must be per_mt|lump_sum|worldscale|ws_differential, got {basis_raw!r}"
            )

    # ── Multi-cargo (parcels, IMOS parity) ─────────────────────────────────
    # cargoes: [{qty, cargo_type?, load_port?, disch_port?, measure?,
    #            freight_basis?, freight_rate?, lump_sum_freight?, ws_flat?,
    #            ws_pct?, differentials?}] — each parcel priced on its own
    # basis; missing per-cargo fields inherit the top-level inputs (so a
    # single-cargo estimate converts to multi-cargo by splitting rows).
    # Shared voyage cost / commission math below is unchanged: parcels only
    # multiply the revenue side. Absent/empty → legacy path byte-identical.
    cargoes_raw = inputs.get("cargoes") or []
    multi_rows: list[dict[str, Any]] = []
    if cargoes_raw:
        if isinstance(cargoes_raw, (str, bytes, dict)) or not isinstance(cargoes_raw, (list, tuple)):
            raise ValueError(
                f"cargoes must be a list of parcel objects, got {type(cargoes_raw).__name__}"
            )
        if inputs.get("scale_table"):
            raise ValueError(
                "scale_table applies to single-cargo estimates only; "
                "give each cargo its own freight_rate in cargoes[] instead"
            )
        base_freight = Decimal("0")
        differentials_total = Decimal("0")
        differential_rows: list[dict[str, Any]] = []
        parcel_qty_total = Decimal("0")
        parcel_modes: set[str] = set()
        # 顶层 differentials / cargo_measure 作为缺省值被各 parcel 继承
        # （模块文档承诺的继承口径；以前多货种模式直接丢弃顶层值）。
        top_differentials = inputs.get("differentials") or []
        top_lump_used: set[int] = set()

        def _parcel_differentials(idx: int, parcel: dict[str, Any]) -> Any:
            own = parcel.get("differentials")
            if own is not None:
                return own
            if not top_differentials:
                return None
            keep: list[Any] = []
            for j, entry in enumerate(top_differentials):
                if j in top_lump_used:
                    continue
                keep.append(entry)
            # lump（一次性费用）只落到第一个继承它的 parcel，否则多货种会重复收费
            for j, entry in enumerate(top_differentials):
                if isinstance(entry, dict) and str(entry.get("basis") or "").strip().lower() in _LUMP_BASIS_KEYS:
                    top_lump_used.add(j)
            return keep or None

        for i, cargo in enumerate(cargoes_raw):
            if not isinstance(cargo, dict):
                raise ValueError(
                    f"cargoes[{i}] must be an object with qty, got {type(cargo).__name__}"
                )
            qty_raw = cargo.get("qty")
            if qty_raw is None or _d(qty_raw) <= 0:
                raise ValueError(f"cargoes[{i}].qty must be > 0, got {qty_raw!r}")
            c_qty = _d(qty_raw)
            parcel_qty_total += c_qty

            # per-cargo basis: own freight_basis, else top-level, else auto-detect
            c_basis_raw = cargo.get("freight_basis")
            if c_basis_raw is not None and str(c_basis_raw).strip() != "":
                c_mode = _FREIGHT_BASIS_ALIASES.get(str(c_basis_raw).strip().lower())
                if c_mode is None:
                    raise ValueError(
                        f"cargoes[{i}].freight_basis must be per_mt|lump_sum|worldscale|ws_differential, "
                        f"got {c_basis_raw!r}"
                    )
            else:
                c_mode = explicit_basis  # may still be None → auto-detect below
            c_rate = _d(cargo.get("freight_rate") if cargo.get("freight_rate") is not None else freight_rate)
            c_lump = _d(
                cargo.get("lump_sum_freight")
                if cargo.get("lump_sum_freight") is not None
                else lump_sum
            )
            c_ws_flat = _d(cargo.get("ws_flat") if cargo.get("ws_flat") is not None else ws_flat)
            c_ws_pct_raw = cargo.get("ws_pct")
            if c_ws_pct_raw is None or (isinstance(c_ws_pct_raw, str) and not c_ws_pct_raw.strip()):
                c_ws_pct = ws_pct
            else:
                c_ws_pct = _d(c_ws_pct_raw)

            if c_mode is None:
                if c_lump > 0:
                    c_mode = "lump_sum"
                elif c_ws_flat > 0 and c_ws_pct > 0:
                    c_mode = "worldscale"
                else:
                    c_mode = "per_mt"
            if c_mode == "per_mt" and c_rate <= 0:
                raise ValueError(
                    f"cargoes[{i}] freight_basis=per_mt requires freight_rate > 0, got {qty_raw=}, "
                    f"rate={c_rate}"
                )
            if c_mode == "lump_sum":
                if c_lump <= 0:
                    c_lump = c_rate
                if c_lump <= 0:
                    raise ValueError(
                        f"cargoes[{i}] freight_basis=lump_sum requires lump_sum_freight > 0, got none"
                    )
                c_base = c_lump
            elif c_mode in ("worldscale", "ws_differential"):
                if c_ws_flat <= 0:
                    raise ValueError(f"cargoes[{i}] freight_basis={c_mode} requires ws_flat > 0, got {c_ws_flat}")
                if c_ws_pct <= 0:
                    raise ValueError(
                        f"cargoes[{i}] freight_basis={c_mode} requires ws_pct > 0, got {c_ws_pct}"
                    )
                c_base = c_qty * c_ws_flat * (c_ws_pct / Decimal("100"))
            else:
                c_base = c_qty * c_rate

            c_measure = cargo.get("measure", cargo.get("cargo_measure"))
            if c_measure is None:
                c_measure = inputs.get("cargo_measure")
            c_diff, c_diff_rows = _parse_diff_list(
                _parcel_differentials(i, cargo),
                cargo_qty=c_qty,
                cargo_measure_raw=c_measure,
                label=f"cargoes[{i}].differentials",
            )
            if c_diff_rows and c_mode in ("worldscale", "ws_differential"):
                c_mode = "ws_differential"
            parcel_modes.add(c_mode)
            # parcel 行展示的是量化后的值，总额也用同一批量化值累加 ——
            # 否则表格行加总与抬头对不上（P2-B15）。
            c_base_q = c_base.quantize(CENT, rounding=ROUND_HALF_UP)
            base_freight += c_base_q
            differentials_total += c_diff
            for r in c_diff_rows:
                r["cargo_index"] = i
                differential_rows.append(r)
            row: dict[str, Any] = {
                "index": i,
                "qty": float(c_qty),
                "freight_basis": _BASIS_OUTPUT[c_mode],
                "base_freight": float(c_base_q),
            }
            for k in ("cargo_type", "load_port", "disch_port"):
                if cargo.get(k) is not None:
                    row[k] = str(cargo[k])
            if c_diff_rows:
                row["differentials_total"] = float(c_diff.quantize(CENT, rounding=ROUND_HALF_UP))
            multi_rows.append(row)

        # capacity / tolerance math key off the total parcel quantity when the
        # top-level cargo_qty is absent (consistent with the legs convention).
        if not cargo_qty and parcel_qty_total:
            cargo_qty = parcel_qty_total
        freight_basis = (
            _BASIS_OUTPUT[next(iter(parcel_modes))] if len(parcel_modes) == 1 else "multi"
        )
        gross_freight = base_freight + differentials_total
        mode = next(iter(parcel_modes)) if len(parcel_modes) == 1 else "per_mt"  # scale_table already rejected
        scale_qty = cargo_qty
        scale_rate = None
    else:
        # ── Single-cargo legacy path (byte-identical when cargoes absent) ──
        # Scale table (比例运费表) — optional fill-in for freight_rate (direct wins).
        scale_qty = _d(inputs.get("scale_qty") if inputs.get("scale_qty") is not None else cargo_qty)
        scale_rate: Decimal | None = None
        if inputs.get("scale_table"):
            from app.services.freight_terms import apply_scale_table  # local: engine stays import-light

            scale_rate = apply_scale_table(scale_qty, inputs["scale_table"])
            if not _d(inputs.get("freight_rate") or 0) and "freight_rate" not in rate_table_hits:
                freight_rate = scale_rate

        # explicit_basis already validated above; legacy auto-detect fills mode.
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
        freight_basis = _BASIS_OUTPUT[mode]
        if differentials_total or differential_rows:
            if mode in ("worldscale", "ws_differential"):
                mode = "ws_differential"
                freight_basis = _BASIS_OUTPUT[mode]
            gross_freight = base_freight + differentials_total
        else:
            gross_freight = base_freight

    # Extra freight terms (additive surcharges; absent → no-op, legacy unchanged).
    # pct_of_freight multiplies the freight base (gross after differentials,
    # before extras) — terms do not compound each other.
    extra_terms_total, extra_term_rows = (Decimal("0"), [])
    if inputs.get("extra_freight_terms"):
        from app.services.freight_terms import parse_extra_freight_terms  # local import

        # per_mt 附加费要用「已解析出的货量」：多货种模式货量在 parcel 合计里，
        # legs 模式在航段合计里，两者都没写回 inputs → 附加费恒为 0（P1-B20）。
        term_inputs = dict(inputs)
        term_inputs["cargo_qty"] = cargo_qty
        extra_terms_total, extra_term_rows = parse_extra_freight_terms(term_inputs, gross_freight)
        if extra_term_rows:
            gross_freight = gross_freight + extra_terms_total

    # (re)derive the output basis from the final mode — but never clobber a
    # multi-cargo "multi" label with the fallback per_mt placeholder.
    if freight_basis != "multi":
        freight_basis = _BASIS_OUTPUT[mode]

    address_commission = (gross_freight * address_comm_pct / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)
    brokerage = (gross_freight * brokerage_pct / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)
    commission = address_commission  # legacy output key
    net_freight = gross_freight - address_commission

    demurrage = rate_table_hits.get("demurrage_income", _d(inputs.get("demurrage_income") or 0))
    other_income = _d(inputs.get("other_income") or 0)
    surcharge_income = rate_table_hits.get("surcharge_income", Decimal("0"))
    total_revenue = net_freight + demurrage + other_income + surcharge_income

    sea_days = _d(inputs.get("sea_days") or 0)
    port_days = _d(inputs.get("port_days") or 0)
    if legs:
        # legs 只给出航段本身；顶层 sea_days/port_days 是航段之外的额外天数，
        # 以前被整体替换掉（顶层 port_days=2 直接消失 → TCE 虚高 65%）。
        # 现在两者相加：顶层值若是 legs 的汇总，请勿重复填写。
        sea_days = sea_days + leg_sea_days
        port_days = port_days + leg_port_days
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
    # 公布口径的天数（4dp）——TCE 用它做除数，财务按公布值复算才能对得上（P2-B21）
    total_days_pub = total_days.quantize(FOUR, rounding=ROUND_HALF_UP)
    if total_days_pub <= 0:
        raise ValueError(
            f"total_days must be > 0 (rounded to 4dp): total_days={total_days}. "
            "A voyage shorter than 0.00005 day makes TCE meaningless."
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
        # per-grade pricing: sea leg burns bunker_grade, port/ECA burn the ECA grade.
        # 缺 grade 时**不能**静默按 0 计价（P1-B17：整段港口/ECA 燃油被当成免费）：
        # 先回落海用油种，再回落单一价目，再回落 bunker_price，最后报错。
        def _grade_price(grade: Any, fallback_grade: Any, label: str) -> Decimal:
            def _lookup(g: Any) -> Decimal | None:
                if not g:
                    return None
                if g in bunker_prices:
                    return _num(bunker_prices[g], f"bunker_prices[{g}]")
                # 油种牌号大小写/连字符差异（VLSFO vs vlsfo）不应导致 0 价
                key = str(g).strip().upper().replace("-", "")
                for k, v in bunker_prices.items():
                    if str(k).strip().upper().replace("-", "") == key:
                        return _num(v, f"bunker_prices[{k}]")
                return None

            hit = _lookup(grade)
            if hit is not None:
                return hit
            if bunker_price > 0:
                # 显式给出的单一 bunker_price 优先（历史口径：它就是这一票的
                # 统一油价）；没有它才回落海用油种 / 唯一价目
                return bunker_price
            hit = _lookup(fallback_grade)
            if hit is not None:
                return hit
            if len(bunker_prices) == 1:
                return _num(next(iter(bunker_prices.values())), "bunker_prices")
            raise ValueError(
                f"{label} price cannot be resolved: grade {grade!r} is not in bunker_prices "
                f"({sorted(bunker_prices)}), no bunker_price given and the price list is ambiguous. "
                "Give bunker_grade / bunker_eca_grade or a single bunker_price."
            )

        sea_grade = inputs.get("bunker_grade")
        sea_price = _grade_price(sea_grade, None, "bunker_grade")
        eca_price = _grade_price(inputs.get("bunker_eca_grade"), sea_grade, "bunker_eca_grade")
        bunker_cost = sea_fuel_mt * sea_price + (port_fuel_mt + eca_fuel_mt) * eca_price
    else:
        bunker_cost = total_fuel_mt * bunker_price

    # EU ETS: CO2 = total fuel × emission factor; priced over the EU leg share.
    # eu_ets_share 是 0–1 的份额（历史口径），eu_ets_share_pct 是百分数（0–100）；
    # 两者统一换算成份额，填错单位会在入口被拒（P1-B26）。
    co2_factor = _d(inputs.get("co2_factor") or DEFAULT_CO2_FACTOR)
    if inputs.get("eu_ets_share_pct") is not None:
        eu_ets_share = _num(inputs["eu_ets_share_pct"], "eu_ets_share_pct") / Decimal("100")
    else:
        eu_ets_share = _d(inputs.get("eu_ets_share") or 0)
    ets_price = _d(inputs.get("ets_price") or 0)
    co2_mt = total_fuel_mt * co2_factor
    emissions_cost = (co2_mt * eu_ets_share * ets_price).quantize(CENT, rounding=ROUND_HALF_UP)

    port_costs = _d(inputs.get("port_costs") or 0)
    canal_costs = _d(inputs.get("canal_costs") or 0)
    other_costs = _d(inputs.get("other_costs") or 0)
    eca_extra_cost = _d(inputs.get("eca_extra_cost") or 0)
    voyage_cost = bunker_cost + port_costs + canal_costs + other_costs + eca_extra_cost + brokerage + emissions_cost

    hire_per_day = _d(inputs.get("hire_per_day") or 0)
    hire_cost = hire_per_day * total_days_pub  # reported separately, not in voyage_cost for TCE

    # Unpriced (index-linked) components — extra hire lines; absent → no-op.
    unpriced_total = Decimal("0")
    unpriced_rows: list[dict[str, Any]] = []
    if inputs.get("unpriced_components"):
        from app.services.unpriced_components import evaluate_unpriced_components  # local import

        unpriced_total, unpriced_rows = evaluate_unpriced_components(
            inputs["unpriced_components"],
            days=total_days_pub,
            db=db,
            tenant_id=tenant_id,
            default_pricing_date=_as_of(inputs),
        )
        hire_cost = hire_cost + unpriced_total

    # TCE / net_result 用**公布口径**的金额与天数计算：财务拿报告里的
    # total_revenue / voyage_cost / total_days 反算必须能得到同一个 TCE（P2-B21）。
    revenue_pub = total_revenue.quantize(CENT, rounding=ROUND_HALF_UP)
    cost_pub = voyage_cost.quantize(CENT, rounding=ROUND_HALF_UP)
    hire_pub = hire_cost.quantize(CENT, rounding=ROUND_HALF_UP)
    tce = ((revenue_pub - cost_pub) / total_days_pub).quantize(CENT, rounding=ROUND_HALF_UP)
    net_result = (revenue_pub - cost_pub - hire_pub).quantize(CENT, rounding=ROUND_HALF_UP)

    result: dict[str, Any] = {
        "gross_freight": float(gross_freight.quantize(CENT, rounding=ROUND_HALF_UP)),
        "commission": float(commission),
        "address_commission": float(address_commission),
        "brokerage": float(brokerage),
        "net_freight": float(net_freight.quantize(CENT, rounding=ROUND_HALF_UP)),
        "total_revenue": float(total_revenue.quantize(CENT, rounding=ROUND_HALF_UP)),
        "bunker_cost": float(bunker_cost.quantize(CENT, rounding=ROUND_HALF_UP)),
        "fuel_mt": float(total_fuel_mt.quantize(FOUR, rounding=ROUND_HALF_UP)),
        "co2_mt": float(co2_mt.quantize(FOUR, rounding=ROUND_HALF_UP)),
        "emissions_cost": float(emissions_cost),
        "voyage_cost": float(voyage_cost.quantize(CENT, rounding=ROUND_HALF_UP)),
        "hire_cost": float(hire_cost.quantize(CENT, rounding=ROUND_HALF_UP)),
        "sea_days": float(sea_days.quantize(FOUR, rounding=ROUND_HALF_UP)),
        "port_days": float(port_days.quantize(FOUR, rounding=ROUND_HALF_UP)),
        "total_days": float(total_days.quantize(FOUR, rounding=ROUND_HALF_UP)),
        "tce": float(tce),
        "net_result": float(net_result),
        "freight_basis": freight_basis,
        "currency": inputs.get("currency") or "USD",
    }

    # rate-table provenance — only present when a table actually contributed,
    # so legacy results stay byte-identical.
    if multi_rows:
        # per-parcel breakdown (multi-cargo estimates)
        result["cargoes"] = multi_rows
        result["cargo_count"] = len(multi_rows)
        result["parcel_qty_total"] = float(parcel_qty_total.quantize(THREE, rounding=ROUND_HALF_UP))
    if enriched_prov:
        # which master-data fields the vessel/fuel-zone/market enrichment filled
        result["inputs_enriched"] = enriched_prov
    if differential_rows:
        result["differentials"] = differential_rows
        result["differentials_total"] = float(differentials_total.quantize(CENT, rounding=ROUND_HALF_UP))
    if extra_term_rows:
        result["extra_freight_terms"] = extra_term_rows
        result["extra_freight_total"] = float(extra_terms_total.quantize(CENT, rounding=ROUND_HALF_UP))
    if unpriced_rows:
        result["unpriced_components"] = unpriced_rows
        result["unpriced_components_total"] = float(unpriced_total.quantize(CENT, rounding=ROUND_HALF_UP))
    if scale_rate is not None:
        result["scale_table_rate"] = float(scale_rate.quantize(FOUR, rounding=ROUND_HALF_UP))
        result["scale_qty"] = float(scale_qty.quantize(THREE, rounding=ROUND_HALF_UP))
    if rate_table_hits:
        result["surcharge_income"] = float(surcharge_income.quantize(CENT, rounding=ROUND_HALF_UP))
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
            # 扰动值保持 Decimal —— 写成 float 再解析会丢尾数（P2-B20）
            inp[field] = base_value + Decimal(str(d))
        else:
            inp[field] = base_value * (Decimal("1") + Decimal(str(d)))
        out = compute_estimate(inp, db=db, tenant_id=tenant_id)
        row = {"field": field, "mode": mode, "tce": out["tce"], "result": out}
        row["delta_abs" if mode == "abs" else "delta_pct"] = d
        rows.append(row)
    return rows
