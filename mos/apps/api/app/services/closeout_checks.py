"""收尾清单判定 —— 抽成可复用函数（单一真相）。

``services/voyage_close.closing_check``（航次收尾清单）与
``services/action_catalog``（系统动作目录 / 自动勾完成）**必须用同一份判定**，
否则会出现"清单说好了、任务却没自动勾掉"或反过来的分裂。

本模块只做**只读判定**，不产文案、不写库：
每个函数返回一个小 dict，含 ``ok``（是否满足）与若干计数，
调用方（清单 UI / 动作判定器）各自决定怎么呈现。

清单里的 8 项与本模块的 8 个函数一一对应：

===================  ==========================================  =========
清单 key             函数                                        严重度
===================  ==========================================  =========
``port_calls``       :func:`port_calls_state`                   warn
``sof``              :func:`sof_state`                          warn
``laytime``          :func:`laytime_state`                      warn
``claims``           :func:`claims_state`                       warn
``invoices``         :func:`invoices_state`                     warn
``bunker``           :func:`bunker_state`                       warn
``emissions``        :func:`emissions_state`                    info
``accruals``         :func:`accruals_state`                     warn
===================  ==========================================  =========
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import (
    BunkerOrder,
    Claim,
    EmissionRecord,
    Invoice,
    LaytimeCalc,
    NoonReport,
    PortCall,
    SofEvent,
    VoyageAccrual,
)

ZERO = Decimal("0")


def _voyage_calls(db: Session, tenant_id: UUID, voyage_id: UUID) -> list[PortCall]:
    return list(
        db.scalars(
            select(PortCall).where(
                PortCall.tenant_id == tenant_id,
                PortCall.voyage_id == voyage_id,
                PortCall.deleted_at.is_(None),
            )
        ).all()
    )


def port_calls_state(db: Session, tenant_id: UUID, voyage_id: UUID) -> dict:
    """挂靠港事实齐备（ATA/ATD 都有）。"""
    calls = _voyage_calls(db, tenant_id, voyage_id)
    missing = [c for c in calls if not (c.ata and c.atd)]
    done = len(calls) - len(missing)
    return {
        "ok": bool(calls) and not missing,
        "total": len(calls),
        "done": done,
        "missing": len(missing),
    }


def sof_state(db: Session, tenant_id: UUID, voyage_id: UUID) -> dict:
    """SOF 装卸事实已记录（COMMENCED + COMPLETED 都在）。"""
    pc_ids = [c.id for c in _voyage_calls(db, tenant_id, voyage_id)]
    codes: set[str] = set()
    if pc_ids:
        evs = db.scalars(
            select(SofEvent).where(
                SofEvent.tenant_id == tenant_id,
                SofEvent.port_call_id.in_(pc_ids),
                SofEvent.deleted_at.is_(None),
            )
        ).all()
        codes = {e.event_code for e in evs}
    return {
        "ok": "COMMENCED" in codes and "COMPLETED" in codes,
        "codes": codes,
    }


def laytime_state(db: Session, tenant_id: UUID, voyage_id: UUID) -> dict:
    """装卸时间计算已定稿（≥1 份 finalized）。"""
    lts = list(
        db.scalars(
            select(LaytimeCalc).where(LaytimeCalc.tenant_id == tenant_id, LaytimeCalc.voyage_id == voyage_id)
        ).all()
    )
    finalized = [l for l in lts if l.status == "finalized" or l.finalized_at]
    return {
        "ok": bool(finalized),
        "total": len(lts),
        "done": len(finalized),
    }


def claims_state(db: Session, tenant_id: UUID, voyage_id: UUID) -> dict:
    """索赔已了结（无 open/negotiating）。"""
    open_claims = list(
        db.scalars(
            select(Claim).where(
                Claim.tenant_id == tenant_id,
                Claim.voyage_id == voyage_id,
                Claim.status.in_(("open", "negotiating")),
            )
        ).all()
    )
    return {"ok": not open_claims, "open": len(open_claims)}


def invoices_state(db: Session, tenant_id: UUID, voyage_id: UUID) -> dict:
    """发票已签发（≥1 张 issued；一张都没有则视为不适用 → ok）。"""
    invs = list(
        db.scalars(select(Invoice).where(Invoice.tenant_id == tenant_id, Invoice.voyage_id == voyage_id)).all()
    )
    issued = [i for i in invs if i.status in ("issued", "partially_paid", "paid")]
    drafts = [i for i in invs if i.status in ("draft", "pending_approval")]
    return {
        "ok": bool(issued) or not invs,
        "total": len(invs),
        "issued": len(issued),
        "drafts": len(drafts),
        "invoices": invs,
        "issued_rows": issued,
    }


def bunker_state(db: Session, tenant_id: UUID, voyage_id: UUID) -> dict:
    """加油订单已交付（全部 delivered/cancelled）。"""
    orders = list(
        db.scalars(
            select(BunkerOrder).where(BunkerOrder.tenant_id == tenant_id, BunkerOrder.voyage_id == voyage_id)
        ).all()
    )
    undelivered = [o for o in orders if o.status not in ("delivered", "cancelled")]
    return {
        "ok": not undelivered,
        "total": len(orders),
        "done": len(orders) - len(undelivered),
        "open": len(undelivered),
    }


def emissions_state(db: Session, tenant_id: UUID, voyage_id: UUID) -> dict:
    """排放数据已记录（有排放记录或有午报可推算）。"""
    has_emissions = db.scalar(
        select(EmissionRecord.id).where(
            EmissionRecord.tenant_id == tenant_id, EmissionRecord.voyage_id == voyage_id
        ).limit(1)
    ) is not None
    has_noon = db.scalar(
        select(NoonReport.id).where(NoonReport.tenant_id == tenant_id, NoonReport.voyage_id == voyage_id).limit(1)
    ) is not None
    return {"ok": has_emissions or has_noon, "has_emissions": has_emissions, "has_noon": has_noon}


def accruals_state(db: Session, tenant_id: UUID, voyage_id: UUID) -> dict:
    """计提与实际发票已对平（差异 ≤ max(5%, 1)）。

    没有已过账计提 → 视为无需对平（ok）。
    """
    accruals = list(
        db.scalars(
            select(VoyageAccrual).where(
                VoyageAccrual.tenant_id == tenant_id,
                VoyageAccrual.voyage_id == voyage_id,
                VoyageAccrual.status == "posted",
            )
        ).all()
    )
    if not accruals:
        return {"ok": True, "has_accruals": False, "accrual": ZERO, "invoice": ZERO, "diff": ZERO}
    accr_total = sum(Decimal(str(a.amount or 0)) for a in accruals)
    inv_state = invoices_state(db, tenant_id, voyage_id)
    issued = inv_state.get("issued_rows") or []
    inv_total = sum(
        Decimal(str(i.base_amount if i.base_amount is not None else i.amount or 0)) for i in issued
    )
    diff = abs(accr_total - inv_total)
    threshold = abs(accr_total) * Decimal("0.05")
    return {
        "ok": diff <= max(threshold, Decimal("1")),
        "has_accruals": True,
        "accrual": accr_total,
        "invoice": inv_total,
        "diff": diff,
    }
