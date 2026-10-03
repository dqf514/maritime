"""Rate table resolution — Phase 4 运价/费率表查找引擎.

Lookup semantics (dimension specificity cascade):

1. Only rows of an *active*, non-deleted table inside its ``valid_from``/
   ``valid_to`` window participate (``as_of`` defaults to today).
2. A row matches a lookup when every non-wildcard value in ``row.dims``
   equals the corresponding lookup value (``None`` / ``"*"`` act as
   wildcards; a row with empty ``dims`` always matches — the catch-all).
3. Among matching rows the winner is the most *specific*: the row with the
   largest number of concrete (non-wildcard) matched dims; ties break on
   higher ``priority``, then earliest ``created_at`` for determinism.

``freight_matrix_lookup`` is the 2-D (load_port, disch_port) convenience
wrapper; ``surcharge_lookup`` resolves route/cargo surcharges; ``resolve_pricing``
resolves every table referenced by a :class:`PricingTemplate` at once.

All functions are tenant-scoped (``tenant_id`` filter on every query).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_rates import PricingTemplate, RateTable, RateTableRow
from app.pagination import envelope, paginate
from app.services.tenant_guard import scoped_get, scoped_query

_WILDCARDS = (None, "", "*")


def _d(v: Any) -> Decimal:
    return Decimal(str(v))


def _as_uuid(v: Any) -> uuid.UUID | None:
    """Coerce JSON string ids to UUID; invalid values become ``None`` (treated as not found)."""
    if isinstance(v, uuid.UUID):
        return v
    try:
        return uuid.UUID(str(v))
    except (ValueError, TypeError, AttributeError):
        return None


def _norm_dims(dims: dict | None) -> dict:
    """Canonical dims form for storage/compare: drop empty values, stringify keys."""
    out: dict[str, Any] = {}
    for k, v in (dims or {}).items():
        if v is None:
            continue
        out[str(k)] = v
    return out


def _is_wildcard(v: Any) -> bool:
    return v in _WILDCARDS


def _dims_signature(dims: dict) -> tuple:
    return tuple(sorted((str(k), str(v)) for k, v in (dims or {}).items()))


def _table_in_effect(table: RateTable, as_of: date | None) -> bool:
    if not table.is_active or table.deleted_at is not None:
        return False
    d = as_of or date.today()
    if table.valid_from and d < table.valid_from:
        return False
    if table.valid_to and d > table.valid_to:
        return False
    return True


def _row_specificity(row_dims: dict, lookup: dict) -> int | None:
    """Concrete matched-dim count, or ``None`` when the row does not match.

    Wildcard row values match anything but do not add specificity.
    """
    spec = 0
    for k, v in (row_dims or {}).items():
        if _is_wildcard(v):
            continue
        if lookup.get(k) != v:
            return None
        spec += 1
    return spec


def _pick_winner(rows: list[RateTableRow], dims: dict) -> RateTableRow | None:
    best: RateTableRow | None = None
    best_key: tuple | None = None
    for row in rows:
        spec = _row_specificity(row.dims or {}, dims)
        if spec is None:
            continue
        key = (spec, row.priority or 0)
        if best is None or best_key is None or key > best_key:
            best, best_key = row, key
        elif key == best_key and best is not None:
            # full tie: deterministic pick — smallest dims signature wins
            # (avoids naive/aware datetime comparison across backends)
            if _dims_signature(row.dims or {}) < _dims_signature(best.dims or {}):
                best = row
    return best


# —— core lookups ——


def resolve_rate(
    db: Session,
    tenant_id: uuid.UUID,
    rate_table_id: uuid.UUID,
    dims: dict,
    *,
    as_of: date | None = None,
) -> Decimal | None:
    """Find the best matching row value for ``dims`` in a rate table.

    Returns ``None`` when the table is missing/inactive/out of window or no
    row matches. Specificity cascade: most concrete matching dims win, then
    highest ``priority``.
    """
    row = resolve_rate_row(db, tenant_id, rate_table_id, dims, as_of=as_of)
    return row.value if row is not None else None


def resolve_rate_row(
    db: Session,
    tenant_id: uuid.UUID,
    rate_table_id: Any,
    dims: dict,
    *,
    as_of: date | None = None,
) -> RateTableRow | None:
    """Like :func:`resolve_rate` but returns the winning row (value/unit/notes)."""
    tid = _as_uuid(rate_table_id)
    if tid is None:
        return None
    table = scoped_get(db, RateTable, tid, tenant_id)
    if table is None or not _table_in_effect(table, as_of):
        return None
    lookup = _norm_dims(dims)
    rows = db.scalars(
        scoped_query(db, RateTableRow, tenant_id).where(RateTableRow.rate_table_id == tid)
    ).all()
    return _pick_winner(list(rows), lookup)


def freight_matrix_lookup(
    db: Session,
    tenant_id: uuid.UUID,
    table_id: uuid.UUID,
    load_port: str,
    disch_port: str,
    *,
    as_of: date | None = None,
) -> Decimal | None:
    """2-D freight matrix lookup: ``{"load_port", "disch_port"}`` dims.

    Less specific rows (single-port, catch-all) cascade in as fallbacks.
    """
    return resolve_rate(
        db,
        tenant_id,
        table_id,
        {"load_port": load_port, "disch_port": disch_port},
        as_of=as_of,
    )


def surcharge_lookup(
    db: Session,
    tenant_id: uuid.UUID,
    table_id: uuid.UUID,
    route: str | None,
    cargo_type: str | None,
    *,
    as_of: date | None = None,
) -> Decimal:
    """Route/cargo surcharge lookup — returns ``Decimal("0")`` when unresolvable."""
    dims: dict[str, Any] = {}
    if route:
        dims["route"] = route
    if cargo_type:
        dims["cargo_type"] = cargo_type
    val = resolve_rate(db, tenant_id, table_id, dims, as_of=as_of)
    return val if val is not None else Decimal("0")


# —— row CRUD support ——


def list_rate_rows(
    db: Session,
    tenant_id: uuid.UUID,
    rate_table_id: Any,
    *,
    dim_filters: dict | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Paginated rows of a rate table (envelope protocol U1).

    ``dim_filters`` keeps rows whose ``dims`` *subset-match* the filter
    (row dim value equals filter value, or row value is a wildcard).
    """
    tid = _as_uuid(rate_table_id)
    if tid is None:
        return envelope([], 0, limit, offset)
    stmt = scoped_query(db, RateTableRow, tenant_id).where(RateTableRow.rate_table_id == tid)
    rows_all = list(db.scalars(stmt.order_by(RateTableRow.priority.desc(), RateTableRow.created_at)).all())
    filters = _norm_dims(dim_filters)
    if filters:
        kept = []
        for r in rows_all:
            rd = r.dims or {}
            if all(k in rd and (_is_wildcard(rd[k]) or rd[k] == v) for k, v in filters.items()):
                kept.append(r)
        rows_all = kept
        total = len(rows_all)
        page = rows_all[offset : offset + limit]
        return envelope([_row_out(r) for r in page], total, limit, offset)
    stmt = stmt.order_by(RateTableRow.priority.desc(), RateTableRow.created_at)
    rows, total = paginate(db, stmt, limit, offset)
    return envelope([_row_out(r) for r in rows], total, limit, offset)


