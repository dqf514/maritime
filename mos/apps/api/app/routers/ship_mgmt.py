"""Ship management APIs + external PMS integration stubs."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_domain import ScheduleBlock
from app.models_ship import (
    ExternalPmsSyncLog,
    ShipCertificate,
    ShipCrewMember,
    ShipDefect,
    ShipSparePart,
    ShipTechnicalProfile,
    ShipWorkOrder,
    ShipWoSpare,
)
from app.models_wave1 import Attachment, ConnectorInstance, Vessel
from app.security import AuthContext, require_module
from app.services.audit import audit

router = APIRouter(tags=["Ship Management"])


def _now() -> datetime:
    return datetime.now().astimezone()


CERT_EXPIRING_DAYS = 30
DRYDOCK_BLOCK_DAYS = 14


def _cert_status_for(expires_on: date | None, current: str = "valid") -> str:
    """Three-band lifecycle from expiry; certs without an expiry keep their band."""
    if expires_on is None:
        return current
    today = date.today()
    if expires_on < today:
        return "expired"
    if expires_on < today + timedelta(days=CERT_EXPIRING_DAYS):
        return "expiring"
    return "valid"


def _refresh_certificate_status(db: Session, tenant_id: UUID) -> None:
    """Lazy status migration — recompute bands from expires_on, commit only changed rows."""
    certs = db.scalars(select(ShipCertificate).where(ShipCertificate.tenant_id == tenant_id)).all()
    changed = False
    for c in certs:
        new_status = _cert_status_for(c.expires_on, c.status)
        if new_status != c.status:
            c.status = new_status
            changed = True
    if changed:
        db.commit()


def _sync_drydock_block(db: Session, tenant_id: UUID, vessel_id: UUID, vessel_name: str, drydock_on: date | None) -> None:
    """Keep one repair ScheduleBlock aligned with the profile's next_drydock (idempotent)."""
    blocks = [
        b
        for b in db.scalars(
            select(ScheduleBlock).where(
                ScheduleBlock.tenant_id == tenant_id,
                ScheduleBlock.vessel_id == vessel_id,
                ScheduleBlock.block_type == "repair",
            )
        ).all()
        if (b.meta or {}).get("source") == "drydock_profile"
    ]
    if drydock_on is None:
        for b in blocks:
            db.delete(b)
        return
    start = datetime(drydock_on.year, drydock_on.month, drydock_on.day, tzinfo=timezone.utc)
    end = start + timedelta(days=DRYDOCK_BLOCK_DAYS)
    title = f"Drydock — {vessel_name}"
    if blocks:
        block = blocks[0]
        block.title = title
        block.start_at = start
        block.end_at = end
        for extra in blocks[1:]:
            db.delete(extra)
    else:
        db.add(
            ScheduleBlock(
                tenant_id=tenant_id,
                vessel_id=vessel_id,
                block_type="repair",
                title=title,
                start_at=start,
                end_at=end,
                meta={"source": "drydock_profile"},
            )
        )


class ProfileIn(BaseModel):
    vessel_id: UUID
    management_mode: str = "in_house"
    class_society: str | None = None
    built_year: int | None = None
    yard: str | None = None
    engine_maker: str | None = None
    engine_type: str | None = None
    next_drydock: date | None = None
    next_special_survey: date | None = None
    technical_status: str = "in_service"
    superintendent: str | None = None
    external_pms_id: str | None = None
    external_system: str | None = None
    meta: dict = Field(default_factory=dict)


class WorkOrderIn(BaseModel):
    vessel_id: UUID
    wo_no: str
    title: str
    category: str = "pms"
    priority: str = "medium"
    status: str = "open"
    due_on: date | None = None
    estimated_cost: Decimal | None = None
    assignee: str | None = None
    external_ref: str | None = None
    source: str = "voyageos"
    meta: dict = Field(default_factory=dict)


class CertificateIn(BaseModel):
    vessel_id: UUID
    cert_code: str
    cert_name: str
    issued_on: date | None = None
    expires_on: date | None = None
    status: str = "valid"
    issuing_body: str | None = None
    external_ref: str | None = None


