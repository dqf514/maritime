"""Phase 8 — Declarative report builder (Report Designer).

Translates a declarative query spec into a SQLAlchemy ``select()`` — no raw
user SQL ever reaches the database:

- identifiers must resolve to known dataset columns (always quoted on output);
- expressions are tokenized and *rebuilt* from a whitelist (column refs, safe
  scalar functions, numeric literals, arithmetic/comparison punctuation);
  any other character, keyword, string literal or comment marker rejects
  the spec — so even keyword-looking identifiers are emitted as quoted refs;
- filter values are always bound parameters (``{param: name}`` placeholders
  resolve from runtime params);
- every dataset base table **must** carry ``tenant_id`` and every query is
  always filtered by it.

Spec shape (query_spec v2)::

    {
      "datasets": [{"dataset": "voyages", "alias": "v"}, ...],
      "joins": [{"left": "v", "right": "i", "join_type": "left",
                 "left_field": "voyage_id", "right_field": "id"}, ...],
      "fields": [{"dataset": "v", "field": "voyage_no", "label": "Voyage #",
                  "expression": "qty * price", "agg": "sum", "format": "number",
                  "sort_order": 0, "visible": true}, ...],
      "filters": [{"dataset": "v", "field": "status", "op": "eq",
                   "value": "completed"}, ...],
      "group_by": [{"dataset": "v", "field": "status"}, ...],
      "order_by": [{"dataset": "v", "field": "voyage_no", "direction": "asc"}, ...],
    }

``dataset`` entries accept ``entity``/``name`` keys; ``field`` entries accept
``field_name``/``name``; joins accept ``type`` for ``join_type``.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, func, literal_column, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models_report import ReportDataset

# ---------------------------------------------------------------------------
# Dataset catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DatasetDef:
    entity: str  # logical key used in query specs
    name: str  # display name
    base_table: str  # physical table name
    description: str = ""


#: Seeded default datasets (all base tables carry tenant_id).
DEFAULT_DATASETS: tuple[DatasetDef, ...] = (
    DatasetDef("voyages", "Voyages", "voyages", "Voyage records"),
    DatasetDef("invoices", "Invoices", "invoices", "AR/AP invoices"),
    DatasetDef("charters", "Charters", "charters", "Charter parties / CP terms"),
    DatasetDef("laytime", "Laytime", "laytime_calcs", "Laytime calculations"),
    DatasetDef("claims", "Claims", "claims", "Demurrage & claims"),
    DatasetDef("bunker_orders", "Bunker Orders", "bunker_orders", "Bunker orders & deliveries"),
    DatasetDef("vessels", "Vessels", "vessels", "Fleet vessels"),
    DatasetDef("counterparties", "Counterparties", "counterparties", "Counterparties"),
    DatasetDef("port_calls", "Port Calls", "port_calls", "Voyage port calls"),
    # Phase 9 — report template datasets
    DatasetDef("payments", "Payments", "payments", "Invoice payments"),
    DatasetDef("port_disbursements", "Port Disbursements", "port_disbursements", "PDA/FDA port costs"),
    DatasetDef("emissions", "Emissions", "emission_records", "Voyage CO2 / fuel emissions"),
    DatasetDef("trades", "Trades", "trades", "FFA / swap / physical trades"),
    DatasetDef("hire_statements", "Hire Statements", "hire_statements", "TC hire statements"),
    DatasetDef("schedule_blocks", "Schedule Blocks", "schedule_blocks", "Vessel schedule windows"),
    DatasetDef("cargo", "Cargo", "cargoes", "Commercial cargo book"),
    DatasetDef("coa_liftings", "COA Liftings", "coa_liftings", "COA lifting nominations"),
    # supporting operational datasets (preset spec adapters)
    DatasetDef("sof_events", "SOF Events", "sof_events", "Statement of Facts events"),
    DatasetDef("noon_reports", "Noon Reports", "noon_reports", "Daily noon position reports"),
    DatasetDef("estimates", "Estimates", "estimates", "Voyage / TC estimates"),
    DatasetDef("off_hire_events", "Off-Hire Events", "off_hire_events", "Off-hire windows"),
    DatasetDef(
        "time_charter_contracts",
        "TC Contracts",
        "time_charter_contracts",
        "Time-charter contracts",
    ),
    DatasetDef("gl_journals", "GL Journals", "period_journals", "Period journal batches"),
    DatasetDef("chart_of_accounts", "Chart of Accounts", "chart_of_accounts", "GL accounts"),
)

DATASETS: dict[str, DatasetDef] = {}
for _d in DEFAULT_DATASETS:
    DATASETS[_d.entity] = _d
    DATASETS[_d.name.lower()] = _d


def get_dataset(key: str) -> DatasetDef | None:
    """Look a dataset up by entity key or display name (case-insensitive)."""
    if not isinstance(key, str):
        return None
    return DATASETS.get(key) or DATASETS.get(key.lower())


def _table_for(ds: DatasetDef):
    return Base.metadata.tables.get(ds.base_table)


def _sql_type(col) -> str:
    t = type(col.type).__name__.lower()
    if "bool" in t:
        return "bool"
    if "int" in t or "numeric" in t or "float" in t or "decimal" in t:
        return "number"
    if "datetime" in t or "timestamp" in t:
        return "datetime"
    if "date" in t:
        return "date"
    if "json" in t:
        return "json"
    if "uuid" in t:
        return "uuid"
    return "string"


def dataset_fields(entity: str) -> list[dict[str, Any]]:
    """Field metadata for a dataset, derived from the live table columns."""
    ds = get_dataset(entity)
    if ds is None:
        return []
    table = _table_for(ds)
    if table is None:
        return []
    out: list[dict[str, Any]] = []
    for col in table.columns:
        out.append(
            {
                "name": col.name,
                "type": _sql_type(col),
                "label": col.name.replace("_", " ").title(),
                "table_alias": ds.base_table,
            }
        )
    return out


def seed_report_datasets(db: Session) -> int:
    """Upsert the default datasets (idempotent). Returns number created.

    Existing rows get their display metadata (name/description/fields) refreshed
    so new fields in ``DEFAULT_DATASETS`` reach already-seeded databases.
    """
    created = 0
    for ds in DEFAULT_DATASETS:
        exists = db.query(ReportDataset).filter(ReportDataset.entity == ds.entity).first()
        fields = dataset_fields(ds.entity)
        if exists is not None:
            exists.name = ds.name
            exists.base_table = ds.base_table
            exists.description = ds.description
            exists.fields = fields
            continue
        db.add(
            ReportDataset(
                name=ds.name,
                entity=ds.entity,
                base_table=ds.base_table,
                description=ds.description,
                fields=fields,
            )
        )
        created += 1
    db.flush()
    return created


def get_dataset_row(db: Session, dataset_id: uuid.UUID) -> ReportDataset | None:
    return db.get(ReportDataset, dataset_id)


def list_dataset_rows(db: Session) -> list[ReportDataset]:
    return db.query(ReportDataset).order_by(ReportDataset.entity).all()


# ---------------------------------------------------------------------------
# Expression whitelist (NO raw user SQL)
# ---------------------------------------------------------------------------

#: Scalar functions accepted in expressions (portable SQL core + SQLite date
#: helpers; anything outside this set rejects the spec).
SAFE_FUNCTIONS = frozenset(
    {
        "abs",
        "round",
        "coalesce",
        "nullif",
        "lower",
        "upper",
        "length",
        "substr",
        "trim",
        "date",
        "datetime",
        "julianday",
    }
)

AGGREGATES = frozenset({"sum", "avg", "count", "min", "max"})
FILTER_OPS = frozenset(
    {
        "eq",
        "ne",
        "gt",
        "gte",
        "lt",
        "lte",
        "like",
        "ilike",
        "in",
        "not_in",
        "between",
        "is_null",
        "not_null",
    }
)
JOIN_TYPES = frozenset({"inner", "left", "right"})

MAX_EXPRESSION_LEN = 200

#: Forbidden anywhere inside an expression (comment / statement markers).
_FORBIDDEN_SUBSTRINGS = ("--", "/*", "*/", ";", "'", '"', "`", "\\")

#: Full tokenizer: identifiers (optionally qualified), numbers, punctuation.
_TOKEN_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?"
    r"|\d+(?:\.\d+)?"
    r"|(?:<>|<=|>=|!=|[+\-*/%(),.<>=])"
    r"|[ \t]+"
)


class ReportSpecError(ValueError):
    """Raised when a declarative spec fails validation or cannot be built."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _tokenize_expression(expr: str) -> list[str] | None:
    """Return tokens if the expression is fully covered by safe tokens."""
    pos = 0
    tokens: list[str] = []
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if m is None:
            return None
        tokens.append(m.group())
        pos = m.end()
    return tokens


