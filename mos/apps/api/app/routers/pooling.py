"""Pooling depth — 管理费/杂费设定、按期费用分摊、现金分摊与公司间分摊。

Endpoints (all under /api/v1):
- POST /pools/{pool_id}/management-fee        设置管理费（pct 或 fixed）
- POST /pools/{pool_id}/admin-fee             设置管理费（admin，pct 或 fixed）
- POST /pools/{pool_id}/periods/{period_id}/calculate-fees   费用分摊计算
- POST /pools/{pool_id}/periods/{period_id}/cash-distribution 现金分摊（标记已付）
- GET  /pools/{pool_id}/periods/{period_id}/summary          期间汇总
- POST /pools/{pool_id}/periods/{period_id}/intercompany-distribution 公司间分摊
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_domain import Pool, PoolPeriod, PoolVessel
from app.models_pooling import PoolDistribution, PoolFee
from app.models_wave1 import Company
from app.security import AuthContext, require_module
from app.services.state_machine import POOL_PERIOD_TRANSITIONS, transition
from app.services.tenant_guard import scoped_get, scoped_query

router = APIRouter()  # 由 main.py 以 /api/v1 挂载


class PoolFeeIn(BaseModel):
    fee_basis: str = Field("pct", description="pct | fixed")  # pct | fixed
    amount: float = Field(0.0, ge=0, description="pct: 百分比; fixed: 固定金额")
    currency: str | None = None
    note: str | None = None


class FeeOut(BaseModel):
    id: str
    pool_id: str
    fee_type: str
    fee_basis: str
    amount: float
    currency: str
    active: bool
    note: str | None


class IntercompanyAllocationIn(BaseModel):
    company_id: UUID
    share_pct: float = Field(..., gt=0, le=100)
    note: str | None = None


class IntercompanyIn(BaseModel):
    allocations: list[IntercompanyAllocationIn]


def _fee_out(row: PoolFee) -> FeeOut:
    return FeeOut(
        id=str(row.id),
        pool_id=str(row.pool_id),
        fee_type=row.fee_type,
        fee_basis=row.fee_basis,
        amount=float(row.amount or 0),
        currency=row.currency or "USD",
        active=bool(row.active),
        note=row.note,
    )


def _require_pool(db: Session, pool_id: UUID, tenant_id: UUID) -> Pool:
    pool = scoped_get(db, Pool, pool_id, tenant_id)
    if not pool:
        raise HTTPException(404, detail={"code": "POOL_NOT_FOUND", "message": "Pool not found"})
    return pool


def _require_period(db: Session, pool_id: UUID, period_id: UUID, tenant_id: UUID) -> PoolPeriod:
    period = db.scalar(
        select(PoolPeriod)
        .join(Pool, Pool.id == PoolPeriod.pool_id)
        .where(
            PoolPeriod.id == period_id,
            PoolPeriod.pool_id == pool_id,
            Pool.tenant_id == tenant_id,
        )
    )
    if not period:
        raise HTTPException(404, detail={"code": "PERIOD_NOT_FOUND", "message": "Pool period not found"})
    return period


def _set_pool_fee(
    db: Session,
    tenant_id: UUID,
    pool_id: UUID,
    fee_type: str,
    body: PoolFeeIn,
) -> PoolFee:
    """Upsert the active fee of one type for a pool (previous active row deactivated)."""
    _require_pool(db, pool_id, tenant_id)
    if body.fee_basis not in ("pct", "fixed"):
        raise HTTPException(400, detail={"code": "INVALID_FEE_BASIS", "message": "fee_basis must be pct or fixed"})
    if body.fee_basis == "pct" and body.amount > 100:
        raise HTTPException(400, detail={"code": "INVALID_FEE_PCT", "message": "pct fee must be within 0-100"})

    existing = db.scalars(
        scoped_query(db, PoolFee, tenant_id).where(
            PoolFee.pool_id == pool_id,
            PoolFee.fee_type == fee_type,
            PoolFee.active.is_(True),
        )
    ).all()
    for row in existing:
        row.active = False

    fee = PoolFee(
        tenant_id=tenant_id,
        pool_id=pool_id,
        fee_type=fee_type,
        fee_basis=body.fee_basis,
        amount=Decimal(str(body.amount)),
        currency=body.currency or "USD",
        active=True,
        note=body.note,
    )
    db.add(fee)
    db.commit()
    db.refresh(fee)
    return fee


def _fee_totals(fees: list[PoolFee], total_pool_result: float) -> tuple[float, float, float]:
    """Return (management_total, admin_total, grand_total) for the period result."""
    mgmt = admin = 0.0
    for f in fees:
        amt = float(f.amount or 0)
        val = total_pool_result * amt / 100.0 if f.fee_basis == "pct" else amt
        if f.fee_type == "management":
            mgmt += val
        else:
            admin += val
    return mgmt, admin, mgmt + admin


@router.post("/pools/{pool_id}/management-fee", response_model=FeeOut)
def set_management_fee(
    pool_id: UUID,
    body: PoolFeeIn,
    auth: AuthContext = Depends(require_module("pooling")),
    db: Session = Depends(get_db),
):
    """Set the pool management fee (pct or fixed); replaces the previous active fee."""
    fee = _set_pool_fee(db, auth.tenant_id, pool_id, "management", body)
    return _fee_out(fee)


@router.post("/pools/{pool_id}/admin-fee", response_model=FeeOut)
def set_admin_fee(
    pool_id: UUID,
    body: PoolFeeIn,
    auth: AuthContext = Depends(require_module("pooling")),
    db: Session = Depends(get_db),
):
    """Set the pool admin fee (pct or fixed); replaces the previous active fee."""
    fee = _set_pool_fee(db, auth.tenant_id, pool_id, "admin", body)
    return _fee_out(fee)


@router.post("/pools/{pool_id}/periods/{period_id}/calculate-fees")
def calculate_fees(
    pool_id: UUID,
    period_id: UUID,
    auth: AuthContext = Depends(require_module("pooling")),
    db: Session = Depends(get_db),
):
    """Fee distribution calc: per-vessel gross share minus pro-rata fee deduction.

    Recomputes PoolDistribution rows for the period. Period moves
    open → calculating (recalc while calculating is allowed; settled/cancelled → 409).
    """
    _require_pool(db, pool_id, auth.tenant_id)
    period = _require_period(db, pool_id, period_id, auth.tenant_id)

    if period.status == "open":
        period.status = transition("pool_period", period.status, "calculating", POOL_PERIOD_TRANSITIONS)
    elif period.status != "calculating":
        # settled / cancelled → IllegalState 409
        transition("pool_period", period.status, "calculating", POOL_PERIOD_TRANSITIONS)

    vessels = db.scalars(
        select(PoolVessel).where(PoolVessel.pool_id == pool_id, PoolVessel.left_on.is_(None))
    ).all()
    if not vessels:
        raise HTTPException(400, detail={"code": "NO_POOL_VESSELS", "message": "Pool has no active vessels"})

    total_pool_result = float(period.total_pool_result or 0)
    total_points = sum(float(v.points or 0) for v in vessels) or 1.0

    fees = db.scalars(
        scoped_query(db, PoolFee, auth.tenant_id).where(
            PoolFee.pool_id == pool_id,
            PoolFee.active.is_(True),
        )
    ).all()
    mgmt_total, admin_total, fee_total = _fee_totals(list(fees), total_pool_result)

    # 重算：先清本期旧分摊
    old = db.scalars(
        scoped_query(db, PoolDistribution, auth.tenant_id).where(
            PoolDistribution.period_id == period_id
        )
    ).all()
    for row in old:
        db.delete(row)

    dist_map: dict[str, float] = {}
    for v in vessels:
        share_ratio = float(v.points or 0) / total_points
        gross = round(total_pool_result * share_ratio, 2)
        deduction = round(fee_total * share_ratio, 2)
        net = round(gross - deduction, 2)
        db.add(
            PoolDistribution(
                tenant_id=auth.tenant_id,
                period_id=period_id,
                vessel_id=v.vessel_id,
                points=v.points,
                gross_share=Decimal(str(gross)),
                fee_deduction=Decimal(str(deduction)),
                net_share=Decimal(str(net)),
                paid_status="pending",
            )
        )
        dist_map[str(v.vessel_id)] = gross

    period.distribution = {
        **dist_map,
        "_fees": {"management": round(mgmt_total, 2), "admin": round(admin_total, 2), "total": round(fee_total, 2)},
    }
    db.commit()

    rows = db.scalars(
        scoped_query(db, PoolDistribution, auth.tenant_id)
        .where(PoolDistribution.period_id == period_id)
        .order_by(PoolDistribution.created_at)
    ).all()
    return {
        "period_id": str(period_id),
        "status": period.status,
        "total_pool_result": total_pool_result,
        "management_fee": round(mgmt_total, 2),
        "admin_fee": round(admin_total, 2),
        "fee_total": round(fee_total, 2),
        "distributions": [
            {
                "id": str(r.id),
                "vessel_id": str(r.vessel_id),
                "points": float(r.points or 0),
                "gross_share": float(r.gross_share or 0),
                "fee_deduction": float(r.fee_deduction or 0),
                "net_share": float(r.net_share or 0),
                "paid_status": r.paid_status,
            }
            for r in rows
        ],
    }


@router.post("/pools/{pool_id}/periods/{period_id}/cash-distribution")
def cash_distribution(
    pool_id: UUID,
    period_id: UUID,
    auth: AuthContext = Depends(require_module("pooling")),
    db: Session = Depends(get_db),
):
    """Cash distribution workflow: mark all pending distributions paid.

    Period moves calculating → settled (already-settled periods can re-run;
    open/cancelled → 409 — run calculate-fees first).
    """
    _require_pool(db, pool_id, auth.tenant_id)
    period = _require_period(db, pool_id, period_id, auth.tenant_id)

    rows = db.scalars(
        scoped_query(db, PoolDistribution, auth.tenant_id).where(
            PoolDistribution.period_id == period_id
        )
    ).all()
    if not rows:
        raise HTTPException(400, detail={"code": "NO_DISTRIBUTIONS", "message": "Run calculate-fees first"})

    if period.status == "calculating":
        period.status = transition("pool_period", period.status, "settled", POOL_PERIOD_TRANSITIONS)
    elif period.status != "settled":
        transition("pool_period", period.status, "settled", POOL_PERIOD_TRANSITIONS)

    paid_total = 0.0
    for r in rows:
        if r.paid_status != "paid":
            r.paid_status = "paid"
        paid_total += float(r.net_share or 0)
    db.commit()

    return {
        "period_id": str(period_id),
        "status": period.status,
        "paid_count": len(rows),
        "paid_total": round(paid_total, 2),
    }


@router.get("/pools/{pool_id}/periods/{period_id}/summary")
def period_summary(
    pool_id: UUID,
    period_id: UUID,
    auth: AuthContext = Depends(require_module("pooling")),
    db: Session = Depends(get_db),
):
    """Period summary: fees, per-vessel distribution, totals and intercompany split."""
    pool = _require_pool(db, pool_id, auth.tenant_id)
    period = _require_period(db, pool_id, period_id, auth.tenant_id)

    fees = db.scalars(
        scoped_query(db, PoolFee, auth.tenant_id).where(
            PoolFee.pool_id == pool_id,
            PoolFee.active.is_(True),
        )
    ).all()
    rows = db.scalars(
        scoped_query(db, PoolDistribution, auth.tenant_id)
        .where(PoolDistribution.period_id == period_id)
        .order_by(PoolDistribution.created_at)
    ).all()

    total_pool_result = float(period.total_pool_result or 0)
    mgmt_total, admin_total, fee_total = _fee_totals(list(fees), total_pool_result)
    gross_total = sum(float(r.gross_share or 0) for r in rows)
    net_total = sum(float(r.net_share or 0) for r in rows)
    paid_count = sum(1 for r in rows if r.paid_status == "paid")
    distribution = period.distribution or {}
    intercompany = distribution.get("intercompany") if isinstance(distribution, dict) else None

    return {
        "pool_id": str(pool.id),
        "pool_name": pool.name,
        "period_id": str(period.id),
        "label": period.label,
        "status": period.status,
        "total_pool_result": total_pool_result,
        "fees": [_fee_out(f).model_dump() for f in fees],
        "management_fee": round(mgmt_total, 2),
        "admin_fee": round(admin_total, 2),
        "fee_total": round(fee_total, 2),
        "distributions": [
            {
                "id": str(r.id),
                "vessel_id": str(r.vessel_id),
                "points": float(r.points or 0),
                "gross_share": float(r.gross_share or 0),
                "fee_deduction": float(r.fee_deduction or 0),
                "net_share": float(r.net_share or 0),
                "paid_status": r.paid_status,
            }
            for r in rows
        ],
        "gross_total": round(gross_total, 2),
        "net_total": round(net_total, 2),
        "paid_count": paid_count,
        "pending_count": len(rows) - paid_count,
        "intercompany": intercompany,
    }


@router.post("/pools/{pool_id}/periods/{period_id}/intercompany-distribution")
def intercompany_distribution(
    pool_id: UUID,
    period_id: UUID,
    body: IntercompanyIn,
    auth: AuthContext = Depends(require_module("pooling")),
    db: Session = Depends(get_db),
):
    """Company settlement: split the period net total across group companies.

    Body: {"allocations": [{"company_id": "...", "share_pct": 60}, ...]}
    share_pct must sum to 100 (±0.01). Result is persisted into
    period.distribution["intercompany"].
    """
    _require_pool(db, pool_id, auth.tenant_id)
    period = _require_period(db, pool_id, period_id, auth.tenant_id)

    if not body.allocations:
        raise HTTPException(400, detail={"code": "NO_ALLOCATIONS", "message": "allocations must not be empty"})
    total_pct = sum(a.share_pct for a in body.allocations)
    if abs(total_pct - 100.0) > 0.01:
        raise HTTPException(
            400,
            detail={"code": "INVALID_SHARE_PCT", "message": f"share_pct must sum to 100, got {total_pct}"},
        )

    fees = db.scalars(
        scoped_query(db, PoolFee, auth.tenant_id).where(
            PoolFee.pool_id == pool_id,
            PoolFee.active.is_(True),
        )
    ).all()
    total_pool_result = float(period.total_pool_result or 0)
    _, _, fee_total = _fee_totals(list(fees), total_pool_result)
    net_total = round(total_pool_result - fee_total, 2)

    result = []
    for a in body.allocations:
        company = scoped_get(db, Company, a.company_id, auth.tenant_id)
        if not company:
            raise HTTPException(
                404,
                detail={"code": "COMPANY_NOT_FOUND", "message": f"Company not found: {a.company_id}"},
            )
        result.append(
            {
                "company_id": str(company.id),
                "company_name": company.name,
                "share_pct": a.share_pct,
                "amount": round(net_total * a.share_pct / 100.0, 2),
                "note": a.note,
            }
        )

    distribution = dict(period.distribution or {})
    distribution["intercompany"] = result
    period.distribution = distribution
    db.commit()

    return {
        "period_id": str(period_id),
        "net_total": net_total,
        "allocations": result,
    }