class CertificatePatchIn(BaseModel):
    cert_name: str | None = None
    issued_on: date | None = None
    expires_on: date | None = None
    issuing_body: str | None = None
    external_ref: str | None = None


class WorkOrderPatchIn(BaseModel):
    title: str | None = None
    category: str | None = None
    priority: str | None = None
    status: str | None = None
    due_on: date | None = None
    assignee: str | None = None


class WoSpareIn(BaseModel):
    part_id: UUID
    qty: Decimal = Field(gt=0)


class DefectIn(BaseModel):
    vessel_id: UUID
    defect_no: str
    title: str
    severity: str = "minor"
    status: str = "open"
    found_on: date | None = None
    due_on: date | None = None
    external_ref: str | None = None


class CrewIn(BaseModel):
    vessel_id: UUID | None = None
    full_name: str
    rank: str
    nationality: str | None = None
    contract_end: date | None = None
    status: str = "onboard"
    external_ref: str | None = None
    certificates: list[dict] | None = None  # [{code, expires_on}] e.g. STCW-II/1, GMDSS


class CrewPatchIn(BaseModel):
    vessel_id: UUID | None = None
    full_name: str | None = None
    rank: str | None = None
    nationality: str | None = None
    contract_end: date | None = None
    status: str | None = None
    external_ref: str | None = None
    certificates: list[dict] | None = None


class ExternalSyncIn(BaseModel):
    """Inbound payload from external PMS (adapter contract)."""

    system: str = "custom"
    entity_type: str  # certificate|work_order|defect|crew|spare|profile
    external_ref: str
    vessel_external_id: str | None = None
    vessel_imo: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


def _vessel_or_404(db: Session, tenant_id: UUID, vessel_id: UUID) -> Vessel:
    v = db.get(Vessel, vessel_id)
    if not v or v.tenant_id != tenant_id:
        raise HTTPException(404, "Vessel not found")
    return v


def _wo_or_404(db: Session, tenant_id: UUID, wo_id: UUID) -> ShipWorkOrder:
    wo = db.get(ShipWorkOrder, wo_id)
    if not wo or wo.tenant_id != tenant_id:
        raise HTTPException(404, "Work order not found")
    return wo


def _consume_wo_spares(db: Session, wo: ShipWorkOrder) -> list[str]:
    """Deduct registered spare consumption from stock once per work order.

    Idempotent via the ``spares_consumed`` meta flag; insufficient stock never
    blocks completion, it only produces warnings.
    """
    if (wo.meta or {}).get("spares_consumed"):
        return []
    warnings: list[str] = []
    totals: dict[UUID, Decimal] = {}
    for r in db.scalars(select(ShipWoSpare).where(ShipWoSpare.wo_id == wo.id)).all():
        totals[r.part_id] = totals.get(r.part_id, Decimal(0)) + Decimal(r.qty)
    for part_id, qty in totals.items():
        part = db.get(ShipSparePart, part_id)
        if not part or part.tenant_id != wo.tenant_id:
            continue
        part.qty_on_hand = Decimal(part.qty_on_hand or 0) - qty
        if part.qty_on_hand < 0:
            warnings.append(
                f"Spare {part.part_no} stock insufficient: consumed {qty}, on hand now {part.qty_on_hand}"
            )
        elif part.qty_on_hand < Decimal(part.min_qty or 0):
            warnings.append(f"Spare {part.part_no} below min_qty after consumption: on hand {part.qty_on_hand}")
    wo.meta = {**(wo.meta or {}), "spares_consumed": True}
    return warnings