def _qualified_ident(tok: str, col_map: dict[str, tuple[str, str]]) -> str | None:
    """Resolve an identifier token to a quoted ``alias"."col`` reference."""
    if "." in tok:
        alias, _, name = tok.partition(".")
        key = f"{alias}.{name}"
        if key in col_map:
            a, c = col_map[key]
            return f'"{a}"."{c}"'
        return None
    matches = {k: v for k, v in col_map.items() if k.split(".", 1)[1] == tok}
    if len(matches) == 1:
        a, c = next(iter(matches.values()))
        return f'"{a}"."{c}"'
    return None  # unknown or ambiguous


def compile_expression(expr: str, col_map: dict[str, tuple[str, str]]) -> str:
    """Validate + rebuild an expression into safe SQL.

    ``col_map`` maps ``alias.column`` → (alias, column) for every column
    selectable in this spec. Returns the rebuilt SQL string (with quoted
    column refs) or raises ReportSpecError.
    """
    if not isinstance(expr, str) or not expr.strip():
        raise ReportSpecError(["expression must be a non-empty string"])
    if len(expr) > MAX_EXPRESSION_LEN:
        raise ReportSpecError([f"expression too long (max {MAX_EXPRESSION_LEN} chars)"])
    low = expr.lower()
    for bad in _FORBIDDEN_SUBSTRINGS:
        if bad in expr:
            raise ReportSpecError([f"expression contains forbidden token {bad!r}"])
    tokens = _tokenize_expression(expr)
    if tokens is None:
        raise ReportSpecError(["expression contains illegal characters"])

    out: list[str] = []
    for tok in tokens:
        if tok.isspace():
            out.append(" ")
            continue
        if tok[0].isdigit():
            out.append(tok)
            continue
        if tok[0] in "+-*/%(),.<>=!":
            out.append(tok)
            continue
        # identifier
        low_tok = tok.lower()
        if "." not in tok and low_tok in SAFE_FUNCTIONS:
            out.append(low_tok)
            continue
        resolved = _qualified_ident(tok, col_map)
        if resolved is None:
            raise ReportSpecError([f"expression references unknown identifier {tok!r}"])
        out.append(resolved)
    rebuilt = "".join(out).strip()
    if not rebuilt:
        raise ReportSpecError(["expression is empty"])
    return rebuilt


