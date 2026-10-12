"""Optimistic locking — concurrent-edit detection (``409 STALE_WRITE``).

A client that read a record and then PATCHes it after someone else changed it
gets ``409 {"code":"STALE_WRITE", ...}`` instead of silently overwriting.
Clients that don't opt in (no ``expected_updated_at`` field) keep today's
behaviour — fully backward compatible.

Design notes
------------
- ``expected_updated_at`` is optional: absent → no check.
- Comparison uses **second precision** (truncate both sides): SQLite stores
  ``CURRENT_TIMESTAMP`` at second granularity and clients round-trip ISO
  strings with mixed sub-second digits — whole seconds are the reliable
  common denominator. Both sides are normalised to naive UTC first (same
  convention as ``routers._finance_common._as_utc_naive``).
- Missing data is **permissive**: if the row has no ``updated_at`` attribute
  or the value is NULL (legacy rows that never got stamped), the check is
  skipped and nothing is logged. Documented choice — do not block writes on
  data we don't have.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException


def _as_utc_naive(dt: datetime) -> datetime:
    """Normalise to naive UTC — mirrors routers._finance_common._as_utc_naive."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _whole_seconds(dt: datetime) -> datetime:
    """Truncate to whole seconds (drop sub-second component)."""
    return dt.replace(microsecond=0)


def _parse_expected(expected: str | datetime) -> datetime:
    if isinstance(expected, datetime):
        return expected
    s = str(expected).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_UPDATED_AT",
                "message": f"expected_updated_at is not a valid ISO datetime: {expected!r}",
            },
        ) from exc


def assert_fresh(row, expected: str | datetime | None) -> None:
    """Raise ``409 STALE_WRITE`` if ``row.updated_at`` has moved past ``expected``.

    No-op when:

    - ``expected`` is None (client did not opt in — back-compat), or
    - the row has no ``updated_at`` attribute, or
    - ``row.updated_at`` is None (legacy rows — permissive on missing data).
    """
    if expected is None:
        return
    current = getattr(row, "updated_at", None)
    if current is None:
        return
    expected_dt = _whole_seconds(_as_utc_naive(_parse_expected(expected)))
    current_dt = _whole_seconds(_as_utc_naive(current))
    if expected_dt == current_dt:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "code": "STALE_WRITE",
            "message": (
                "This record was modified since you loaded it. "
                "Reload it and re-apply your changes."
            ),
            "current": current.isoformat(),
        },
    )
