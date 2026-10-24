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
from app.services.money import invoice_base_open


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
    """未结发票敞口 vs 信用限额。

    P1-B4：敞口**必须先折本币再求和**。旧实现直接把不同币种的发票金额加
    在一起（EUR 1000 + USD 1000 = 2000），算出来的使用率是 125% 而不是
    121.7% —— 数字看着像那么回事，其实口径是错的。

    同一条规则也适用于**限额**：限额不是本币时先折本币再比；折不动（没有
    汇率）就**不下结论**（``comparison_status="cannot_evaluate"``，``breach`` 为
    False）—— 拿外币限额跟本币敞口比出来的 breach 是**假 breach**。
    """
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
    # 未收 = 金额 + 税 − 已收；跨币种先折本币
    exposure = sum((invoice_base_open(i) for i in open_invoices), Decimal("0"))
    limit_row = db.scalar(
        select(RiskLimit).where(
            RiskLimit.tenant_id == tenant_id,
            RiskLimit.scope == f"counterparty:{counterparty_id}",
            RiskLimit.limit_type == "credit",
            RiskLimit.active.is_(True),
        )
    )
    limit_ccy = (limit_row.currency or "USD") if limit_row else None
    exposure_f = float(exposure)
    base_ccy = _base_currency(db, tenant_id)
    # 限额与敞口必须同币种才能比（P1-B4）—— 限额不是本币时先折本币。
    limit_original = Decimal(str(limit_row.amount)) if limit_row else None
    limit_base: Decimal | None = None
    if limit_row is None:
        comparison_status = "no_limit"
        comparison_note = "No credit limit configured for this counterparty."
    elif (limit_ccy or "").upper() == base_ccy.upper():
        limit_base = limit_original
        comparison_status = "ok"
        comparison_note = f"Limit and exposure are both in {base_ccy}."
    else:
        converted = _convert_to_base(db, tenant_id, limit_original, limit_ccy)
        if converted is None:
            # 外币限额但没有汇率 → **无法评估**。旧实现把外币限额原样跟本币
            # 敞口比（1,000,000 EUR vs 900,000 USD），得出一个毫无意义的
            # breach。现在不评估就不报 breach（fail closed against false positives）。
            comparison_status = "cannot_evaluate"
            comparison_note = (
                f"No FX rate {limit_ccy}→{base_ccy}: the limit could not be converted to "
                f"the exposure currency ({base_ccy}), so no breach verdict is reported."
            )
        else:
            limit_base = converted
            comparison_status = "converted"
            comparison_note = (
                f"Limit converted from {limit_ccy} to {base_ccy} at the latest available "
                "FX rate before comparison."
            )
    limit_f = float(limit_base) if limit_base is not None else None
    return {
        "counterparty_id": str(counterparty_id),
        "name": party.name,
        "credit_rating": party.credit_rating,
        "open_exposure": exposure_f,
        "open_exposure_currency": base_ccy,
        "open_invoice_count": len(open_invoices),
        # 本币限额（折算后的口径 —— 比较用的就是这个数）
        "credit_limit": limit_f,
        "credit_limit_currency": base_ccy if limit_base is not None else None,
        # 原币限额（保留原始数字，调用方能看到「限了多少、折成了多少」）
        "credit_limit_original": float(limit_original) if limit_original is not None else None,
        "credit_limit_original_currency": limit_ccy,
        "comparison_status": comparison_status,
        "comparison_note": comparison_note,
        "breach": bool(limit_f is not None and exposure_f > limit_f),
        "utilization_pct": round(exposure_f / limit_f * 100, 1) if limit_f else None,
    }


def _base_currency(db: Session, tenant_id: UUID) -> str:
    from app.models_wave1 import Company

    comp = db.scalar(select(Company).where(Company.tenant_id == tenant_id).limit(1))
    return (comp.base_currency if comp and comp.base_currency else "USD")


def _convert_to_base(db: Session, tenant_id: UUID, amount: Decimal, currency: str) -> Decimal | None:
    """原币金额 → 本位币；没有汇率时返回 None（调用方必须显式处理）。"""
    from app.services.fx_date_rules import resolve_fx_rate

    base = _base_currency(db, tenant_id)
    if (currency or "").upper() == base.upper():
        return amount
    rate = resolve_fx_rate(db, tenant_id, currency, base)
    if rate is None:
        return None
    return amount * rate


@job_handler("counterparty.rescreen")
def _rescreen_all_job(db: Session, job) -> None:
    """批量重筛作业：遍历本租户全部对手方逐个重筛。"""
    from uuid import UUID as _UUID

    tenant_id = _UUID(str(job.payload.get("tenant_id") or job.tenant_id))
    parties = db.scalars(select(Counterparty).where(Counterparty.tenant_id == tenant_id)).all()
    for pty in parties:
        rescreen(db, tenant_id, pty.id)