# ---------------------------------------------------------------------------
# Spec normalization
# ---------------------------------------------------------------------------


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _ds_key(entry: Any) -> str | None:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        for k in ("dataset", "entity", "name", "dataset_key"):
            if entry.get(k):
                return str(entry[k])
    return None


def _field_name(entry: Any) -> str | None:
    if isinstance(entry, dict):
        for k in ("field", "field_name", "name"):
            if entry.get(k):
                return str(entry[k])
    return None


def _dataset_entries(spec: dict) -> list[tuple[str, DatasetDef]]:
    """Return [(alias, DatasetDef), ...] for spec["datasets"]."""
    out: list[tuple[str, DatasetDef]] = []
    for entry in _as_list(spec.get("datasets")):
        key = _ds_key(entry)
        if key is None:
            raise ReportSpecError(["dataset entry needs a dataset/entity name"])
        ds = get_dataset(key)
        if ds is None:
            raise ReportSpecError([f"unknown dataset {key!r}"])
        alias = None
        if isinstance(entry, dict):
            alias = entry.get("alias") or entry.get("table_alias")
        alias = str(alias) if alias else ds.entity
        out.append((alias, ds))
    return out


def _col_map(entries: list[tuple[str, DatasetDef]]) -> dict[str, tuple[str, str]]:
    """Map ``alias.column`` → (alias, column) plus bare ``alias.column`` forms."""
    cmap: dict[str, tuple[str, str]] = {}
    for alias, ds in entries:
        table = _table_for(ds)
        if table is None:
            raise ReportSpecError([f"dataset {ds.entity!r} has no table {ds.base_table!r}"])
        for col in table.columns:
            cmap[f"{alias}.{col.name}"] = (alias, col.name)
    return cmap


