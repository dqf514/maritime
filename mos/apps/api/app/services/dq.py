"""Data-quality rule engine — auto-detect master/finance data gaps into DqIssue rows."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models_domain import DqIssue, Invoice, Voyage
from app.models_wave1 import Counterparty, Port, Vessel

AUTO_RULES = (
    "vessel_missing_imo",
    "vessel_missing_flag",
    "vessel_missing_speed",
    "port_missing_coords",
    "port_missing_unlocode",
    "counterparty_missing_country",
    "invoice_missing_due_date",
    "voyage_no_vessel",
)


def _findings(db: Session, tenant_id: UUID) -> list[tuple[str, str, str, str]]:
    """Current violations as (rule_code, entity_type, entity_id, message)."""
    out: list[tuple[str, str, str, str]] = []
    vessels = db.scalars(
        select(Vessel).where(
            Vessel.tenant_id == tenant_id,
            Vessel.status == "active",
            Vessel.deleted_at.is_(None),
        )
    ).all()
    for v in vessels:
        if not v.imo:
            out.append(("vessel_missing_imo", "vessel", str(v.id), f"Vessel {v.name} has no IMO number"))
        if not v.flag:
            out.append(("vessel_missing_flag", "vessel", str(v.id), f"Vessel {v.name} has no flag"))
        if v.speed_knots is None:
            out.append(("vessel_missing_speed", "vessel", str(v.id), f"Vessel {v.name} has no service speed"))
    ports = db.scalars(select(Port).where(Port.deleted_at.is_(None))).all()
    for p in ports:
        if p.latitude is None or p.longitude is None:
            out.append(("port_missing_coords", "port", str(p.id), f"Port {p.name} has no coordinates"))
        if not p.unlocode:
            out.append(("port_missing_unlocode", "port", str(p.id), f"Port {p.name} has no UN/LOCODE"))
    parties = db.scalars(
        select(Counterparty).where(Counterparty.tenant_id == tenant_id, Counterparty.deleted_at.is_(None))
    ).all()
    for c in parties:
        if not c.country:
            out.append(("counterparty_missing_country", "counterparty", str(c.id), f"Counterparty {c.name} has no country"))
    invoices = db.scalars(
        select(Invoice).where(
            Invoice.tenant_id == tenant_id,
            Invoice.status == "issued",
            Invoice.due_date.is_(None),
        )
    ).all()
    for i in invoices:
        out.append(("invoice_missing_due_date", "invoice", str(i.id), f"Invoice {i.invoice_no} issued without due date"))
    voyages = db.scalars(
        select(Voyage).where(
            Voyage.tenant_id == tenant_id,
            Voyage.status == "in_progress",
            Voyage.vessel_id.is_(None),
        )
    ).all()
    for v in voyages:
        out.append(("voyage_no_vessel", "voyage", str(v.id), f"Voyage {v.voyage_no} in progress without a vessel"))
    return out


def run_dq_scan(db: Session, tenant_id: UUID) -> dict:
    """Sync DqIssue rows with current rule violations.

    Open auto issues whose violation disappeared are resolved; violations
    without an open issue create one (same rule+entity is never duplicated).
    """
    findings = _findings(db, tenant_id)
    found_keys = {(rule, etype, eid) for rule, etype, eid, _ in findings}

    open_rows = db.scalars(
        select(DqIssue).where(
            DqIssue.tenant_id == tenant_id,
            DqIssue.status == "open",
            DqIssue.rule_code.in_(AUTO_RULES),
        )
    ).all()
    open_keys = {(r.rule_code, r.entity_type, r.entity_id) for r in open_rows}

    resolved = 0
    for row in open_rows:
        if (row.rule_code, row.entity_type, row.entity_id) not in found_keys:
            row.status = "resolved"
            resolved += 1
    new = 0
    messages = {(rule, etype, eid): msg for rule, etype, eid, msg in findings}
    for key in sorted(found_keys - open_keys):
        rule, etype, eid = key
        db.add(
            DqIssue(
                tenant_id=tenant_id,
                rule_code=rule,
                entity_type=etype,
                entity_id=eid,
                severity="warn",
                status="open",
                message=messages[key],
            )
        )
        new += 1
    db.commit()
    open_total = db.scalar(
        select(func.count())
        .select_from(DqIssue)
        .where(DqIssue.tenant_id == tenant_id, DqIssue.status == "open")
    ) or 0
    return {"new": new, "resolved": resolved, "open_total": open_total}


def open_issue_count(db: Session, tenant_id: UUID) -> int:
    return db.scalar(
        select(func.count()).select_from(DqIssue).where(DqIssue.tenant_id == tenant_id, DqIssue.status == "open")
    ) or 0
