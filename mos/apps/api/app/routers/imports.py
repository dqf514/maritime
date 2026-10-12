"""CSV import wizard API — preview (validate) + commit (bulk create).

Excel/CSV 导入（含校验预览 + 防公式注入）：
- POST /imports/preview  解析 CSV、按目标模型必填/类型校验、逐行返回错误
- POST /imports/commit   仅提交合法行，服务端写 tenant_id，剥离 `'` 守卫符，绝不 eval

公式注入防护与 apps/web/lib/csv.ts guardFormula 同款：单元格以 = + @ \t \r 开头，
或以 - 开头但不是纯数字 → 行错误 formula_not_allowed（导入侧直接拒绝，不静默加撇号）。
"""

from __future__ import annotations

import csv
import io
import re
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_wave1 import Counterparty, Port, Vessel
from app.schemas_wave1 import CounterpartyIn, PortIn, VesselIn
from app.security import AuthContext, require_module

router = APIRouter(prefix="/imports", tags=["Imports"])

MAX_ROWS = 500
MAX_CONTENT_BYTES = 2 * 1024 * 1024  # 2MB

EntityKey = Literal["ports", "counterparties", "vessels"]

# 纯数字（含负号小数）— 允许作为单元格值
_PURE_NUMBER = re.compile(r"-\d+(\.\d+)?")
_BOOL_TRUE = {"true", "1", "yes", "y", "on"}
_BOOL_FALSE = {"false", "0", "no", "n", "off"}


class EntitySpec:
    def __init__(self, model, schema, fields: list[str], required: list[str], tenant_scoped: bool, key_fields: list[str]):
        self.model = model
        self.schema = schema
        self.fields = fields
        self.required = required
        self.tenant_scoped = tenant_scoped
        self.key_fields = key_fields  # 预览关键列


ENTITIES: dict[str, EntitySpec] = {
    "ports": EntitySpec(
        model=Port,
        schema=PortIn,
        fields=["name", "unlocode", "country", "timezone", "latitude", "longitude", "is_eu", "holidays"],
        required=["name"],
        tenant_scoped=False,  # 港口为全局参考数据（与 masterdata create_port 一致）
        key_fields=["name", "unlocode", "country"],
    ),
    "counterparties": EntitySpec(
        model=Counterparty,
        schema=CounterpartyIn,
        fields=[
            "name",
            "type",
            "country",
            "credit_rating",
            "sanctions_status",
            "address",
            "tax_id",
            "swift_code",
            "registration_no",
            "website",
            "phone",
            "email",
            "notes",
        ],
        required=["name"],
        tenant_scoped=True,
        key_fields=["name", "type", "country"],
    ),
    "vessels": EntitySpec(
        model=Vessel,
        schema=VesselIn,
        fields=[
            "name",
            "imo",
            "mmsi",
            "flag",
            "vessel_type",
            "dwt",
            "speed_knots",
            "consumption_sea",
            "consumption_port",
            "status",
        ],
        required=["name"],
        tenant_scoped=True,
        key_fields=["name", "imo", "vessel_type"],
    ),
}


# ── 公式注入防护（mirror apps/web/lib/csv.ts guardFormula） ─────────────


def _is_formula(value: str) -> bool:
    if not value:
        return False
    if value[0] in "=+@\t\r":
        return True
    if value.startswith("-") and not _PURE_NUMBER.fullmatch(value):
        return True
    return False


def _unguard(value: str) -> str:
    """Strip a leading Excel-export guard apostrophe (commit sanitisation)."""
    if value.startswith("'"):
        return value[1:]
    return value


# ── CSV 解析 / 字段整理 ────────────────────────────────────────────────


def _parse_csv(content: str) -> list[list[str]]:
    text = content.lstrip("﻿")
    reader = csv.reader(io.StringIO(text))
    rows: list[list[str]] = []
    for row in reader:
        if any(cell.strip() for cell in row):
            rows.append(row)
    return rows