@router.get("/ship/fleet")
def fleet_overview(
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
):
    vessels = db.scalars(select(Vessel).where(Vessel.tenant_id == auth.tenant_id, Vessel.status == "active")).all()
    _refresh_certificate_status(db, auth.tenant_id)
    profiles = {
        p.vessel_id: p
        for p in db.scalars(select(ShipTechnicalProfile).where(ShipTechnicalProfile.tenant_id == auth.tenant_id)).all()
    }
    open_wo = db.scalars(
        select(ShipWorkOrder).where(
            ShipWorkOrder.tenant_id == auth.tenant_id,
            ShipWorkOrder.status.in_(["open", "in_progress"]),
        )
    ).all()
    certs = db.scalars(select(ShipCertificate).where(ShipCertificate.tenant_id == auth.tenant_id)).all()
    defects = db.scalars(
        select(ShipDefect).where(ShipDefect.tenant_id == auth.tenant_id, ShipDefect.status == "open")
    ).all()

    by_vessel_wo: dict[UUID, int] = {}
    for w in open_wo:
        by_vessel_wo[w.vessel_id] = by_vessel_wo.get(w.vessel_id, 0) + 1
    by_vessel_def: dict[UUID, int] = {}
    for d in defects:
        by_vessel_def[d.vessel_id] = by_vessel_def.get(d.vessel_id, 0) + 1
    expiring = [c for c in certs if c.status in ("expiring", "expired")]

    rows = []
    for v in vessels:
        p = profiles.get(v.id)
        rows.append(
            {
                "vessel_id": str(v.id),
                "name": v.name,
                "imo": v.imo,
                "flag": v.flag,
                "vessel_type": v.vessel_type,
                "dwt": float(v.dwt) if v.dwt is not None else None,
                "technical_status": p.technical_status if p else "in_service",
                "management_mode": p.management_mode if p else "in_house",
                "class_society": p.class_society if p else None,
                "next_drydock": p.next_drydock.isoformat() if p and p.next_drydock else None,
                "superintendent": p.superintendent if p else None,
                "external_system": p.external_system if p else None,
                "open_work_orders": by_vessel_wo.get(v.id, 0),
                "open_defects": by_vessel_def.get(v.id, 0),
                "expiring_certs": sum(1 for c in expiring if c.vessel_id == v.id),
            }
        )
    return {
        "fleet_size": len(rows),
        "open_work_orders": len(open_wo),
        "open_defects": len(defects),
        "expiring_certificates": len(expiring),
        "vessels": rows,
    }