def _resolve_col(
    ref: dict | str,
    entries: list[tuple[str, DatasetDef]],
    col_map: dict[str, tuple[str, str]],
    what: str,
) -> tuple[str, str]:
    """Resolve a {dataset, field} reference to (alias, column)."""
    if isinstance(ref, str):
        # bare column name across datasets
        matches = {k: v for k, v in col_map.items() if k.split(".", 1)[1] == ref}
        if len(matches) == 1:
            return next(iter(matches.values()))
        if not matches:
            raise ReportSpecError([f"{what}: unknown field {ref!r}"])
        raise ReportSpecError([f"{what}: ambiguous field {ref!r}"])
    key = _ds_key(ref)
    field = _field_name(ref)
    if not field:
        raise ReportSpecError([f"{what}: entry needs a field name"])
    aliases = [a for a, _ in entries]
    if key:
        # key may be an alias or a dataset entity/name
        if key in aliases:
            alias = key
        else:
            ds = get_dataset(key)
            alias = None
            if ds is not None:
                for a, d in entries:
                    if d.entity == ds.entity:
                        alias = a
                        break
            if alias is None:
                raise ReportSpecError([f"{what}: unknown dataset {key!r}"])
    else:
        if len(entries) == 1:
            alias = entries[0][0]
        else:
            raise ReportSpecError([f"{what}: dataset required when several datasets are joined"])
    cmap_key = f"{alias}.{field}"
    if cmap_key not in col_map:
        raise ReportSpecError([f"{what}: unknown field {field!r} on dataset {alias!r}"])
    return alias, field


