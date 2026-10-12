"""Extra freight terms + scale tables (比例运费表).

Deliberately NOT in ``services/cargo_terms.py`` (owned elsewhere) — this module
owns the voyage-estimate freight add-ons and the quantity-tiered rate lookup.

**Scale table** — tiered per-mt rates by cargo quantity::

    apply_scale_table(qty, [
        {"qty_from": 0,     "qty_to": 30000, "rate": 20.0},
        {"qty_from": 30000, "qty_to": 60000, "rate": 18.5},
        {"qty_from": 60000, "qty_to": null,  "rate": 17.0},   # open-ended top tier
    ])

Tier selection is half-open ``[qty_from, qty_to)``: ``qty_from`` is inclusive,
``qty_to`` is exclusive and belongs to the next tier. ``qty_to`` null/omitted
marks the unbounded top tier (must be last). A quantity that falls in a gap or
below the first tier raises ValueError; overlapping / unsorted / empty tables
raise ValueError (API layers surface 422).

**Extra freight terms** — additive surcharges appended to freight::

    inputs["extra_freight_terms"] = [
        {"term": "BAF",  "basis": "per_mt",          "rate": 2.5},
        {"term": "ISPS", "basis": "per_lump",        "rate": 1500},
        {"term": "War",  "basis": "pct_of_freight",  "rate": 1.25,
         "applies_when": {"cargo_type": "coal"}},
    ]

- ``per_mt`` → rate × cargo_qty (mt)
- ``per_lump`` → rate (flat amount)
- ``pct_of_freight`` → rate% of the freight base (gross freight after
  differentials, BEFORE extra terms — terms do not compound)
- ``applies_when`` is an optional predicate dict matched against the estimate
  inputs: a plain key/value pair must match exactly; keys ending ``_min`` /
  ``_max`` are numeric bounds on the named field (e.g. ``cargo_qty_min``).
  Terms whose predicate fails are skipped silently (omitted from rows/total).

Both are additive: absent/empty inputs leave the caller's legacy output
byte-identical. All arithmetic is Decimal with ROUND_HALF_UP at 2dp.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

TWOPLACES = Decimal("0.01")

_TERM_BASIS_ALIASES: dict[str, str] = {
    "per_mt": "per_mt",
    "per-mt": "per_mt",
    "permt": "per_mt",
    "mt": "per_mt",
    "per_lump": "per_lump",
    "per-lump": "per_lump",
    "per_lump_sum": "per_lump",
    "lump": "per_lump",
    "lump_sum": "per_lump",
    "lumpsum": "per_lump",
    "flat": "per_lump",
    "pct_of_freight": "pct_of_freight",
    "pct-of-freight": "pct_of_freight",
    "pct": "pct_of_freight",
    "percent_of_freight": "pct_of_freight",
    "pct_freight": "pct_of_freight",
}


def _d(v: Any) -> Decimal:
    if v is None:
        return Decimal("0")
    return Decimal(str(v))


# ---- scale table ---------------------------------------------------------


def validate_scale_table(rows: Any) -> list[dict[str, Any]]:
    """Validate + normalize a scale table. Returns sorted row dicts.

    Raises ValueError on empty/malformed tables, negative bounds, overlapping
    tiers, an unbounded tier that is not last, or tiers with qty_from >= qty_to.
    """
    if isinstance(rows, (str, bytes, dict)) or not isinstance(rows, (list, tuple)):
        raise ValueError(f"scale_table must be a list of tier rows, got {type(rows).__name__}")
    if not rows:
        raise ValueError("scale_table must not be empty")
    parsed: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"scale_table[{i}] must be an object, got {type(row).__name__}")
        if row.get("qty_from") is None:
            raise ValueError(f"scale_table[{i}].qty_from is required")
        if row.get("rate") is None:
            raise ValueError(f"scale_table[{i}].rate is required")
        qty_from = _d(row["qty_from"])
        if qty_from < 0:
            raise ValueError(f"scale_table[{i}].qty_from must be >= 0, got {qty_from}")
        qty_to_raw = row.get("qty_to")
        qty_to = None if qty_to_raw is None else _d(qty_to_raw)
        if qty_to is not None and qty_to <= qty_from:
            raise ValueError(
                f"scale_table[{i}].qty_to must be > qty_from, got "
                f"qty_from={qty_from}, qty_to={qty_to}"
            )
        rate = _d(row["rate"])
        if rate < 0:
            raise ValueError(f"scale_table[{i}].rate must be >= 0, got {rate}")
        parsed.append({"qty_from": qty_from, "qty_to": qty_to, "rate": rate})

    parsed.sort(key=lambda r: r["qty_from"])
    for i in range(1, len(parsed)):
        prev, cur = parsed[i - 1], parsed[i]
        if prev["qty_to"] is None:
            raise ValueError(
                "scale_table: the open-ended tier (qty_to null) must be last; "
                f"another tier starts at {cur['qty_from']}"
            )
        if cur["qty_from"] < prev["qty_to"]:
            raise ValueError(
                "scale_table: overlapping tiers — "
                f"[{prev['qty_from']}, {prev['qty_to']}) and "
                f"[{cur['qty_from']}, {cur['qty_to']})"
            )
    return parsed


def apply_scale_table(qty: Any, rows: Any) -> Decimal:
    """Return the per-mt rate for ``qty`` from a tiered scale table (纯函数).

    Tier selection is half-open [qty_from, qty_to): qty == qty_from selects the
    tier, qty == qty_to selects the next tier. The top tier may leave qty_to
    null/omitted (unbounded). Raises ValueError when the table is invalid or
    when ``qty`` falls outside every tier (below the first tier, or in a gap).
    """
    qty_d = _d(qty)
    if qty_d < 0:
        raise ValueError(f"scale table quantity must be >= 0, got {qty_d}")
    tiers = validate_scale_table(rows)
    for tier in tiers:
        if qty_d < tier["qty_from"]:
            continue
        if tier["qty_to"] is None or qty_d < tier["qty_to"]:
            return tier["rate"]
    raise ValueError(
        f"scale table has no tier covering qty={qty_d} "
        f"(first tier starts at {tiers[0]['qty_from']})"
    )


# ---- extra freight terms -------------------------------------------------


def _applies_when_ok(pred: Any, context: dict[str, Any]) -> bool:
    """Evaluate an applies_when predicate dict against the estimate inputs."""
    if pred is None:
        return True
    if not isinstance(pred, dict):
        raise ValueError(f"applies_when must be an object, got {type(pred).__name__}")
    for key, expected in pred.items():
        if key.endswith("_min"):
            field = key[: -len("_min")]
            actual = context.get(field)
            if actual is None or _d(actual) < _d(expected):
                return False
        elif key.endswith("_max"):
            field = key[: -len("_max")]
            actual = context.get(field)
            if actual is None or _d(actual) > _d(expected):
                return False
        else:
            if context.get(key) != expected:
                return False
    return True


def parse_extra_freight_terms(
    inputs: dict[str, Any], freight_base: Decimal
) -> tuple[Decimal, list[dict[str, Any]]]:
    """Parse ``inputs["extra_freight_terms"]`` → (total, rows).

    ``freight_base`` is the freight the ``pct_of_freight`` basis multiplies —
    gross freight after differentials and before these extras (non-compounding).
    Absent/empty input → (0, []) so legacy results stay byte-identical.
    """
    raw = inputs.get("extra_freight_terms")
    if not raw:
        return Decimal("0"), []
    if isinstance(raw, (str, bytes, dict)) or not isinstance(raw, (list, tuple)):
        raise ValueError("extra_freight_terms must be a list of term objects")
    cargo_qty = _d(inputs.get("cargo_qty") or 0)
    total = Decimal("0")
    rows: list[dict[str, Any]] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(
                f"extra_freight_terms[{i}] must be an object with term/basis/rate, "
                f"got {type(entry).__name__}"
            )
        if not _applies_when_ok(entry.get("applies_when"), inputs):
            continue
        term = entry.get("term")
        if not term or (isinstance(term, str) and not str(term).strip()):
            raise ValueError(f"extra_freight_terms[{i}].term is required")
        basis_raw = str(entry.get("basis") or "").strip().lower()
        basis = _TERM_BASIS_ALIASES.get(basis_raw)
        if not basis:
            raise ValueError(
                f"extra_freight_terms[{i}].basis must be per_mt|per_lump|pct_of_freight, "
                f"got {entry.get('basis')!r}"
            )
        rate_raw = entry.get("rate")
        if rate_raw is None or (isinstance(rate_raw, str) and not str(rate_raw).strip()):
            raise ValueError(f"extra_freight_terms[{i}].rate is required")
        rate = _d(rate_raw)
        if basis == "per_mt":
            value = rate * cargo_qty
        elif basis == "per_lump":
            value = rate
        else:  # pct_of_freight
            value = (freight_base * rate / Decimal("100")).quantize(
                TWOPLACES, rounding=ROUND_HALF_UP
            )
        if basis != "pct_of_freight":
            value = value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        total += value
        row: dict[str, Any] = {
            "term": str(term),
            "basis": basis,
            "rate": float(rate),
            "value": float(value),
        }
        rows.append(row)
    return total.quantize(TWOPLACES, rounding=ROUND_HALF_UP), rows