def _row_out(r: RateTableRow) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "rate_table_id": str(r.rate_table_id),
        "dims": r.dims or {},
        "value": float(r.value),
        "unit": r.unit,
        "priority": r.priority,
        "notes": r.notes,
    }


def upsert_rate_row(
    db: Session,
    tenant_id: uuid.UUID,
    rate_table_id: Any,
    dims: dict,
    value: Any,
    *,
    unit: str | None = None,
    priority: int = 0,
    notes: str | None = None,
) -> RateTableRow | None:
    """Create or update the row with this exact ``dims`` signature.

    Returns the row, or ``None`` when the parent table is not accessible.
    """
    tid = _as_uuid(rate_table_id)
    if tid is None:
        return None
    table = scoped_get(db, RateTable, tid, tenant_id)
    if table is None:
        return None
    dims_n = _norm_dims(dims)
    sig = _dims_signature(dims_n)
    existing = db.scalars(
        scoped_query(db, RateTableRow, tenant_id).where(RateTableRow.rate_table_id == tid)
    ).all()
    row = next((r for r in existing if _dims_signature(r.dims or {}) == sig), None)
    if row is None:
        row = RateTableRow(
            tenant_id=tenant_id,
            rate_table_id=tid,
            dims=dims_n,
            value=_d(value),
            unit=unit,
            priority=priority,
            notes=notes,
        )
        db.add(row)
    else:
        row.dims = dims_n
        row.value = _d(value)
        row.unit = unit
        row.priority = priority
        row.notes = notes
        row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


# —— pricing template ——


