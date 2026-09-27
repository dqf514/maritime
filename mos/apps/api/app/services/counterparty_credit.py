"""对手方信用与合规（Phase 2 / D24）：制裁重筛 + 信用敞口。

- 重筛（rescreen）：按当前制裁状态重记一次筛查审计（SanctionsScreening），
  供定期批量重筛作业调用；外部名单提供方可在 provider 处接入（现为
  internal-list-v1，与 assert_not_sanctioned 同源口径）。
- 信用敞口：未结发票合计（issued/partially_paid）对比信用限额
  （RiskLimit scope="counterparty:{id}", limit_type="credit"），超额即 breach。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_finance_ext import RiskLimit, SanctionsScreening
from app.models_wave1 import Counterparty
from app.models_domain import Invoice
from app.services.job_queue import job_handler


def rescreen(db: Session, tenant_id: UUID, counterparty_id: UUID, *, provider: str = "internal-list-v1") -> dict[str, Any]:
    """重筛一次并落审计行（不阻断业务写路径；状态变更由数据源刷新驱动）。"""
    party = db.get(Counterparty, counterparty_id)
    if not party or party.tenant_id != tenant_id:
        return {"error": "not_found"}
    result = "clear" if (party.sanctions_status or "clear") == "clear" else "blocked"
    row = SanctionsScreening(
        tenant_id=tenant_id,
        counterparty_id=counterparty_id,
        provider=provider,
        result=result,
    )
    db.add(row)
    db.commit()
    return {
        "counterparty_id": str(counterparty_id),
        "name": party.name,
        "result": result,
        "sanctions_status": party.sanctions_status,
        "screening_id": str(row.id),
    }


def credit_exposure(db: Session, tenant_id: UUID, counterparty_id: UUID) -> dict[str, Any]:
    """未结发票敞口 vs 信用限额。"""
    party = db.get(Counterparty, counterparty_id)
    if not party or party.tenant_id != tenant_id:
        return {"error": "not_found"}
    open_invoices = db.scalars(
        select(Invoice).where(
            Invoice.tenant_id == tenant_id,
            Invoice.counterparty_id == counterparty_id,
            Invoice.status.in_(["issued", "partially_paid"]),
        )
    ).all()
    exposure = sum(
        (Decimal(str(i.amount or 0)) + Decimal(str(i.tax_amount or 0)) - Decimal(str(i.paid_amount or 0)) for i in open_invoices),
        Decimal("0"),
    )
    limit_row = db.scalar(
        select(RiskLimit).where(
            RiskLimit.tenant_id == tenant_id,
            RiskLimit.scope == f"counterparty:{counterparty_id}",
            RiskLimit.limit_type == "credit",
            RiskLimit.active.is_(True),
        )
    )
    limit = float(limit_row.amount) if limit_row else None
    exposure_f = float(exposure)
    return {
        "counterparty_id": str(counterparty_id),
        "name": party.name,
        "credit_rating": party.credit_rating,
        "open_exposure": exposure_f,
        "open_invoice_count": len(open_invoices),
        "credit_limit": limit,
        "breach": bool(limit is not None and exposure_f > limit),
        "utilization_pct": round(exposure_f / limit * 100, 1) if limit else None,
    }


@job_handler("counterparty.rescreen")
def _rescreen_all_job(db: Session, job) -> None:
    """批量重筛作业：遍历本租户全部对手方逐个重筛。"""
    from uuid import UUID as _UUID

    tenant_id = _UUID(str(job.payload.get("tenant_id") or job.tenant_id))
    parties = db.scalars(select(Counterparty).where(Counterparty.tenant_id == tenant_id)).all()
    for pty in parties:
        rescreen(db, tenant_id, pty.id)
