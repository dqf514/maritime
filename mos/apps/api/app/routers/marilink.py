"""MariLink ship-shore communication API endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.security import AuthContext, require_module, require_roles
from app.db import get_db
from app.models_shipshore import ShipTerminal, ShipForm, ShipReport
from app.services import marilink
from app.services.recycle import soft_delete


def _terminal_out(t: ShipTerminal) -> TerminalOut:
    return TerminalOut(
        id=str(t.id),
        vessel_id=str(t.vessel_id),
        terminal_key=t.terminal_key,
        device_info=t.device_info,
        sw_version=t.sw_version,
        last_sync_at=t.last_sync_at.isoformat() if t.last_sync_at else None,
        last_position=t.last_position,
        offline_queue_size=t.offline_queue_size,
        status=t.status,
    )


def _form_out(f: ShipForm) -> FormOut:
    return FormOut(
        id=str(f.id),
        form_type=f.form_type,
        form_name=f.form_name,
        form_schema=f.schema_json,
        fields_json=f.fields_json,
        auto_import=f.auto_import,
        target_model=f.target_model,
        is_active=f.is_active,
    )


def _report_out(r: ShipReport) -> ReportOut:
    return ReportOut(
        id=str(r.id),
        terminal_id=str(r.terminal_id),
        form_id=str(r.form_id),
        voyage_id=str(r.voyage_id) if r.voyage_id else None,
        form_type=r.form_type,
        report_ref=r.report_ref,
        submitted_at=r.submitted_at.isoformat(),
        submitted_by=r.submitted_by,
        data_json=r.data_json,
        position=r.position,
        status=r.status,
        reviewed_by=str(r.reviewed_by) if r.reviewed_by else None,
        reviewed_at=r.reviewed_at.isoformat() if r.reviewed_at else None,
        review_notes=r.review_notes,
        imported_model=r.imported_model,
        imported_id=r.imported_id,
        updated_at=r.updated_at.isoformat() if r.updated_at else None,
    )

# 无自前缀：main.py 以 /api/v1 统一挂载（此前双前缀导致路由落在 /api/v1/api/v1/marilink/...，前端调不通）
router = APIRouter(prefix="/marilink", tags=["marilink"])


# ── Terminal Management ──


class TerminalOut(BaseModel):
    id: str
    vessel_id: str
    terminal_key: str
    device_info: dict | None
    sw_version: str | None
    last_sync_at: str | None
    last_position: dict | None
    offline_queue_size: int
    status: str


class TerminalRegisterIn(BaseModel):
    vessel_id: str
    device_info: dict | None = None
    sw_version: str | None = None


@router.get("/terminals", response_model=list[TerminalOut])
def list_terminals(
    vessel_id: UUID | None = Query(None),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """List ship terminals."""
    from sqlalchemy import select

    stmt = select(ShipTerminal).where(
        ShipTerminal.tenant_id == auth.tenant_id, ShipTerminal.status != "deleted"
    )
    if vessel_id:
        stmt = stmt.where(ShipTerminal.vessel_id == vessel_id)
    terminals = db.scalars(stmt).all()
    return [_terminal_out(t) for t in terminals]


@router.post("/terminals", response_model=TerminalOut, status_code=201)
def register_terminal(
    body: TerminalRegisterIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """Register a new ship terminal."""
    terminal = marilink.register_terminal(
        db,
        tenant_id=auth.tenant_id,
        vessel_id=UUID(body.vessel_id),
        device_info=body.device_info,
        sw_version=body.sw_version,
    )
    return _terminal_out(terminal)


@router.post("/terminals/{terminal_id}/heartbeat")
def terminal_heartbeat(
    terminal_id: UUID,
    position: dict | None = Body(None),
    offline_queue_size: int = Body(0),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """Update terminal heartbeat."""
    try:
        terminal = marilink.terminal_heartbeat(
            db, terminal_id, position, offline_queue_size
        )
        return {"ok": True, "last_sync_at": terminal.last_sync_at.isoformat()}
    except ValueError as e:
        raise HTTPException(404, str(e))


class TerminalUpdateIn(BaseModel):
    vessel_id: str | None = None
    device_info: dict | None = None
    sw_version: str | None = None
    status: str | None = None


@router.patch("/terminals/{terminal_id}", response_model=TerminalOut)
def update_terminal(
    terminal_id: UUID,
    body: TerminalUpdateIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """Partial update — only explicitly provided fields are applied (model_fields_set)."""
    from app.models_wave1 import Vessel

    terminal = db.get(ShipTerminal, terminal_id)
    if not terminal or terminal.tenant_id != auth.tenant_id or terminal.status == "deleted":
        raise HTTPException(404, "Terminal not found")
    fields = body.model_fields_set
    if "vessel_id" in fields and body.vessel_id is not None:
        try:
            vessel_id = UUID(body.vessel_id)
        except ValueError:
            raise HTTPException(422, "Invalid vessel_id")
        vessel = db.get(Vessel, vessel_id)
        if (
            not vessel
            or vessel.tenant_id != auth.tenant_id
            or vessel.status == "deleted"
            or getattr(vessel, "deleted_at", None) is not None
        ):
            raise HTTPException(404, "Vessel not found")
        terminal.vessel_id = vessel_id
    if "device_info" in fields:
        terminal.device_info = body.device_info
    if "sw_version" in fields:
        terminal.sw_version = body.sw_version
    if "status" in fields and body.status is not None:
        if body.status not in ("active", "inactive", "maintenance"):
            raise HTTPException(422, "status must be active|inactive|maintenance")
        terminal.status = body.status
    db.commit()
    db.refresh(terminal)
    return _terminal_out(terminal)


@router.delete("/terminals/{terminal_id}")
def delete_terminal(
    terminal_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """Soft-delete a ship terminal (recycle bin)."""
    terminal = db.get(ShipTerminal, terminal_id)
    if not terminal or terminal.tenant_id != auth.tenant_id or terminal.status == "deleted":
        raise HTTPException(404, "Terminal not found")
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="ship_terminal",
        row=terminal,
        title=terminal.terminal_key,
    )
    db.commit()
    return {"ok": True, "recycled": True}


# ── Form Templates ──


class FormOut(BaseModel):
    id: str
    form_type: str
    form_name: str
    form_schema: dict
    fields_json: list | None
    auto_import: bool
    target_model: str | None
    is_active: bool


class FormIn(BaseModel):
    form_type: str
    form_name: str
    form_schema: dict
    fields_json: list | None = None
    auto_import: bool = False
    target_model: str | None = None


@router.get("/forms", response_model=list[FormOut])
def list_forms(
    form_type: str | None = Query(None),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """List active form templates."""
    forms = marilink.get_active_forms(db, auth.tenant_id, form_type)
    return [_form_out(f) for f in forms]


@router.post("/forms", response_model=FormOut, status_code=201)
def create_form(
    body: FormIn,
    auth: AuthContext = Depends(require_roles("tenant_admin", "platform_admin")),
    db: Session = Depends(get_db),
):
    """Create a new form template."""
    form = marilink.create_form(
        db,
        tenant_id=auth.tenant_id,
        form_type=body.form_type,
        form_name=body.form_name,
        schema_json=body.form_schema,
        fields_json=body.fields_json,
        auto_import=body.auto_import,
        target_model=body.target_model,
        created_by=auth.user_id,
    )
    return _form_out(form)


class FormUpdateIn(BaseModel):
    form_type: str | None = None
    form_name: str | None = None
    form_schema: dict | None = None
    fields_json: list | None = None
    auto_import: bool | None = None
    target_model: str | None = None
    is_active: bool | None = None


@router.patch("/forms/{form_id}", response_model=FormOut)
def update_form(
    form_id: UUID,
    body: FormUpdateIn,
    auth: AuthContext = Depends(require_roles("tenant_admin", "platform_admin")),
    db: Session = Depends(get_db),
):
    """Partial update — only explicitly provided fields are applied (model_fields_set)."""
    form = db.get(ShipForm, form_id)
    if not form or form.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Form not found")
    fields = body.model_fields_set
    if "form_type" in fields and body.form_type is not None:
        form.form_type = body.form_type
    if "form_name" in fields and body.form_name is not None:
        form.form_name = body.form_name
    if "form_schema" in fields and body.form_schema is not None:
        form.schema_json = body.form_schema
    if "fields_json" in fields:
        form.fields_json = body.fields_json
    if "auto_import" in fields and body.auto_import is not None:
        form.auto_import = body.auto_import
    if "target_model" in fields:
        form.target_model = body.target_model
    if "is_active" in fields and body.is_active is not None:
        form.is_active = body.is_active
    db.commit()
    db.refresh(form)
    return _form_out(form)


@router.delete("/forms/{form_id}")
def delete_form(
    form_id: UUID,
    auth: AuthContext = Depends(require_roles("tenant_admin", "platform_admin")),
    db: Session = Depends(get_db),
):
    """Delete a form template.

    Hard delete when no submitted reports reference it (FK ship_reports.form_id);
    reports referencing a template block deletion with 409.
    """
    form = db.get(ShipForm, form_id)
    if not form or form.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Form not found")
    from sqlalchemy import func, select

    ref_count = db.scalar(
        select(func.count())
        .select_from(ShipReport)
        .where(ShipReport.form_id == form_id, ShipReport.status != "deleted")
    ) or 0
    if ref_count:
        raise HTTPException(
            409,
            detail={"code": "FORM_IN_USE", "message": f"form referenced by {ref_count} report(s)"},
        )
    db.delete(form)
    db.commit()
    return {"ok": True}


@router.post("/forms/seed-presets", status_code=201)
def seed_preset_forms(
    auth: AuthContext = Depends(require_roles("tenant_admin", "platform_admin")),
    db: Session = Depends(get_db),
):
    """Seed preset form templates."""
    marilink.seed_preset_forms(db, auth.tenant_id, auth.user_id)
    return {"ok": True, "message": "Preset form templates seeded"}


# ── Reports ──


class ReportOut(BaseModel):
    id: str
    terminal_id: str
    form_id: str
    voyage_id: str | None
    form_type: str
    report_ref: str
    submitted_at: str
    submitted_by: str
    data_json: dict
    position: dict | None
    status: str
    reviewed_by: str | None
    reviewed_at: str | None
    review_notes: str | None
    imported_model: str | None
    imported_id: dict | None
    updated_at: str | None = None


class ReportSubmitIn(BaseModel):
    terminal_id: str
    form_id: str
    form_type: str
    data_json: dict
    submitted_by: str
    voyage_id: str | None = None
    position: dict | None = None


@router.get("/reports", response_model=list[ReportOut])
def list_reports(
    form_type: str | None = Query(None),
    status: str | None = Query(None),
    vessel_id: UUID | None = Query(None),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """List ship reports (soft-deleted rows excluded)."""
    reports = marilink.get_reports(db, auth.tenant_id, form_type, status, vessel_id)
    return [_report_out(r) for r in reports if r.status != "deleted"]


@router.post("/reports", response_model=ReportOut, status_code=201)
def submit_report(
    body: ReportSubmitIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """Submit a report from ship terminal."""
    report = marilink.submit_report(
        db,
        tenant_id=auth.tenant_id,
        terminal_id=UUID(body.terminal_id),
        form_id=UUID(body.form_id),
        form_type=body.form_type,
        data_json=body.data_json,
        submitted_by=body.submitted_by,
        voyage_id=UUID(body.voyage_id) if body.voyage_id else None,
        position=body.position,
    )
    return _report_out(report)


class ReviewIn(BaseModel):
    approved: bool
    notes: str | None = None


@router.post("/reports/{report_id}/review", response_model=ReportOut)
def review_report(
    report_id: UUID,
    body: ReviewIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """Review (approve/reject) a ship report."""
    try:
        report = marilink.review_report(
            db, report_id, auth.user_id, body.approved, body.notes
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _report_out(report)


class ReportUpdateIn(BaseModel):
    data_json: dict | None = None
    position: dict | None = None
    voyage_id: str | None = None
    form_type: str | None = None
    submitted_by: str | None = None
    review_notes: str | None = None


@router.patch("/reports/{report_id}", response_model=ReportOut)
def update_report(
    report_id: UUID,
    body: ReportUpdateIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """Partial update — only explicitly provided fields (model_fields_set).

    Approved/rejected reports are locked (state guard 409); status transitions
    go through /reports/{id}/review.
    """
    report = db.get(ShipReport, report_id)
    if not report or report.tenant_id != auth.tenant_id or report.status == "deleted":
        raise HTTPException(404, "Report not found")
    if report.status in ("approved", "rejected"):
        raise HTTPException(
            409,
            detail={"code": "REPORT_LOCKED", "message": f"report already {report.status}"},
        )
    fields = body.model_fields_set
    if "data_json" in fields and body.data_json is not None:
        report.data_json = body.data_json
    if "position" in fields:
        report.position = body.position
    if "voyage_id" in fields:
        report.voyage_id = UUID(body.voyage_id) if body.voyage_id else None
    if "form_type" in fields and body.form_type is not None:
        report.form_type = body.form_type
    if "submitted_by" in fields and body.submitted_by is not None:
        report.submitted_by = body.submitted_by
    if "review_notes" in fields:
        report.review_notes = body.review_notes
    db.commit()
    db.refresh(report)
    return _report_out(report)


@router.delete("/reports/{report_id}")
def delete_report(
    report_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """Soft-delete a ship report (recycle bin)."""
    report = db.get(ShipReport, report_id)
    if not report or report.tenant_id != auth.tenant_id or report.status == "deleted":
        raise HTTPException(404, "Report not found")
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="ship_report",
        row=report,
        title=report.report_ref,
    )
    db.commit()
    return {"ok": True, "recycled": True}
