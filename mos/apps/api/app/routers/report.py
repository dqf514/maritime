"""Phase 6/8 — Report engine API endpoints.

Phase 8 (Report Designer): dataset catalog, declarative preview, query_spec
CRUD and spec-driven run/export. Dataset + preview routes are registered
before ``/{report_id}`` so static segments win path matching.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from app.db import get_db
from app.security import AuthContext, require_module
from app.services.report_builder import (
    ReportSpecError,
    get_dataset_row,
    list_dataset_rows,
    preview as builder_preview,
    seed_report_datasets,
    validate_spec,
)
from app.services.report_engine import (
    create_report,
    create_schedule,
    delete_report,
    delete_schedule,
    execute_report,
    export_report_csv,
    export_report_xlsx,
    get_report,
    get_schedule,
    list_reports,
    list_schedules,
    run_declarative_report,
    seed_system_reports,
    spec_for_report,
    system_report_spec,
    update_report,
    update_schedule,
)

router = APIRouter(prefix="/reports", tags=["Reports"])


class ReportCreateIn(BaseModel):
    report_name: str
    report_type: str = "custom"
    data_source: str = "sql"
    query: str | None = None
    parameters: dict | None = None
    columns: list | None = None
    filters: list | None = None
    sort: list | None = None
    template: str | None = None
    description: str | None = None
    query_spec: dict | None = None
    spec_version: str | None = None


class ReportUpdateIn(BaseModel):
    report_name: str | None = None
    query: str | None = None
    parameters: dict | None = None
    columns: list | None = None
    filters: list | None = None
    sort: list | None = None
    template: str | None = None
    description: str | None = None
    query_spec: dict | None = None
    spec_version: str | None = None


class PreviewIn(BaseModel):
    """Preview request. ``query_spec`` is accepted as an alias of ``spec``
    (the designer historically posted the wrong key)."""

    spec: dict | None = None
    query_spec: dict | None = None
    params: dict | None = None
    limit: int = 100

    @model_validator(mode="after")
    def _merge_aliases(self) -> "PreviewIn":
        if self.spec is None and self.query_spec is not None:
            self.spec = self.query_spec
        if self.spec is None:
            raise ValueError("spec (or query_spec) is required")
        return self


class ScheduleCreateIn(BaseModel):
    report_id: UUID
    schedule_type: str = "on_demand"
    cron_expression: str | None = None
    recipients: list[str] | None = None
    output_format: str = "excel"
    is_active: bool = True


class ScheduleUpdateIn(BaseModel):
    schedule_type: str | None = None
    cron_expression: str | None = None
    recipients: list[str] | None = None
    output_format: str | None = None
    is_active: bool | None = None


@router.get("/system/seed")
def seed_reports(
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """Seed system preset reports for the current tenant."""
    created = seed_system_reports(db, auth.tenant_id)
    db.commit()
    return {"seeded": len(created), "message": f"Created {len(created)} system reports"}


# ---------------------------------------------------------------------------
# Phase 8 — Report Designer: datasets / preview (registered before /{report_id})
# ---------------------------------------------------------------------------


def _ensure_datasets(db: Session) -> None:
    """(Re)seed the dataset catalog — idempotent upsert, keeps catalog fresh."""
    seed_report_datasets(db)
    db.commit()


@router.get("/datasets")
def list_datasets(
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """List available datasets with their field metadata."""
    _ensure_datasets(db)
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "entity": r.entity,
            "base_table": r.base_table,
            "description": r.description,
            "fields": r.fields or [],
        }
        for r in list_dataset_rows(db)
    ]


@router.get("/datasets/{dataset_id}")
def get_dataset_detail(
    dataset_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """Dataset detail with field metadata."""
    _ensure_datasets(db)
    r = get_dataset_row(db, dataset_id)
    if r is None:
        raise HTTPException(404, "Dataset not found")
    return {
        "id": str(r.id),
        "name": r.name,
        "entity": r.entity,
        "base_table": r.base_table,
        "description": r.description,
        "fields": r.fields or [],
    }


@router.post("/preview")
def preview_query_spec(
    body: PreviewIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """Preview a declarative query spec (sample rows). Rejects unsafe specs."""
    errors = validate_spec(body.spec)
    if errors:
        raise HTTPException(400, detail={"code": "INVALID_REPORT_SPEC", "errors": errors})
    try:
        return builder_preview(
            db, body.spec, auth.tenant_id, limit=body.limit, params=body.params or {}
        )
    except ReportSpecError as e:
        raise HTTPException(400, detail={"code": "INVALID_REPORT_SPEC", "errors": e.errors})


@router.get("/system/specs/{report_type}")
def get_system_report_spec(
    report_type: str,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """Declarative-spec adapter for a system report (designer starting point)."""
    spec = system_report_spec(report_type)
    if spec is None:
        raise HTTPException(404, "Unknown system report type")
    return {"report_type": report_type, "spec": spec}


@router.get("")
def list_all_reports(
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    reports = list_reports(db, auth.tenant_id)
    return [
        {
            "id": str(r.id),
            "report_name": r.report_name,
            "report_type": r.report_type,
            "data_source": r.data_source,
            "is_system": r.is_system,
            "description": r.description,
            "created_at": str(r.created_at) if r.created_at else None,
        }
        for r in reports
    ]


@router.post("")
def create_new_report(
    body: ReportCreateIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    data = body.model_dump(exclude_none=True)
    if data.get("query_spec") is not None:
        errors = validate_spec(data["query_spec"])
        if errors:
            raise HTTPException(400, detail={"code": "INVALID_REPORT_SPEC", "errors": errors})
        _ensure_datasets(db)
    r = create_report(db, auth.tenant_id, data)
    db.commit()
    return {"id": str(r.id), "report_name": r.report_name, "spec_version": r.spec_version}


@router.get("/{report_id}")
def get_single_report(
    report_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    r = get_report(db, auth.tenant_id, report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    return {
        "id": str(r.id),
        "report_name": r.report_name,
        "report_type": r.report_type,
        "data_source": r.data_source,
        "query": r.query,
        "parameters": r.parameters,
        "columns": r.columns,
        "filters": r.filters,
        "sort": r.sort,
        "template": r.template,
        "is_system": r.is_system,
        "description": r.description,
        "query_spec": r.query_spec,
        "spec_version": r.spec_version,
    }


@router.patch("/{report_id}")
def patch_report(
    report_id: UUID,
    body: ReportUpdateIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    r = get_report(db, auth.tenant_id, report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    data = body.model_dump(exclude_none=True)
    if data.get("query_spec") is not None:
        errors = validate_spec(data["query_spec"])
        if errors:
            raise HTTPException(400, detail={"code": "INVALID_REPORT_SPEC", "errors": errors})
        _ensure_datasets(db)
    r = update_report(db, r, data)
    db.commit()
    return {"id": str(r.id), "updated": True}


@router.put("/{report_id}")
def put_report(
    report_id: UUID,
    body: ReportUpdateIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """Update a report definition (including query_spec)."""
    r = get_report(db, auth.tenant_id, report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    data = body.model_dump(exclude_none=True)
    if data.get("query_spec") is not None:
        errors = validate_spec(data["query_spec"])
        if errors:
            raise HTTPException(400, detail={"code": "INVALID_REPORT_SPEC", "errors": errors})
        _ensure_datasets(db)
    r = update_report(db, r, data)
    db.commit()
    return {"id": str(r.id), "updated": True, "spec_version": r.spec_version}


@router.delete("/{report_id}")
def remove_report(
    report_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    r = get_report(db, auth.tenant_id, report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    try:
        delete_report(db, r)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return {"deleted": True}


@router.post("/{report_id}/execute")
def run_report(
    report_id: UUID,
    params: dict | None = None,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    r = get_report(db, auth.tenant_id, report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    result = execute_report(db, auth.tenant_id, r, params or {})
    return result


@router.get("/{report_id}/data")
def report_data(
    report_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """Run a report; query_spec v2 reports run through the declarative builder."""
    r = get_report(db, auth.tenant_id, report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    params = dict(request.query_params)
    if r.query_spec:
        try:
            return run_declarative_report(db, r.id, params, tenant_id=auth.tenant_id)
        except (LookupError, ValueError):
            raise HTTPException(404, "Report not found")
        except ReportSpecError as e:
            raise HTTPException(400, detail={"code": "INVALID_REPORT_SPEC", "errors": e.errors})
    return execute_report(db, auth.tenant_id, r, params)


@router.get("/{report_id}/export")
def export_report(
    report_id: UUID,
    request: Request,
    format: str = "csv",
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """Export a report run (format=csv|xlsx as a downloadable attachment)."""
    fmt = (format or "csv").lower()
    if fmt not in ("csv", "xlsx", "excel"):
        raise HTTPException(400, detail={"code": "EXPORT_FORMAT_UNSUPPORTED", "format": format})
    r = get_report(db, auth.tenant_id, report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    params = dict(request.query_params)
    params.pop("format", None)
    if r.query_spec:
        try:
            result = run_declarative_report(db, r.id, params, tenant_id=auth.tenant_id)
        except (LookupError, ValueError):
            raise HTTPException(404, "Report not found")
        except ReportSpecError as e:
            raise HTTPException(400, detail={"code": "INVALID_REPORT_SPEC", "errors": e.errors})
    else:
        result = execute_report(db, auth.tenant_id, r, params)
    stamp = date.today().strftime("%Y%m%d")
    if fmt in ("xlsx", "excel"):
        payload = export_report_xlsx(result)
        return Response(
            content=payload,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="report_{report_id}_{stamp}.xlsx"'
            },
        )
    content = "﻿" + export_report_csv(result)
    filename = f"report_{report_id}_{stamp}.csv"
    return StreamingResponse(
        iter([content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{report_id}/export/csv")
def export_csv(
    report_id: UUID,
    params: dict | None = None,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    r = get_report(db, auth.tenant_id, report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    result = execute_report(db, auth.tenant_id, r, params or {})
    csv_text = export_report_csv(result)
    return {"csv": csv_text, "rows": result.get("total_rows", 0)}


@router.get("/schedules/list")
def list_all_schedules(
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    schedules = list_schedules(db, auth.tenant_id)
    return [
        {
            "id": str(s.id),
            "report_id": str(s.report_id),
            "schedule_type": s.schedule_type,
            "cron_expression": s.cron_expression,
            "recipients": s.recipients,
            "output_format": s.output_format,
            "is_active": s.is_active,
            "last_run_at": str(s.last_run_at) if s.last_run_at else None,
        }
        for s in schedules
    ]


@router.post("/schedules")
def create_new_schedule(
    body: ScheduleCreateIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    data = body.model_dump(exclude_none=True)
    s = create_schedule(db, auth.tenant_id, data)
    db.commit()
    return {"id": str(s.id), "schedule_type": s.schedule_type}


@router.patch("/schedules/{schedule_id}")
def patch_schedule(
    schedule_id: UUID,
    body: ScheduleUpdateIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    s = get_schedule(db, auth.tenant_id, schedule_id)
    if not s:
        raise HTTPException(404, "Schedule not found")
    data = body.model_dump(exclude_none=True)
    s = update_schedule(db, s, data)
    db.commit()
    return {"id": str(s.id), "updated": True}


@router.delete("/schedules/{schedule_id}")
def remove_schedule(
    schedule_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    s = get_schedule(db, auth.tenant_id, schedule_id)
    if not s:
        raise HTTPException(404, "Schedule not found")
    delete_schedule(db, s)
    db.commit()
    return {"deleted": True}
