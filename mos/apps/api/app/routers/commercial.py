"""Commercial domain: Estimate / Chartering / Scheduling."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal, Optional
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_domain import (
    Charter,
    CharterAmendment,
    CoaLifting,
    Estimate,
    OffHireEvent,
    ScheduleBlock,
    Voyage,
)
from app.models_wave1 import Counterparty, Vessel
from app.security import AuthContext, require_module
from app.services.doc_numbering import next_doc_number
from app.services.estimate_engine import compute_estimate, sensitivity
from app.services.recycle import soft_delete
from app.services.tenant_guard import scoped_get
from app.services.state_machine import (
    CHARTER_AMENDMENT_TRANSITIONS,
    CHARTER_TRANSITIONS,
    COA_LIFTING_TRANSITIONS,
    OFFHIRE_TRANSITIONS,
    transition,
)
from app.models_time_charter import HireStatement, TimeCharterContract
from app.services import hire_engine
from app.services.pricing_engine import AdvancedPricingEngine, WorldscaleCalculator
from app.services.distance_service import get_distance, get_route
from app.models_reference import PortDistance, WorldscaleRate

router = APIRouter(tags=["Commercial"])


def _f(v) -> float | None:
    return float(v) if v is not None else None


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


class _CharterTermsMixin(BaseModel):
    """Shared CP commercial terms with validation/normalization."""

    demurrage_rate: float | None = None
    despatch_rate: float | None = None
    laytime_terms: str | None = None
    cp_form: str | None = None
    freight_rate: float | None = None
    freight_basis: Literal["per_mt", "lumpsum", "worldscale"] | None = None
    cargo_qty: float | None = None
    load_rate_pd: float | None = None
    disch_rate_pd: float | None = None
    address_comm_pct: float | None = None
    brokerage_pct: float | None = None
    hire_per_day: float | None = None
    hire_cycle_days: int | None = None
    delivery_port_id: UUID | None = None
    redelivery_port_id: UUID | None = None
    delivery_at: datetime | None = None
    redelivery_at: datetime | None = None
    ets_responsibility: Literal["owner", "charterer"] | None = None

    @field_validator("laytime_terms")
    @classmethod
    def _upper_laytime_terms(cls, v: str | None) -> str | None:
        return v.strip().upper() if v else v

    @field_validator("cp_form")
    @classmethod
    def _upper_cp_form(cls, v: str | None) -> str | None:
        return v.strip().upper() if v else v


class CharterIn(_CharterTermsMixin):
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
    demurrage_rate: float | None = None
    despatch_rate: float | None = None
    laytime_terms: str | None = None
    cp_form: str | None = None
    freight_rate: float | None = None
    freight_basis: str | None = None
    cargo_qty: float | None = None
    load_rate_pd: float | None = None
    disch_rate_pd: float | None = None
    address_comm_pct: float | None = None
    brokerage_pct: float | None = None
    hire_per_day: float | None = None
    hire_cycle_days: int | None = None
    delivery_port_id: UUID | None = None
    redelivery_port_id: UUID | None = None
    delivery_at: datetime | None = None
    redelivery_at: datetime | None = None
    ets_responsibility: str | None = None


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
    if body.vessel_id is not None and scoped_get(db, Vessel, body.vessel_id, auth.tenant_id) is None:
        raise HTTPException(404, "Vessel not found")
    if body.counterparty_id is not None and scoped_get(db, Counterparty, body.counterparty_id, auth.tenant_id) is None:
        raise HTTPException(404, "Counterparty not found")
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
        if scoped_get(db, Vessel, body.vessel_id, auth.tenant_id) is None:
            raise HTTPException(404, "Vessel not found")
        row.vessel_id = body.vessel_id
    if body.clear_counterparty or ("counterparty_id" in fields and body.counterparty_id is None):
        row.counterparty_id = None
    elif body.counterparty_id is not None:
        if scoped_get(db, Counterparty, body.counterparty_id, auth.tenant_id) is None:
            raise HTTPException(404, "Counterparty not found")
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
    try:
        row.results = compute_estimate(row.inputs or {})
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "INVALID_ESTIMATE_INPUT", "message": str(exc)})
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
    try:
        return sensitivity(row.inputs or {}, field, [-0.1, -0.05, 0.0, 0.05, 0.1])
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "INVALID_ESTIMATE_INPUT", "message": str(exc)})


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
        try:
            est.results = compute_estimate(est.inputs or {})
        except ValueError as exc:
            raise HTTPException(422, detail={"code": "INVALID_ESTIMATE_INPUT", "message": str(exc)})
    basis_map = {"rate": "per_mt", "lump_sum": "lumpsum", "worldscale": "worldscale"}
    inputs = est.inputs or {}
    results = est.results or {}
    charter = Charter(
        tenant_id=auth.tenant_id,
        charter_no=next_doc_number(db, auth.tenant_id, Charter, Charter.charter_no, "CP"),
        charter_type="voyage" if est.mode == "voyage" else "tct",
        vessel_id=est.vessel_id,
        counterparty_id=est.counterparty_id,
        estimate_id=est.id,
        freight_terms={"from_estimate": results},
        clauses={},
        status="draft",
        cargo_qty=inputs.get("cargo_qty"),
        freight_rate=inputs.get("freight_rate"),
        freight_basis=basis_map.get(results.get("freight_basis")),
        address_comm_pct=inputs.get("address_comm_pct") or inputs.get("commission_pct"),
        brokerage_pct=inputs.get("brokerage_pct"),
        hire_per_day=inputs.get("hire_per_day"),
        demurrage_rate=inputs.get("demurrage_rate"),
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
        demurrage_rate=_f(c.demurrage_rate),
        despatch_rate=_f(c.despatch_rate),
        laytime_terms=c.laytime_terms,
        cp_form=c.cp_form,
        freight_rate=_f(c.freight_rate),
        freight_basis=c.freight_basis,
        cargo_qty=_f(c.cargo_qty),
        load_rate_pd=_f(c.load_rate_pd),
        disch_rate_pd=_f(c.disch_rate_pd),
        address_comm_pct=_f(c.address_comm_pct),
        brokerage_pct=_f(c.brokerage_pct),
        hire_per_day=_f(c.hire_per_day),
        hire_cycle_days=c.hire_cycle_days,
        delivery_port_id=c.delivery_port_id,
        redelivery_port_id=c.redelivery_port_id,
        delivery_at=c.delivery_at,
        redelivery_at=c.redelivery_at,
        ets_responsibility=c.ets_responsibility,
    )


@router.get("/charters", response_model=list[CharterOut])
def list_charters(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(Charter)
        .where(Charter.tenant_id == auth.tenant_id, Charter.status != "deleted")
        .order_by(Charter.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [_charter_out(r) for r in rows]


CHARTER_TERM_FIELDS = (
    "demurrage_rate",
    "despatch_rate",
    "laytime_terms",
    "cp_form",
    "freight_rate",
    "freight_basis",
    "cargo_qty",
    "load_rate_pd",
    "disch_rate_pd",
    "address_comm_pct",
    "brokerage_pct",
    "hire_per_day",
    "hire_cycle_days",
    "delivery_port_id",
    "redelivery_port_id",
    "delivery_at",
    "redelivery_at",
    "ets_responsibility",
)


# Key commercial terms that are locked once the charter is active/completed;
# changing them requires an approved CharterAmendment (DDS change-order flow).
CHARTER_AMENDABLE_FIELDS = (
    "demurrage_rate",
    "freight_rate",
    "freight_basis",
    "cargo_qty",
    "laycan_from",
    "laycan_to",
    "hire_per_day",
)


@router.post("/charters", response_model=CharterOut)
def create_charter(body: CharterIn, auth: AuthContext = Depends(require_module("chartering")), db: Session = Depends(get_db)):
    blocked = False
    if body.counterparty_id:
        party = db.get(Counterparty, body.counterparty_id)
        if not party or party.tenant_id != auth.tenant_id or party.deleted_at:
            raise HTTPException(404, "Counterparty not found")
        if party.sanctions_status != "clear":
            blocked = True
    if body.vessel_id is not None and scoped_get(db, Vessel, body.vessel_id, auth.tenant_id) is None:
        raise HTTPException(404, "Vessel not found")
    if body.estimate_id is not None and scoped_get(db, Estimate, body.estimate_id, auth.tenant_id) is None:
        raise HTTPException(404, "Estimate not found")
    row = Charter(
        tenant_id=auth.tenant_id,
        charter_no=next_doc_number(db, auth.tenant_id, Charter, Charter.charter_no, "CP"),
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
        **{f: getattr(body, f) for f in CHARTER_TERM_FIELDS},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _charter_out(row)


class CharterUpdate(_CharterTermsMixin):
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
    if row.status in ("active", "completed"):
        locked = sorted(set(CHARTER_AMENDABLE_FIELDS) & fields)
        if locked:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "AMENDMENT_REQUIRED",
                    "message": f"Charter is {row.status}; key terms {locked} can only change via an approved amendment",
                    "fields": locked,
                },
            )
    if "charter_type" in fields and body.charter_type is not None:
        row.charter_type = body.charter_type
    if body.clear_vessel or ("vessel_id" in fields and body.vessel_id is None):
        row.vessel_id = None
    elif body.vessel_id is not None:
        vessel = scoped_get(db, Vessel, body.vessel_id, auth.tenant_id)
        if not vessel:
            raise HTTPException(404, "Vessel not found")
        row.vessel_id = body.vessel_id
    if body.clear_counterparty or ("counterparty_id" in fields and body.counterparty_id is None):
        row.counterparty_id = None
    elif body.counterparty_id is not None:
        party = db.get(Counterparty, body.counterparty_id)
        if not party or party.tenant_id != auth.tenant_id or party.deleted_at:
            raise HTTPException(404, "Counterparty not found")
        row.counterparty_id = body.counterparty_id
        row.sanctions_blocked = bool(party and party.sanctions_status != "clear")
    if "laycan_from" in fields:
        row.laycan_from = body.laycan_from
    if "laycan_to" in fields:
        row.laycan_to = body.laycan_to
    if "commission_pct" in fields:
        row.commission_pct = body.commission_pct
    for f in CHARTER_TERM_FIELDS:
        if f in fields:
            setattr(row, f, getattr(body, f))
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
        vno = next_doc_number(db, auth.tenant_id, Voyage, Voyage.voyage_no, "V")
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


# ---- COA lifting lifecycle (planned → nominated → fixed → completed / withdrawn) ----


class CoaLiftingOut(BaseModel):
    id: UUID
    charter_id: UUID
    period_label: str
    planned_qty: float | None = None
    actual_qty: float | None = None
    status: str
    voyage_id: UUID | None = None
    laycan_from: datetime | None = None
    laycan_to: datetime | None = None


def _lifting_out(lift: CoaLifting) -> CoaLiftingOut:
    return CoaLiftingOut(
        id=lift.id,
        charter_id=lift.charter_id,
        period_label=lift.period_label,
        planned_qty=_f(lift.planned_qty),
        actual_qty=_f(lift.actual_qty),
        status=lift.status,
        voyage_id=lift.voyage_id,
        laycan_from=lift.laycan_from,
        laycan_to=lift.laycan_to,
    )


def _get_lifting(db: Session, auth: AuthContext, lifting_id: UUID) -> CoaLifting:
    lift = db.get(CoaLifting, lifting_id)
    if not lift:
        raise HTTPException(404, "COA lifting not found")
    charter = db.get(Charter, lift.charter_id)
    if not charter or charter.tenant_id != auth.tenant_id or not _alive(charter.status):
        raise HTTPException(404, "COA lifting not found")
    return lift


@router.get("/charters/{charter_id}/liftings", response_model=list[CoaLiftingOut])
def list_liftings(
    charter_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    row = db.get(Charter, charter_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Charter not found")
    rows = db.scalars(
        select(CoaLifting).where(CoaLifting.charter_id == row.id).order_by(CoaLifting.period_label)
    ).all()
    return [_lifting_out(lift) for lift in rows]


class LiftingNominateIn(BaseModel):
    laycan_from: datetime
    laycan_to: datetime


@router.post("/coa-liftings/{lifting_id}/nominate", response_model=CoaLiftingOut)
def nominate_lifting(
    lifting_id: UUID,
    body: LiftingNominateIn,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    lift = _get_lifting(db, auth, lifting_id)
    if body.laycan_to < body.laycan_from:
        raise HTTPException(422, detail={"code": "INVALID_LAYCAN", "message": "laycan_to must not be before laycan_from"})
    lift.status = transition("coa_lifting", lift.status, "nominated", COA_LIFTING_TRANSITIONS)
    lift.laycan_from = body.laycan_from
    lift.laycan_to = body.laycan_to
    db.commit()
    db.refresh(lift)
    return _lifting_out(lift)


class LiftingFixIn(BaseModel):
    voyage_id: UUID


@router.post("/coa-liftings/{lifting_id}/fix", response_model=CoaLiftingOut)
def fix_lifting(
    lifting_id: UUID,
    body: LiftingFixIn,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    lift = _get_lifting(db, auth, lifting_id)
    voyage = db.get(Voyage, body.voyage_id)
    if not voyage or voyage.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Voyage not found")
    lift.status = transition("coa_lifting", lift.status, "fixed", COA_LIFTING_TRANSITIONS)
    lift.voyage_id = voyage.id
    db.commit()
    db.refresh(lift)
    return _lifting_out(lift)


class LiftingCompleteIn(BaseModel):
    actual_qty: float | None = None


@router.post("/coa-liftings/{lifting_id}/complete", response_model=CoaLiftingOut)
def complete_lifting(
    lifting_id: UUID,
    body: LiftingCompleteIn | None = None,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    lift = _get_lifting(db, auth, lifting_id)
    lift.status = transition("coa_lifting", lift.status, "completed", COA_LIFTING_TRANSITIONS)
    if body and body.actual_qty is not None:
        lift.actual_qty = body.actual_qty
    db.commit()
    db.refresh(lift)
    return _lifting_out(lift)


# ---- Charter amendments (change orders for locked key terms) ----


class CharterAmendmentIn(BaseModel):
    changes: dict
    reason: str | None = None


class CharterAmendmentOut(BaseModel):
    id: UUID
    charter_id: UUID
    seq: int
    changes: dict
    reason: str | None = None
    status: str
    approved_by: UUID | None = None
    created_at: datetime | None = None


def _amendment_out(a: CharterAmendment) -> CharterAmendmentOut:
    return CharterAmendmentOut(
        id=a.id,
        charter_id=a.charter_id,
        seq=a.seq,
        changes=a.changes or {},
        reason=a.reason,
        status=a.status,
        approved_by=a.approved_by,
        created_at=a.created_at,
    )


def _validate_amendment_changes(changes: dict) -> None:
    if not changes:
        raise HTTPException(422, detail={"code": "EMPTY_AMENDMENT", "message": "changes must not be empty"})
    unknown = sorted(set(changes) - set(CHARTER_AMENDABLE_FIELDS))
    if unknown:
        raise HTTPException(
            422,
            detail={
                "code": "INVALID_AMENDMENT_FIELDS",
                "message": f"Fields {unknown} are not amendable; allowed: {list(CHARTER_AMENDABLE_FIELDS)}",
            },
        )


@router.post("/charters/{charter_id}/amendments", response_model=CharterAmendmentOut)
def create_amendment(
    charter_id: UUID,
    body: CharterAmendmentIn,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    row = db.get(Charter, charter_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Charter not found")
    _validate_amendment_changes(body.changes)
    max_seq = db.scalar(select(func.max(CharterAmendment.seq)).where(CharterAmendment.charter_id == row.id)) or 0
    amd = CharterAmendment(
        tenant_id=auth.tenant_id,
        charter_id=row.id,
        seq=max_seq + 1,
        changes=body.changes,
        reason=body.reason,
        status="proposed",
    )
    db.add(amd)
    db.commit()
    db.refresh(amd)
    return _amendment_out(amd)


@router.get("/charters/{charter_id}/amendments", response_model=list[CharterAmendmentOut])
def list_amendments(
    charter_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    row = db.get(Charter, charter_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Charter not found")
    rows = db.scalars(
        select(CharterAmendment).where(CharterAmendment.charter_id == row.id).order_by(CharterAmendment.seq)
    ).all()
    return [_amendment_out(a) for a in rows]


def _get_amendment(db: Session, auth: AuthContext, amendment_id: UUID) -> tuple[CharterAmendment, Charter]:
    amd = db.get(CharterAmendment, amendment_id)
    if not amd or amd.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Charter amendment not found")
    charter = db.get(Charter, amd.charter_id)
    if not charter or charter.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Charter amendment not found")
    return amd, charter


@router.post("/charter-amendments/{amendment_id}/approve", response_model=CharterAmendmentOut)
def approve_amendment(
    amendment_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    amd, charter = _get_amendment(db, auth, amendment_id)
    amd.status = transition("charter_amendment", amd.status, "approved", CHARTER_AMENDMENT_TRANSITIONS)
    amd.approved_by = auth.user_id
    for k, v in (amd.changes or {}).items():
        if k in ("laycan_from", "laycan_to") and isinstance(v, str):
            v = date.fromisoformat(v)
        setattr(charter, k, v)
    charter.updated_at = datetime.now().astimezone()
    db.commit()
    db.refresh(amd)
    return _amendment_out(amd)


@router.post("/charter-amendments/{amendment_id}/reject", response_model=CharterAmendmentOut)
def reject_amendment(
    amendment_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    amd, _charter = _get_amendment(db, auth, amendment_id)
    amd.status = transition("charter_amendment", amd.status, "rejected", CHARTER_AMENDMENT_TRANSITIONS)
    db.commit()
    db.refresh(amd)
    return _amendment_out(amd)


# ---- Off-hire events (TC hire deduction) ----


class OffHireIn(BaseModel):
    start_at: datetime
    reason: str | None = None
    deduct_hire: bool = True
    charter_id: UUID | None = None


class OffHireCloseIn(BaseModel):
    end_at: datetime | None = None


class OffHireOut(BaseModel):
    id: UUID
    voyage_id: UUID
    charter_id: UUID | None
    start_at: datetime
    end_at: datetime | None
    reason: str | None
    deduct_hire: bool
    status: str
    deducted_days: float | None = None


def _offhire_days(ev: OffHireEvent) -> float | None:
    if ev.end_at is None:
        return None
    hours = (ev.end_at - ev.start_at).total_seconds() / 3600.0
    return float((Decimal(str(hours)) / Decimal("24")).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _offhire_out(ev: OffHireEvent) -> OffHireOut:
    return OffHireOut(
        id=ev.id,
        voyage_id=ev.voyage_id,
        charter_id=ev.charter_id,
        start_at=ev.start_at,
        end_at=ev.end_at,
        reason=ev.reason,
        deduct_hire=ev.deduct_hire,
        status=ev.status,
        deducted_days=_offhire_days(ev),
    )


@router.post("/voyages/{voyage_id}/off-hire", response_model=OffHireOut)
def open_off_hire(
    voyage_id: UUID,
    body: OffHireIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    voyage = db.get(Voyage, voyage_id)
    if not voyage or voyage.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Voyage not found")
    charter_id = body.charter_id or voyage.charter_id
    if charter_id:
        charter = db.get(Charter, charter_id)
        if not charter or charter.tenant_id != auth.tenant_id:
            raise HTTPException(404, "Charter not found")
    ev = OffHireEvent(
        tenant_id=auth.tenant_id,
        voyage_id=voyage.id,
        charter_id=charter_id,
        start_at=body.start_at,
        reason=body.reason,
        deduct_hire=body.deduct_hire,
        status="open",
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return _offhire_out(ev)


@router.post("/off-hire/{event_id}/close", response_model=OffHireOut)
def close_off_hire(
    event_id: UUID,
    body: OffHireCloseIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    ev = db.get(OffHireEvent, event_id)
    if not ev or ev.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Off-hire event not found")
    end_at = body.end_at or datetime.now(timezone.utc)
    start_at = ev.start_at if ev.start_at.tzinfo else ev.start_at.replace(tzinfo=timezone.utc)
    if end_at <= start_at:
        raise HTTPException(422, detail={"code": "INVALID_OFFHIRE_WINDOW", "message": "end_at must be after start_at"})
    ev.status = transition("off_hire", ev.status, "closed", OFFHIRE_TRANSITIONS)
    ev.end_at = end_at
    db.commit()
    db.refresh(ev)
    return _offhire_out(ev)


@router.get("/voyages/{voyage_id}/off-hire", response_model=list[OffHireOut])
def list_off_hire(
    voyage_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    voyage = db.get(Voyage, voyage_id)
    if not voyage or voyage.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Voyage not found")
    rows = db.scalars(
        select(OffHireEvent)
        .where(OffHireEvent.tenant_id == auth.tenant_id, OffHireEvent.voyage_id == voyage_id)
        .order_by(OffHireEvent.start_at)
    ).all()
    return [_offhire_out(r) for r in rows]


@router.get("/charters/{charter_id}/hire-summary")
def charter_hire_summary(
    charter_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    """Billable TC hire: hire_per_day × (charter days − deductible off-hire days).

    Output shape is a stable contract consumed by the finance hire-invoice endpoint:
    {charter_id, hire_per_day, gross_days, offhire_days, billable_days, amount_due, currency}
    """
    row = db.get(Charter, charter_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Charter not found")
    if row.hire_per_day is None:
        raise HTTPException(422, detail={"code": "HIRE_RATE_MISSING", "message": "Charter has no hire_per_day"})

    if row.delivery_at and row.redelivery_at:
        gross = Decimal(str((row.redelivery_at - row.delivery_at).total_seconds())) / Decimal("86400")
    elif row.hire_cycle_days:
        gross = Decimal(row.hire_cycle_days)
    else:
        raise HTTPException(
            422,
            detail={"code": "HIRE_PERIOD_MISSING", "message": "Set delivery_at/redelivery_at or hire_cycle_days"},
        )

    voyage_ids = db.scalars(
        select(Voyage.id).where(Voyage.tenant_id == auth.tenant_id, Voyage.charter_id == row.id)
    ).all()
    events = db.scalars(
        select(OffHireEvent).where(
            OffHireEvent.tenant_id == auth.tenant_id,
            OffHireEvent.deduct_hire.is_(True),
            OffHireEvent.end_at.isnot(None),
            or_(
                OffHireEvent.charter_id == row.id,
                OffHireEvent.voyage_id.in_(voyage_ids) if voyage_ids else False,
            ),
        )
    ).all()
    offhire = sum(
        (Decimal(str((ev.end_at - ev.start_at).total_seconds())) / Decimal("86400") for ev in events),
        Decimal("0"),
    )

    q = Decimal("0.0001")
    gross_days = gross.quantize(q, rounding=ROUND_HALF_UP)
    offhire_days = offhire.quantize(q, rounding=ROUND_HALF_UP)
    billable_days = max(gross_days - offhire_days, Decimal("0"))
    amount_due = (Decimal(row.hire_per_day) * billable_days).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "charter_id": str(row.id),
        "hire_per_day": float(row.hire_per_day),
        "gross_days": float(gross_days),
        "offhire_days": float(offhire_days),
        "billable_days": float(billable_days),
        "amount_due": float(amount_due),
        "currency": (row.freight_terms or {}).get("currency") or "USD",
    }



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


# ── Time Charter Contracts ──


class TCContractIn(BaseModel):
    charter_id: UUID
    contract_type: Literal["tci", "tco"]
    vessel_id: UUID
    counterparty_id: UUID
    delivery_port: str | None = None
    delivery_date: date | None = None
    redelivery_port: str | None = None
    redelivery_date: date | None = None
    hire_rate: Decimal
    hire_currency: str = "USD"
    payment_frequency: Literal["monthly", "semi_monthly"] = "monthly"
    cancel_date: date | None = None


class TCContractOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    charter_id: str
    contract_type: str
    vessel_id: str
    counterparty_id: str
    delivery_port: str | None
    delivery_date: date | None
    redelivery_port: str | None
    redelivery_date: date | None
    hire_rate: float
    hire_currency: str
    payment_frequency: str
    cancel_date: date | None
    status: str


@router.get("/tc-contracts", response_model=list[TCContractOut])
def list_tc_contracts(
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(TimeCharterContract).where(TimeCharterContract.tenant_id == auth.tenant_id)
    ).all()
    return rows


@router.post("/tc-contracts", response_model=TCContractOut, status_code=201)
def create_tc_contract(
    body: TCContractIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    charter = scoped_get(db, Charter, body.charter_id, auth.tenant_id)
    if not charter:
        raise HTTPException(404, "Charter not found")
    contract = TimeCharterContract(
        tenant_id=auth.tenant_id,
        charter_id=body.charter_id,
        contract_type=body.contract_type,
        vessel_id=body.vessel_id,
        counterparty_id=body.counterparty_id,
        delivery_port=body.delivery_port,
        delivery_date=body.delivery_date,
        redelivery_port=body.redelivery_port,
        redelivery_date=body.redelivery_date,
        hire_rate=body.hire_rate,
        hire_currency=body.hire_currency,
        payment_frequency=body.payment_frequency,
        cancel_date=body.cancel_date,
    )
    db.add(contract)
    db.commit()
    db.refresh(contract)
    return contract


@router.get("/tc-contracts/{contract_id}", response_model=TCContractOut)
def get_tc_contract(
    contract_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    c = scoped_get(db, TimeCharterContract, contract_id, auth.tenant_id)
    if not c:
        raise HTTPException(404, "Contract not found")
    return c


@router.get("/tc-contracts/{contract_id}/summary")
def tc_contract_summary(
    contract_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    c = scoped_get(db, TimeCharterContract, contract_id, auth.tenant_id)
    if not c:
        raise HTTPException(404, "Contract not found")
    return hire_engine.contract_summary(db, c)


# ── Hire Statements ──


class HireStatementIn(BaseModel):
    contract_id: UUID
    period_start: date
    period_end: date


class HireStatementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    contract_id: str
    statement_number: str
    period_start: date
    period_end: date
    hire_days: float
    off_hire_days: float
    gross_hire: float
    off_hire_deduction: float
    bunker_adjustment: float
    other_adjustments: float
    net_hire: float
    currency: str
    status: str
    breakdown: dict


@router.get("/tc-contracts/{contract_id}/statements", response_model=list[HireStatementOut])
def list_hire_statements(
    contract_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    c = scoped_get(db, TimeCharterContract, contract_id, auth.tenant_id)
    if not c:
        raise HTTPException(404, "Contract not found")
    rows = db.scalars(
        select(HireStatement).where(
            HireStatement.tenant_id == auth.tenant_id,
            HireStatement.contract_id == contract_id,
        ).order_by(HireStatement.period_start)
    ).all()
    return rows


@router.post("/hire-statements", response_model=HireStatementOut, status_code=201)
def create_hire_statement(
    body: HireStatementIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    c = scoped_get(db, TimeCharterContract, body.contract_id, auth.tenant_id)
    if not c:
        raise HTTPException(404, "Contract not found")
    if body.period_end <= body.period_start:
        raise HTTPException(422, "period_end must be after period_start")
    stmt = hire_engine.create_hire_statement(db, c, body.period_start, body.period_end)
    db.commit()
    db.refresh(stmt)
    return stmt


@router.post("/tc-contracts/{contract_id}/generate-statements", response_model=list[HireStatementOut])
def auto_generate_statements(
    contract_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    c = scoped_get(db, TimeCharterContract, contract_id, auth.tenant_id)
    if not c:
        raise HTTPException(404, "Contract not found")
    stmts = hire_engine.generate_all_statements(db, c)
    db.commit()
    for s in stmts:
        db.refresh(s)
    return stmts


@router.post("/hire-statements/{statement_id}/transition")
def hire_statement_transition(
    statement_id: UUID,
    target: str = Query(..., pattern="^(sent|approved|paid|void)$"),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    stmt = scoped_get(db, HireStatement, statement_id, auth.tenant_id)
    if not stmt:
        raise HTTPException(404, "Statement not found")
    allowed = {
        "draft": {"sent", "void"},
        "sent": {"approved", "void"},
        "approved": {"paid", "void"},
        "paid": set(),
        "void": set(),
    }
    current = stmt.status
    if target not in allowed.get(current, set()):
        raise HTTPException(409, f"Cannot transition {current} → {target}")
    stmt.status = target
    db.commit()
    return {"id": str(stmt.id), "status": stmt.status}


# ── Pricing Engine ──


class PricingIn(BaseModel):
    freight_basis: str  # per_mt | lumpsum | worldscale
    cargo_qty_mt: Decimal
    freight_rate: Decimal | None = None
    ws_pct: Decimal | None = None
    from_port: str | None = None
    to_port: str | None = None
    year: int | None = None


@router.post("/pricing/calculate")
def calculate_price(
    body: PricingIn,
    auth: AuthContext = Depends(require_module("commercial")),
    db: Session = Depends(get_db),
):
    return AdvancedPricingEngine.price_voyage(
        db,
        freight_basis=body.freight_basis,
        cargo_qty_mt=body.cargo_qty_mt,
        freight_rate=body.freight_rate,
        ws_pct=body.ws_pct,
        from_port=body.from_port,
        to_port=body.to_port,
        year=body.year,
    )


@router.get("/pricing/worldscale")
def lookup_worldscale(
    from_port: str = Query(...),
    to_port: str = Query(...),
    year: int = Query(2026),
    auth: AuthContext = Depends(require_module("commercial")),
    db: Session = Depends(get_db),
):
    ws = WorldscaleCalculator.lookup(db, from_port.upper(), to_port.upper(), year)
    if not ws:
        raise HTTPException(404, "No worldscale rate found")
    return {
        "from_port": ws.from_port_unlocode,
        "to_port": ws.to_port_unlocode,
        "year": ws.year,
        "flat_rate": float(ws.flat_rate),
        "cargo_type": ws.cargo_type,
    }


# ── Port Distance ──


@router.get("/distances")
def query_distance(
    from_port: str = Query(...),
    to_port: str = Query(...),
    route: str = Query("shortest", pattern="^(shortest|canal|cape)$"),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    result = get_distance(db, from_port, to_port, route)
    if not result:
        raise HTTPException(404, "No distance found for this port pair")
    return result


@router.post("/distances/route")
def query_route(
    ports: list[str] = Body(..., description="Ordered port UN/LOCODEs"),
    route: str = Query("shortest", pattern="^(shortest|canal|cape)$"),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    if len(ports) < 2:
        raise HTTPException(422, "At least 2 ports required")
    return get_route(db, ports, route)


class PortDistanceIn(BaseModel):
    from_port_unlocode: str
    to_port_unlocode: str
    distance_nm: Decimal
    route_type: str = "standard"
    canal_transit: str | None = None
    canal_toll: Decimal | None = None
    transit_days: Decimal | None = None
    notes: str | None = None


@router.post("/distances", status_code=201)
def upsert_distance(
    body: PortDistanceIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    existing = db.scalars(
        select(PortDistance).where(
            PortDistance.from_port_unlocode == body.from_port_unlocode.upper(),
            PortDistance.to_port_unlocode == body.to_port_unlocode.upper(),
            PortDistance.route_type == body.route_type,
        )
    ).first()
    if existing:
        existing.distance_nm = body.distance_nm
        existing.canal_transit = body.canal_transit
        existing.canal_toll = body.canal_toll
        existing.transit_days = body.transit_days
        existing.notes = body.notes
        db.commit()
        db.refresh(existing)
        return {"id": str(existing.id), "action": "updated"}
    row = PortDistance(
        from_port_unlocode=body.from_port_unlocode.upper(),
        to_port_unlocode=body.to_port_unlocode.upper(),
        distance_nm=body.distance_nm,
        route_type=body.route_type,
        canal_transit=body.canal_transit,
        canal_toll=body.canal_toll,
        transit_days=body.transit_days,
        notes=body.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "action": "created"}


# ── Sensitivity Analysis + BEP ──


@router.get("/estimates/{estimate_id}/sensitivity")
def estimate_sensitivity(
    estimate_id: UUID,
    pct: float = Query(10.0, gt=0, le=50, description="Perturbation percentage"),
    auth: AuthContext = Depends(require_module("commercial")),
    db: Session = Depends(get_db),
):
    from app.services.sensitivity import sensitivity_analysis
    try:
        return sensitivity_analysis(db, auth.tenant_id, estimate_id, pct)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/estimates/{estimate_id}/bep")
def estimate_bep(
    estimate_id: UUID,
    auth: AuthContext = Depends(require_module("commercial")),
    db: Session = Depends(get_db),
):
    from app.services.sensitivity import calculate_bep
    try:
        return calculate_bep(db, auth.tenant_id, estimate_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ── Consecutive Voyages (TC Contract) ──


@router.get("/tc-contracts/{contract_id}/voyages")
def list_contract_voyages(
    contract_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    from app.services.consecutive_voyages import contract_voyages_summary
    c = scoped_get(db, TimeCharterContract, contract_id, auth.tenant_id)
    if not c:
        raise HTTPException(404, "Contract not found")
    return contract_voyages_summary(db, contract_id)


@router.post("/tc-contracts/{contract_id}/voyages", status_code=201)
def create_consecutive_voyage(
    contract_id: UUID,
    vessel_id: UUID,
    title: str | None = None,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    from app.services.consecutive_voyages import create_consecutive_voyage as create_cv
    c = scoped_get(db, TimeCharterContract, contract_id, auth.tenant_id)
    if not c:
        raise HTTPException(404, "Contract not found")
    try:
        voyage = create_cv(db, auth.tenant_id, contract_id, vessel_id, title)
        return {
            "id": str(voyage.id),
            "voyage_no": voyage.voyage_no,
            "tc_seq": voyage.tc_seq,
            "status": voyage.status,
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/tc-contracts/{contract_id}/allocate-tco")
def allocate_tco(
    contract_id: UUID,
    total_cost: Decimal = Query(..., gt=0),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    from app.services.consecutive_voyages import allocate_tco_costs
    c = scoped_get(db, TimeCharterContract, contract_id, auth.tenant_id)
    if not c:
        raise HTTPException(404, "Contract not found")
    allocations = allocate_tco_costs(db, contract_id, total_cost)
    return {
        "contract_id": str(contract_id),
        "total_cost": float(total_cost),
        "allocations": allocations,
    }
