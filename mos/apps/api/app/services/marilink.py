"""MariLink ship-shore communication service.

Handles terminal registration, report submission/review,
and auto-import of ship reports into operational models.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.models_shipshore import ShipTerminal, ShipForm, ShipReport


# ── Terminal Management ──


def register_terminal(
    db: Session,
    tenant_id: UUID,
    vessel_id: UUID,
    device_info: dict | None = None,
    sw_version: str | None = None,
) -> ShipTerminal:
    """Register a new ship terminal or update existing one."""
    terminal_key = f"T-{vessel_id}-{uuid4().hex[:8]}"
    terminal = ShipTerminal(
        tenant_id=tenant_id,
        vessel_id=vessel_id,
        terminal_key=terminal_key,
        device_info=device_info,
        sw_version=sw_version,
        status="active",
    )
    db.add(terminal)
    db.commit()
    db.refresh(terminal)
    return terminal


def terminal_heartbeat(
    db: Session,
    terminal_id: UUID,
    position: dict | None = None,
    offline_queue_size: int = 0,
) -> ShipTerminal:
    """Update terminal heartbeat with position and sync status."""
    terminal = db.get(ShipTerminal, terminal_id)
    if not terminal:
        raise ValueError("Terminal not found")
    terminal.last_sync_at = datetime.now()
    if position:
        terminal.last_position = position
    terminal.offline_queue_size = offline_queue_size
    db.commit()
    db.refresh(terminal)
    return terminal


def get_vessel_terminals(db: Session, tenant_id: UUID, vessel_id: UUID) -> list[ShipTerminal]:
    """Get all terminals for a vessel."""
    stmt = select(ShipTerminal).where(
        and_(
            ShipTerminal.tenant_id == tenant_id,
            ShipTerminal.vessel_id == vessel_id,
        )
    )
    return list(db.scalars(stmt).all())


# ── Form Templates ──


def create_form(
    db: Session,
    tenant_id: UUID,
    form_type: str,
    form_name: str,
    schema_json: dict,
    fields_json: list | None = None,
    auto_import: bool = False,
    target_model: str | None = None,
    created_by: UUID | None = None,
) -> ShipForm:
    """Create a configurable form template."""
    form = ShipForm(
        tenant_id=tenant_id,
        form_type=form_type,
        form_name=form_name,
        schema_json=schema_json,
        fields_json=fields_json,
        auto_import=auto_import,
        target_model=target_model,
        created_by=created_by,
    )
    db.add(form)
    db.commit()
    db.refresh(form)
    return form


def get_active_forms(db: Session, tenant_id: UUID, form_type: str | None = None) -> list[ShipForm]:
    """Get active form templates."""
    stmt = select(ShipForm).where(
        and_(
            ShipForm.tenant_id == tenant_id,
            ShipForm.is_active.is_(True),
        )
    )
    if form_type:
        stmt = stmt.where(ShipForm.form_type == form_type)
    stmt = stmt.order_by(ShipForm.sort_order)
    return list(db.scalars(stmt).all())


# ── Report Submission & Review ──


def submit_report(
    db: Session,
    tenant_id: UUID,
    terminal_id: UUID,
    form_id: UUID,
    form_type: str,
    data_json: dict,
    submitted_by: str,
    voyage_id: UUID | None = None,
    position: dict | None = None,
) -> ShipReport:
    """Submit a report from ship terminal."""
    today = datetime.now().strftime("%Y%m%d")
    count = db.scalars(
        select(ShipReport).where(
            and_(
                ShipReport.tenant_id == tenant_id,
                ShipReport.form_type == form_type,
                ShipReport.report_ref.like(f"%{today}%"),
            )
        )
    ).all()
    seq = len(count) + 1
    type_prefix = {
        "noon_report": "NR",
        "bunker_report": "BR",
        "rob_report": "ROB",
        "incident": "INC",
        "arrival_notice": "ARR",
        "departure_report": "DEP",
    }.get(form_type, "RPT")
    report_ref = f"{type_prefix}-{today}-{seq:03d}"

    report = ShipReport(
        tenant_id=tenant_id,
        terminal_id=terminal_id,
        form_id=form_id,
        voyage_id=voyage_id,
        form_type=form_type,
        report_ref=report_ref,
        submitted_by=submitted_by,
        data_json=data_json,
        position=position,
        status="submitted",
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def review_report(
    db: Session,
    report_id: UUID,
    reviewer_id: UUID,
    approved: bool,
    notes: str | None = None,
) -> ShipReport:
    """Review (approve/reject) a submitted report.

    If approved and form has auto_import, imports data into target model.
    """
    report = db.get(ShipReport, report_id)
    if not report:
        raise ValueError("Report not found")
    if report.status != "submitted":
        raise ValueError(f"Report already {report.status}")

    report.reviewed_by = reviewer_id
    report.reviewed_at = datetime.now()
    report.review_notes = notes

    if approved:
        report.status = "approved"
        form = db.get(ShipForm, report.form_id)
        if form and form.auto_import and form.target_model:
            result = _auto_import_report(db, report, form)
            if result:
                report.imported_model = form.target_model
                report.imported_id = result
    else:
        report.status = "rejected"

    db.commit()
    db.refresh(report)
    return report


def _auto_import_report(
    db: Session, report: ShipReport, form: ShipForm
) -> dict | None:
    """Auto-import report data into target operational model."""
    data = report.data_json

    if form.target_model == "noon_report":
        return _import_noon_report(db, report, data)
    elif form.target_model == "bunker_order":
        return _import_bunker_report(db, report, data)
    return None


def _import_noon_report(db: Session, report: ShipReport, data: dict) -> dict | None:
    """Import noon report data into NoonReport model."""
    from app.models_domain import NoonReport

    if not report.voyage_id:
        return None

    nr = NoonReport(
        tenant_id=report.tenant_id,
        voyage_id=report.voyage_id,
        report_at=report.submitted_at,
        lat=data.get("lat"),
        lon=data.get("lon"),
        speed=data.get("speed"),
        rob_fo=data.get("rob_fo"),
        rob_do=data.get("rob_do"),
        eta_next=data.get("eta_next"),
        remarks=data.get("remarks"),
        wind_bf=data.get("wind_bf"),
        sea_state=data.get("sea_state"),
        current_kn=data.get("current_kn"),
        eta_deviation_hours=data.get("eta_deviation_hours"),
    )
    db.add(nr)
    db.flush()
    return {"id": str(nr.id), "model": "NoonReport"}


def _import_bunker_report(db: Session, report: ShipReport, data: dict) -> dict | None:
    """Import bunker report data into BunkerOrder model."""
    from app.models_domain import BunkerOrder

    terminal = db.get(ShipTerminal, report.terminal_id)
    if not terminal:
        return None

    bo = BunkerOrder(
        tenant_id=report.tenant_id,
        order_no=f"AUTO-{report.report_ref}",
        vessel_id=terminal.vessel_id,
        voyage_id=report.voyage_id,
        grade=data.get("grade", "VLSFO"),
        qty_ordered=data.get("qty_ordered"),
        rob_before=data.get("rob_before"),
        supplier=data.get("supplier"),
        bdn_date=data.get("bdn_date"),
        sulphur_pct=data.get("sulphur_pct"),
        density_kg_m3=data.get("density"),
    )
    db.add(bo)
    db.flush()
    return {"id": str(bo.id), "model": "BunkerOrder"}


def get_reports(
    db: Session,
    tenant_id: UUID,
    form_type: str | None = None,
    status: str | None = None,
    vessel_id: UUID | None = None,
) -> list[ShipReport]:
    """Get ship reports with optional filters."""
    stmt = select(ShipReport).where(ShipReport.tenant_id == tenant_id)
    if form_type:
        stmt = stmt.where(ShipReport.form_type == form_type)
    if status:
        stmt = stmt.where(ShipReport.status == status)
    if vessel_id:
        terminal_ids = [
            t.id for t in get_vessel_terminals(db, tenant_id, vessel_id)
        ]
        if terminal_ids:
            stmt = stmt.where(ShipReport.terminal_id.in_(terminal_ids))
    stmt = stmt.order_by(ShipReport.submitted_at.desc())
    return list(db.scalars(stmt).all())


# ── Preset form templates ──

NOON_REPORT_SCHEMA = {
    "type": "object",
    "required": ["lat", "lon", "speed", "rob_fo", "rob_do"],
    "properties": {
        "lat": {"type": "number", "title": "Latitude"},
        "lon": {"type": "number", "title": "Longitude"},
        "speed": {"type": "number", "title": "Speed (knots)"},
        "rob_fo": {"type": "number", "title": "ROB Fuel Oil (MT)"},
        "rob_do": {"type": "number", "title": "ROB Diesel Oil (MT)"},
        "eta_next": {"type": "string", "format": "date-time", "title": "ETA Next Port"},
        "wind_bf": {"type": "number", "title": "Wind (Beaufort)"},
        "sea_state": {"type": "string", "title": "Sea State"},
        "current_kn": {"type": "number", "title": "Current (knots)"},
        "remarks": {"type": "string", "title": "Remarks"},
        "eta_deviation_hours": {"type": "number", "title": "ETA Deviation (hours)"},
    },
}

NOON_REPORT_FIELDS = [
    {"key": "lat", "label": "Latitude", "type": "number", "required": True},
    {"key": "lon", "label": "Longitude", "type": "number", "required": True},
    {"key": "speed", "label": "Speed (knots)", "type": "number", "required": True},
    {"key": "rob_fo", "label": "ROB Fuel Oil (MT)", "type": "number", "required": True},
    {"key": "rob_do", "label": "ROB Diesel Oil (MT)", "type": "number", "required": True},
    {"key": "eta_next", "label": "ETA Next Port", "type": "datetime"},
    {"key": "wind_bf", "label": "Wind (Beaufort)", "type": "number"},
    {"key": "sea_state", "label": "Sea State", "type": "string"},
    {"key": "current_kn", "label": "Current (knots)", "type": "number"},
    {"key": "remarks", "label": "Remarks", "type": "text"},
    {"key": "eta_deviation_hours", "label": "ETA Deviation (hours)", "type": "number"},
]


def seed_preset_forms(db: Session, tenant_id: UUID, created_by: UUID | None = None):
    """Seed preset form templates for a tenant."""
    create_form(
        db,
        tenant_id=tenant_id,
        form_type="noon_report",
        form_name="Noon Report",
        schema_json=NOON_REPORT_SCHEMA,
        fields_json=NOON_REPORT_FIELDS,
        auto_import=True,
        target_model="noon_report",
        created_by=created_by,
    )
    create_form(
        db,
        tenant_id=tenant_id,
        form_type="bunker_report",
        form_name="Bunker ROB Report",
        schema_json={
            "type": "object",
            "required": ["grade", "rob_before"],
            "properties": {
                "grade": {"type": "string", "title": "Grade"},
                "rob_before": {"type": "number", "title": "ROB Before (MT)"},
                "qty_ordered": {"type": "number", "title": "Qty Ordered (MT)"},
                "supplier": {"type": "string", "title": "Supplier"},
                "bdn_date": {"type": "string", "format": "date-time", "title": "BDN Date"},
                "sulphur_pct": {"type": "number", "title": "Sulphur (%)"},
                "density": {"type": "number", "title": "Density (kg/m3)"},
            },
        },
        fields_json=[
            {"key": "grade", "label": "Grade", "type": "select", "options": ["VLSFO", "MGO", "HFO"], "required": True},
            {"key": "rob_before", "label": "ROB Before (MT)", "type": "number", "required": True},
            {"key": "qty_ordered", "label": "Qty Ordered (MT)", "type": "number"},
            {"key": "supplier", "label": "Supplier", "type": "string"},
            {"key": "bdn_date", "label": "BDN Date", "type": "datetime"},
            {"key": "sulphur_pct", "label": "Sulphur (%)", "type": "number"},
            {"key": "density", "label": "Density (kg/m3)", "type": "number"},
        ],
        auto_import=True,
        target_model="bunker_order",
        created_by=created_by,
    )
    create_form(
        db,
        tenant_id=tenant_id,
        form_type="incident",
        form_name="Incident Report",
        schema_json={
            "type": "object",
            "required": ["incident_type", "description"],
            "properties": {
                "incident_type": {"type": "string", "title": "Incident Type"},
                "description": {"type": "string", "title": "Description"},
                "severity": {"type": "string", "title": "Severity"},
                "actions_taken": {"type": "string", "title": "Actions Taken"},
            },
        },
        fields_json=[
            {"key": "incident_type", "label": "Incident Type", "type": "select", "options": ["machinery", "cargo", "personnel", "environmental", "security", "other"], "required": True},
            {"key": "description", "label": "Description", "type": "text", "required": True},
            {"key": "severity", "label": "Severity", "type": "select", "options": ["low", "medium", "high", "critical"]},
            {"key": "actions_taken", "label": "Actions Taken", "type": "text"},
        ],
        created_by=created_by,
    )