def resolve_pricing(
    db: Session,
    tenant_id: uuid.UUID,
    template_id: uuid.UUID,
    context: dict,
    *,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Resolve every rate table a pricing template references.

    ``context`` carries lookup dims (``load_port``/``disch_port``/``route``/
    ``cargo_type``/...) and optional scalars (``cargo_qty``, ``demurrage_days``)
    used to derive amounts. Returns::

        {
          "template_id", "template_name", "rules",
          "rates": {role: {"rate", "unit", "currency"} | None},
          "amounts": {role: derived amount when computable},
        }
    """
    template = scoped_get(db, PricingTemplate, _as_uuid(template_id), tenant_id) if _as_uuid(template_id) else None
    if template is None:
        raise LookupError(f"pricing template {template_id} not found")
    ctx = dict(context or {})
    lookup_dims = _norm_dims(
        {k: ctx.get(k) for k in ("load_port", "disch_port", "from_port", "to_port", "route", "cargo_type", "vessel_class")}
    )
    rates: dict[str, Any] = {}
    amounts: dict[str, Any] = {}
    for role, raw_tid in (template.rate_table_refs or {}).items():
        tid = _as_uuid(raw_tid)
        if tid is None:
            rates[role] = None
            continue
        table = scoped_get(db, RateTable, tid, tenant_id)
        if table is None or not _table_in_effect(table, as_of):
            rates[role] = None
            continue
        row = _pick_winner(
            list(
                db.scalars(
                    scoped_query(db, RateTableRow, tenant_id).where(RateTableRow.rate_table_id == tid)
                ).all()
            ),
            lookup_dims,
        )
        if row is None:
            rates[role] = None
            continue
        rates[role] = {"rate": float(row.value), "unit": row.unit, "currency": table.currency}
        amount = _derive_amount(role, row, ctx)
        if amount is not None:
            amounts[role] = float(amount)
    return {
        "template_id": str(template.id),
        "template_name": template.name,
        "rules": template.rules or {},
        "rates": rates,
        "amounts": amounts,
    }


def _derive_amount(role: str, row: RateTableRow, ctx: dict) -> Decimal | None:
    """Best-effort amount from a resolved rate × context scalar."""
    unit = (row.unit or "").lower()
    if role in ("freight", "surcharge", "bunker_surcharge") or unit in ("per_mt", "per_mt_cargo"):
        qty = ctx.get("cargo_qty")
        if qty is None:
            return None
        return (_d(row.value) * _d(qty)).quantize(Decimal("0.01"))
    if role in ("demurrage", "demurrage_rate") or unit == "per_day":
        days = ctx.get("demurrage_days")
        if days is None:
            return None
        return (_d(row.value) * _d(days)).quantize(Decimal("0.01"))
    if unit == "lumpsum":
        return _d(row.value)
    return None


# —— validation ——


def validate_rate_table(db: Session, tenant_id: uuid.UUID, table_id: Any) -> list[str]:
    """Gap/conflict audit for a rate table — returns human-readable issues."""
    tid = _as_uuid(table_id)
    table = scoped_get(db, RateTable, tid, tenant_id) if tid else None
    if table is None:
        return ["rate table not found"]
    issues: list[str] = []
    if table.valid_from and table.valid_to and table.valid_from > table.valid_to:
        issues.append(f"valid_from ({table.valid_from}) is after valid_to ({table.valid_to})")
    rows = list(
        db.scalars(
            scoped_query(db, RateTableRow, tenant_id).where(RateTableRow.rate_table_id == tid)
        ).all()
    )
    if not rows:
        issues.append("table has no rows — every lookup will fail")
        return issues

    by_sig: dict[tuple, list[RateTableRow]] = {}
    for r in rows:
        by_sig.setdefault(_dims_signature(r.dims or {}), []).append(r)
    for sig, group in by_sig.items():
        if len(group) > 1:
            keys = ", ".join(f"{k}={v}" for k, v in sig) or "(catch-all)"
            issues.append(f"duplicate rows for dims [{keys}] — {len(group)} rows share this signature")
        values = {_d(r.value) for r in group}
        if len(group) > 1 and len(values) > 1:
            keys = ", ".join(f"{k}={v}" for k, v in sig) or "(catch-all)"
            issues.append(f"conflicting values for dims [{keys}]: {sorted(str(v) for v in values)}")
        for r in group:
            if (r.priority or 0) == 0 and len(group) > 1:
                keys = ", ".join(f"{k}={v}" for k, v in sig) or "(catch-all)"
                issues.append(f"ambiguous dims [{keys}] rows share priority 0 — raise one row's priority")

    for r in rows:
        if r.value is not None and r.value < 0:
            keys = ", ".join(f"{k}={v}" for k, v in (r.dims or {}).items()) or "(catch-all)"
            issues.append(f"negative value {r.value} on dims [{keys}]")

    has_catchall = any(not (r.dims or {}) or all(_is_wildcard(v) for v in (r.dims or {}).values()) for r in rows)
    if not has_catchall:
        issues.append("no catch-all row (empty dims) — partial dimension lookups may find nothing (gap)")

    if table.kind == "freight_matrix":
        multi = [r for r in rows if len([k for k, v in (r.dims or {}).items() if not _is_wildcard(v)]) >= 2]
        if not multi:
            issues.append("freight_matrix table has no 2-D rows (load_port + disch_port) — matrix is effectively flat")

    return issues
