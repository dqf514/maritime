"""Index-linked (unpriced) component pricing — 指数联动定价.

An *unpriced component* is a hire/TC element whose money value is settled by a
market index rather than a flat rate. Components are ADDITIVE inputs: they are
resolved into extra hire lines and appended to the estimate breakdown only when
the ``unpriced_components`` array is present; absent/empty → the caller stays on
the legacy path with byte-identical output.

Component spec (all amounts Decimal, deterministic ROUND_HALF_UP)::

    {
      "name": "BSI 30-day adjust",        # required label for the breakdown line
      "formula": "rolling_index",         # rolling_index | range | level | offset
      "index_name": "BSI",                # MarketQuote symbol (optional when
                                          # observations are inline, or formula=offset
                                          # with base_value)
      "observations": [                   # explicit series (wins over db lookup);
        {"date": "2026-01-08", "value": 1200}, ...
      ],
      "pricing_date": "2026-01-10",       # as-of date; default = inputs.rate_as_of,
                                          # else max obs date, else today
      "window_days": 30,                  # trailing window for rolling_index/range
                                          # (default 30, must be > 0)
      "range_agg": "max",                 # range selector: max | min (default max)
      "base_value": 1000,                 # offset anchor (or fallback spot)
      "offset_value": -250,               # required for formula=offset
      "floor": 800,                       # clamp on the resolved index value
      "cap": 2000,                        # clamp on the resolved index value
      "factor": 1,                        # unit conversion index → money (default 1)
      "basis": "per_day"                  # per_day (× days) | per_lump (flat)
    }

Formula semantics (window = ``(pricing_date - window_days, pricing_date]``, i.e.
the observation exactly ``window_days`` back is excluded, the observation on the
pricing date is included):

- ``rolling_index`` — arithmetic mean of the window observations.
- ``range`` — the window's max (or min when ``range_agg="min"``).
- ``level`` — the spot at the pricing date: the observation with the greatest
  date ≤ pricing_date (mean if several entries share that date).
- ``offset`` — ``base_value`` (or the ``level`` spot when base_value is absent)
  plus ``offset_value``. Requires ``offset_value``.

Then ``value = clamp(raw, floor, cap)``, ``rate = value * factor`` and
``amount = rate * days`` (basis=per_day) or ``amount = rate`` (per_lump).
The resolved value is already in index units; ``factor`` converts to money
(e.g. index points → USD/day). Values are quantized half-up at 2dp on the
amount and 4dp on the raw value.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

TWOPLACES = Decimal("0.01")
FOUR = Decimal("0.0001")

_FORMULAS = ("rolling_index", "range", "level", "offset")
_BASES = ("per_day", "per_lump")
_RANGE_AGGS = ("max", "min")
DEFAULT_WINDOW_DAYS = 30


def _d(v: Any) -> Decimal:
    if v is None:
        return Decimal("0")
    return Decimal(str(v))


def _as_date(raw: Any) -> date:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        raise ValueError(f"invalid date {raw!r}, expected YYYY-MM-DD") from None


def _parse_observations(raw: Any, idx: int) -> list[tuple[date, Decimal]]:
    """Normalize an inline observation list to sorted (date, value) pairs."""
    if isinstance(raw, (str, bytes, dict)) or not isinstance(raw, (list, tuple)):
        raise ValueError(f"unpriced_components[{idx}].observations must be a list")
    out: list[tuple[date, Decimal]] = []
    for j, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(
                f"unpriced_components[{idx}].observations[{j}] must be "
                f"{{date, value}}, got {type(entry).__name__}"
            )
        if entry.get("date") is None:
            raise ValueError(f"unpriced_components[{idx}].observations[{j}].date is required")
        if entry.get("value") is None:
            raise ValueError(f"unpriced_components[{idx}].observations[{j}].value is required")
        out.append((_as_date(entry["date"]), _d(entry["value"])))
    out.sort(key=lambda t: t[0])
    return out


def _load_market_observations(
    index_name: str, lookback_from: date, lookback_days: int, db: Any, tenant_id: Any
) -> list[tuple[date, Decimal]]:
    """Tenant-scoped MarketQuote series lookup (explicit observations win)."""
    if db is None or tenant_id is None:
        raise ValueError(
            f"unpriced component {index_name!r} has no inline observations and no "
            "db/tenant_id to resolve a market series from"
        )
    from sqlalchemy import select

    from app.models_domain import MarketQuote  # local import: keep engine import-light

    since = date.fromordinal(lookback_from.toordinal() - max(lookback_days, 1) - 1)
    rows = db.scalars(
        select(MarketQuote)
        .where(
            MarketQuote.tenant_id == tenant_id,
            MarketQuote.symbol == index_name,
            MarketQuote.quote_date >= since,
            MarketQuote.quote_date <= lookback_from,
        )
        .order_by(MarketQuote.quote_date)
    ).all()
    return [(r.quote_date, _d(r.value)) for r in rows]


def _window_obs(
    obs: list[tuple[date, Decimal]], pricing_date: date, window_days: int
) -> list[Decimal]:
    """Trailing window (pricing_date - window_days, pricing_date] values."""
    lower = date.fromordinal(pricing_date.toordinal() - window_days)
    return [v for (d, v) in obs if lower < d <= pricing_date]


def _spot_obs(obs: list[tuple[date, Decimal]], pricing_date: date) -> Decimal | None:
    """Value at the greatest date ≤ pricing_date (mean if several on that date)."""
    candidates = [(d, v) for (d, v) in obs if d <= pricing_date]
    if not candidates:
        return None
    latest = max(d for d, _ in candidates)
    same_day = [v for (d, v) in candidates if d == latest]
    return sum(same_day) / Decimal(len(same_day))


def resolve_component(
    spec: dict[str, Any],
    *,
    days: Decimal,
    db: Any = None,
    tenant_id: Any = None,
    default_pricing_date: date | None = None,
) -> dict[str, Any]:
    """Resolve one component spec to a breakdown row (pure aside from db lookup).

    Raises ValueError on malformed specs (API layers map to 422).
    """
    if not isinstance(spec, dict):
        raise ValueError(f"unpriced component must be an object, got {type(spec).__name__}")
    name = spec.get("name")
    if not name or (isinstance(name, str) and not str(name).strip()):
        raise ValueError("unpriced_components[].name is required")
    formula = str(spec.get("formula") or "").strip().lower()
    if formula not in _FORMULAS:
        raise ValueError(
            f"unpriced component {name!r}: formula must be "
            f"{'|'.join(_FORMULAS)}, got {spec.get('formula')!r}"
        )

    basis_raw = str(spec.get("basis") or "per_day").strip().lower()
    if basis_raw not in _BASES:
        raise ValueError(
            f"unpriced component {name!r}: basis must be per_day|per_lump, got {spec.get('basis')!r}"
        )
    basis = basis_raw

    window_raw = spec.get("window_days")
    window_days = int(_d(window_raw)) if window_raw is not None else DEFAULT_WINDOW_DAYS
    if window_days <= 0:
        raise ValueError(f"unpriced component {name!r}: window_days must be > 0, got {window_raw!r}")

    range_agg = str(spec.get("range_agg") or "max").strip().lower()
    if range_agg not in _RANGE_AGGS:
        raise ValueError(
            f"unpriced component {name!r}: range_agg must be max|min, got {spec.get('range_agg')!r}"
        )

    index_name = spec.get("index_name")
    if index_name is not None:
        index_name = str(index_name).strip() or None

    inline_obs = spec.get("observations")
    if inline_obs:
        obs = _parse_observations(inline_obs, 0)
    elif index_name:
        # lookback wide enough for the window (or a full year for spot formulas)
        lookback = window_days if formula in ("rolling_index", "range") else 366
        anchor_for_load = None
        if spec.get("pricing_date") is not None:
            anchor_for_load = _as_date(spec["pricing_date"])
        elif default_pricing_date is not None:
            anchor_for_load = default_pricing_date
        else:
            anchor_for_load = date.today()
        obs = _load_market_observations(index_name, anchor_for_load, lookback, db, tenant_id)
    else:
        obs = []

    # pricing date resolution: component → caller default (rate_as_of) →
    # max obs date → today. The caller default is an explicit estimate-level
    # as-of date and outranks "latest known observation".
    if spec.get("pricing_date") is not None:
        pricing_date = _as_date(spec["pricing_date"])
    elif default_pricing_date is not None:
        pricing_date = default_pricing_date
    elif obs:
        pricing_date = max(d for d, _ in obs)
    else:
        pricing_date = date.today()

    has_base = spec.get("base_value") is not None
    has_offset = spec.get("offset_value") is not None

    if formula == "rolling_index":
        values = _window_obs(obs, pricing_date, window_days)
        if not values:
            raise ValueError(
                f"unpriced component {name!r}: rolling_index has no observations in "
                f"window ({window_days} days ending {pricing_date.isoformat()})"
            )
        raw = sum(values) / Decimal(len(values))
    elif formula == "range":
        values = _window_obs(obs, pricing_date, window_days)
        if not values:
            raise ValueError(
                f"unpriced component {name!r}: range has no observations in "
                f"window ({window_days} days ending {pricing_date.isoformat()})"
            )
        raw = max(values) if range_agg == "max" else min(values)
    elif formula == "level":
        raw = _spot_obs(obs, pricing_date)
        if raw is None:
            if has_base:
                raw = _d(spec["base_value"])
            else:
                raise ValueError(
                    f"unpriced component {name!r}: level has no observation on or "
                    f"before {pricing_date.isoformat()}"
                )
    else:  # offset
        if not has_offset:
            raise ValueError(f"unpriced component {name!r}: offset requires offset_value")
        if has_base:
            anchor = _d(spec["base_value"])
        else:
            anchor = _spot_obs(obs, pricing_date)
            if anchor is None:
                raise ValueError(
                    f"unpriced component {name!r}: offset without base_value needs an "
                    f"observation on or before {pricing_date.isoformat()}"
                )
        raw = anchor + _d(spec["offset_value"])

    value = raw
    if spec.get("floor") is not None and value < _d(spec["floor"]):
        value = _d(spec["floor"])
    if spec.get("cap") is not None and value > _d(spec["cap"]):
        value = _d(spec["cap"])

    factor = _d(spec.get("factor") if spec.get("factor") is not None else 1)
    rate = value * factor
    amount = (rate * days) if basis == "per_day" else rate
    amount = amount.quantize(TWOPLACES, rounding=ROUND_HALF_UP)

    row: dict[str, Any] = {
        "name": str(name),
        "formula": formula,
        "basis": basis,
        "value": float(value.quantize(FOUR, rounding=ROUND_HALF_UP)),
        "rate": float(rate.quantize(FOUR, rounding=ROUND_HALF_UP)),
        "amount": float(amount),
    }
    if value != raw:
        row["raw_value"] = float(raw.quantize(FOUR, rounding=ROUND_HALF_UP))
    if index_name:
        row["index_name"] = index_name
    if formula in ("rolling_index", "range"):
        row["window_days"] = window_days
        if formula == "range":
            row["range_agg"] = range_agg
    row["pricing_date"] = pricing_date.isoformat()
    return row


def evaluate_unpriced_components(
    components: Any,
    *,
    days: Decimal,
    db: Any = None,
    tenant_id: Any = None,
    default_pricing_date: date | None = None,
) -> tuple[Decimal, list[dict[str, Any]]]:
    """Resolve a component list → (total_amount, rows). Empty/None → (0, [])."""
    if not components:
        return Decimal("0"), []
    if isinstance(components, (str, bytes, dict)) or not isinstance(components, (list, tuple)):
        raise ValueError("unpriced_components must be a list of component objects")
    total = Decimal("0")
    rows: list[dict[str, Any]] = []
    for spec in components:
        row = resolve_component(
            spec,
            days=days,
            db=db,
            tenant_id=tenant_id,
            default_pricing_date=default_pricing_date,
        )
        total += Decimal(str(row["amount"]))
        rows.append(row)
    return total.quantize(TWOPLACES, rounding=ROUND_HALF_UP), rows
