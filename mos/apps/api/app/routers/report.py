"""Phase 6 — Report engine API endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.security import AuthContext, require_module
from app.services.report_engine import (
    create_report,
    create_schedule,
    delete_report,
    delete_schedule,
    execute_report,
    export_report_csv,
    get_report,
    get_schedule,
    list_reports,
    list_schedules,
    seed_system_reports,
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


class ReportUpdateIn(BaseModel):
    report_name: str | None = None
    query: str | None = None
    parameters: dict | None = None
    columns: list | None = None
    filters: list | None = None
    sort: list | None = None
    template: str | None = None
    description: str | None = None


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
    r = create_report(db, auth.tenant_id, data)
    db.commit()
    return {"id": str(r.id), "report_name": r.report_name}


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
    r = update_report(db, r, data)
    db.commit()
    return {"id": str(r.id), "updated": True}


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
