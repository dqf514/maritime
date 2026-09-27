"""港口费用基准库（Phase 2 / D8）：PDA/FDA 历史费用沉淀为按港口/费目的参考基准。

数据来源：已批准/定稿的 PortDisbursement（lines: {费目: 金额}）经 port_call →
port 归集。不新增存储——基准实时派生，永远与账面一致。

用途：
- 估算参考：新 PDA 前查同港同费目基准（avg/p50/count）；
- 例外预警：在办 PDA 费目超出基准 ×(1+tolerance) 进入超基准队列。
"""

from __future__ import annotations

import statistics
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import PortCall, PortDisbursement

# 只有这些状态的单据计入基准（费用已确认）
BENCHMARK_STATUSES = {"approved", "fda", "settled", "closed"}


def _fee_rows(db: Session, tenant_id: UUID, port_id: UUID | None = None) -> list[tuple[str, float, UUID]]:
    """历史确认费用行：(费目, 金额, pda_id)。"""
    q = (
        select(PortDisbursement, PortCall.port_id)
        .join(PortCall, PortDisbursement.port_call_id == PortCall.id, isouter=True)
        .where(
            PortDisbursement.tenant_id == tenant_id,
            PortDisbursement.status.in_(sorted(BENCHMARK_STATUSES)),
        )
    )
    if port_id is not None:
        q = q.where(PortCall.port_id == port_id)
    out: list[tuple[str, float, UUID]] = []
    for pda, pid in db.execute(q).all():
        for fee, amount in (pda.lines or {}).items():
            try:
                out.append((str(fee), float(amount), pda.id))
            except (TypeError, ValueError):
                continue
    return out


def benchmark_for_port(db: Session, tenant_id: UUID, port_id: UUID | None = None) -> dict[str, Any]:
    """按费目统计基准：count / avg / p50 / min / max。"""
    rows = _fee_rows(db, tenant_id, port_id)
    by_fee: dict[str, list[float]] = {}
    for fee, amount, _ in rows:
        by_fee.setdefault(fee, []).append(amount)
    fees = {}
    for fee, amounts in sorted(by_fee.items()):
        fees[fee] = {
            "count": len(amounts),
            "avg": round(statistics.fmean(amounts), 2),
            "p50": round(statistics.median(amounts), 2),
            "min": round(min(amounts), 2),
            "max": round(max(amounts), 2),
        }
    return {"port_id": str(port_id) if port_id else None, "fees": fees, "sample_count": len({p for _, _, p in rows})}


def over_benchmark(
    db: Session,
    tenant_id: UUID,
    *,
    tolerance: float = 0.25,
    statuses: tuple[str, ...] = ("draft", "submitted"),
) -> list[dict[str, Any]]:
    """在办 PDA 中超出基准 (1+tolerance) 的费目行（超基准预警队列数据源）。"""
    flagged: list[dict[str, Any]] = []
    # 每个港口单独算基准后比对
    port_ids = {
        pid
        for (pid,) in db.execute(
            select(PortCall.port_id)
            .join(PortDisbursement, PortDisbursement.port_call_id == PortCall.id)
            .where(PortDisbursement.tenant_id == tenant_id, PortDisbursement.status.in_(list(statuses)))
            .distinct()
        ).all()
        if pid
    }
    for pid in port_ids:
        bench = benchmark_for_port(db, tenant_id, pid)
        q = (
            select(PortDisbursement)
            .join(PortCall, PortDisbursement.port_call_id == PortCall.id)
            .where(
                PortDisbursement.tenant_id == tenant_id,
                PortDisbursement.status.in_(list(statuses)),
                PortCall.port_id == pid,
            )
        )
        for pda in db.scalars(q).all():
            for fee, amount in (pda.lines or {}).items():
                stat = bench["fees"].get(str(fee))
                if not stat or stat["count"] < 2:
                    continue  # 样本不足不判
                try:
                    amt = float(amount)
                except (TypeError, ValueError):
                    continue
                limit = stat["p50"] * (1 + tolerance)
                if amt > limit:
                    flagged.append(
                        {
                            "pda_id": str(pda.id),
                            "port_id": str(pid),
                            "fee": str(fee),
                            "amount": amt,
                            "benchmark_p50": stat["p50"],
                            "excess_pct": round((amt / stat["p50"] - 1) * 100, 1) if stat["p50"] else None,
                            "status": pda.status,
                        }
                    )
    return flagged