def validate_spec(spec: dict) -> list[str]:
    """Validate a declarative query spec; return a list of error strings."""
    errors: list[str] = []
    if not isinstance(spec, dict):
        return ["spec must be an object"]

    try:
        entries = _dataset_entries(spec)
    except ReportSpecError as e:
        return e.errors
    if not entries:
        return ["spec.datasets must list at least one dataset"]

    aliases = [a for a, _ in entries]
    if len(set(aliases)) != len(aliases):
        errors.append("dataset aliases must be unique")

    # every base table must carry tenant_id (ALWAYS filter rule)
    for alias, ds in entries:
        table = _table_for(ds)
        if table is None:
            errors.append(f"dataset {ds.entity!r} has no table {ds.base_table!r}")
        elif "tenant_id" not in table.c:
            errors.append(f"dataset {ds.entity!r} table {ds.base_table!r} has no tenant_id")

    try:
        col_map = _col_map(entries)
    except ReportSpecError as e:
        return errors + e.errors

    alias_set = set(aliases)

    # joins
    join_rights: set[str] = set()
    introduced: set[str] = {entries[0][0]}
    for i, j in enumerate(_as_list(spec.get("joins"))):
        what = f"joins[{i}]"
        if not isinstance(j, dict):
            errors.append(f"{what}: must be an object")
            continue
        jt = j.get("join_type") or j.get("type") or "left"
        if jt not in JOIN_TYPES:
            errors.append(f"{what}: join_type must be one of {sorted(JOIN_TYPES)}")
        left = j.get("left") or j.get("left_dataset")
        right = j.get("right") or j.get("right_dataset")
        if left not in alias_set:
            errors.append(f"{what}: unknown left dataset {left!r}")
        if right not in alias_set:
            errors.append(f"{what}: unknown right dataset {right!r}")
        elif right in join_rights:
            errors.append(f"{what}: dataset {right!r} is joined twice")
        else:
            join_rights.add(right)
        lf = j.get("left_field") or (j.get("on") or {}).get("left_field")
        rf = j.get("right_field") or (j.get("on") or {}).get("right_field")
        if not lf or not rf:
            errors.append(f"{what}: left_field and right_field are required")
        else:
            if f"{left}.{lf}" not in col_map:
                errors.append(f"{what}: unknown left_field {lf!r} on {left!r}")
            if f"{right}.{rf}" not in col_map:
                errors.append(f"{what}: unknown right_field {rf!r} on {right!r}")
        if jt == "right":
            if i > 0:
                errors.append(f"{what}: right joins are only supported as the first join")
            elif entries[0][0] not in (left, right):
                errors.append(f"{what}: right join must involve the first dataset")
            else:
                introduced.update({left, right})
        elif left in alias_set and left not in introduced:
            errors.append(f"{what}: left dataset {left!r} must already be joined")
        elif left in alias_set:
            introduced.add(right)
    for a, _ds in entries:
        if a not in introduced:
            errors.append(f"dataset {a!r} is not joined into the query")

    # fields
    keys_seen: set[str] = set()
    has_agg = False
    non_agg_fields: list[tuple[str, str, str]] = []  # (alias, field, key)
    field_exprs: dict[str, str] = {}  # key → field name (for order_by refs)
    for i, f in enumerate(_as_list(spec.get("fields"))):
        what = f"fields[{i}]"
        if not isinstance(f, dict):
            errors.append(f"{what}: must be an object")
            continue
        visible = f.get("visible", True)
        label = f.get("label") or _field_name(f) or f"col_{i + 1}"
        key = str(label)
        if key in keys_seen:
            errors.append(f"{what}: duplicate output key {key!r}")
        keys_seen.add(key)
        agg = f.get("agg")
        if agg is not None and agg not in AGGREGATES:
            errors.append(f"{what}: agg must be one of {sorted(AGGREGATES)}")
        if agg:
            has_agg = True
        expr = f.get("expression")
        if expr:
            try:
                compile_expression(str(expr), col_map)
            except ReportSpecError as e:
                errors.extend(f"{what}: {msg}" for msg in e.errors)
            if _field_name(f):
                field_exprs[key] = _field_name(f)  # type: ignore[assignment]
        else:
            try:
                alias, field = _resolve_col(f, entries, col_map, what)
            except ReportSpecError as e:
                errors.extend(f"{what}: {msg}" for msg in e.errors)
            else:
                field_exprs[key] = field
                if not agg and visible:
                    non_agg_fields.append((alias, field, key))

    # filters
    for i, flt in enumerate(_as_list(spec.get("filters"))):
        what = f"filters[{i}]"
        if not isinstance(flt, dict):
            errors.append(f"{what}: must be an object")
            continue
        op = flt.get("op") or flt.get("operator") or "eq"
        if op not in FILTER_OPS:
            errors.append(f"{what}: op must be one of {sorted(FILTER_OPS)}")
        try:
            _resolve_col(flt, entries, col_map, what)
        except ReportSpecError as e:
            errors.extend(f"{what}: {msg}" for msg in e.errors)
        value = flt.get("value")
        if op in ("is_null", "not_null"):
            continue
        if op == "between" and not _is_param(value):
            coerced = _coerce_filter_value(op, value)
            if not isinstance(coerced, (list, tuple)) or len(coerced) != 2:
                errors.append(f"{what}: value must be a 2-item list for op 'between'")

    # group_by
    group_refs: set[tuple[str, str]] = set()
    for i, g in enumerate(_as_list(spec.get("group_by"))):
        what = f"group_by[{i}]"
        try:
            group_refs.add(_resolve_col(g, entries, col_map, what))
        except ReportSpecError as e:
            errors.extend(f"{what}: {msg}" for msg in e.errors)

    # when aggregating (or grouping), every selected non-agg field must be grouped
    if has_agg or group_refs:
        for alias, field, key in non_agg_fields:
            if (alias, field) not in group_refs:
                errors.append(
                    f"field {key!r} ({alias}.{field}) must appear in group_by when aggregating"
                )

    # order_by
    for i, o in enumerate(_as_list(spec.get("order_by"))):
        what = f"order_by[{i}]"
        if isinstance(o, str):
            name = o.lstrip("-")
            if name in field_exprs or name in keys_seen:
                continue
            try:
                _resolve_col(name, entries, col_map, what)
            except ReportSpecError as e:
                errors.extend(f"{what}: {msg}" for msg in e.errors)
            continue
        if not isinstance(o, dict):
            errors.append(f"{what}: must be an object or field name")
            continue
        direction = (o.get("direction") or o.get("sort") or "asc").lower()
        if direction not in ("asc", "desc"):
            errors.append(f"{what}: direction must be asc or desc")
        name = _field_name(o)
        label = o.get("label")
        if name is None and label is not None and str(label) in keys_seen:
            continue  # ordering by an output column label
        if name is None:
            errors.append(f"{what}: needs a field name or output label")
            continue
        if name in field_exprs or name in keys_seen:
            continue
        try:
            _resolve_col(o, entries, col_map, what)
        except ReportSpecError as e:
            errors.extend(f"{what}: {msg}" for msg in e.errors)

    return errors


