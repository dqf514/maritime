"""Market / DQ / Emissions / Analytics 路由（原 finance_ext 的余部）。

发票/索赔/laytime/燃油/港口使费已按域拆分至同目录独立路由文件。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.pagination import envelope, paginate
from app.security import AuthContext, require_module
from app.models_domain import (
    BunkerOrder,
    Charter,
    Claim,
    DqIssue,
    EmissionRecord,
    Invoice,
    LaytimeCalc,
    MarketQuote,
    NoonReport,
    Payment,
    Pool,
    PoolPeriod,
    PoolVessel,
    PortCall,
    PortDisbursement,
    PortalMessage,
    BerthWindow,
    RiskPosition,
    Document,
    SofEvent,
    Voyage,
    VoyageAccrual,
)
from app.models_finance_ext import BunkerInquiry, CreditNote, OffHireEvent, RiskLimit
from app.models_wave1 import Company, Counterparty, ExchangeRate, Port, Vessel
from app.services import cii as cii_service
from app.services.laytime_engine import compute_laytime, compute_laytime_statement
from app.services.pnl import PNL_LINE_KEYS, voyage_pnl_rows
from app.services import pnl_engine
from app.services.sanctions import assert_not_sanctioned
from app.services.state_machine import POOL_PERIOD_TRANSITIONS, transition
from app.services.tenant_guard import scoped_get
from app.routers._finance_common import DEFAULT_VAR_LIMIT

router = APIRouter()


# —— Market / DQ / Emissions / Analytics ——
@router.post("/market/quotes")
def add_quote(symbol: str, value: float, quote_date: date | None = None, auth: AuthContext = Depends(require_module("analytics")), db: Session = Depends(get_db)):
    qd = quote_date or date.today()
    row = db.scalar(
        select(MarketQuote).where(
            MarketQuote.tenant_id == auth.tenant_id,
            MarketQuote.symbol == symbol,
            MarketQuote.quote_date == qd,
        )
    )
    if row:
        row.value = value
        row.source = "manual"
    else:
        row = MarketQuote(tenant_id=auth.tenant_id, symbol=symbol, value=value, quote_date=qd, source="manual")
        db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "symbol": symbol, "value": float(row.value), "quote_date": qd.isoformat()}


@router.get("/market/quotes")
def list_quotes(auth: AuthContext = Depends(require_module("analytics")), db: Session = Depends(get_db)):
    rows = db.scalars(select(MarketQuote).where(MarketQuote.tenant_id == auth.tenant_id)).all()
    return [{"symbol": r.symbol, "value": float(r.value), "quote_date": r.quote_date.isoformat()} for r in rows]


@router.post("/dq/issues")
def create_dq(rule_code: str, entity_type: str, entity_id: str, message: str, auth: AuthContext = Depends(require_module("analytics")), db: Session = Depends(get_db)):
    row = DqIssue(tenant_id=auth.tenant_id, rule_code=rule_code, entity_type=entity_type, entity_id=entity_id, message=message)
    db.add(row)
    db.commit()
    return {"id": str(row.id), "status": row.status}


@router.get("/dq/issues")
def list_dq(
    status: str | None = Query(None),
    auth: AuthContext = Depends(require_module("analytics")),
    db: Session = Depends(get_db),
):
    q = select(DqIssue).where(DqIssue.tenant_id == auth.tenant_id)
    if status:
        q = q.where(DqIssue.status == status)
    rows = db.scalars(q).all()
    return [
        {
            "id": str(r.id),
            "rule_code": r.rule_code,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "severity": r.severity,
            "message": r.message,
            "status": r.status,
        }
        for r in rows
    ]


def _eeoi(co2_mt: float, cargo_mt: float | None, distance_nm: float | None) -> float | None:
    """EEOI (Energy Efficiency Operational Indicator) 口径: CO2 排放量(吨) ÷
    (货量 cargo_mt × 航程 distance_nm),单位 吨CO2/吨海里。
    每次按入参即时计算,不落库(EmissionRecord 无对应列,不在本任务范围)。"""
    if not cargo_mt or not distance_nm or cargo_mt <= 0 or distance_nm <= 0 or co2_mt <= 0:
        return None
    return co2_mt / (cargo_mt * distance_nm)


@router.post("/emissions")
def create_emission(
    voyage_id: UUID | None = None,
    vessel_id: UUID | None = None,
    fo_mt: float = 0,
    do_mt: float = 0,
    distance_nm: float | None = None,
    cargo_mt: float | None = None,  # 货量(吨);与 distance_nm 同时给出时响应带 eeoi
    dwt: float | None = None,
    ship_type: str = "bulk_carrier",
    year: int | None = None,
    auth: AuthContext = Depends(require_module("emissions")),
    db: Session = Depends(get_db),
):
    co2 = fo_mt * 3.114 + do_mt * 3.206
    extra: dict = {}
    eeoi = _eeoi(co2, cargo_mt, distance_nm)
    if eeoi is not None:
        extra["eeoi"] = eeoi
    if distance_nm and dwt and co2 > 0:
        res = cii_service.rate_cii(co2_mt=co2, dwt=dwt, distance_nm=distance_nm, year=year or date.today().year, ship_type=ship_type)
        cii = res["rating"]
        extra = {"attained_cii": res["attained_cii"], "required_cii": res["required_cii"], "cii_year": res["year"]}
    else:
        cii = "C" if co2 > 1000 else "B" if co2 > 500 else "A"
    row = EmissionRecord(tenant_id=auth.tenant_id, voyage_id=voyage_id, vessel_id=vessel_id, fo_mt=fo_mt, do_mt=do_mt, co2_mt=co2, cii_rating=cii)
    db.add(row)
    db.commit()
    return {"id": str(row.id), "co2_mt": co2, "cii_rating": cii, **extra}


@router.get("/emissions")
def list_emissions(auth: AuthContext = Depends(require_module("emissions")), db: Session = Depends(get_db)):
    rows = db.scalars(select(EmissionRecord).where(EmissionRecord.tenant_id == auth.tenant_id)).all()
    return [
        {
            "id": str(r.id),
            "voyage_id": str(r.voyage_id) if r.voyage_id else None,
            "vessel_id": str(r.vessel_id) if r.vessel_id else None,
            "fo_mt": float(r.fo_mt or 0),
            "do_mt": float(r.do_mt or 0),
            "co2_mt": float(r.co2_mt or 0),
            "cii_rating": r.cii_rating,
            "period": r.period,
        }
        for r in rows
    ]


class FuelEuIn(BaseModel):
    voyage_id: UUID | None = None
    vessel_id: UUID | None = None
    fo_mt: float = 0
    do_mt: float = 0
    lng_mt: float = 0
    distance_nm: float = 0
    cargo_mt: float = 0
    dwt: float = 0
    ship_type: str = "bulk_carrier"
    eu_share: float | None = None  # fraction of voyage in EU scope; auto-inferred from port calls when omitted
    ets_price_eur: float = 70.0
    fueleu_penalty_eur_per_tco2e: float = 2400.0


def _infer_eu_share(db: Session, tenant_id: UUID, voyage_id: UUID) -> float | None:
    """EU scope share —— 口径统一在 services.compliance_report.infer_eu_share（D17）。"""
    from app.services.compliance_report import infer_eu_share

    return infer_eu_share(db, tenant_id, voyage_id)


@router.post("/emissions/fueleu-calc")
def fueleu_calc(body: FuelEuIn, auth: AuthContext = Depends(require_module("emissions")), db: Session = Depends(get_db)):
    """FuelEU / EU ETS style calculator — persists EmissionRecord + returns compliance snapshot."""
    eu_share = body.eu_share
    eu_share_source = "manual"
    if eu_share is None:
        inferred = _infer_eu_share(db, auth.tenant_id, body.voyage_id) if body.voyage_id else None
        eu_share = inferred if inferred is not None else 1.0
        eu_share_source = "auto" if inferred is not None else "default"
    # ETS cost bearer is a commercial hint only — it does not change the amounts.
    borne_by = "owner"
    if body.voyage_id:
        voyage = db.get(Voyage, body.voyage_id)
        charter = db.get(Charter, voyage.charter_id) if voyage and voyage.charter_id else None
        if charter and charter.ets_responsibility == "charterer":
            borne_by = "charterer"
    # Simplified GHG intensity (gCO2e/MJ) vs FuelEU target trajectory
    energy_mj = body.fo_mt * 42700 + body.do_mt * 42700 + body.lng_mt * 48000  # approx LHV MJ/t
    co2e_t = body.fo_mt * 3.114 + body.do_mt * 3.206 + body.lng_mt * 2.75
    intensity = (co2e_t * 1_000_000 / energy_mj) if energy_mj > 0 else 0.0
    target_2025 = 89.34  # illustrative FuelEU reference gCO2e/MJ
    compliance_balance_t = max(0.0, (intensity - target_2025) / 1_000_000 * energy_mj) * eu_share
    ets_allowances = co2e_t * eu_share
    ets_cost = ets_allowances * body.ets_price_eur
    fueleu_penalty = compliance_balance_t * body.fueleu_penalty_eur_per_tco2e
    extra: dict = {}
    if body.dwt > 0 and body.distance_nm > 0 and co2e_t > 0:
        res = cii_service.rate_cii(co2_mt=co2e_t, dwt=body.dwt, distance_nm=body.distance_nm, year=date.today().year, ship_type=body.ship_type)
        cii = res["rating"]
        extra = {"attained_cii": res["attained_cii"], "required_cii": res["required_cii"]}
    else:
        cii = "C" if co2e_t > 1000 else "B" if co2e_t > 500 else "A"
    eeoi = _eeoi(co2e_t, body.cargo_mt or None, body.distance_nm or None)
    if eeoi is not None:
        extra["eeoi"] = eeoi
    row = EmissionRecord(
        tenant_id=auth.tenant_id,
        voyage_id=body.voyage_id,
        vessel_id=body.vessel_id,
        fo_mt=body.fo_mt,
        do_mt=body.do_mt,
        co2_mt=co2e_t,
        cii_rating=cii,
        period="fueleu",
    )
    db.add(row)
    db.commit()
    return {
        "id": str(row.id),
        "co2e_t": round(co2e_t, 3),
        "ghg_intensity": round(intensity, 4),
        "target_intensity": target_2025,
        "compliance_balance_t": round(compliance_balance_t, 4),
        "ets_allowances_t": round(ets_allowances, 3),
        "ets_cost_eur": round(ets_cost, 2),
        "fueleu_penalty_eur": round(fueleu_penalty, 2),
        "total_compliance_cost_eur": round(ets_cost + fueleu_penalty, 2),
        "cii_rating": cii,
        "eu_share": round(eu_share, 4),
        "eu_share_source": eu_share_source,
        "borne_by": borne_by,
        "format": "FuelEU_EU_ETS_v1",
        **extra,
    }


@router.get("/emissions/export")
def export_emissions(auth: AuthContext = Depends(require_module("emissions")), db: Session = Depends(get_db)):
    rows = db.scalars(select(EmissionRecord).where(EmissionRecord.tenant_id == auth.tenant_id)).all()
    return {
        "format": "EU_ETS_FuelEU_v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "rows": [
            {
                "voyage_id": str(r.voyage_id) if r.voyage_id else None,
                "vessel_id": str(r.vessel_id) if r.vessel_id else None,
                "fo_mt": float(r.fo_mt or 0),
                "do_mt": float(r.do_mt or 0),
                "co2_mt": float(r.co2_mt or 0),
                "cii": r.cii_rating,
                "period": r.period,
            }
            for r in rows
        ],
    }


@router.get("/analytics/reports/tce")
def report_tce(auth: AuthContext = Depends(require_module("analytics")), db: Session = Depends(get_db)):
    from app.models_domain import Estimate

    rows = db.scalars(select(Estimate).where(Estimate.tenant_id == auth.tenant_id, Estimate.status.in_(["calculated", "converted"]))).all()
    return [{"title": r.title, "tce": (r.results or {}).get("tce"), "id": str(r.id)} for r in rows]


# P&L aggregation lives in app.services.pnl (shared with the exception centre
# and the voyage 360 overview); PNL_LINE_KEYS re-exported for existing imports.


@router.get("/analytics/reports/voyage-pnl")
def report_pnl(
    basis: str = Query("actual", pattern="^(actual|accrual)$"),
    auth: AuthContext = Depends(require_module("analytics")),
    db: Session = Depends(get_db),
):
    """Dynamic voyage P&L: estimate vs actual revenue/cost drivers.

    basis=actual (default): booked invoices / PDAs / bunker orders.
    basis=accrual: additionally merges non-reversed VoyageAccrual rows into the
    line items (`lines_accrual`, `lines` merged, `accrual_net`, `accrual_pnl`).
    Legacy aggregate keys (actual_revenue/actual_cost/...) are unchanged.
    """
    return voyage_pnl_rows(db, auth.tenant_id, basis)


@router.get("/analytics/reports/pnl-4col")
def report_pnl_4col(
    voyage_id: str | None = Query(None),
    auth: AuthContext = Depends(require_module("analytics")),
    db: Session = Depends(get_db),
):
    """4-column P&L: estimate | actual | posted | variance per voyage."""
    vid = UUID(voyage_id) if voyage_id else None
    return pnl_engine.voyage_pnl_4col(db, auth.tenant_id, vid)


@router.get("/analytics/reports/pnl-fleet")
def report_pnl_fleet(
    auth: AuthContext = Depends(require_module("analytics")),
    db: Session = Depends(get_db),
):
    """Fleet-wide 4-column P&L summary."""
    return pnl_engine.fleet_pnl_summary(db, auth.tenant_id)


# —— Pooling / Risk / Berth / Portal / Docs ——
@router.get("/pools")
def list_pools(auth: AuthContext = Depends(require_module("pooling")), db: Session = Depends(get_db)):
    rows = db.scalars(select(Pool).where(Pool.tenant_id == auth.tenant_id)).all()
    out = []
    for r in rows:
        vessels = db.scalars(select(PoolVessel).where(PoolVessel.pool_id == r.id, PoolVessel.left_on.is_(None))).all()
        periods = db.scalars(select(PoolPeriod).where(PoolPeriod.pool_id == r.id)).all()
        out.append(
            {
                "id": str(r.id),
                "name": r.name,
                "vessel_count": len(vessels),
                "vessels": [{"id": str(v.id), "vessel_id": str(v.vessel_id), "points": float(v.points)} for v in vessels],
                "periods": [
                    {
                        "id": str(p.id),
                        "label": p.label,
                        "total_pool_result": float(p.total_pool_result or 0),
                        "status": p.status,
                        "distribution": p.distribution or {},
                    }
                    for p in periods
                ],
            }
        )
    return out


@router.post("/pools")
def create_pool(name: str, auth: AuthContext = Depends(require_module("pooling")), db: Session = Depends(get_db)):
    row = Pool(tenant_id=auth.tenant_id, name=name)
    db.add(row)
    db.commit()
    return {"id": str(row.id), "name": name}


@router.post("/pools/{pool_id}/vessels")
def add_pool_vessel(
    pool_id: UUID,
    vessel_id: UUID,
    points: float = 1.0,
    auth: AuthContext = Depends(require_module("pooling")),
    db: Session = Depends(get_db),
):
    from app.models_wave1 import Vessel

    pool = db.get(Pool, pool_id)
    if not pool or pool.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Pool not found")
    vessel = db.get(Vessel, vessel_id)
    if (
        not vessel
        or vessel.tenant_id != auth.tenant_id
        or vessel.status == "deleted"
        or getattr(vessel, "deleted_at", None) is not None
    ):
        raise HTTPException(404, detail={"code": "VESSEL_NOT_FOUND", "message": "Vessel not found"})
    if points <= 0:
        raise HTTPException(400, detail={"code": "INVALID_POINTS", "message": "Points must be positive"})

    # Already active in this pool
    existing = db.scalar(
        select(PoolVessel).where(
            PoolVessel.pool_id == pool_id,
            PoolVessel.vessel_id == vessel_id,
            PoolVessel.left_on.is_(None),
        )
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "VESSEL_ALREADY_IN_POOL",
                "message": "Vessel is already active in this pool",
                "membership_id": str(existing.id),
                "points": float(existing.points),
            },
        )

    # Same vessel cannot be active in two pools of the same tenant at once
    other = db.scalar(
        select(PoolVessel)
        .join(Pool, Pool.id == PoolVessel.pool_id)
        .where(
            Pool.tenant_id == auth.tenant_id,
            PoolVessel.vessel_id == vessel_id,
            PoolVessel.left_on.is_(None),
            PoolVessel.pool_id != pool_id,
        )
    )
    if other:
        other_pool = db.get(Pool, other.pool_id)
        raise HTTPException(
            status_code=409,
            detail={
                "code": "VESSEL_IN_OTHER_POOL",
                "message": "Vessel is already active in another pool; leave that pool first",
                "pool_id": str(other.pool_id),
                "pool_name": other_pool.name if other_pool else None,
            },
        )

    row = PoolVessel(pool_id=pool_id, vessel_id=vessel_id, points=points, joined_on=date.today())
    db.add(row)
    db.commit()
    return {"id": str(row.id), "vessel_id": str(vessel_id), "points": float(row.points)}


@router.patch("/pools/{pool_id}/vessels/{membership_id}")
def update_pool_vessel(
    pool_id: UUID,
    membership_id: UUID,
    points: float | None = None,
    auth: AuthContext = Depends(require_module("pooling")),
    db: Session = Depends(get_db),
):
    pool = db.get(Pool, pool_id)
    if not pool or pool.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Pool not found")
    row = db.get(PoolVessel, membership_id)
    if not row or row.pool_id != pool_id or row.left_on is not None:
        raise HTTPException(404, "Pool vessel membership not found")
    if points is not None:
        if points <= 0:
            raise HTTPException(400, detail={"code": "INVALID_POINTS", "message": "Points must be positive"})
        row.points = points
    db.commit()
    return {"id": str(row.id), "vessel_id": str(row.vessel_id), "points": float(row.points)}


@router.delete("/pools/{pool_id}/vessels/{membership_id}")
def leave_pool_vessel(
    pool_id: UUID,
    membership_id: UUID,
    auth: AuthContext = Depends(require_module("pooling")),
    db: Session = Depends(get_db),
):
    """Mark vessel as left the pool (historical row kept for settlement audit)."""
    pool = db.get(Pool, pool_id)
    if not pool or pool.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Pool not found")
    row = db.get(PoolVessel, membership_id)
    if not row or row.pool_id != pool_id or row.left_on is not None:
        raise HTTPException(404, "Pool vessel membership not found")
    row.left_on = date.today()
    db.commit()
    return {"ok": True, "id": str(row.id), "left_on": row.left_on.isoformat()}


@router.post("/pools/{pool_id}/periods")
def create_period(pool_id: UUID, label: str, total_pool_result: float, auth: AuthContext = Depends(require_module("pooling")), db: Session = Depends(get_db)):
    pool = db.get(Pool, pool_id)
    if not pool or pool.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Pool not found")
    vessels = db.scalars(select(PoolVessel).where(PoolVessel.pool_id == pool_id, PoolVessel.left_on.is_(None))).all()
    total_points = sum(float(v.points) for v in vessels) or 1.0
    dist = {str(v.vessel_id): round(total_pool_result * float(v.points) / total_points, 2) for v in vessels}
    row = PoolPeriod(pool_id=pool_id, label=label, total_pool_result=total_pool_result, distribution=dist, status="calculating")
    db.add(row)
    db.commit()
    return {"id": str(row.id), "distribution": dist, "status": row.status}


@router.post("/pools/periods/{period_id}/settle")
def settle_period(period_id: UUID, auth: AuthContext = Depends(require_module("pooling")), db: Session = Depends(get_db)):
    row = db.get(PoolPeriod, period_id)
    if not row:
        raise HTTPException(404, "Period not found")
    pool = db.get(Pool, row.pool_id)
    if not pool or pool.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Pool not found")
    row.status = transition("pool_period", row.status, "settled", POOL_PERIOD_TRANSITIONS)
    db.commit()
    return {"id": str(row.id), "status": row.status, "distribution": row.distribution}


def _resolve_var_limit(db: Session, tenant_id: UUID, symbol: str, counterparty: str | None = None) -> float:
    """Most specific active VaR limit wins: counterparty > symbol > global; fallback 100k."""
    scopes = []
    if counterparty:
        scopes.append(f"counterparty:{counterparty}")
    scopes.append(f"symbol:{symbol}")
    scopes.append("global")
    rows = db.scalars(
        select(RiskLimit).where(
            RiskLimit.tenant_id == tenant_id,
            RiskLimit.active.is_(True),
            RiskLimit.scope.in_(scopes),
        )
    ).all()
    by_scope = {r.scope: r for r in rows}
    for scope in scopes:
        if scope in by_scope:
            return float(by_scope[scope].amount)
    return DEFAULT_VAR_LIMIT


class RiskLimitIn(BaseModel):
    scope: str  # "global" | "symbol:<SYMBOL>" | "counterparty:<key>"
    limit_type: str = "var_1d"
    amount: float
    currency: str = "USD"
    active: bool = True


@router.get("/risk/limits")
def list_risk_limits(auth: AuthContext = Depends(require_module("risk")), db: Session = Depends(get_db)):
    rows = db.scalars(select(RiskLimit).where(RiskLimit.tenant_id == auth.tenant_id)).all()
    return [
        {
            "id": str(r.id),
            "scope": r.scope,
            "limit_type": r.limit_type,
            "amount": float(r.amount or 0),
            "currency": r.currency,
            "active": bool(r.active),
        }
        for r in rows
    ]


@router.post("/risk/limits")
def create_risk_limit(body: RiskLimitIn, auth: AuthContext = Depends(require_module("risk")), db: Session = Depends(get_db)):
    if body.amount <= 0:
        raise HTTPException(422, detail={"code": "INVALID_AMOUNT", "message": "Limit amount must be > 0"})
    row = RiskLimit(
        tenant_id=auth.tenant_id,
        scope=body.scope,
        limit_type=body.limit_type,
        amount=Decimal(str(body.amount)).quantize(Decimal("0.01")),
        currency=body.currency,
        active=body.active,
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "scope": row.scope, "amount": float(row.amount)}


@router.post("/risk/positions")
def create_risk(
    symbol: str,
    qty: float,
    entry_price: float,
    side: str = "long",
    counterparty: str | None = None,
    auth: AuthContext = Depends(require_module("risk")),
    db: Session = Depends(get_db),
):
    var_1d = abs(qty * entry_price * 0.02)
    limit = _resolve_var_limit(db, auth.tenant_id, symbol, counterparty)
    row = RiskPosition(
        tenant_id=auth.tenant_id,
        symbol=symbol,
        side=side,
        qty=qty,
        entry_price=entry_price,
        mark_price=entry_price,
        var_1d=var_1d,
        limit_breach=var_1d > limit,
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "var_1d": var_1d, "limit": limit, "limit_breach": row.limit_breach}


@router.get("/risk/positions")
def list_risk(auth: AuthContext = Depends(require_module("risk")), db: Session = Depends(get_db)):
    rows = db.scalars(select(RiskPosition).where(RiskPosition.tenant_id == auth.tenant_id)).all()
    return [{"id": str(r.id), "symbol": r.symbol, "var_1d": float(r.var_1d or 0), "limit_breach": r.limit_breach} for r in rows]


@router.get("/risk/hedge-view")
def hedge_view(auth: AuthContext = Depends(require_module("risk")), db: Session = Depends(get_db)):
    """FFA/纸货 vs 实货对冲视图,按 symbol 聚合。

    口径(简化):
    - 纸货 paper_qty = RiskPosition 按 symbol 聚合的有符号数量(long +qty, short −qty)。
    - 实货 physical_qty = active 状态 Charter(在手货盘)的 cargo_qty 合计;
      Charter 无 symbol 字段,映射取其关联 Voyage 的 cargo 文本(去空格大写)
      作为 symbol,同一租约多个航次取第一个非空 cargo,无则归入 "UNMAPPED"。
    - net_exposure = physical − paper;hedge_ratio = paper / physical
      (physical = 0 时为 null)。
    """
    paper: dict[str, Decimal] = {}
    for p in db.scalars(select(RiskPosition).where(RiskPosition.tenant_id == auth.tenant_id)).all():
        sign = Decimal("-1") if (p.side or "long") == "short" else Decimal("1")
        paper[p.symbol] = paper.get(p.symbol, Decimal("0")) + sign * Decimal(str(p.qty or 0))

    physical: dict[str, Decimal] = {}
    charters = db.scalars(
        select(Charter).where(Charter.tenant_id == auth.tenant_id, Charter.status == "active")
    ).all()
    for ch in charters:
        voyages = db.scalars(select(Voyage).where(Voyage.charter_id == ch.id)).all()
        cargo_text = next((v.cargo for v in voyages if v.cargo), None)
        symbol = (cargo_text.strip().upper() if cargo_text and cargo_text.strip() else "UNMAPPED")
        physical[symbol] = physical.get(symbol, Decimal("0")) + Decimal(str(ch.cargo_qty or 0))

    out = []
    for symbol in sorted(set(paper) | set(physical)):
        p = float(paper.get(symbol, Decimal("0")))
        ph = float(physical.get(symbol, Decimal("0")))
        out.append(
            {
                "symbol": symbol,
                "paper_qty": p,
                "physical_qty": ph,
                "net_exposure": ph - p,
                "hedge_ratio": (p / ph) if ph != 0 else None,
            }
        )
    return out



class BerthIn(BaseModel):
    berth_name: str
    start_at: datetime
    end_at: datetime
    port_id: UUID | None = None
    voyage_id: UUID | None = None


@router.post("/berths")
def create_berth(body: BerthIn, auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    row = BerthWindow(
        tenant_id=auth.tenant_id,
        berth_name=body.berth_name,
        start_at=body.start_at,
        end_at=body.end_at,
        port_id=body.port_id,
        voyage_id=body.voyage_id,
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "berth_name": body.berth_name, "status": row.status}


@router.post("/portal/messages")
def portal_message(counterparty_id: UUID, subject: str, body: str | None = None, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    party = db.get(Counterparty, counterparty_id)
    if not party or party.tenant_id != auth.tenant_id or party.deleted_at:
        raise HTTPException(404, "Counterparty not found")
    assert_not_sanctioned(db, auth.tenant_id, party.id)
    row = PortalMessage(tenant_id=auth.tenant_id, counterparty_id=counterparty_id, subject=subject, body=body)
    db.add(row)
    db.commit()
    return {"id": str(row.id)}


@router.get("/portal/invoices")
def portal_invoices(counterparty_id: UUID, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Invoice).where(Invoice.tenant_id == auth.tenant_id, Invoice.counterparty_id == counterparty_id)
    ).all()
    return [{"invoice_no": r.invoice_no, "status": r.status, "amount": float(r.amount)} for r in rows]


@router.post("/documents")
def create_doc(entity_type: str, entity_id: UUID, title: str, doc_type: str = "file", auth: AuthContext = Depends(require_module("docs")), db: Session = Depends(get_db)):
    row = Document(tenant_id=auth.tenant_id, entity_type=entity_type, entity_id=entity_id, title=title, doc_type=doc_type, storage_uri=f"demo://{entity_type}/{entity_id}/{title}")
    db.add(row)
    db.commit()
    return {"id": str(row.id), "storage_uri": row.storage_uri}


@router.get("/risk/exposure")
def risk_exposure(
    horizon_days: int = Query(90, ge=30, le=365),
    market_hire_rate: float | None = Query(None, gt=0),
    sensitivity_per_day: float = Query(1000.0, gt=0),
    auth: AuthContext = Depends(require_module("risk")),
    db: Session = Depends(get_db),
):
    """D23 船队敞口：30/60/90 天已锁定租金 + 敏感度 + 可选市场对比。"""
    from app.services.exposure import fleet_exposure

    return fleet_exposure(
        db,
        auth.tenant_id,
        horizon_days=horizon_days,
        market_hire_rate=market_hire_rate,
        sensitivity_per_day=sensitivity_per_day,
    )


@router.get("/emissions/compliance-report")
def emissions_compliance_report(
    scheme: str = Query("mrv", pattern="^(mrv|ets|fueleu)$"),
    period: str | None = Query(None),
    auth: AuthContext = Depends(require_module("emissions")),
    db: Session = Depends(get_db),
):
    """D17 申报导出：MRV 排放清单 / ETS 配额 / FuelEU 合规平衡（含 CSV）。"""
    from app.services.compliance_report import compliance_report

    return compliance_report(db, auth.tenant_id, scheme, period)


class RiskLimitUpdate(BaseModel):
    amount: float | None = None
    currency: str | None = None
    active: bool | None = None


@router.patch("/risk/limits/{limit_id}")
def update_risk_limit(
    limit_id: UUID,
    body: RiskLimitUpdate,
    auth: AuthContext = Depends(require_module("risk")),
    db: Session = Depends(get_db),
):
    """U6 行内编辑落点：限额金额/币种/启用态的安全字段更新。"""
    row = scoped_get(db, RiskLimit, limit_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, "Risk limit not found")
    if body.amount is not None:
        row.amount = body.amount
    if body.currency is not None:
        row.currency = body.currency
    if body.active is not None:
        row.active = body.active
    db.commit()
    return {"id": str(row.id), "amount": float(row.amount), "currency": row.currency, "active": bool(row.active)}