@router.get("/ship/vessels/{vessel_id}")
def vessel_technical(
    vessel_id: UUID,
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
):
    v = _vessel_or_404(db, auth.tenant_id, vessel_id)
    _refresh_certificate_status(db, auth.tenant_id)
    p = db.scalar(
        select(ShipTechnicalProfile).where(
            ShipTechnicalProfile.tenant_id == auth.tenant_id,
            ShipTechnicalProfile.vessel_id == vessel_id,
        )
    )
    certs = db.scalars(
        select(ShipCertificate).where(
            ShipCertificate.tenant_id == auth.tenant_id, ShipCertificate.vessel_id == vessel_id
        )
    ).all()
    wos = db.scalars(
        select(ShipWorkOrder).where(ShipWorkOrder.tenant_id == auth.tenant_id, ShipWorkOrder.vessel_id == vessel_id)
    ).all()
    crew = db.scalars(
        select(ShipCrewMember).where(ShipCrewMember.tenant_id == auth.tenant_id, ShipCrewMember.vessel_id == vessel_id)
    ).all()
    defects = db.scalars(
        select(ShipDefect).where(ShipDefect.tenant_id == auth.tenant_id, ShipDefect.vessel_id == vessel_id)
    ).all()
    spares = db.scalars(
        select(ShipSparePart).where(ShipSparePart.tenant_id == auth.tenant_id, ShipSparePart.vessel_id == vessel_id)
    ).all()
    return {
        "vessel": {
            "id": str(v.id),
            "name": v.name,
            "imo": v.imo,
            "flag": v.flag,
            "vessel_type": v.vessel_type,
            "dwt": float(v.dwt) if v.dwt is not None else None,
        },
        "profile": {
            "management_mode": p.management_mode if p else "in_house",
            "class_society": p.class_society if p else None,
            "built_year": p.built_year if p else None,
            "yard": p.yard if p else None,
            "engine_maker": p.engine_maker if p else None,
            "engine_type": p.engine_type if p else None,
            "next_drydock": p.next_drydock.isoformat() if p and p.next_drydock else None,
            "next_special_survey": p.next_special_survey.isoformat() if p and p.next_special_survey else None,
            "technical_status": p.technical_status if p else "in_service",
            "superintendent": p.superintendent if p else None,
            "external_pms_id": p.external_pms_id if p else None,
            "external_system": p.external_system if p else None,
        }
        if True
        else None,
        "certificates": [
            {
                "id": str(c.id),
                "cert_code": c.cert_code,
                "cert_name": c.cert_name,
                "expires_on": c.expires_on.isoformat() if c.expires_on else None,
                "status": c.status,
                "issuing_body": c.issuing_body,
            }
            for c in certs
        ],
        "work_orders": [
            {
                "id": str(w.id),
                "wo_no": w.wo_no,
                "title": w.title,
                "category": w.category,
                "priority": w.priority,
                "status": w.status,
                "due_on": w.due_on.isoformat() if w.due_on else None,
                "source": w.source,
            }
            for w in wos
        ],
        "crew": [
            {
                "id": str(c.id),
                "full_name": c.full_name,
                "rank": c.rank,
                "nationality": c.nationality,
                "status": c.status,
                "contract_end": c.contract_end.isoformat() if c.contract_end else None,
            }
            for c in crew
        ],
        "defects": [
            {
                "id": str(d.id),
                "defect_no": d.defect_no,
                "title": d.title,
                "severity": d.severity,
                "status": d.status,
                "due_on": d.due_on.isoformat() if d.due_on else None,
            }
            for d in defects
        ],
        "spares": [
            {
                "id": str(s.id),
                "part_no": s.part_no,
                "description": s.description,
                "qty_on_hand": float(s.qty_on_hand),
                "min_qty": float(s.min_qty),
                "below_min": float(s.qty_on_hand) < float(s.min_qty),
            }
            for s in spares
        ],
    }


@router.put("/ship/profiles")
def upsert_profile(
    body: ProfileIn,
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
):
    v = _vessel_or_404(db, auth.tenant_id, body.vessel_id)
    row = db.scalar(
        select(ShipTechnicalProfile).where(
            ShipTechnicalProfile.tenant_id == auth.tenant_id,
            ShipTechnicalProfile.vessel_id == body.vessel_id,
        )
    )
    data = body.model_dump()
    if not row:
        row = ShipTechnicalProfile(tenant_id=auth.tenant_id, **data)
        db.add(row)
    else:
        for k, v2 in data.items():
            setattr(row, k, v2)
        row.updated_at = _now()
    _sync_drydock_block(db, auth.tenant_id, body.vessel_id, v.name, body.next_drydock)
    db.commit()
    return {"ok": True, "vessel_id": str(body.vessel_id)}


@router.get("/ship/work-orders")
def list_work_orders(
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
    status: str | None = None,
):
    q = select(ShipWorkOrder).where(ShipWorkOrder.tenant_id == auth.tenant_id)
    if status:
        q = q.where(ShipWorkOrder.status == status)
    rows = db.scalars(q).all()
    return [
        {
            "id": str(r.id),
            "vessel_id": str(r.vessel_id),
            "wo_no": r.wo_no,
            "title": r.title,
            "category": r.category,
            "priority": r.priority,
            "status": r.status,
            "due_on": r.due_on.isoformat() if r.due_on else None,
            "source": r.source,
            "external_ref": r.external_ref,
        }
        for r in rows
    ]


@router.post("/ship/work-orders")
def create_work_order(
    body: WorkOrderIn,
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
):
    _vessel_or_404(db, auth.tenant_id, body.vessel_id)
    row = ShipWorkOrder(tenant_id=auth.tenant_id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "wo_no": row.wo_no}