def _map_headers(header: list[str], fields: list[str]) -> dict[int, str]:
    lookup = {f.lower(): f for f in fields}
    mapping: dict[int, str] = {}
    for i, h in enumerate(header):
        key = h.strip().lower()
        if key in lookup:
            mapping[i] = lookup[key]
    return mapping


def _clean_cell(raw: str) -> str:
    return raw.strip()


def _to_bool(raw: str) -> bool | None:
    low = raw.lower()
    if low in _BOOL_TRUE:
        return True
    if low in _BOOL_FALSE:
        return False
    return None


def _build_data(spec: EntitySpec, mapping: dict[int, str], row: list[str]) -> tuple[dict[str, Any], list[str]]:
    """Map a CSV row onto schema fields. Returns (data, errors)."""
    errors: list[str] = []
    data: dict[str, Any] = {}
    for col_idx, field in mapping.items():
        raw = row[col_idx] if col_idx < len(row) else ""
        cleaned = _clean_cell(raw)
        if cleaned == "":
            # required fields handled after loop (so missing column ≠ empty-only)
            continue
        if field == "is_eu":
            parsed = _to_bool(cleaned)
            if parsed is None:
                errors.append("is_eu: invalid_bool")
            else:
                data["is_eu"] = parsed
        elif field == "holidays":
            data["holidays"] = [p.strip() for p in re.split(r"[,;]", cleaned) if p.strip()]
        else:
            data[field] = cleaned

    for req in spec.required:
        if not str(data.get(req) or "").strip():
            errors.append(f"{req}_required")

    if errors:
        return data, errors

    try:
        validated = spec.schema.model_validate(data)
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(x) for x in err.get("loc", ()) if x != "body")
            errors.append(f"{loc}: {err.get('msg', 'invalid')}" if loc else str(err.get("msg", "invalid")))
        return data, errors

    out = validated.model_dump()
    # 仅保留目标字段（model_dump 可能带默认值字段，全部保留是预期 — 与 create schema 对齐）
    return out, errors


def _check_row_formulas(row: list[str]) -> list[str]:
    for cell in row:
        if _is_formula(_clean_cell(cell)):
            return ["formula_not_allowed"]
    return []


# ── 请求 / 响应模型 ────────────────────────────────────────────────────


class PreviewIn(BaseModel):
    entity: EntityKey
    format: Literal["csv"] = "csv"
    content: str


class CommitIn(BaseModel):
    entity: EntityKey
    rows: list[dict[str, Any]]


class PreviewRowOut(BaseModel):
    row_no: int
    data: dict[str, Any]
    errors: list[str]
    valid: bool


class PreviewOut(BaseModel):
    entity: str
    rows: list[PreviewRowOut]
    summary: dict[str, int]
    key_fields: list[str]


class CommitFailure(BaseModel):
    index: int
    errors: list[str]


class CommitOut(BaseModel):
    created: int
    failed: list[CommitFailure]
    created_ids: list[UUID]


def _spec_or_400(entity: str) -> EntitySpec:
    spec = ENTITIES.get(entity)
    if spec is None:
        raise HTTPException(400, detail={"code": "UNKNOWN_ENTITY", "entity": entity})
    return spec


def _reject_oversize(content: str) -> None:
    if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"code": "CONTENT_TOO_LARGE", "max_bytes": MAX_CONTENT_BYTES},
        )


# ── 端点 ──────────────────────────────────────────────────────────────


