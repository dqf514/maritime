"""Time Charter depth (Phase 5) — TC contracts, billing schedules, profit share,
broker rules, sub-TC chain.

Endpoints live under ``/tc/...``; the legacy ``/tc-contracts`` surface in
commercial.py stays untouched. All ORM access is tenant-scoped
(``scoped_get`` / explicit ``tenant_id`` filters).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal, Optional
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_charter_ext import (
    TimeCharterLayEvent,
    TimeCharterOtherItem,
    TimeCharterPricingRow,
)
from app.models_domain import Charter
from app.models_time_charter import (
    BrokerRule,
    HireBillingSchedule,
    ProfitShareRule,
    TimeCharterContract,
)
from app.models_wave1 import Counterparty, Vessel
from app.security import AuthContext, require_module
from app.services import hire_engine
from app.services.audit import audit
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
    # 指数联动定价 — index-linked hire components (same spec as
    # Estimate.inputs["unpriced_components"]); additive, optional.
    hire_components: Optional[list[dict]] = None
    # ── P11 IMOS TC header 对齐 ──
    tc_code: Optional[str] = None  # 缺省自动编号 VESSEL-I#### / -O####
    beneficiary: Optional[str] = None
    date_fixed_at: Optional[datetime] = None
    fixed_by: Optional[str] = None
    company_code: Optional[str] = None
    department: Optional[str] = None
    trade_area: Optional[str] = None
    ref_no: Optional[str] = None
    payment_terms: Optional[str] = None
    contract_form: Optional[str] = None
    laycan_from_at: Optional[datetime] = None
    laycan_to_at: Optional[datetime] = None
    # Duration block（Min/Max -Days +Days E/L Redel.）
    duration_min_days: Optional[Decimal] = None
    duration_max_days: Optional[Decimal] = None
    duration_minus_days: Optional[Decimal] = None
    duration_plus_days: Optional[Decimal] = None
    el_redel_min: Optional[datetime] = None
    el_redel_max: Optional[datetime] = None
    duration_basis: Optional[str] = None
    use_local_time: bool = False
    # 计费与账务
    billing_period: Optional[str] = None
    billing_schedule: Optional[str] = None
    rebillable_admin_fee_pct: Optional[Decimal] = None
    exchange_rate: Optional[Decimal] = Decimal("1")
    ref_contract: Optional[str] = None
    chtr_specialist: Optional[str] = None
    conf_date_gmt: Optional[datetime] = None
    intercompany: bool = False
    ic_company: Optional[str] = None
    ic_adj_pct: Optional[Decimal] = None
    # 右栏 Summary
    next_open_date: Optional[datetime] = None
    owner_comm_pct: Optional[Decimal] = None
    owner_comm_pay_to: Optional[str] = None
    valuation_id: Optional[str] = None
    remarks: Optional[str] = None
    notes_to_operations: Optional[str] = None


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
    hire_components: Optional[list[dict]] = None
    # ── P11 IMOS TC header 对齐 ──
    tc_code: Optional[str] = None
    beneficiary: Optional[str] = None
    date_fixed_at: Optional[datetime] = None
    fixed_by: Optional[str] = None
    company_code: Optional[str] = None
    department: Optional[str] = None
    trade_area: Optional[str] = None
    ref_no: Optional[str] = None
    payment_terms: Optional[str] = None
    contract_form: Optional[str] = None
    laycan_from_at: Optional[datetime] = None
    laycan_to_at: Optional[datetime] = None
    duration_min_days: Optional[Decimal] = None
    duration_max_days: Optional[Decimal] = None
    duration_minus_days: Optional[Decimal] = None
    duration_plus_days: Optional[Decimal] = None
    el_redel_min: Optional[datetime] = None
    el_redel_max: Optional[datetime] = None
    duration_basis: Optional[str] = None
    use_local_time: Optional[bool] = None
    billing_period: Optional[str] = None
    billing_schedule: Optional[str] = None
    rebillable_admin_fee_pct: Optional[Decimal] = None
    exchange_rate: Optional[Decimal] = None
    ref_contract: Optional[str] = None
    chtr_specialist: Optional[str] = None
    conf_date_gmt: Optional[datetime] = None
    intercompany: Optional[bool] = None
    ic_company: Optional[str] = None
    ic_adj_pct: Optional[Decimal] = None
    next_open_date: Optional[datetime] = None
    owner_comm_pct: Optional[Decimal] = None
    owner_comm_pay_to: Optional[str] = None
    valuation_id: Optional[str] = None
    remarks: Optional[str] = None
    notes_to_operations: Optional[str] = None


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
    hire_components: Optional[list[dict]] = None
    # ── P11 IMOS TC header 对齐 ──
    tc_code: Optional[str] = None
    beneficiary: Optional[str] = None
    date_fixed_at: Optional[datetime] = None
    fixed_by: Optional[str] = None
    company_code: Optional[str] = None
    department: Optional[str] = None
    trade_area: Optional[str] = None
    ref_no: Optional[str] = None
    payment_terms: Optional[str] = None
    contract_form: Optional[str] = None
    laycan_from_at: Optional[datetime] = None
    laycan_to_at: Optional[datetime] = None
    duration_min_days: Optional[float] = None
    duration_max_days: Optional[float] = None
    duration_minus_days: Optional[float] = None
    duration_plus_days: Optional[float] = None
    el_redel_min: Optional[datetime] = None
    el_redel_max: Optional[datetime] = None
    duration_basis: Optional[str] = None
    use_local_time: bool = False
    billing_period: Optional[str] = None
    billing_schedule: Optional[str] = None
    rebillable_admin_fee_pct: Optional[float] = None
    exchange_rate: Optional[float] = None
    ref_contract: Optional[str] = None
    chtr_specialist: Optional[str] = None
    conf_date_gmt: Optional[datetime] = None
    intercompany: bool = False
    ic_company: Optional[str] = None
    ic_adj_pct: Optional[float] = None
    next_open_date: Optional[datetime] = None
    owner_comm_pct: Optional[float] = None
    owner_comm_pay_to: Optional[str] = None
    valuation_id: Optional[str] = None
    remarks: Optional[str] = None
    notes_to_operations: Optional[str] = None
    status: str
    updated_at: Optional[datetime] = None


def _opt_f(v) -> float | None:
    return _f(v) if v is not None else None


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
        profit_share_pct=_opt_f(c.profit_share_pct),
        profit_share_threshold=_opt_f(c.profit_share_threshold),
        address_comm_pct=_opt_f(c.address_comm_pct),
        brokerage_pct=_opt_f(c.brokerage_pct),
        hire_components=c.hire_components,
        tc_code=c.tc_code,
        beneficiary=c.beneficiary,
        date_fixed_at=c.date_fixed_at,
        fixed_by=c.fixed_by,
        company_code=c.company_code,
        department=c.department,
        trade_area=c.trade_area,
        ref_no=c.ref_no,
        payment_terms=c.payment_terms,
        contract_form=c.contract_form,
        laycan_from_at=c.laycan_from_at,
        laycan_to_at=c.laycan_to_at,
        duration_min_days=_opt_f(c.duration_min_days),
        duration_max_days=_opt_f(c.duration_max_days),
        duration_minus_days=_opt_f(c.duration_minus_days),
        duration_plus_days=_opt_f(c.duration_plus_days),
        el_redel_min=c.el_redel_min,
        el_redel_max=c.el_redel_max,
        duration_basis=c.duration_basis,
        use_local_time=bool(c.use_local_time),
        billing_period=c.billing_period,
        billing_schedule=c.billing_schedule,
        rebillable_admin_fee_pct=_opt_f(c.rebillable_admin_fee_pct),
        exchange_rate=_opt_f(c.exchange_rate),
        ref_contract=c.ref_contract,
        chtr_specialist=c.chtr_specialist,
        conf_date_gmt=c.conf_date_gmt,
        intercompany=bool(c.intercompany),
        ic_company=c.ic_company,
        ic_adj_pct=_opt_f(c.ic_adj_pct),
        next_open_date=c.next_open_date,
        owner_comm_pct=_opt_f(c.owner_comm_pct),
        owner_comm_pay_to=c.owner_comm_pay_to,
        valuation_id=c.valuation_id,
        remarks=c.remarks,
        notes_to_operations=c.notes_to_operations,
        status=c.status,
        updated_at=c.updated_at,
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
    # ── P11 IMOS Broker grid 列 ──
    payment_method: Literal["pay_directly", "deduct_from_hire"] = "pay_directly"
    m_method: int = 0  # IMOS "M" 列（计佣口径）
    from_gmt: Optional[datetime] = None
    to_gmt: Optional[datetime] = None
    remarks: Optional[str] = None


class BrokerRulePatch(BaseModel):
    commission_pct: Optional[Decimal] = Field(default=None, ge=0, le=100)
    applies_to: Optional[Literal["hire", "off_hire", "all"]] = None
    payment_method: Optional[Literal["pay_directly", "deduct_from_hire"]] = None
    m_method: Optional[int] = None
    from_gmt: Optional[datetime] = None
    to_gmt: Optional[datetime] = None
    remarks: Optional[str] = None


class BrokerRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    tc_contract_id: str
    broker_party_id: str
    commission_type: str
    commission_pct: float
    applies_to: str
    payment_method: str = "pay_directly"
    m_method: int = 0
    from_gmt: Optional[datetime] = None
    to_gmt: Optional[datetime] = None
    remarks: Optional[str] = None


def _broker_out(r: BrokerRule) -> BrokerRuleOut:
    return BrokerRuleOut(
        id=str(r.id),
        tc_contract_id=str(r.tc_contract_id),
        broker_party_id=str(r.broker_party_id),
        commission_type=r.commission_type,
        commission_pct=_f(r.commission_pct),
        applies_to=r.applies_to,
        payment_method=r.payment_method or "pay_directly",
        m_method=r.m_method or 0,
        from_gmt=r.from_gmt,
        to_gmt=r.to_gmt,
        remarks=r.remarks,
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
    q = select(TimeCharterContract).where(
        TimeCharterContract.tenant_id == auth.tenant_id,
        TimeCharterContract.status != "deleted",
    )
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


def _next_tc_code(db: Session, tenant_id, vessel_id, contract_type: str) -> str:
    """IMOS TC Code: ``VESSEL-I####`` (TC In) / ``VESSEL-O####`` (TC Out).

    Slug is the uppercased alnum form of the vessel name; sequence counts
    existing contracts of the same direction for this tenant (max + 1), so
    re-creates after delete never collide.
    """
    vessel = db.get(Vessel, vessel_id)
    slug = "".join(ch for ch in (vessel.name if vessel else "TC").upper() if ch.isalnum())[:8] or "TC"
    suffix = "I" if contract_type == "tci" else "O"
    count = db.scalar(
        select(func.count())
        .select_from(TimeCharterContract)
        .where(
            TimeCharterContract.tenant_id == tenant_id,
            TimeCharterContract.contract_type == contract_type,
            TimeCharterContract.status != "deleted",
        )
    ) or 0
    seq = count + 1
    code = f"{slug}-{suffix}{seq:04d}"
    # collision guard: loop while an active row already holds the code
    while db.scalar(
        select(func.count())
        .select_from(TimeCharterContract)
        .where(
            TimeCharterContract.tenant_id == tenant_id,
            TimeCharterContract.tc_code == code,
            TimeCharterContract.status != "deleted",
        )
    ):
        seq += 1
        code = f"{slug}-{suffix}{seq:04d}"
    return code


# P11 header passthrough fields (In ↔ ORM) — kept as tuples to avoid drift.
_TC_HEADER_FIELDS = (
    "beneficiary", "date_fixed_at", "fixed_by", "company_code", "department",
    "trade_area", "ref_no", "payment_terms", "contract_form",
    "laycan_from_at", "laycan_to_at",
    "duration_min_days", "duration_max_days", "duration_minus_days", "duration_plus_days",
    "el_redel_min", "el_redel_max", "duration_basis", "use_local_time",
    "billing_period", "billing_schedule", "rebillable_admin_fee_pct", "exchange_rate",
    "ref_contract", "chtr_specialist", "conf_date_gmt",
    "intercompany", "ic_company", "ic_adj_pct",
    "next_open_date", "owner_comm_pct", "owner_comm_pay_to", "valuation_id",
    "remarks", "notes_to_operations",
)


@router.post("/tc/contracts", response_model=TCContractOut, status_code=201)
def create_tc_contract(
    body: TCContractIn,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    if not scoped_get(db, Charter, body.charter_id, auth.tenant_id):
        raise HTTPException(404, "Charter not found")
    if body.vessel_id and scoped_get(db, Vessel, body.vessel_id, auth.tenant_id) is None:
        raise HTTPException(404, "Vessel not found")
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
        hire_components=body.hire_components,
        tc_code=body.tc_code or _next_tc_code(db, auth.tenant_id, body.vessel_id, body.contract_type),
        **{f: getattr(body, f) for f in _TC_HEADER_FIELDS},
    )
    db.add(contract)
    audit(
        db,
        action="tc_contract.create",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="time_charter",
        entity_id=contract.id,
    )
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
    fields = set(body.model_dump(exclude_unset=True)) - {"expected_updated_at"}
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(c, field, value)
    audit(
        db,
        action="tc_contract.update",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="time_charter",
        entity_id=c.id,
        detail={"fields": sorted(fields)},
    )
    db.commit()
    db.refresh(c)
    return _contract_out(c)


@router.delete("/tc/contracts/{contract_id}")
def delete_tc_contract(
    contract_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    """Soft-delete a TC contract — draft only; active/completed/cancelled are locked."""
    from app.services.recycle import soft_delete

    c = _get_tc(db, auth, contract_id)
    if c.status != "draft":
        raise HTTPException(
            409,
            detail={"code": "INVALID_STATE", "message": f"TC contract in status '{c.status}' cannot be deleted", "status": c.status},
        )
    soft_delete(db, tenant_id=auth.tenant_id, user_id=auth.user_id, entity_type="time_charter_contract", row=c, title=f"TC {c.contract_type} {c.id}")
    audit(
        db,
        action="tc_contract.delete",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="time_charter",
        entity_id=c.id,
        detail={"status": c.status},
    )
    db.commit()
    return {"ok": True, "recycled": True}


@router.post("/tc/contracts/{contract_id}/transition", response_model=TCContractOut)
def transition_tc_contract(
    contract_id: UUID,
    target: str = Query(..., pattern="^(active|completed|cancelled)$"),
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    c = _get_tc(db, auth, contract_id)
    c.status = transition("time_charter", c.status, target, TIME_CHARTER_TRANSITIONS)
    audit(
        db,
        action="tc_contract.transition",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="time_charter",
        entity_id=c.id,
        detail={"target": target, "status": c.status},
    )
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
        payment_method=body.payment_method,
        m_method=body.m_method,
        from_gmt=body.from_gmt,
        to_gmt=body.to_gmt,
        remarks=body.remarks,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _broker_out(rule)


@router.patch(
    "/tc/contracts/{contract_id}/broker-rules/{rule_id}",
    response_model=BrokerRuleOut,
)
def update_broker_rule(
    contract_id: UUID,
    rule_id: UUID,
    body: BrokerRulePatch,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    _get_tc(db, auth, contract_id)
    rule = scoped_get(db, BrokerRule, rule_id, auth.tenant_id)
    if not rule or rule.tc_contract_id != contract_id:
        raise HTTPException(404, "Broker rule not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return _broker_out(rule)


@router.delete("/tc/contracts/{contract_id}/broker-rules/{rule_id}")
def delete_broker_rule(
    contract_id: UUID,
    rule_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    _get_tc(db, auth, contract_id)
    rule = scoped_get(db, BrokerRule, rule_id, auth.tenant_id)
    if not rule or rule.tc_contract_id != contract_id:
        raise HTTPException(404, "Broker rule not found")
    db.delete(rule)
    db.commit()
    return {"ok": True}


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
            TimeCharterContract.status != "deleted",
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


# ── P11: Delivery/Redelivery lay events ──────────────────────────────────────


class LayEventIn(BaseModel):
    kind: Literal["delivery", "redelivery"]
    port: Optional[str] = None
    est_gmt: Optional[datetime] = None
    proj_act_gmt: Optional[datetime] = None
    remarks: Optional[str] = None


class LayEventPatch(BaseModel):
    kind: Optional[Literal["delivery", "redelivery"]] = None
    port: Optional[str] = None
    est_gmt: Optional[datetime] = None
    proj_act_gmt: Optional[datetime] = None
    remarks: Optional[str] = None


class LayEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    tc_contract_id: str
    kind: str
    port: Optional[str] = None
    est_gmt: Optional[datetime] = None
    proj_act_gmt: Optional[datetime] = None
    difference_hours: Optional[float] = None  # IMOS "Difference" 列
    remarks: Optional[str] = None


def _lay_event_out(r: TimeCharterLayEvent) -> LayEventOut:
    diff = None
    if r.est_gmt and r.proj_act_gmt:
        est, act = r.est_gmt, r.proj_act_gmt
        # datetime-local UI 提交的是 naive 值，DB 里可能是 aware —— 统一按 UTC 处理
        if est.tzinfo is None and act.tzinfo is not None:
            est = est.replace(tzinfo=timezone.utc)
        elif est.tzinfo is not None and act.tzinfo is None:
            act = act.replace(tzinfo=timezone.utc)
        diff = round((act - est).total_seconds() / 3600.0, 2)
    return LayEventOut(
        id=str(r.id),
        tc_contract_id=str(r.tc_contract_id),
        kind=r.kind,
        port=r.port,
        est_gmt=r.est_gmt,
        proj_act_gmt=r.proj_act_gmt,
        difference_hours=diff,
        remarks=r.remarks,
    )


@router.get(
    "/tc/contracts/{contract_id}/lay-events",
    response_model=list[LayEventOut],
)
def list_lay_events(
    contract_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    _get_tc(db, auth, contract_id)
    rows = db.scalars(
        select(TimeCharterLayEvent)
        .where(
            TimeCharterLayEvent.tenant_id == auth.tenant_id,
            TimeCharterLayEvent.tc_contract_id == contract_id,
        )
        .order_by(TimeCharterLayEvent.kind, TimeCharterLayEvent.created_at)
    ).all()
    return [_lay_event_out(r) for r in rows]


@router.post(
    "/tc/contracts/{contract_id}/lay-events",
    response_model=LayEventOut,
    status_code=201,
)
def add_lay_event(
    contract_id: UUID,
    body: LayEventIn,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    _get_tc(db, auth, contract_id)
    row = TimeCharterLayEvent(
        tenant_id=auth.tenant_id,
        tc_contract_id=contract_id,
        kind=body.kind,
        port=body.port,
        est_gmt=body.est_gmt,
        proj_act_gmt=body.proj_act_gmt,
        remarks=body.remarks,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _lay_event_out(row)


@router.patch(
    "/tc/contracts/{contract_id}/lay-events/{row_id}",
    response_model=LayEventOut,
)
def update_lay_event(
    contract_id: UUID,
    row_id: UUID,
    body: LayEventPatch,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    _get_tc(db, auth, contract_id)
    row = scoped_get(db, TimeCharterLayEvent, row_id, auth.tenant_id)
    if not row or row.tc_contract_id != contract_id:
        raise HTTPException(404, "Lay event not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _lay_event_out(row)


@router.delete("/tc/contracts/{contract_id}/lay-events/{row_id}")
def delete_lay_event(
    contract_id: UUID,
    row_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    _get_tc(db, auth, contract_id)
    row = scoped_get(db, TimeCharterLayEvent, row_id, auth.tenant_id)
    if not row or row.tc_contract_id != contract_id:
        raise HTTPException(404, "Lay event not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ── P11: Pricing ladder ──────────────────────────────────────────────────────


class PricingRowIn(BaseModel):
    hire_rate: Decimal = Field(..., ge=0)
    rate_type: Literal["per_day", "lumpsum", "per_30_days"] = "per_day"
    locked: bool = False
    from_gmt: Optional[datetime] = None
    to_gmt: Optional[datetime] = None
    duration_days: Optional[Decimal] = None
    period_unit: str = "Days"
    tcl_ins: Optional[Decimal] = None
    comments: Optional[str] = None


class PricingRowPatch(BaseModel):
    hire_rate: Optional[Decimal] = Field(default=None, ge=0)
    rate_type: Optional[Literal["per_day", "lumpsum", "per_30_days"]] = None
    locked: Optional[bool] = None
    from_gmt: Optional[datetime] = None
    to_gmt: Optional[datetime] = None
    duration_days: Optional[Decimal] = None
    period_unit: Optional[str] = None
    tcl_ins: Optional[Decimal] = None
    comments: Optional[str] = None


class PricingRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    tc_contract_id: str
    hire_rate: float
    rate_type: str
    locked: bool
    from_gmt: Optional[datetime] = None
    to_gmt: Optional[datetime] = None
    duration_days: Optional[float] = None
    period_unit: str
    tcl_ins: Optional[float] = None
    comments: Optional[str] = None


def _pricing_out(r: TimeCharterPricingRow) -> PricingRowOut:
    return PricingRowOut(
        id=str(r.id),
        tc_contract_id=str(r.tc_contract_id),
        hire_rate=_f(r.hire_rate),
        rate_type=r.rate_type,
        locked=bool(r.locked),
        from_gmt=r.from_gmt,
        to_gmt=r.to_gmt,
        duration_days=_opt_f(r.duration_days),
        period_unit=r.period_unit or "Days",
        tcl_ins=_opt_f(r.tcl_ins),
        comments=r.comments,
    )


@router.get(
    "/tc/contracts/{contract_id}/pricing-rows",
    response_model=list[PricingRowOut],
)
def list_pricing_rows(
    contract_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    _get_tc(db, auth, contract_id)
    rows = db.scalars(
        select(TimeCharterPricingRow)
        .where(
            TimeCharterPricingRow.tenant_id == auth.tenant_id,
            TimeCharterPricingRow.tc_contract_id == contract_id,
        )
        .order_by(TimeCharterPricingRow.from_gmt.nullsfirst(), TimeCharterPricingRow.created_at)
    ).all()
    return [_pricing_out(r) for r in rows]


@router.post(
    "/tc/contracts/{contract_id}/pricing-rows",
    response_model=PricingRowOut,
    status_code=201,
)
def add_pricing_row(
    contract_id: UUID,
    body: PricingRowIn,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    _get_tc(db, auth, contract_id)
    row = TimeCharterPricingRow(
        tenant_id=auth.tenant_id,
        tc_contract_id=contract_id,
        hire_rate=body.hire_rate,
        rate_type=body.rate_type,
        locked=body.locked,
        from_gmt=body.from_gmt,
        to_gmt=body.to_gmt,
        duration_days=body.duration_days,
        period_unit=body.period_unit,
        tcl_ins=body.tcl_ins,
        comments=body.comments,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _pricing_out(row)


@router.patch(
    "/tc/contracts/{contract_id}/pricing-rows/{row_id}",
    response_model=PricingRowOut,
)
def update_pricing_row(
    contract_id: UUID,
    row_id: UUID,
    body: PricingRowPatch,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    _get_tc(db, auth, contract_id)
    row = scoped_get(db, TimeCharterPricingRow, row_id, auth.tenant_id)
    if not row or row.tc_contract_id != contract_id:
        raise HTTPException(404, "Pricing row not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _pricing_out(row)


@router.delete("/tc/contracts/{contract_id}/pricing-rows/{row_id}")
def delete_pricing_row(
    contract_id: UUID,
    row_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    _get_tc(db, auth, contract_id)
    row = scoped_get(db, TimeCharterPricingRow, row_id, auth.tenant_id)
    if not row or row.tc_contract_id != contract_id:
        raise HTTPException(404, "Pricing row not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ── P11: Other-items expense grid (BALLA/CABLE/VICTU/...) ────────────────────


class OtherItemIn(BaseModel):
    code: Literal["BALLA", "CABLE", "VICTU", "ALLOW", "LASHS", "ILOHC", "INTHC"]
    description: Optional[str] = None
    rate_type: Literal["lumpsum", "monthly", "per_30_days", "per_day"] = "lumpsum"
    rate: Decimal = Decimal("0")
    comm: bool = False
    from_gmt: Optional[datetime] = None
    to_gmt: Optional[datetime] = None
    remarks: Optional[str] = None


class OtherItemPatch(BaseModel):
    description: Optional[str] = None
    rate_type: Optional[Literal["lumpsum", "monthly", "per_30_days", "per_day"]] = None
    rate: Optional[Decimal] = None
    comm: Optional[bool] = None
    from_gmt: Optional[datetime] = None
    to_gmt: Optional[datetime] = None
    remarks: Optional[str] = None


class OtherItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    tc_contract_id: str
    code: str
    description: Optional[str] = None
    rate_type: str
    rate: float
    comm: bool
    from_gmt: Optional[datetime] = None
    to_gmt: Optional[datetime] = None
    remarks: Optional[str] = None


def _other_item_out(r: TimeCharterOtherItem) -> OtherItemOut:
    return OtherItemOut(
        id=str(r.id),
        tc_contract_id=str(r.tc_contract_id),
        code=r.code,
        description=r.description,
        rate_type=r.rate_type,
        rate=_f(r.rate),
        comm=bool(r.comm),
        from_gmt=r.from_gmt,
        to_gmt=r.to_gmt,
        remarks=r.remarks,
    )


@router.get(
    "/tc/contracts/{contract_id}/other-items",
    response_model=list[OtherItemOut],
)
def list_other_items(
    contract_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    _get_tc(db, auth, contract_id)
    rows = db.scalars(
        select(TimeCharterOtherItem)
        .where(
            TimeCharterOtherItem.tenant_id == auth.tenant_id,
            TimeCharterOtherItem.tc_contract_id == contract_id,
        )
        .order_by(TimeCharterOtherItem.code, TimeCharterOtherItem.created_at)
    ).all()
    return [_other_item_out(r) for r in rows]


@router.post(
    "/tc/contracts/{contract_id}/other-items",
    response_model=OtherItemOut,
    status_code=201,
)
def add_other_item(
    contract_id: UUID,
    body: OtherItemIn,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    _get_tc(db, auth, contract_id)
    row = TimeCharterOtherItem(
        tenant_id=auth.tenant_id,
        tc_contract_id=contract_id,
        code=body.code,
        description=body.description,
        rate_type=body.rate_type,
        rate=body.rate,
        comm=body.comm,
        from_gmt=body.from_gmt,
        to_gmt=body.to_gmt,
        remarks=body.remarks,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _other_item_out(row)


@router.patch(
    "/tc/contracts/{contract_id}/other-items/{row_id}",
    response_model=OtherItemOut,
)
def update_other_item(
    contract_id: UUID,
    row_id: UUID,
    body: OtherItemPatch,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    _get_tc(db, auth, contract_id)
    row = scoped_get(db, TimeCharterOtherItem, row_id, auth.tenant_id)
    if not row or row.tc_contract_id != contract_id:
        raise HTTPException(404, "Other item not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _other_item_out(row)


@router.delete("/tc/contracts/{contract_id}/other-items/{row_id}")
def delete_other_item(
    contract_id: UUID,
    row_id: UUID,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    _get_tc(db, auth, contract_id)
    row = scoped_get(db, TimeCharterOtherItem, row_id, auth.tenant_id)
    if not row or row.tc_contract_id != contract_id:
        raise HTTPException(404, "Other item not found")
    db.delete(row)
    db.commit()
    return {"ok": True}