@router.patch("/ship/work-orders/{wo_id}")
def update_work_order(
    wo_id: UUID,
    body: WorkOrderPatchIn,
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
):
    wo = _wo_or_404(db, auth.tenant_id, wo_id)
    data = body.model_dump(exclude_unset=True)
    warnings: list[str] = []
    for k, v in data.items():
        setattr(wo, k, v)
    if data.get("status") == "done":
        wo.completed_on = wo.completed_on or date.today()
        warnings = _consume_wo_spares(db, wo)
    db.commit()
    return {"id": str(wo.id), "status": wo.status, "warnings": warnings}


@router.post("/ship/work-orders/{wo_id}/spares")
def register_wo_spare(
    wo_id: UUID,
    body: WoSpareIn,
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
):
    """Register planned spare consumption; stock is deducted when the WO completes."""
    wo = _wo_or_404(db, auth.tenant_id, wo_id)
    part = db.get(ShipSparePart, body.part_id)
    if not part or part.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Spare part not found")
    row = ShipWoSpare(tenant_id=auth.tenant_id, wo_id=wo.id, part_id=part.id, qty=body.qty)
    db.add(row)
    db.commit()
    db.refresh(row)
    warnings: list[str] = []
    if wo.status != "done" and body.qty > Decimal(part.qty_on_hand or 0):
        warnings.append(f"Spare {part.part_no} stock may be insufficient: requested {body.qty}, on hand {part.qty_on_hand}")
    return {
        "id": str(row.id),
        "wo_id": str(wo.id),
        "part_id": str(part.id),
        "qty": float(row.qty),
        "qty_on_hand": float(part.qty_on_hand),
        "warnings": warnings,
    }