@router.post("/preview", response_model=PreviewOut)
def preview_import(
    body: PreviewIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _ = auth, db  # 预览只读，不落库；仍要求 masterdata 模块 + 登录
    if body.format != "csv":
        raise HTTPException(400, detail={"code": "UNSUPPORTED_FORMAT", "allowed": ["csv"]})
    spec = _spec_or_400(body.entity)
    if not body.content or not body.content.strip():
        raise HTTPException(400, detail={"code": "EMPTY_CONTENT"})
    _reject_oversize(body.content)

    raw_rows = _parse_csv(body.content)
    if not raw_rows:
        raise HTTPException(400, detail={"code": "EMPTY_CONTENT"})

    header, data_rows = raw_rows[0], raw_rows[1:]
    if len(data_rows) > MAX_ROWS:
        raise HTTPException(
            400,
            detail={"code": "ROW_LIMIT", "max_rows": MAX_ROWS, "rows": len(data_rows)},
        )

    mapping = _map_headers(header, spec.fields)
    if not mapping:
        raise HTTPException(
            400,
            detail={"code": "UNKNOWN_HEADERS", "expected": spec.fields},
        )

    out_rows: list[PreviewRowOut] = []
    valid_count = 0
    for i, row in enumerate(data_rows, start=1):
        errors = _check_row_formulas(row)
        data: dict[str, Any] = {}
        if not errors:
            data, build_errors = _build_data(spec, mapping, row)
            errors.extend(build_errors)
        else:
            # 仍给出可读 data 供预览网格展示
            for col_idx, field in mapping.items():
                raw = row[col_idx] if col_idx < len(row) else ""
                cleaned = _clean_cell(raw)
                if cleaned:
                    data[field] = cleaned
        valid = not errors
        if valid:
            valid_count += 1
        out_rows.append(PreviewRowOut(row_no=i, data=data, errors=errors, valid=valid))

    return PreviewOut(
        entity=body.entity,
        rows=out_rows,
        summary={
            "total": len(out_rows),
            "valid": valid_count,
            "invalid": len(out_rows) - valid_count,
        },
        key_fields=spec.key_fields,
    )


@router.post("/commit", response_model=CommitOut)
def commit_import(
    body: CommitIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    spec = _spec_or_400(body.entity)
    if len(body.rows) > MAX_ROWS:
        raise HTTPException(
            400,
            detail={"code": "ROW_LIMIT", "max_rows": MAX_ROWS, "rows": len(body.rows)},
        )

    created = 0
    created_ids: list[UUID] = []
    failed: list[CommitFailure] = []

    for idx, raw_row in enumerate(body.rows):
        # Sanitize: strip leading `'` guard chars; never eval.
        cleaned: dict[str, Any] = {}
        formula_hit = False
        for key, value in raw_row.items():
            if isinstance(value, str):
                # Reject raw formula cells (defense in depth; preview already flags these).
                if _is_formula(value.strip()):
                    formula_hit = True
                cleaned[key] = _unguard(value)
            else:
                cleaned[key] = value
        if formula_hit:
            failed.append(CommitFailure(index=idx, errors=["formula_not_allowed"]))
            continue

        # Keep only known fields; drop None / empty so schema defaults apply
        payload: dict[str, Any] = {}
        for field in spec.fields:
            if field not in cleaned:
                continue
            val = cleaned[field]
            if val is None:
                continue
            if isinstance(val, str):
                val = val.strip()
                if val == "":
                    continue
            payload[field] = val

        for req in spec.required:
            if not str(payload.get(req) or "").strip():
                failed.append(CommitFailure(index=idx, errors=[f"{req}_required"]))
                break
        else:
            try:
                validated = spec.schema.model_validate(payload)
            except ValidationError as exc:
                errs = []
                for err in exc.errors():
                    loc = ".".join(str(x) for x in err.get("loc", ()) if x != "body")
                    errs.append(f"{loc}: {err.get('msg', 'invalid')}" if loc else str(err.get("msg", "invalid")))
                failed.append(CommitFailure(index=idx, errors=errs))
                continue

            fields = validated.model_dump()
            if spec.tenant_scoped:
                fields["tenant_id"] = auth.tenant_id
            try:
                with db.begin_nested():
                    row = spec.model(**fields)
                    db.add(row)
                    db.flush()
                created += 1
                created_ids.append(row.id)
            except IntegrityError:
                failed.append(CommitFailure(index=idx, errors=["duplicate"]))
            except Exception as exc:  # noqa: BLE001 — per-row isolation
                failed.append(CommitFailure(index=idx, errors=[str(exc) or "create_failed"]))

    db.commit()
    return CommitOut(created=created, failed=failed, created_ids=created_ids)