def _is_param(value: Any) -> bool:
    return isinstance(value, dict) and "param" in value


def _coerce_filter_value(op: str, value: Any) -> Any:
    """Normalize filter values for list-style ops.

    The designer UI sends ``in``/``not_in`` values as a single comma-separated
    string ("a, b, c") — auto-split them into lists here so both string and
    list payloads work. ``between`` accepts "lo,hi" the same way.
    Runtime ``{"param": ...}`` placeholders pass through unresolved.
    """
    if _is_param(value):
        return value
    if op in ("in", "not_in"):
        if value is None:
            return []
        if isinstance(value, str):
            return [p.strip() for p in value.split(",") if p.strip()]
        if isinstance(value, (list, tuple)):
            return list(value)
        return [value]
    if op == "between" and isinstance(value, str):
        parts = [p.strip() for p in value.split(",")]
        if len(parts) == 2:
            return parts
    return value


def _resolve_param(value: Any, params: dict | None) -> Any:
    if not _is_param(value):
        return value
    name = value["param"]
    if params is None or name not in params:
        raise ReportSpecError([f"missing runtime parameter {name!r}"])
    return params[name]


# ---------------------------------------------------------------------------
# Build / execute
# ---------------------------------------------------------------------------


def build_query(spec: dict, tenant_id: uuid.UUID, params: dict | None = None) -> Select:
    """Translate a validated spec into a tenant-scoped SQLAlchemy select()."""
    errors = validate_spec(spec)
    if errors:
        raise ReportSpecError(errors)

    entries = _dataset_entries(spec)
    col_map = _col_map(entries)
    alias_map = {alias: _table_for(ds).alias(alias) for alias, ds in entries}

    def col_of(alias: str, field: str):
        return alias_map[alias].c[field]

    def guard_of(alias: str) -> list[Any]:
        """Tenant isolation + soft-delete convention (tenant_guard) for one alias."""
        tbl = alias_map[alias]
        conds: list[Any] = [tbl.c.tenant_id == tenant_id]
        if "deleted_at" in tbl.c:
            conds.append(tbl.c.deleted_at.is_(None))
        if "status" in tbl.c:
            conds.append(tbl.c.status != "deleted")
        return conds

    # FROM chain: guard conditions of joined tables go into the ON clause so
    # outer joins keep their non-matching left rows (a WHERE guard on a
    # nullable side would drop them). The FROM anchor keeps its guards in WHERE.
    joins = _as_list(spec.get("joins"))
    anchor = entries[0][0]
    from_obj = alias_map[anchor]
    for j in joins:
        jt = j.get("join_type") or j.get("type") or "left"
        left = j.get("left") or j.get("left_dataset")
        right = j.get("right") or j.get("right_dataset")
        lf = j.get("left_field") or (j.get("on") or {}).get("left_field")
        rf = j.get("right_field") or (j.get("on") or {}).get("right_field")
        on_eq = col_of(left, lf) == col_of(right, rf)
        if jt == "right":
            # A RIGHT JOIN B == B LEFT JOIN A (validated: first join only)
            from_obj = alias_map[right].outerjoin(alias_map[left], and_(on_eq, *guard_of(left)))
            anchor = right
        else:
            onclause = and_(on_eq, *guard_of(right))
            if jt == "inner":
                from_obj = from_obj.join(alias_map[right], onclause)
            else:  # left
                from_obj = from_obj.outerjoin(alias_map[right], onclause)

    # select fields
    select_elems: list[Any] = []
    output_keys: list[str] = []
    field_index: dict[str, Any] = {}  # output key / field name → element
    non_agg_elems: list[Any] = []
    field_specs = _as_list(spec.get("fields"))
    visible_fields = [f for f in field_specs if isinstance(f, dict) and f.get("visible", True)]
    visible_fields = sorted(
        enumerate(visible_fields),
        key=lambda t: (t[1]["sort_order"] if t[1].get("sort_order") is not None else t[0], t[0]),
    )
    has_agg = any(f.get("agg") for _, f in visible_fields)

    for i, f in visible_fields:
        label = str(f.get("label") or _field_name(f) or f"col_{i + 1}")
        expr = f.get("expression")
        if expr:
            sql = compile_expression(str(expr), col_map)
            elem = literal_column(sql)
        else:
            alias, field = _resolve_col(f, entries, col_map, "fields")
            elem = col_of(alias, field)
        agg = f.get("agg")
        if agg:
            elem = {"sum": func.sum, "avg": func.avg, "count": func.count,
                    "min": func.min, "max": func.max}[agg](elem)
        else:
            non_agg_elems.append(elem)
        elem = elem.label(label)
        select_elems.append(elem)
        output_keys.append(label)
        field_index[label] = elem
        if _field_name(f):
            field_index[_field_name(f)] = elem

    if not select_elems:
        # default: every column of the first dataset
        base_alias = entries[0][0]
        table = alias_map[base_alias]
        for c in table.c:
            select_elems.append(c.label(c.name))
            output_keys.append(c.name)
            field_index[c.name] = select_elems[-1]

    # tenant isolation — ALWAYS (anchor in WHERE, joined tables in their ON)
    wheres = list(guard_of(anchor))

    # filters (parameterized)
    for flt in _as_list(spec.get("filters")):
        alias, field = _resolve_col(flt, entries, col_map, "filters")
        col = col_of(alias, field)
        op = flt.get("op") or flt.get("operator") or "eq"
        value = _coerce_filter_value(op, _resolve_param(flt.get("value"), params))
        if op == "eq":
            wheres.append(col == value)
        elif op == "ne":
            wheres.append(col != value)
        elif op == "gt":
            wheres.append(col > value)
        elif op == "gte":
            wheres.append(col >= value)
        elif op == "lt":
            wheres.append(col < value)
        elif op == "lte":
            wheres.append(col <= value)
        elif op == "like":
            wheres.append(col.like(value))
        elif op == "ilike":
            wheres.append(col.ilike(value))
        elif op == "in":
            wheres.append(col.in_(value if isinstance(value, list) else list(value)))
        elif op == "not_in":
            wheres.append(col.not_in(value if isinstance(value, list) else list(value)))
        elif op == "between":
            wheres.append(col.between(value[0], value[1]))
        elif op == "is_null":
            wheres.append(col.is_(None))
        elif op == "not_null":
            wheres.append(col.is_not(None))

    stmt: Select = select(*select_elems).select_from(from_obj).where(and_(*wheres))

    # group by
    group_elems: list[Any] = []
    for g in _as_list(spec.get("group_by")):
        alias, field = _resolve_col(g, entries, col_map, "group_by")
        group_elems.append(col_of(alias, field))
    if has_agg and not group_elems:
        group_elems = list(non_agg_elems)
    if group_elems:
        stmt = stmt.group_by(*group_elems)

    # order by
    for o in _as_list(spec.get("order_by")):
        direction = "asc"
        elem: Any = None
        if isinstance(o, str):
            name = o.lstrip("-")
            if o.startswith("-"):
                direction = "desc"
            elem = field_index.get(name)
            if elem is None:
                alias, field = _resolve_col(name, entries, col_map, "order_by")
                elem = col_of(alias, field)
        else:
            direction = (o.get("direction") or o.get("sort") or "asc").lower()
            name = _field_name(o)
            label = str(o["label"]) if o.get("label") is not None else None
            if name and name in field_index:
                elem = field_index[name]
            elif label is not None and label in field_index:
                elem = field_index[label]
            else:
                alias, field = _resolve_col(o, entries, col_map, "order_by")
                elem = col_of(alias, field)
        stmt = stmt.order_by(elem.desc() if direction == "desc" else elem.asc())

    return stmt


