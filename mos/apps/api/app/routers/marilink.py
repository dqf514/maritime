"""MariLink ship-shore communication API endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.security import AuthContext, require_module
from app.db import get_db
from app.models_shipshore import ShipTerminal, ShipForm, ShipReport
from app.services import marilink

router = APIRouter(prefix="/api/v1/marilink", tags=["marilink"])


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

    stmt = select(ShipTerminal).where(ShipTerminal.tenant_id == auth.tenant_id)
    if vessel_id:
        stmt = stmt.where(ShipTerminal.vessel_id == vessel_id)
    terminals = db.scalars(stmt).all()
    return [
        TerminalOut(
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
        for t in terminals
    ]


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
    return TerminalOut(
        id=str(terminal.id),
        vessel_id=str(terminal.vessel_id),
        terminal_key=terminal.terminal_key,
        device_info=terminal.device_info,
        sw_version=terminal.sw_version,
        last_sync_at=terminal.last_sync_at.isoformat() if terminal.last_sync_at else None,
        last_position=terminal.last_position,
        offline_queue_size=terminal.offline_queue_size,
        status=terminal.status,
    )


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
    return [
        FormOut(
            id=str(f.id),
            form_type=f.form_type,
            form_name=f.form_name,
            form_schema=f.schema_json,
            fields_json=f.fields_json,
            auto_import=f.auto_import,
            target_model=f.target_model,
            is_active=f.is_active,
        )
        for f in forms
    ]


@router.post("/forms", response_model=FormOut, status_code=201)
def create_form(
    body: FormIn,
    auth: AuthContext = Depends(require_module("admin")),
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
    return FormOut(
        id=str(form.id),
        form_type=form.form_type,
        form_name=form.form_name,
        form_schema=form.schema_json,
        fields_json=form.fields_json,
        auto_import=form.auto_import,
        target_model=form.target_model,
        is_active=form.is_active,
    )


@router.post("/forms/seed-presets", status_code=201)
def seed_preset_forms(
    auth: AuthContext = Depends(require_module("admin")),
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
    """List ship reports."""
    reports = marilink.get_reports(db, auth.tenant_id, form_type, status, vessel_id)
    return [
        ReportOut(
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
        )
        for r in reports
    ]


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
    return ReportOut(
        id=str(report.id),
        terminal_id=str(report.terminal_id),
        form_id=str(report.form_id),
        voyage_id=str(report.voyage_id) if report.voyage_id else None,
        form_type=report.form_type,
        report_ref=report.report_ref,
        submitted_at=report.submitted_at.isoformat(),
        submitted_by=report.submitted_by,
        data_json=report.data_json,
        position=report.position,
        status=report.status,
        reviewed_by=None,
        reviewed_at=None,
        review_notes=None,
        imported_model=None,
        imported_id=None,
    )


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
    return ReportOut(
        id=str(report.id),
        terminal_id=str(report.terminal_id),
        form_id=str(report.form_id),
        voyage_id=str(report.voyage_id) if report.voyage_id else None,
        form_type=report.form_type,
        report_ref=report.report_ref,
        submitted_at=report.submitted_at.isoformat(),
        submitted_by=report.submitted_by,
        data_json=report.data_json,
        position=report.position,
        status=report.status,
        reviewed_by=str(report.reviewed_by) if report.reviewed_by else None,
        reviewed_at=report.reviewed_at.isoformat() if report.reviewed_at else None,
        review_notes=report.review_notes,
        imported_model=report.imported_model,
        imported_id=report.imported_id,
    )
