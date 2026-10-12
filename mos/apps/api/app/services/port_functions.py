"""Port function codes（挂靠功能编码体系 — C2-P2）。

Canonical single-letter codes for what a port call *does* in a voyage,
aligned with common IMOS / voyage-planner style coding (L/D for cargo,
P/I/W for non-cargo calls). Kept as a module-level constant + exposed via
``GET /api/v1/meta/port-functions`` (see ``routers/meta.py``).

| Code | Meaning              | tone   |
|------|----------------------|--------|
| L    | Load                 | ok     |
| D    | Discharge            | info   |
| P    | Passage / Transit    | muted  |
| I    | Intermediate stop    | warn   |
| W    | Waypoint / Call      | default|

``tone`` maps onto the site-wide status color language
(``ok|warn|danger|info|muted`` + ``default`` = no special color) so the
gantt / schedule legend can color port-function chips without a second
lookup table.

The legacy free-text ``PortCall.purpose`` (load|discharge|bunker|transit)
is unchanged — ``function_code`` is additive and nullable. When absent,
nothing behaves differently.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

# code → labels + UI tone (stable order = catalog order)
PORT_FUNCTIONS: dict[str, dict[str, Any]] = {
    "L": {"label_en": "Load", "label_zh": "装货", "tone": "ok"},
    "D": {"label_en": "Discharge", "label_zh": "卸货", "tone": "info"},
    "P": {"label_en": "Passage / Transit", "label_zh": "过境 / 通行", "tone": "muted"},
    "I": {"label_en": "Intermediate stop", "label_zh": "中途挂靠", "tone": "warn"},
    "W": {"label_en": "Waypoint / Call", "label_zh": "航路点 / 挂靠", "tone": "default"},
}

PORT_FUNCTION_CODES: tuple[str, ...] = tuple(PORT_FUNCTIONS)


def port_functions_payload() -> list[dict[str, Any]]:
    """Catalog rows for ``GET /meta/port-functions`` (and any legend UI)."""
    return [
        {
            "code": code,
            "label_en": meta["label_en"],
            "label_zh": meta["label_zh"],
            "tone": meta["tone"],
        }
        for code, meta in PORT_FUNCTIONS.items()
    ]


def is_valid_function_code(code: str | None) -> bool:
    return code is not None and code in PORT_FUNCTIONS


def assert_function_code(code: str) -> str:
    """Validate a non-null function code; 422 INVALID_PORT_FUNCTION if unknown."""
    if code not in PORT_FUNCTIONS:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_PORT_FUNCTION",
                "message": f"Unknown function_code '{code}'",
                "allowed": list(PORT_FUNCTION_CODES),
            },
        )
    return code


def normalize_function_code(code: str | None) -> str | None:
    """Canonical form for storage: None/blank stays None (additive field);
    known codes pass through; unknown → 422 INVALID_PORT_FUNCTION.

    Case-insensitive on input (``l`` → ``L``); whitespace trimmed.
    """
    if code is None:
        return None
    if not isinstance(code, str):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_PORT_FUNCTION",
                "message": f"Unknown function_code '{code}'",
                "allowed": list(PORT_FUNCTION_CODES),
            },
        )
    cleaned = code.strip()
    if not cleaned:
        return None
    upper = cleaned.upper()
    return assert_function_code(upper)
