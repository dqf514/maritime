"""Time Charter depth (Phase 5) — TC contracts, billing schedules, profit share,
broker rules, sub-TC chain.

Endpoints live under ``/tc/...``; the legacy ``/tc-contracts`` surface in
commercial.py stays untouched. All ORM access is tenant-scoped
(``scoped_get`` / explicit ``tenant_id`` filters).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_domain import Charter
from app.models_time_charter import (
    BrokerRule,
    HireBillingSchedule,
    ProfitShareRule,
    TimeCharterContract,
)
from app.models_wave1 import Counterparty
from app.security import AuthContext, require_module
from app.services import hire_engine
from app.services.state_machine import TIME_CHARTER_TRANSITIONS, transition
from app.services.tenant_guard import scoped_get

router = APIRouter(tags=["Time Charter"])

ContractStyle = Literal["time_charter", "bareboat"]
ContractType = Literal["tci", "tco"]


def _f(v) -> float:
    return float(v) if v is not None else 0.0


# ── Schemas ──────────────────────────────────────────────────────────────────


class TCContractIn(BaseModel):
    charter_id: UUID
    contract_type: ContractType
    contract_style: ContractStyle = "time_charter"
    vessel_id: UUID
    counterparty_id: UUID
    delivery_port: Optional[str] = None
    delivery_date: Optional[date] = None
    redelivery_port: Optional[str] = None
    redelivery_date: Optional[date] = None
    hire_rate: Decimal
    hire_currency: str = "USD"
    payment_frequency: Literal["monthly", "semi_monthly"] = "monthly"
    cancel_date: Optional[date] = None
    parent_contract_id: Optional[UUID] = None
    profit_share_pct: Optional[Decimal] = None
    profit_share_threshold: Optional[Decimal] = None
    address_comm_pct: Optional[Decimal] = None
    brokerage_pct: Optional[Decimal] = None


class TCContractPatch(BaseModel):
    contract_style: Optional[ContractStyle] = None
    delivery_port: Optional[str] = None
    delivery_date: Optional[date] = None
    redelivery_port: Optional[str] = None
    redelivery_date: Optional[date] = None
    hire_rate: Optional[Decimal] = None
    hire_currency: Optional[str] = None
    payment_frequency: Optional[Literal["monthly", "semi_monthly"]] = None
    cancel_date: Optional[date] = None
    profit_share_pct: Optional[Decimal] = None
    profit_share_threshold: Optional[Decimal] = None
    address_comm_pct: Optional[Decimal] = None
    brokerage_pct: Optional[Decimal] = None


class TCContractOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    charter_id: str
    contract_type: str
    contract_style: str
    parent_contract_id: Optional[str] = None
    vessel_id: str
    counterparty_id: str
    delivery_port: Optional[str] = None
    delivery_date: Optional[date] = None
    redelivery_port: Optional[str] = None
    redelivery_date: Optional[date] = None
    hire_rate: float
    hire_currency: str
    payment_frequency: str
    cancel_date: Optional[date] = None
    profit_share_pct: Optional[float] = None
    profit_share_threshold: Optional[float] = None
    address_comm_pct: Optional[float] = None
    brokerage_pct: Optional[float] = None
    status: str


def _contract_out(c: TimeCharterContract) -> TCContractOut:
    return TCContractOut(
        id=str(c.id),
        charter_id=str(c.charter_id),
        contract_type=c.contract_type,
        contract_style=c.contract_style or "time_charter",
        parent_contract_id=str(c.parent_contract_id) if c.parent_contract_id else None,
        vessel_id=str(c.vessel_id),
        counterparty_id=str(c.counterparty_id),
        delivery_port=c.delivery_port,
        delivery_date=c.delivery_date,
        redelivery_port=c.redelivery_port,
        redelivery_date=c.redelivery_date,
        hire_rate=_f(c.hire_rate),
        hire_currency=c.hire_currency,
        payment_frequency=c.payment_frequency,
        cancel_date=c.cancel_date,
        profit_share_pct=_f(c.profit_share_pct) if c.profit_share_pct is not None else None,
        profit_share_threshold=_f(c.profit_share_threshold) if c.profit_share_threshold is not None else None,
        address_comm_pct=_f(c.address_comm_pct) if c.address_comm_pct is not None else None,
        brokerage_pct=_f(c.brokerage_pct) if c.brokerage_pct is not None else None,
        status=c.status,
    )


class BillingScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    tc_contract_id: str
    period_start: date
    period_end: date
    due_date: date
    amount: float
    status: str
    hire_statement_id: Optional[str] = None
    invoice_id: Optional[str] = None


def _billing_out(r: HireBillingSchedule) -> BillingScheduleOut:
    return BillingScheduleOut(
        id=str(r.id),
        tc_contract_id=str(r.tc_contract_id),
        period_start=r.period_start,
        period_end=r.period_end,
        due_date=r.due_date,
        amount=_f(r.amount),
        status=r.status,
        hire_statement_id=str(r.hire_statement_id) if r.hire_statement_id else None,
        invoice_id=str(r.invoice_id) if r.invoice_id else None,
    )


class BillingScheduleGenerateIn(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class BillingSchedulePatch(BaseModel):
    status: Optional[Literal["draft", "invoiced", "paid", "overdue"]] = None
    amount: Optional[Decimal] = None
    due_date: Optional[date] = None
    hire_statement_id: Optional[UUID] = None
    invoice_id: Optional[UUID] = None


class ProfitShareRuleIn(BaseModel):
    tier_from: Decimal
    tier_to: Optional[Decimal] = None
    share_pct: Decimal = Field(..., ge=0, le=100)
    basis: Literal["tce", "revenue", "profit"] = "tce"

    @field_validator("tier_to")
    @classmethod
    def _tier_order(cls, v, info):
        # NB: avoid dict.get() here — arch guard scans router AST for ".get"
        if v is not None and "tier_from" in info.data and v <= info.data["tier_from"]:
            raise ValueError("tier_to must be greater than tier_from")
        return v


class ProfitShareRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    tc_contract_id: str
    tier_from: float
    tier_to: Optional[float] = None
    share_pct: float
    basis: str


def _ps_out(r: ProfitShareRule) -> ProfitShareRuleOut:
    return ProfitShareRuleOut(
        id=str(r.id),
        tc_contract_id=str(r.tc_contract_id),
        tier_from=_f(r.tier_from),
        tier_to=_f(r.tier_to) if r.tier_to is not None else None,
        share_pct=_f(r.share_pct),
        basis=r.basis,
    )


class BrokerRuleIn(BaseModel):
    broker_party_id: UUID
    commission_type: Literal["brokerage", "address"]
    commission_pct: Decimal = Field(..., ge=0, le=100)
    applies_to: Literal["hire", "off_hire", "all"] = "all"


class BrokerRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    tc_contract_id: str
    broker_party_id: str
    commission_type: str
    commission_pct: float
    applies_to: str


def _broker_out(r: BrokerRule) -> BrokerRuleOut:
    return BrokerRuleOut(
        id=str(r.id),
        tc_contract_id=str(r.tc_contract_id),
        broker_party_id=str(r.broker_party_id),
        commission_type=r.commission_type,
        commission_pct=_f(r.commission_pct),
        applies_to=r.applies_to,
    )


class ChildTCIn(BaseModel):
    contract_type: Optional[ContractType] = None
    contract_style: Optional[ContractStyle] = None
    vessel_id: Optional[UUID] = None
    counterparty_id: Optional[UUID] = None
    delivery_port: Optional[str] = None
    delivery_date: Optional[date] = None
    redelivery_port: Optional[str] = None
    redelivery_date: Optional[date] = None
    hire_rate: Decimal
    hire_currency: Optional[str] = None
    payment_frequency: Optional[Literal["monthly", "semi_monthly"]] = None
    cancel_date: Optional[date] = None
    profit_share_pct: Optional[Decimal] = None
    profit_share_threshold: Optional[Decimal] = None
    address_comm_pct: Optional[Decimal] = None
    brokerage_pct: Optional[Decimal] = None


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_tc(db: Session, auth: AuthContext, contract_id: UUID) -> TimeCharterContract:
    c = scoped_get(db, TimeCharterContract, contract_id, auth.tenant_id)
    if not c:
        raise HTTPException(404, "TC contract not found")
    return c


# ── Contracts ────────────────────────────────────────────────────────────────


@router.get("/tc/contracts", response_model=list[TCContractOut])
def list_tc_contracts(
    contract_type: Optional[ContractType] = None,
    contract_style: Optional[ContractStyle] = None,
    status: Optional[str] = None,
    vessel_id: Optional[UUID] = None,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    q = select(TimeCharterContract).where(TimeCharterContract.tenant_id == auth.tenant_id)
    if contract_type:
        q = q.where(TimeCharterContract.contract_type == contract_type)
    if contract_style:
        q = q.where(TimeCharterContract.contract_style == contract_style)
    if status:
        q = q.where(TimeCharterContract.status == status)
    if vessel_id:
        q = q.where(TimeCharterContract.vessel_id == vessel_id)
    rows = db.scalars(q.order_by(TimeCharterContract.created_at)).all()
    return [_contract_out(c) for c in rows]


@router.post("/tc/contracts", response_model=TCContractOut, status_code=201)
def create_tc_contract(
    body: TCContractIn,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    if not scoped_get(db, Charter, body.charter_id, auth.tenant_id):
        raise HTTPException(404, "Charter not found")
    if body.parent_contract_id and not scoped_get(
        db, TimeCharterContract, body.parent_contract_id, auth.tenant_id
    ):
        raise HTTPException(404, "Parent TC contract not found")
    contract = TimeCharterContract(
        tenant_id=auth.tenant_id,
        charter_id=body.charter_id,
        contract_type=body.contract_type,
        contract_style=body.contract_style,
        parent_contract_id=body.parent_contract_id,
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
        profit_share_pct=body.profit_share_pct,
        profit_share_threshold=body.profit_share_threshold,
        address_comm_pct=body.address_comm_pct,
        brokerage_pct=body.brokerage_pct,
    )
    db.add(contract)
    db.commit()
    db.refresh(contract)
    return _contract_out(contract)


@router.get("/tc/contracts/{contract_id}", response_model=TCContractOut)
def get_tc_contract_detail(
    contract_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    return _contract_out(_get_tc(db, auth, contract_id))


@router.patch("/tc/contracts/{contract_id}", response_model=TCContractOut)
def update_tc_contract(
    contract_id: UUID,
    body: TCContractPatch,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    c = _get_tc(db, auth, contract_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(c, field, value)
    db.commit()
    db.refresh(c)
    return _contract_out(c)


@router.post("/tc/contracts/{contract_id}/transition", response_model=TCContractOut)
def transition_tc_contract(
    contract_id: UUID,
    target: str = Query(..., pattern="^(active|completed|cancelled)$"),
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    c = _get_tc(db, auth, contract_id)
    c.status = transition("time_charter", c.status, target, TIME_CHARTER_TRANSITIONS)
    db.commit()
    db.refresh(c)
    return _contract_out(c)


# ── Billing schedule ─────────────────────────────────────────────────────────


@router.get(
    "/tc/contracts/{contract_id}/billing-schedule",
    response_model=list[BillingScheduleOut],
)
def list_billing_schedule(
    contract_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    _get_tc(db, auth, contract_id)
    rows = db.scalars(
        select(HireBillingSchedule)
        .where(
            HireBillingSchedule.tenant_id == auth.tenant_id,
            HireBillingSchedule.tc_contract_id == contract_id,
        )
        .order_by(HireBillingSchedule.period_start)
    ).all()
    return [_billing_out(r) for r in rows]


@router.post(
    "/tc/contracts/{contract_id}/billing-schedule/generate",
    response_model=list[BillingScheduleOut],
    status_code=201,
)
def generate_billing_schedule(
    contract_id: UUID,
    body: BillingScheduleGenerateIn = BillingScheduleGenerateIn(),
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    c = _get_tc(db, auth, contract_id)
    start = body.start_date or c.delivery_date
    end = body.end_date or c.redelivery_date
    if not start or not end:
        raise HTTPException(
            422,
            detail={
                "code": "HIRE_PERIOD_MISSING",
                "message": "start_date/end_date (or delivery/redelivery dates) required",
            },
        )
    try:
        rows = hire_engine.generate_billing_schedule(db, contract_id, start, end)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "INVALID_PERIOD", "message": str(exc)})
    db.commit()
    for r in rows:
        db.refresh(r)
    return [_billing_out(r) for r in rows]


@router.patch("/tc/billing-schedule/{schedule_id}", response_model=BillingScheduleOut)
def update_billing_schedule(
    schedule_id: UUID,
    body: BillingSchedulePatch,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, HireBillingSchedule, schedule_id, auth.tenant_id)
    if not row:
        raise HTTPException(404, "Billing schedule not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _billing_out(row)


# ── Profit share ─────────────────────────────────────────────────────────────


@router.get(
    "/tc/contracts/{contract_id}/profit-share",
    response_model=list[ProfitShareRuleOut],
)
def list_profit_share_rules(
    contract_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    _get_tc(db, auth, contract_id)
    rows = db.scalars(
        select(ProfitShareRule)
        .where(
            ProfitShareRule.tenant_id == auth.tenant_id,
            ProfitShareRule.tc_contract_id == contract_id,
        )
        .order_by(ProfitShareRule.tier_from)
    ).all()
    return [_ps_out(r) for r in rows]


@router.post(
    "/tc/contracts/{contract_id}/profit-share",
    response_model=ProfitShareRuleOut,
    status_code=201,
)
def add_profit_share_rule(
    contract_id: UUID,
    body: ProfitShareRuleIn,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    _get_tc(db, auth, contract_id)
    rule = ProfitShareRule(
        tenant_id=auth.tenant_id,
        tc_contract_id=contract_id,
        tier_from=body.tier_from,
        tier_to=body.tier_to,
        share_pct=body.share_pct,
        basis=body.basis,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _ps_out(rule)


@router.get("/tc/contracts/{contract_id}/profit-share/calculate")
def calculate_profit_share(
    contract_id: UUID,
    period_tce: Decimal = Query(...),
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    _get_tc(db, auth, contract_id)
    return hire_engine.calculate_profit_share(db, contract_id, period_tce)


# ── Broker rules ─────────────────────────────────────────────────────────────


@router.get(
    "/tc/contracts/{contract_id}/broker-rules",
    response_model=list[BrokerRuleOut],
)
def list_broker_rules(
    contract_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    _get_tc(db, auth, contract_id)
    rows = db.scalars(
        select(BrokerRule)
        .where(
            BrokerRule.tenant_id == auth.tenant_id,
            BrokerRule.tc_contract_id == contract_id,
        )
        .order_by(BrokerRule.created_at)
    ).all()
    return [_broker_out(r) for r in rows]


@router.post(
    "/tc/contracts/{contract_id}/broker-rules",
    response_model=BrokerRuleOut,
    status_code=201,
)
def add_broker_rule(
    contract_id: UUID,
    body: BrokerRuleIn,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    _get_tc(db, auth, contract_id)
    if not scoped_get(db, Counterparty, body.broker_party_id, auth.tenant_id):
        raise HTTPException(404, "Broker party not found")
    rule = BrokerRule(
        tenant_id=auth.tenant_id,
        tc_contract_id=contract_id,
        broker_party_id=body.broker_party_id,
        commission_type=body.commission_type,
        commission_pct=body.commission_pct,
        applies_to=body.applies_to,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _broker_out(rule)


# ── Child TCs ────────────────────────────────────────────────────────────────


@router.get("/tc/contracts/{contract_id}/children", response_model=list[TCContractOut])
def list_child_tcs(
    contract_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    _get_tc(db, auth, contract_id)
    rows = db.scalars(
        select(TimeCharterContract)
        .where(
            TimeCharterContract.tenant_id == auth.tenant_id,
            TimeCharterContract.parent_contract_id == contract_id,
        )
        .order_by(TimeCharterContract.created_at)
    ).all()
    return [_contract_out(c) for c in rows]


@router.post(
    "/tc/contracts/{contract_id}/children",
    response_model=TCContractOut,
    status_code=201,
)
def create_child_tc(
    contract_id: UUID,
    body: ChildTCIn,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    parent = _get_tc(db, auth, contract_id)
    child = TimeCharterContract(
        tenant_id=auth.tenant_id,
        charter_id=parent.charter_id,
        contract_type=body.contract_type or parent.contract_type,
        contract_style=body.contract_style or parent.contract_style or "time_charter",
        parent_contract_id=parent.id,
        vessel_id=body.vessel_id or parent.vessel_id,
        counterparty_id=body.counterparty_id or parent.counterparty_id,
        delivery_port=body.delivery_port,
        delivery_date=body.delivery_date,
        redelivery_port=body.redelivery_port,
        redelivery_date=body.redelivery_date,
        hire_rate=body.hire_rate,
        hire_currency=body.hire_currency or parent.hire_currency,
        payment_frequency=body.payment_frequency or parent.payment_frequency,
        cancel_date=body.cancel_date,
        profit_share_pct=body.profit_share_pct,
        profit_share_threshold=body.profit_share_threshold,
        address_comm_pct=body.address_comm_pct,
        brokerage_pct=body.brokerage_pct,
    )
    db.add(child)
    db.commit()
    db.refresh(child)
    return _contract_out(child)


# ── Hire summary ─────────────────────────────────────────────────────────────


@router.get("/tc/contracts/{contract_id}/hire-summary")
def tc_hire_summary(
    contract_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    """Aggregated hire + profit share + billing schedule totals for a TC contract."""
    c = _get_tc(db, auth, contract_id)
    summary = hire_engine.contract_summary(db, c)

    billing_rows = db.scalars(
        select(HireBillingSchedule).where(
            HireBillingSchedule.tenant_id == auth.tenant_id,
            HireBillingSchedule.tc_contract_id == contract_id,
        )
    ).all()
    billing_by_status: dict[str, float] = {}
    for r in billing_rows:
        billing_by_status[r.status] = billing_by_status.get(r.status, 0.0) + _f(r.amount)

    ps_rules = db.scalars(
        select(ProfitShareRule).where(
            ProfitShareRule.tenant_id == auth.tenant_id,
            ProfitShareRule.tc_contract_id == contract_id,
        )
    ).all()
    broker_rules = db.scalars(
        select(BrokerRule).where(
            BrokerRule.tenant_id == auth.tenant_id,
            BrokerRule.tc_contract_id == contract_id,
        )
    ).all()

    return {
        **summary,
        "contract_style": c.contract_style or "time_charter",
        "parent_contract_id": str(c.parent_contract_id) if c.parent_contract_id else None,
        "billing_schedule_count": len(billing_rows),
        "billing_total": sum(billing_by_status.values()),
        "billing_by_status": billing_by_status,
        "profit_share": {
            "threshold": _f(c.profit_share_threshold) if c.profit_share_threshold is not None else None,
            "pct": _f(c.profit_share_pct) if c.profit_share_pct is not None else None,
            "rule_count": len(ps_rules),
        },
        "broker_rules": {
            "count": len(broker_rules),
            "total_commission_pct": sum(_f(r.commission_pct) for r in broker_rules),
        },
    }
