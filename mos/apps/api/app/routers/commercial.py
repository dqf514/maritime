"""Commercial domain: Estimate / Chartering / Scheduling."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_domain import Charter, CoaLifting, Estimate, ScheduleBlock, Voyage
from app.models_wave1 import Counterparty, Vessel
from app.security import AuthContext, require_module
from app.services.estimate_engine import compute_estimate, sensitivity
from app.services.recycle import soft_delete
from app.services.state_machine import CHARTER_TRANSITIONS, transition

router = APIRouter(tags=["Commercial"])


def _alive(status: str | None) -> bool:
    return status != "deleted"


class EstimateIn(BaseModel):
    title: str
    mode: str = "voyage"
    vessel_id: UUID | None = None
    counterparty_id: UUID | None = None
    inputs: dict = Field(default_factory=dict)


class EstimateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    mode: str
    vessel_id: UUID | None
    counterparty_id: UUID | None
    version: int
    status: str
    inputs: dict
    results: dict
    parent_id: UUID | None = None


class CharterIn(BaseModel):
    charter_type: str = "voyage"
    vessel_id: UUID | None = None
    counterparty_id: UUID | None = None
    estimate_id: UUID | None = None
    laycan_from: date | None = None
    laycan_to: date | None = None
    commission_pct: float | None = None
    freight_terms: dict = Field(default_factory=dict)
    clauses: dict = Field(default_factory=dict)


class CharterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    charter_no: str
    charter_type: str
    status: str
    vessel_id: UUID | None
    counterparty_id: UUID | None
    estimate_id: UUID | None
    laycan_from: date | None
    laycan_to: date | None
    commission_pct: float | None = None
    freight_terms: dict
    clauses: dict
    sanctions_blocked: bool


class ScheduleIn(BaseModel):
    vessel_id: UUID
    block_type: str = "voyage"
    title: str
    start_at: datetime
    end_at: datetime
    voyage_id: UUID | None = None


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    vessel_id: UUID
    block_type: str
    title: str
    start_at: datetime
    end_at: datetime
    voyage_id: UUID | None
    hard_conflict: bool


@router.get("/estimates", response_model=list[EstimateOut])
def list_estimates(auth: AuthContext = Depends(require_module("estimate")), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Estimate)
        .where(Estimate.tenant_id == auth.tenant_id, Estimate.status != "deleted")
        .order_by(Estimate.created_at.desc())
    ).all()
    return [EstimateOut.model_validate(r) for r in rows]


@router.post("/estimates", response_model=EstimateOut)
def create_estimate(body: EstimateIn, auth: AuthContext = Depends(require_module("estimate")), db: Session = Depends(get_db)):
    row = Estimate(
        tenant_id=auth.tenant_id,
        title=body.title,
        mode=body.mode,
        vessel_id=body.vessel_id,
        counterparty_id=body.counterparty_id,
        inputs=body.inputs,
        results={},
        created_by=auth.user_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return EstimateOut.model_validate(row)


@router.get("/estimates/{estimate_id}", response_model=EstimateOut)
def get_estimate(estimate_id: UUID, auth: AuthContext = Depends(require_module("estimate")), db: Session = Depends(get_db)):
    row = db.get(Estimate, estimate_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Estimate not found")
    return EstimateOut.model_validate(row)


class EstimateUpdate(BaseModel):
    title: str | None = None
    mode: str | None = None
    vessel_id: Optional[UUID] = None
    counterparty_id: Optional[UUID] = None
    inputs: dict | None = None
    clear_vessel: bool = False
    clear_counterparty: bool = False


@router.put("/estimates/{estimate_id}", response_model=EstimateOut)
def update_estimate(
    estimate_id: UUID,
    body: EstimateUpdate,
    auth: AuthContext = Depends(require_module("estimate")),
    db: Session = Depends(get_db),
):
    row = db.get(Estimate, estimate_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Estimate not found")
    fields = body.model_fields_set
    if "title" in fields and body.title is not None:
        row.title = body.title
    if "mode" in fields and body.mode is not None:
        row.mode = body.mode
    if body.clear_vessel or ("vessel_id" in fields and body.vessel_id is None):
        row.vessel_id = None
    elif body.vessel_id is not None:
        row.vessel_id = body.vessel_id
    if body.clear_counterparty or ("counterparty_id" in fields and body.counterparty_id is None):
        row.counterparty_id = None
    elif body.counterparty_id is not None:
        row.counterparty_id = body.counterparty_id
    if body.inputs is not None:
        row.inputs = body.inputs
        row.results = {}
        if row.status == "calculated":
            row.status = "draft"
    row.updated_at = datetime.now().astimezone()
    db.commit()
    db.refresh(row)
    return EstimateOut.model_validate(row)


@router.delete("/estimates/{estimate_id}")
def delete_estimate(estimate_id: UUID, auth: AuthContext = Depends(require_module("estimate")), db: Session = Depends(get_db)):
    row = db.get(Estimate, estimate_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Estimate not found")
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="estimate",
        row=row,
        title=row.title,
    )
    db.commit()
    return {"ok": True, "recycled": True}


@router.post("/estimates/{estimate_id}/calculate", response_model=EstimateOut)
def calculate_estimate(estimate_id: UUID, auth: AuthContext = Depends(require_module("estimate")), db: Session = Depends(get_db)):
    row = db.get(Estimate, estimate_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Estimate not found")
    row.results = compute_estimate(row.inputs or {})
    row.status = "calculated"
    row.updated_at = datetime.now().astimezone()
    db.commit()
    db.refresh(row)
    return EstimateOut.model_validate(row)


@router.post("/estimates/{estimate_id}/clone", response_model=EstimateOut)
def clone_estimate(estimate_id: UUID, auth: AuthContext = Depends(require_module("estimate")), db: Session = Depends(get_db)):
    src = db.get(Estimate, estimate_id)
    if not src or src.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Estimate not found")
    row = Estimate(
        tenant_id=auth.tenant_id,
        title=f"{src.title} (v{src.version + 1})",
        mode=src.mode,
        vessel_id=src.vessel_id,
        counterparty_id=src.counterparty_id,
        version=src.version + 1,
        inputs=dict(src.inputs or {}),
        results={},
        parent_id=src.id,
        created_by=auth.user_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return EstimateOut.model_validate(row)


@router.post("/estimates/{estimate_id}/sensitivity")
def estimate_sensitivity(
    estimate_id: UUID,
    field: str = Query("freight_rate"),
    auth: AuthContext = Depends(require_module("estimate")),
    db: Session = Depends(get_db),
):
    row = db.get(Estimate, estimate_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Estimate not found")
    return sensitivity(row.inputs or {}, field, [-0.1, -0.05, 0.0, 0.05, 0.1])


@router.post("/estimates/compare")
def compare_estimates(
    ids: list[UUID],
    auth: AuthContext = Depends(require_module("estimate")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(Estimate).where(Estimate.tenant_id == auth.tenant_id, Estimate.id.in_(ids))).all()
    return [
        {"id": str(r.id), "title": r.title, "version": r.version, "tce": (r.results or {}).get("tce"), "results": r.results}
        for r in rows
    ]


@router.post("/estimates/{estimate_id}/to-charter", response_model=CharterOut)
def estimate_to_charter(estimate_id: UUID, auth: AuthContext = Depends(require_module("chartering")), db: Session = Depends(get_db)):
    est = db.get(Estimate, estimate_id)
    if not est or est.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Estimate not found")
    if not est.results:
        est.results = compute_estimate(est.inputs or {})
    charter = Charter(
        tenant_id=auth.tenant_id,
        charter_no=f"CP-{datetime.now().strftime('%Y%m%d')}-{str(uuid4())[:6].upper()}",
        charter_type="voyage" if est.mode == "voyage" else "tct",
        vessel_id=est.vessel_id,
        counterparty_id=est.counterparty_id,
        estimate_id=est.id,
        freight_terms={"from_estimate": est.results},
        clauses={},
        status="draft",
    )
    if est.counterparty_id:
        party = db.get(Counterparty, est.counterparty_id)
        if party and party.sanctions_status != "clear":
            charter.sanctions_blocked = True
    db.add(charter)
    est.status = "converted"
    db.commit()
    db.refresh(charter)
    return _charter_out(charter)


def _charter_out(c: Charter) -> CharterOut:
    return CharterOut(
        id=c.id,
        charter_no=c.charter_no,
        charter_type=c.charter_type,
        status=c.status,
        vessel_id=c.vessel_id,
        counterparty_id=c.counterparty_id,
        estimate_id=c.estimate_id,
        laycan_from=c.laycan_from,
        laycan_to=c.laycan_to,
        commission_pct=float(c.commission_pct) if c.commission_pct is not None else None,
        freight_terms=c.freight_terms or {},
        clauses=c.clauses or {},
        sanctions_blocked=c.sanctions_blocked,
    )


@router.get("/charters", response_model=list[CharterOut])
def list_charters(auth: AuthContext = Depends(require_module("chartering")), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Charter)
        .where(Charter.tenant_id == auth.tenant_id, Charter.status != "deleted")
        .order_by(Charter.created_at.desc())
    ).all()
    return [_charter_out(r) for r in rows]


@router.post("/charters", response_model=CharterOut)
def create_charter(body: CharterIn, auth: AuthContext = Depends(require_module("chartering")), db: Session = Depends(get_db)):
    blocked = False
    if body.counterparty_id:
        party = db.get(Counterparty, body.counterparty_id)
        if party and party.sanctions_status != "clear":
            blocked = True
    row = Charter(
        tenant_id=auth.tenant_id,
        charter_no=f"CP-{datetime.now().strftime('%Y%m%d')}-{str(uuid4())[:6].upper()}",
        charter_type=body.charter_type,
        vessel_id=body.vessel_id,
        counterparty_id=body.counterparty_id,
        estimate_id=body.estimate_id,
        laycan_from=body.laycan_from,
        laycan_to=body.laycan_to,
        commission_pct=body.commission_pct,
        freight_terms=body.freight_terms,
        clauses=body.clauses,
        sanctions_blocked=blocked,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _charter_out(row)


class CharterUpdate(BaseModel):
    charter_type: str | None = None
    vessel_id: Optional[UUID] = None
    counterparty_id: Optional[UUID] = None
    laycan_from: date | None = None
    laycan_to: date | None = None
    commission_pct: float | None = None
    freight_terms: dict | None = None
    clauses: dict | None = None
    clear_vessel: bool = False
    clear_counterparty: bool = False


@router.patch("/charters/{charter_id}", response_model=CharterOut)
def update_charter(
    charter_id: UUID,
    body: CharterUpdate,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    row = db.get(Charter, charter_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Charter not found")
    fields = body.model_fields_set
    if "charter_type" in fields and body.charter_type is not None:
        row.charter_type = body.charter_type
    if body.clear_vessel or ("vessel_id" in fields and body.vessel_id is None):
        row.vessel_id = None
    elif body.vessel_id is not None:
        row.vessel_id = body.vessel_id
    if body.clear_counterparty or ("counterparty_id" in fields and body.counterparty_id is None):
        row.counterparty_id = None
    elif body.counterparty_id is not None:
        row.counterparty_id = body.counterparty_id
        party = db.get(Counterparty, body.counterparty_id)
        row.sanctions_blocked = bool(party and party.sanctions_status != "clear")
    if "laycan_from" in fields:
        row.laycan_from = body.laycan_from
    if "laycan_to" in fields:
        row.laycan_to = body.laycan_to
    if "commission_pct" in fields:
        row.commission_pct = body.commission_pct
    if body.freight_terms is not None:
        row.freight_terms = body.freight_terms
    if body.clauses is not None:
        row.clauses = body.clauses
    row.updated_at = datetime.now().astimezone()
    db.commit()
    db.refresh(row)
    return _charter_out(row)


@router.delete("/charters/{charter_id}")
def delete_charter(charter_id: UUID, auth: AuthContext = Depends(require_module("chartering")), db: Session = Depends(get_db)):
    row = db.get(Charter, charter_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Charter not found")
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="charter",
        row=row,
        title=row.charter_no,
    )
    db.commit()
    return {"ok": True, "recycled": True}


class CharterTransition(BaseModel):
    target: str


@router.post("/charters/{charter_id}/transition", response_model=CharterOut)
def charter_transition(
    charter_id: UUID,
    body: CharterTransition,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    row = db.get(Charter, charter_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Charter not found")
    if body.target == "active" and row.sanctions_blocked:
        raise HTTPException(status_code=409, detail={"code": "SANCTIONS_BLOCKED", "message": "Cannot activate sanctioned counterparty charter"})

    from app.models_saas import WorkflowDefinition, WorkflowInstance
    from app.services.saas_engine import start_workflow

    has_wf = db.scalar(
        select(WorkflowDefinition).where(
            WorkflowDefinition.tenant_id == auth.tenant_id,
            WorkflowDefinition.entity_type == "charter",
            WorkflowDefinition.enabled.is_(True),
        )
    )
    if body.target == "active" and has_wf and "tenant_admin" not in auth.roles:
        running = db.scalar(
            select(WorkflowInstance).where(
                WorkflowInstance.tenant_id == auth.tenant_id,
                WorkflowInstance.entity_type == "charter",
                WorkflowInstance.entity_id == row.id,
                WorkflowInstance.status == "running",
            )
        )
        if running or row.status == "pending_approval":
            raise HTTPException(
                status_code=409,
                detail={"code": "WORKFLOW_REQUIRED", "message": "Charter must be approved via workflow inbox"},
            )

    row.status = transition("charter", row.status, body.target, CHARTER_TRANSITIONS)
    row.updated_at = datetime.now(timezone.utc)

    if body.target == "pending_approval" and has_wf:
        start_workflow(db, tenant_id=auth.tenant_id, entity_type="charter", entity_id=row.id, started_by=auth.user_id)

    if body.target == "active" and row.vessel_id:
        # auto-create voyage + schedule occupancy
        vno = f"V-{datetime.now().strftime('%Y%m%d')}-{str(uuid4())[:4].upper()}"
        voyage = Voyage(
            tenant_id=auth.tenant_id,
            voyage_no=vno,
            status="planned",
            vessel_id=row.vessel_id,
            charter_id=row.id,
            cargo=(row.freight_terms or {}).get("cargo")
            or (
                f"qty {(row.freight_terms or {}).get('cargo_qty')}"
                if (row.freight_terms or {}).get("cargo_qty")
                else None
            ),
            cp_date=date.today(),
        )
        db.add(voyage)
        db.flush()
        from datetime import timedelta

        start = datetime.now(timezone.utc)
        end = start + timedelta(days=14)
        conflict = _has_conflict(db, auth.tenant_id, row.vessel_id, start, end)
        db.add(
            ScheduleBlock(
                tenant_id=auth.tenant_id,
                vessel_id=row.vessel_id,
                block_type="voyage",
                title=vno,
                start_at=start,
                end_at=end,
                voyage_id=voyage.id,
                hard_conflict=conflict,
            )
        )
    db.commit()
    db.refresh(row)
    return _charter_out(row)


@router.post("/charters/{charter_id}/liftings")
def add_lifting(
    charter_id: UUID,
    period_label: str,
    planned_qty: float,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    row = db.get(Charter, charter_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Charter not found")
    lift = CoaLifting(charter_id=row.id, period_label=period_label, planned_qty=planned_qty)
    db.add(lift)
    db.commit()
    return {"id": str(lift.id), "period_label": period_label, "planned_qty": planned_qty}


def _has_conflict(db: Session, tenant_id: UUID, vessel_id: UUID, start: datetime, end: datetime) -> bool:
    rows = db.scalars(
        select(ScheduleBlock).where(
            ScheduleBlock.tenant_id == tenant_id,
            ScheduleBlock.vessel_id == vessel_id,
            and_(ScheduleBlock.start_at < end, ScheduleBlock.end_at > start),
        )
    ).all()
    return len(rows) > 0


@router.get("/schedules", response_model=list[ScheduleOut])
def list_schedules(
    vessel_id: UUID | None = None,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    # scheduling uses operations license as fleet ops; also allow estimate tenants via chartering path
    stmt = select(ScheduleBlock).where(ScheduleBlock.tenant_id == auth.tenant_id)
    if vessel_id:
        stmt = stmt.where(ScheduleBlock.vessel_id == vessel_id)
    rows = db.scalars(stmt.order_by(ScheduleBlock.start_at)).all()
    return [ScheduleOut.model_validate(r) for r in rows]


@router.post("/schedules", response_model=ScheduleOut)
def create_schedule(body: ScheduleIn, auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    vessel = db.get(Vessel, body.vessel_id)
    if not vessel or vessel.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Vessel not found")
    if body.end_at <= body.start_at:
        raise HTTPException(400, "end_at must be after start_at")
    conflict = _has_conflict(db, auth.tenant_id, body.vessel_id, body.start_at, body.end_at)
    row = ScheduleBlock(
        tenant_id=auth.tenant_id,
        vessel_id=body.vessel_id,
        block_type=body.block_type,
        title=body.title,
        start_at=body.start_at,
        end_at=body.end_at,
        voyage_id=body.voyage_id,
        hard_conflict=conflict,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ScheduleOut.model_validate(row)


@router.get("/schedules/conflicts")
def schedule_conflicts(auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(ScheduleBlock).where(ScheduleBlock.tenant_id == auth.tenant_id, ScheduleBlock.hard_conflict.is_(True))
    ).all()
    return [{"id": str(r.id), "title": r.title, "vessel_id": str(r.vessel_id)} for r in rows]
