"""Canonical invoice type registry (发票类型补全 — IMOS coding system).

Plan codes: FRT/DEM/TCIP/TCOB/PDA/FDA/BKR/XEXP/XREV/XDIFF.

Every historical internal name (``freight``, ``demurrage``, …) remains a valid
alias so existing rows/tests keep working; new input accepts either a canonical
code or an alias. Storage stays as given (back-compat); use
:func:`normalize_invoice_type` when the canonical code is needed.
"""

from __future__ import annotations

# Canonical code → labels (UI + docs).
INVOICE_TYPE_LABELS: dict[str, dict[str, str]] = {
    "FRT": {"en": "Freight", "zh": "运费"},
    "DEM": {"en": "Demurrage / Despatch", "zh": "滞期费/速遣费"},
    "TCIP": {"en": "Time Charter Hire (In)", "zh": "期租租入租金"},
    "TCOB": {"en": "Time Charter Billing (Out)", "zh": "期租租出账单"},
    "PDA": {"en": "Port Disbursement Account", "zh": "港口使费账单"},
    "FDA": {"en": "Final Disbursement Account", "zh": "最终使费账单"},
    "BKR": {"en": "Bunker", "zh": "燃油"},
    "XEXP": {"en": "Extra Expense", "zh": "额外费用"},
    "XREV": {"en": "Reversal / Red-flush", "zh": "冲销/红冲"},
    "XDIFF": {"en": "Exchange Difference", "zh": "汇兑差异"},
}

# Historical internal names (and a few synonyms) → canonical code.
INVOICE_TYPE_ALIASES: dict[str, str] = {
    # FRT
    "freight": "FRT",
    # DEM (demurrage family; despatch is the counter-side of the same laytime claim)
    "demurrage": "DEM",
    "despatch": "DEM",
    "dispatch": "DEM",
    # TCIP — time charter hire (operator pays owner / hire statement)
    "hire": "TCIP",
    "tc_hire": "TCIP",
    "tcip": "TCIP",
    # TCOB — time charter out billing
    "tc_out_hire": "TCOB",
    "hire_out": "TCOB",
    "tcob": "TCOB",
    # PDA
    "port_disbursement": "PDA",
    "pda": "PDA",
    # FDA
    "port_da": "FDA",
    "fda": "FDA",
    # BKR
    "bunker": "BKR",
    "bkr": "BKR",
    # XEXP
    "other": "XEXP",
    "broker_commission": "XEXP",
    "commission": "XEXP",
    "carbon_allowance": "XEXP",
    "eu_ets": "XEXP",
    "xexp": "XEXP",
    # XREV
    "credit_note": "XREV",
    "reversal": "XREV",
    "red_flush": "XREV",
    "xrev": "XREV",
    # XDIFF
    "fx_difference": "XDIFF",
    "exchange_difference": "XDIFF",
    "xdiff": "XDIFF",
}

CANONICAL_INVOICE_TYPES: tuple[str, ...] = tuple(INVOICE_TYPE_LABELS.keys())

#: Every accepted input value (canonical codes + aliases), lowercased for lookup.
VALID_INVOICE_TYPES: frozenset[str] = frozenset(
    {code.lower() for code in CANONICAL_INVOICE_TYPES} | set(INVOICE_TYPE_ALIASES)
)


def normalize_invoice_type(value: str) -> str:
    """Return the canonical code for ``value`` (code or alias). Case-insensitive."""
    key = (value or "").strip().lower()
    if key in {c.lower() for c in CANONICAL_INVOICE_TYPES}:
        return key.upper()
    if key in INVOICE_TYPE_ALIASES:
        return INVOICE_TYPE_ALIASES[key]
    raise ValueError(f"Unknown invoice_type: {value!r}")


def is_valid_invoice_type(value: str) -> bool:
    return (value or "").strip().lower() in VALID_INVOICE_TYPES


def invoice_type_label(value: str) -> dict[str, str] | None:
    """Label map for a code or alias; ``None`` when unknown."""
    try:
        code = normalize_invoice_type(value)
    except ValueError:
        return None
    return INVOICE_TYPE_LABELS.get(code)


def invalid_invoice_type_detail(value: str) -> dict:
    """422 detail payload listing every valid type (codes + aliases)."""
    return {
        "code": "INVALID_INVOICE_TYPE",
        "message": (
            f"invoice_type {value!r} is not valid; use a canonical code "
            f"({', '.join(CANONICAL_INVOICE_TYPES)}) or a legacy alias "
            f"({', '.join(sorted(INVOICE_TYPE_ALIASES))})"
        ),
        "canonical_codes": list(CANONICAL_INVOICE_TYPES),
        "valid_aliases": sorted(INVOICE_TYPE_ALIASES),
        "valid_types": sorted({*CANONICAL_INVOICE_TYPES, *INVOICE_TYPE_ALIASES}),
    }
