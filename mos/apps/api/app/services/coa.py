"""Phase 6 COA services — 合同分单、运力分摊、燃油中性盈亏.

口径（确定性、Decimal）：
- 分摊 :func:`allocate_lifting` — 一票 CoaLifting 指派到某行 CoaItinerary
  （按 ``itinerary_seq``）；数量取 lifting 的 ``actual_qty``（未完航取
  ``planned_qty``）；行内 ``allocated_qty`` 累加，超出该行计划量 → 422。
- 汇总 :func:`allocation_summary` — 合同总量 vs 分单计划量 vs 已分摊量。
- 燃油中性盈亏 :func:`fuel_neutral_pnl` — 收入按计价方式计提
  （per_voyage × 完成票数 / per_mt × 完成量 / lumpsum 一次性），成本取
  关联航次的加油单（fuel）与使费（other）；``pnl_fuel_neutral`` = 收入 − 非燃油
  成本（把油价波动中性化），``pnl_gross`` = 收入 − 全部成本。
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_coa import CoaAllocation, CoaContract, CoaItinerary
from app.models_domain import BunkerOrder, Charter, CoaLifting, PortDisbursement
from app.services.tenant_guard import scoped_get

ZERO = Decimal("0")


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def _lifting_qty(lift: CoaLifting) -> Decimal:
    """计价数量：完航票取 actual_qty，否则取 planned_qty。"""
    q = lift.actual_qty if lift.actual_qty is not None else lift.planned_qty
    return Decimal(str(q or 0))


def get_contract(db: Session, tenant_id: UUID, coa_contract_id: UUID) -> CoaContract:
    row = scoped_get(db, CoaContract, coa_contract_id, tenant_id)
    if row is None:
        raise HTTPException(404, "COA contract not found")
    return row


def allocate_lifting(
    db: Session,
    tenant_id: UUID,
    coa_contract_id: UUID,
    lifting_id: UUID,
    itinerary_seq: int,
) -> CoaAllocation:
    """把一票 lifting 分摊到指定分单行；一票只可分摊一次，行内量不得超计划。"""
    contract = get_contract(db, tenant_id, coa_contract_id)
    if contract.status not in ("draft", "active"):
        raise HTTPException(
            422,
            detail={"code": "COA_NOT_ALLOCATABLE", "message": f"contract is {contract.status}"},
        )
    # 归属经由父租约校验（IDOR 防护）；tenant_id 列为报表数据集补强，旧数据可能为空
    lift = db.get(CoaLifting, lifting_id)
    if lift is None:
        raise HTTPException(404, "Lifting not found")
    ch = db.get(Charter, lift.charter_id)
    if ch is None or ch.tenant_id != tenant_id:
        raise HTTPException(404, "Lifting not found")
    if lift.charter_id != contract.charter_id:
        raise HTTPException(
            422,
            detail={"code": "LIFTING_WRONG_CHARTER", "message": "lifting does not belong to the COA charter"},
        )
    existing = db.scalar(select(CoaAllocation).where(CoaAllocation.lifting_id == lift.id))
    if existing is not None:
        raise HTTPException(
            422,
            detail={"code": "LIFTING_ALREADY_ALLOCATED", "message": "lifting already allocated"},
        )
    itinerary = db.scalar(
        select(CoaItinerary).where(
            CoaItinerary.coa_contract_id == contract.id,
            CoaItinerary.seq == itinerary_seq,
        )
    )
    if itinerary is None:
        raise HTTPException(404, "Itinerary not found")
    qty = _lifting_qty(lift)
    if qty <= ZERO:
        raise HTTPException(
            422,
            detail={"code": "LIFTING_QTY_MISSING", "message": "lifting has no planned/actual qty"},
        )
    allocated = itinerary.allocated_qty or ZERO
    if allocated + qty > itinerary.qty:
        raise HTTPException(
            422,
            detail={
                "code": "ITINERARY_OVER_ALLOCATED",
                "message": f"itinerary seq {itinerary_seq}: {allocated + qty} > planned {itinerary.qty}",
            },
        )
    alloc = CoaAllocation(
        tenant_id=tenant_id,
        coa_contract_id=contract.id,
        itinerary_id=itinerary.id,
        lifting_id=lift.id,
        qty=qty,
    )
    itinerary.allocated_qty = allocated + qty
    db.add(alloc)
    db.commit()
    db.refresh(alloc)
    return alloc


def allocation_summary(db: Session, tenant_id: UUID, coa_contract_id: UUID) -> dict:
    """合同总量 vs 分单计划 vs 已分摊（按行 + 合计）。"""
    contract = get_contract(db, tenant_id, coa_contract_id)
    itineraries = db.scalars(
        select(CoaItinerary)
        .where(CoaItinerary.coa_contract_id == contract.id)
        .order_by(CoaItinerary.seq)
    ).all()
    rows = [
        {
            "seq": it.seq,
            "load_port_id": str(it.load_port_id) if it.load_port_id else None,
            "disch_port_id": str(it.disch_port_id) if it.disch_port_id else None,
            "qty": _f(it.qty),
            "allocated_qty": _f(it.allocated_qty),
            "remaining_qty": _f(it.qty) - _f(it.allocated_qty),
        }
        for it in itineraries
    ]
    planned = sum((it.qty or ZERO) for it in itineraries)
    allocated = sum((it.allocated_qty or ZERO) for it in itineraries)
    return {
        "coa_contract_id": str(contract.id),
        "coa_no": contract.coa_no,
        "total_qty": _f(contract.total_qty),
        "qty_unit": contract.qty_unit,
        "planned_qty": _f(planned),
        "allocated_qty": _f(allocated),
        "remaining_qty": _f(contract.total_qty) - _f(allocated),
        "unplanned_qty": _f(contract.total_qty) - _f(planned),
        "itineraries": rows,
    }


def _contract_costs(db: Session, tenant_id: UUID, contract: CoaContract) -> tuple[Decimal, Decimal, int]:
    """关联航次的成本：(fuel_cost, other_cost, voyage_count)。

    关联路径：CoaAllocation → CoaLifting → voyage_id；无航次的分摊不产生成本。
    """
    allocs = db.scalars(
        select(CoaAllocation).where(CoaAllocation.coa_contract_id == contract.id)
    ).all()
    voyage_ids: set[UUID] = set()
    for a in allocs:
        lift = db.get(CoaLifting, a.lifting_id)
        if lift is not None and lift.voyage_id is not None:
            voyage_ids.add(lift.voyage_id)
    if not voyage_ids:
        return ZERO, ZERO, 0
    fuel = ZERO
    for b in db.scalars(
        select(BunkerOrder).where(
            BunkerOrder.tenant_id == tenant_id,
            BunkerOrder.voyage_id.in_(voyage_ids),
        )
    ).all():
        qty = b.qty_delivered if b.qty_delivered is not None else b.qty_ordered
        fuel += Decimal(str(qty or 0)) * Decimal(str(b.unit_price or 0))
    other = ZERO
    for p in db.scalars(
        select(PortDisbursement).where(
            PortDisbursement.tenant_id == tenant_id,
            PortDisbursement.voyage_id.in_(voyage_ids),
        )
    ).all():
        other += Decimal(str(p.fda_amount or p.pda_amount or 0))
    return fuel, other, len(voyage_ids)


def fuel_neutral_pnl(db: Session, tenant_id: UUID, coa_contract_id: UUID) -> dict:
    """COA 燃油中性盈亏（确定性）。

    - 收入：per_voyage = rate × 完成分摊票数；per_mt = rate × 完成分摊量；
      lumpsum = rate 一次计（有完成票即计）。“完成”= lifting.status == completed
      或已有 actual_qty。
    - 成本：关联航次加油单 → fuel_cost；使费 PDA/FDA → other_cost。
    - pnl_fuel_neutral = revenue − other_cost（油价中性）；
      pnl_gross = revenue − fuel_cost − other_cost。
    """
    contract = get_contract(db, tenant_id, coa_contract_id)
    allocs = db.scalars(
        select(CoaAllocation).where(CoaAllocation.coa_contract_id == contract.id)
    ).all()
    completed_qty = ZERO
    completed_count = 0
    for a in allocs:
        lift = db.get(CoaLifting, a.lifting_id)
        if lift is None:
            continue
        done = lift.status == "completed" or lift.actual_qty is not None
        if not done:
            continue
        completed_count += 1
        completed_qty += _lifting_qty(lift)

    rate = Decimal(str(contract.rate or 0))
    basis = contract.rate_basis
    if basis == "per_voyage":
        revenue = rate * completed_count
    elif basis == "per_mt":
        revenue = rate * completed_qty
    elif basis == "lumpsum":
        revenue = rate if completed_count > 0 else ZERO
    else:
        raise HTTPException(
            422,
            detail={"code": "COA_RATE_BASIS_UNKNOWN", "message": f"rate_basis {basis}"},
        )

    fuel_cost, other_cost, voyage_count = _contract_costs(db, tenant_id, contract)
    pnl_fuel_neutral = revenue - other_cost
    pnl_gross = revenue - fuel_cost - other_cost
    return {
        "coa_contract_id": str(contract.id),
        "coa_no": contract.coa_no,
        "rate_basis": basis,
        "rate": _f(contract.rate),
        "currency": contract.currency,
        "completed_liftings": completed_count,
        "completed_qty": _f(completed_qty),
        "voyage_count": voyage_count,
        "revenue": _f(revenue),
        "fuel_cost": _f(fuel_cost),
        "other_cost": _f(other_cost),
        "pnl_fuel_neutral": _f(pnl_fuel_neutral),
        "pnl_gross": _f(pnl_gross),
    }