@router.get("/ship/work-orders/{wo_id}/spares")
def list_wo_spares(
    wo_id: UUID,
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
):
    wo = _wo_or_404(db, auth.tenant_id, wo_id)
    rows = db.scalars(
        select(ShipWoSpare).where(ShipWoSpare.wo_id == wo.id).order_by(ShipWoSpare.created_at)
    ).all()
    parts = {p.id: p for p in db.scalars(select(ShipSparePart).where(ShipSparePart.tenant_id == auth.tenant_id)).all()}
    return [
        {
            "id": str(r.id),
            "part_id": str(r.part_id),
            "part_no": parts[r.part_id].part_no if r.part_id in parts else None,
            "description": parts[r.part_id].description if r.part_id in parts else None,
            "qty": float(r.qty),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.post("/ship/certificates")
def create_certificate(
    body: CertificateIn,
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
):
    _vessel_or_404(db, auth.tenant_id, body.vessel_id)
    row = ShipCertificate(tenant_id=auth.tenant_id, **body.model_dump())
    row.status = _cert_status_for(row.expires_on, row.status)
    db.add(row)
    db.commit()
    return {"id": str(row.id)}


def _cert_or_404(db: Session, tenant_id: UUID, cert_id: UUID) -> ShipCertificate:
    cert = db.get(ShipCertificate, cert_id)
    if not cert or cert.tenant_id != tenant_id:
        raise HTTPException(404, "Certificate not found")
    return cert


def _cert_list_row(cert: ShipCertificate, vessel_name: str | None, current_file: Attachment | None) -> dict:
    days_to_expiry = (cert.expires_on - date.today()).days if cert.expires_on else None
    return {
        "id": str(cert.id),
        "vessel_id": str(cert.vessel_id),
        "vessel_name": vessel_name,
        "cert_code": cert.cert_code,
        "cert_name": cert.cert_name,
        "issued_on": cert.issued_on.isoformat() if cert.issued_on else None,
        "expires_on": cert.expires_on.isoformat() if cert.expires_on else None,
        "status": cert.status,
        "issuing_body": cert.issuing_body,
        "external_ref": cert.external_ref,
        "days_to_expiry": days_to_expiry,
        "current_file": {
            "id": str(current_file.id),
            "file_name": current_file.file_name,
            "version_no": current_file.version_no,
            "download_url": f"/api/v1/files/{current_file.id}/download",
        }
        if current_file
        else None,
    }


@router.get("/ship/certificates")
def list_certificates(
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
    vessel_id: UUID | None = None,
    status: str | None = None,
    expiring_within_days: int | None = None,
):
    _refresh_certificate_status(db, auth.tenant_id)
    q = select(ShipCertificate).where(ShipCertificate.tenant_id == auth.tenant_id)
    if vessel_id:
        q = q.where(ShipCertificate.vessel_id == vessel_id)
    if status:
        q = q.where(ShipCertificate.status == status)
    certs = db.scalars(q).all()
    vessels = {v.id: v.name for v in db.scalars(select(Vessel).where(Vessel.tenant_id == auth.tenant_id)).all()}
    current_files: dict[UUID, Attachment] = {}
    for a in db.scalars(
        select(Attachment).where(
            Attachment.tenant_id == auth.tenant_id,
            Attachment.entity_type == "ship_certificate",
            Attachment.is_current == True,  # noqa: E712
        )
    ).all():
        current_files[a.entity_id] = a
    rows = [_cert_list_row(c, vessels.get(c.vessel_id), current_files.get(c.id)) for c in certs]
    if expiring_within_days is not None:
        rows = [r for r in rows if r["days_to_expiry"] is not None and r["days_to_expiry"] <= expiring_within_days]
    rows.sort(key=lambda r: (r["days_to_expiry"] is None, r["days_to_expiry"] or 0))
    return rows


@router.patch("/ship/certificates/{cert_id}")
def update_certificate(
    cert_id: UUID,
    body: CertificatePatchIn,
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
):
    cert = _cert_or_404(db, auth.tenant_id, cert_id)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(cert, k, v)
    if "expires_on" in data:
        cert.status = _cert_status_for(cert.expires_on, "valid")
    audit(
        db,
        action="ship.certificate.update",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="ship_certificate",
        entity_id=cert.id,
        detail={"fields": sorted(data.keys())},
    )
    db.commit()
    return {"id": str(cert.id), "status": cert.status}


@router.delete("/ship/certificates/{cert_id}")
def delete_certificate(
    cert_id: UUID,
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
):
    from pathlib import Path  # noqa: PLC0415

    cert = _cert_or_404(db, auth.tenant_id, cert_id)
    files = db.scalars(
        select(Attachment).where(
            Attachment.tenant_id == auth.tenant_id,
            Attachment.entity_type == "ship_certificate",
            Attachment.entity_id == cert.id,
        )
    ).all()
    for f in files:
        Path(f.file_path).unlink(missing_ok=True)
        db.delete(f)
    audit(
        db,
        action="ship.certificate.delete",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="ship_certificate",
        entity_id=cert.id,
        detail={"cert_code": cert.cert_code, "files_removed": len(files)},
    )
    db.delete(cert)
    db.commit()
    return {"ok": True}


@router.post("/ship/defects")
def create_defect(
    body: DefectIn,
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
):
    _vessel_or_404(db, auth.tenant_id, body.vessel_id)
    row = ShipDefect(tenant_id=auth.tenant_id, **body.model_dump())
    db.add(row)
    db.commit()
    return {"id": str(row.id)}


@router.post("/ship/crew")
def create_crew(
    body: CrewIn,
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
):
    if body.vessel_id:
        _vessel_or_404(db, auth.tenant_id, body.vessel_id)
    data = body.model_dump()
    certificates = data.pop("certificates", None)
    row = ShipCrewMember(tenant_id=auth.tenant_id, **data)
    if certificates is not None:
        row.meta = {"certificates": certificates}
    db.add(row)
    db.commit()
    return {"id": str(row.id)}


@router.patch("/ship/crew/{crew_id}")
def update_crew(
    crew_id: UUID,
    body: CrewPatchIn,
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
):
    row = db.get(ShipCrewMember, crew_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Crew member not found")
    data = body.model_dump(exclude_unset=True)
    certificates = data.pop("certificates", None)
    if data.get("vessel_id"):
        _vessel_or_404(db, auth.tenant_id, data["vessel_id"])
    for k, v in data.items():
        setattr(row, k, v)
    if certificates is not None:
        row.meta = {**(row.meta or {}), "certificates": certificates}
    db.commit()
    return {"id": str(row.id), "ok": True}


@router.get("/ship/crew/cert-alerts")
def crew_cert_alerts(
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
    days: int = 60,
):
    """Crew certificates (STCW etc.) expiring within ``days`` days, soonest first."""
    today = date.today()
    horizon = today + timedelta(days=days)
    alerts: list[dict] = []
    crew = db.scalars(select(ShipCrewMember).where(ShipCrewMember.tenant_id == auth.tenant_id)).all()
    for c in crew:
        for cert in (c.meta or {}).get("certificates") or []:
            raw = cert.get("expires_on")
            if not raw:
                continue
            try:
                expires_on = date.fromisoformat(str(raw))
            except ValueError:
                continue
            if expires_on <= horizon:
                alerts.append(
                    {
                        "crew_id": str(c.id),
                        "crew_name": c.full_name,
                        "code": cert.get("code"),
                        "expires_on": expires_on.isoformat(),
                        "days_left": (expires_on - today).days,
                    }
                )
    alerts.sort(key=lambda a: a["days_left"])
    return alerts


@router.get("/ship/integrations/adapters")
def list_pms_adapters(auth: AuthContext = Depends(require_module("ship_mgmt"))):
    """Reserved adapter catalog for external vessel management systems."""
    _ = auth
    return [
        {
            "code": "pms.spectec",
            "name": "SpecTec / AMOS",
            "capabilities": ["work_orders", "certificates", "spares", "pull", "webhook"],
            "status": "adapter_stub",
        },
        {
            "code": "pms.abs_ns",
            "name": "ABS Nautical Systems",
            "capabilities": ["work_orders", "certificates", "crew", "pull"],
            "status": "adapter_stub",
        },
        {
            "code": "pms.shipnet",
            "name": "ShipNet One",
            "capabilities": ["work_orders", "defects", "drydock", "webhook"],
            "status": "adapter_stub",
        },
        {
            "code": "pms.generic_webhook",
            "name": "Generic PMS Webhook",
            "capabilities": ["inbound_sync", "outbound_ack"],
            "status": "ready",
        },
        {
            "code": "pms.mock",
            "name": "VoyageOS Mock PMS",
            "capabilities": ["demo_pull", "demo_push"],
            "status": "ready",
        },
    ]


@router.post("/ship/integrations/inbound")
def inbound_pms_sync(
    body: ExternalSyncIn,
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
):
    """Inbound webhook contract — maps external PMS entities into VoyageOS ship tables."""
    vessel = None
    if body.vessel_imo:
        vessel = db.scalar(
            select(Vessel).where(Vessel.tenant_id == auth.tenant_id, Vessel.imo == body.vessel_imo)
        )
    if not vessel and body.vessel_external_id:
        profile = db.scalar(
            select(ShipTechnicalProfile).where(
                ShipTechnicalProfile.tenant_id == auth.tenant_id,
                ShipTechnicalProfile.external_pms_id == body.vessel_external_id,
            )
        )
        if profile:
            vessel = db.get(Vessel, profile.vessel_id)

    created_id = None
    warnings: list[str] = []
    if vessel and body.entity_type == "work_order":
        existing = db.scalar(
            select(ShipWorkOrder).where(
                ShipWorkOrder.tenant_id == auth.tenant_id,
                ShipWorkOrder.external_ref == body.external_ref,
            )
        )
        if existing:
            existing.title = body.data.get("title", existing.title)
            existing.status = body.data.get("status", existing.status)
            existing.priority = body.data.get("priority", existing.priority)
            if existing.status == "done":
                existing.completed_on = existing.completed_on or date.today()
                warnings = _consume_wo_spares(db, existing)
            created_id = str(existing.id)
        else:
            wo = ShipWorkOrder(
                tenant_id=auth.tenant_id,
                vessel_id=vessel.id,
                wo_no=body.data.get("wo_no") or f"EXT-{body.external_ref}",
                title=body.data.get("title") or "External work order",
                category=body.data.get("category", "pms"),
                priority=body.data.get("priority", "medium"),
                status=body.data.get("status", "open"),
                source="external_pms",
                external_ref=body.external_ref,
                meta={"system": body.system, **body.data},
            )
            db.add(wo)
            db.flush()
            created_id = str(wo.id)
    elif vessel and body.entity_type == "certificate":
        cert = ShipCertificate(
            tenant_id=auth.tenant_id,
            vessel_id=vessel.id,
            cert_code=body.data.get("cert_code") or body.external_ref,
            cert_name=body.data.get("cert_name") or "External certificate",
            status=body.data.get("status", "valid"),
            issuing_body=body.data.get("issuing_body"),
            external_ref=body.external_ref,
            meta={"system": body.system},
        )
        if body.data.get("expires_on"):
            cert.expires_on = date.fromisoformat(body.data["expires_on"])
        cert.status = _cert_status_for(cert.expires_on, cert.status)
        db.add(cert)
        db.flush()
        created_id = str(cert.id)
    elif vessel and body.entity_type == "defect":
        d = ShipDefect(
            tenant_id=auth.tenant_id,
            vessel_id=vessel.id,
            defect_no=body.data.get("defect_no") or f"D-{body.external_ref}",
            title=body.data.get("title") or "External defect",
            severity=body.data.get("severity", "minor"),
            status=body.data.get("status", "open"),
            external_ref=body.external_ref,
            meta={"system": body.system},
        )
        db.add(d)
        db.flush()
        created_id = str(d.id)

    log = ExternalPmsSyncLog(
        tenant_id=auth.tenant_id,
        direction="inbound",
        entity_type=body.entity_type,
        status="ok" if vessel else "orphan",
        message=None if vessel else "Vessel not resolved — payload stored for retry",
        payload=body.model_dump(),
    )
    db.add(log)
    db.commit()
    return {
        "accepted": True,
        "vessel_resolved": bool(vessel),
        "created_id": created_id,
        "warnings": warnings,
        "synced_at": _now().isoformat(),
    }


@router.post("/ship/integrations/pull/{connector_id}")
def pull_from_pms(
    connector_id: UUID,
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
):
    """Pull stub — exercises connector health and writes a demo WO when type is pms.mock."""
    conn = db.get(ConnectorInstance, connector_id)
    if not conn or conn.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Connector not found")
    vessels = db.scalars(select(Vessel).where(Vessel.tenant_id == auth.tenant_id).limit(1)).all()
    created = 0
    if conn.connector_type in ("pms.mock", "pms.generic_webhook") and vessels:
        v = vessels[0]
        ref = f"MOCK-PULL-{_now().strftime('%H%M%S')}"
        db.add(
            ShipWorkOrder(
                tenant_id=auth.tenant_id,
                vessel_id=v.id,
                wo_no=ref,
                title="Pulled PMS maintenance job (demo)",
                category="pms",
                priority="medium",
                status="open",
                source="external_pms",
                external_ref=ref,
                meta={"connector": conn.connector_type},
            )
        )
        created = 1
    conn.last_health = {
        "ok": True,
        "tested_at": _now().isoformat(),
        "message": f"Pull stub OK — imported {created} work order(s)",
        "latency_ms": 18,
    }
    conn.status = "active"
    db.add(
        ExternalPmsSyncLog(
            tenant_id=auth.tenant_id,
            connector_id=conn.id,
            direction="pull",
            entity_type="work_order",
            status="ok",
            message=f"created={created}",
            payload={"connector_type": conn.connector_type},
        )
    )
    db.commit()
    return {"ok": True, "created": created, "connector_id": str(connector_id)}


@router.get("/ship/integrations/sync-logs")
def sync_logs(
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(ExternalPmsSyncLog)
        .where(ExternalPmsSyncLog.tenant_id == auth.tenant_id)
        .order_by(ExternalPmsSyncLog.created_at.desc())
        .limit(50)
    ).all()
    return [
        {
            "id": str(r.id),
            "direction": r.direction,
            "entity_type": r.entity_type,
            "status": r.status,
            "message": r.message,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