def _result_columns(spec: dict) -> list[dict[str, Any]]:
    """Column metadata (key/label/format/agg/type) for the visible fields."""
    fields = [f for f in _as_list(spec.get("fields")) if isinstance(f, dict) and f.get("visible", True)]
    fields = sorted(
        enumerate(fields),
        key=lambda t: (t[1]["sort_order"] if t[1].get("sort_order") is not None else t[0], t[0]),
    )
    cols: list[dict[str, Any]] = []
    for i, f in fields:
        label = str(f.get("label") or _field_name(f) or f"col_{i + 1}")
        cols.append(
            {
                "key": label,
                "label": label,
                "format": f.get("format"),
                "agg": f.get("agg"),
                "type": "expression" if f.get("expression") else None,
            }
        )
    return cols


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


MAX_ROWS = 5000


def execute_query(
    db: Session,
    spec: dict,
    tenant_id: uuid.UUID,
    params: dict | None = None,
    limit: int | None = None,
) -> dict:
    """Run a declarative spec and return {columns, rows, total_rows}."""
    stmt = build_query(spec, tenant_id, params=params)
    if limit:
        stmt = stmt.limit(int(limit))
    result = db.execute(stmt)
    columns = _result_columns(spec)
    if not columns:
        columns = [{"key": k, "label": k, "format": None, "agg": None, "type": None} for k in result.keys()]
    keys = [c["key"] for c in columns]
    rows: list[dict[str, Any]] = []
    for raw in result.fetchmany(limit or MAX_ROWS):
        values = tuple(raw)  # Row iterates values (RowMapping would iterate keys)
        rows.append({k: _jsonable(v) for k, v in zip(keys, values)})
    return {"columns": columns, "rows": rows, "total_rows": len(rows)}


def preview(
    db: Session,
    spec: dict,
    tenant_id: uuid.UUID,
    limit: int = 100,
    params: dict | None = None,
) -> dict:
    """Sample results for the designer (limit clamped to 1..1000)."""
    try:
        limit = max(1, min(int(limit or 100), 1000))
    except (TypeError, ValueError):
        limit = 100
    return execute_query(db, spec, tenant_id, params=params, limit=limit)
