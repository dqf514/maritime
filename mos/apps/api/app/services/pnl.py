"""Voyage P&L aggregation — estimate vs actual revenue/cost drivers.

Extracted from routers/finance_ext.py so the report endpoint, the exception
centre and the voyage 360 overview share one aggregation.

口径（WP-1 · P0-B6/B7 · P1-B1/B2）：

- **只算已签发的发票**（``issued``/``partially_paid``/``paid``）。旧实现把
  草稿、审批中、作废的发票也算进"实际收入" —— 一张还没签的草稿就能把航次
  拉出盈利。
- **按规范发票类型映射**（``services/invoice_types``）。旧实现只认
  ``freight``/``hire`` 这类历史别名，规范码 ``FRT``/``TCIP``/``XREV`` 落到
  P&L 里**一行都不进**。
- **本币口径**：多币种发票按 ``base_amount`` 折本币再求和。
- **红冲不重复取负**：红冲是一张负数发票行（P0-B2），金额本身就是负的。
- **佣金只算一次**：净额发票（``commission_basis="net"``）的地址佣金已经
  从金额里扣过，损益里**不再**重复计一次经纪佣金以外的项。
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import (
    BunkerOrder,
    Charter,
    Estimate,
    Invoice,
    PortDisbursement,
    Voyage,
    VoyageAccrual,
)
from app.services.money import (
    REVENUE_STATUSES,
    ZERO,
    dec,
    invoice_base_amount,
    invoice_base_paid,
    invoice_commission_basis,
    invoice_commission_deducted,
    invoice_gross_before_commission,
    invoice_type_code,
    money,
    round_half_up,
)

# P&L line items. Revenue side: revenue/hire/demurrage/other; cost side the rest.
PNL_LINE_KEYS = ("revenue", "hire", "demurrage", "port_costs", "canal", "bunker", "commission", "emissions", "other")
_PNL_REVENUE_KEYS = {"revenue", "hire", "demurrage", "other"}
# 规范发票类型 → P&L 行。PDA/FDA/BKR 故意**不**映射 —— 那些成本来自
# PDA / 油订单，再计一次会双算（它们仍进 actual_revenue，与旧行为一致）。
#
# **必须与 ``services/pnl_engine.py::_INVOICE_LINE`` 逐字一致**（P0-B7）：
# 两张映射曾经漂移（4 栏视图少了 ``XDIFF``），汇兑差异发票在一边整行消失。
_INVOICE_LINE = {
    "FRT": "revenue",
    "TCIP": "hire",
    "TCOB": "hire",
    "DEM": "demurrage",
    "XEXP": "other",
    "XREV": "revenue",
    # 汇兑差异（P1-B15）—— 以前没映射，汇兑收益/损失在 P&L 明细里
    # **整行消失**（只体现在总额里，对不上账）。金额带符号：正=收益、负=损失。
    "XDIFF": "other",
}
_ACCRUAL_LINE = {
    "freight": "revenue",
    "hire": "hire",
    "demurrage": "demurrage",
    "port": "port_costs",
    "canal": "canal",
    "bunker": "bunker",
    "commission": "commission",
    "emissions": "emissions",
    "other": "other",
}

#: 计佣基数适用的 P&L 行（运费 / 期租 / 滞期）。
_COMMISSION_LINES = {"revenue", "hire"}


def _blank_lines() -> dict[str, Decimal]:
    """一行 P&L（9 行）—— 零值用 ``Decimal``（P2-B24：汇总不再走 float）。"""
    return {k: ZERO for k in PNL_LINE_KEYS}


def _lines_out(lines: dict[str, Decimal]) -> dict[str, float]:
    """``Decimal`` 行 → JSON 里的 ``float``（统一量化到分，显式 ROUND_HALF_UP）。"""
    return {k: float(round_half_up(v, 2)) for k, v in lines.items()}


def _invoice_line(inv) -> str | None:
    """发票 → P&L 行（按规范类型；历史别名同样能解析）。"""
    return _INVOICE_LINE.get(invoice_type_code(inv))


def voyage_pnl_rows(db: Session, tenant_id: UUID, basis: str = "actual") -> list[dict]:
    """Dynamic voyage P&L rows.

    basis=actual (default): booked invoices / PDAs / bunker orders.
    basis=accrual: additionally merges non-reversed VoyageAccrual rows into the
    line items (`lines_accrual`, `lines` merged, `accrual_net`, `accrual_pnl`).
    """
    voyages = db.scalars(select(Voyage).where(Voyage.tenant_id == tenant_id)).all()
    # P0-B6：只统计已签发的发票 —— 草稿/审批中/作废/已删不算收入
    invs = db.scalars(
        select(Invoice).where(
            Invoice.tenant_id == tenant_id,
            Invoice.status.in_(REVENUE_STATUSES),
        )
    ).all()
    pdas = db.scalars(select(PortDisbursement).where(PortDisbursement.tenant_id == tenant_id)).all()
    bunkers = db.scalars(select(BunkerOrder).where(BunkerOrder.tenant_id == tenant_id)).all()

    rev_by: dict[str, Decimal] = {}
    paid_by: dict[str, Decimal] = {}
    line_by: dict[str, dict[str, Decimal]] = {}
    # 佣金基数：地址佣金与经纪佣金分开累计（净额发票的地址佣金已从收入里扣过）
    addr_base: dict[str, Decimal] = {}
    broker_base: dict[str, Decimal] = {}
    comm_deducted: dict[str, Decimal] = {}
    # 航次 → 租约（佣金率在租约上）；净额发票要按地址佣金率反推毛额基数
    charter_by_voyage: dict[str, Charter] = {}
    for v in voyages:
        if v.charter_id:
            ch = db.get(Charter, v.charter_id)
            if ch is not None:
                charter_by_voyage[str(v.id)] = ch
    for i in invs:
        key = str(i.voyage_id) if i.voyage_id else "unassigned"
        # Multi-currency: aggregate in base currency when the invoice carries one.
        # 口径（P2-B24）：内部一律 Decimal，float 只在响应组装时出现。
        rev = invoice_base_amount(i)
        rev_by[key] = rev_by.get(key, ZERO) + rev
        paid_by[key] = paid_by.get(key, ZERO) + invoice_base_paid(i)
        line = _invoice_line(i)
        if not line:
            continue
        lines = line_by.setdefault(key, _blank_lines())
        # 红冲发票金额本身就是负数 —— 不再额外取负（否则变成正的）
        lines[line] += rev
        if line in _COMMISSION_LINES:
            if invoice_commission_basis(i) == "net":
                # 地址佣金已在发票金额里扣掉 → 只把经纪佣金基数挂上
                ch = charter_by_voyage.get(key)
                addr_pct = dec(ch.address_comm_pct or 0) if ch else ZERO
                broker_base[key] = broker_base.get(key, ZERO) + invoice_gross_before_commission(
                    i, addr_pct
                )
                comm_deducted[key] = comm_deducted.get(key, ZERO) + invoice_commission_deducted(i)
            else:
                addr_base[key] = addr_base.get(key, ZERO) + rev
                broker_base[key] = broker_base.get(key, ZERO) + rev

    pda_by: dict[str, Decimal] = {}
    for p in pdas:
        if not p.voyage_id:
            continue
        key = str(p.voyage_id)
        amt = dec(p.fda_amount or p.pda_amount or 0)
        pda_by[key] = pda_by.get(key, ZERO) + amt

    bunker_by: dict[str, Decimal] = {}
    for b in bunkers:
        if not b.voyage_id:
            continue
        key = str(b.voyage_id)
        qty = dec(b.qty_delivered or b.qty_ordered or 0)
        price = dec(b.unit_price or 0)
        bunker_by[key] = bunker_by.get(key, ZERO) + qty * price

    accrual_by: dict[str, dict[str, Decimal]] = {}
    if basis == "accrual":
        accruals = db.scalars(
            select(VoyageAccrual).where(
                VoyageAccrual.tenant_id == tenant_id,
                VoyageAccrual.status != "reversed",
            )
        ).all()
        for a in accruals:
            key = str(a.voyage_id) if a.voyage_id else "unassigned"
            line = _ACCRUAL_LINE.get(a.line_type, "other")
            lines = accrual_by.setdefault(key, _blank_lines())
            lines[line] += dec(a.amount or 0)

    def _commission(charter: Charter | None, key: str) -> Decimal:
        """佣金成本行 —— 每一笔佣金**只算一次**（P1-B1/B2）。

        - 毛额发票：地址佣金 + 经纪佣金都算
        - 净额发票：地址佣金已从收入里扣掉 → 这里只算经纪佣金
        """
        if not charter:
            return ZERO
        addr_pct = dec(charter.address_comm_pct or 0)
        broker_pct = dec(charter.brokerage_pct or 0)
        # Decimal 口径（P2-B24）—— 浮点除法再落库会差分
        total = (
            dec(addr_base.get(key, ZERO)) * addr_pct / dec(100)
            + dec(broker_base.get(key, ZERO)) * broker_pct / dec(100)
        )
        return money(total)

    out = []
    for v in voyages:
        vid = str(v.id)
        est_rev = ZERO
        est_cost = ZERO
        est_tce = None
        ch = db.get(Charter, v.charter_id) if v.charter_id else None
        if ch and ch.estimate_id:
            est = db.get(Estimate, ch.estimate_id)
            if est and est.results:
                est_rev = dec(est.results.get("total_revenue") or 0)
                est_cost = dec(est.results.get("voyage_cost") or 0)
                est_tce = est.results.get("tce")
        act_rev = rev_by.get(vid, ZERO)
        act_cost = pda_by.get(vid, ZERO) + bunker_by.get(vid, ZERO)
        act_pnl = act_rev - act_cost
        est_pnl = est_rev - est_cost
        lines_actual = line_by.get(vid, _blank_lines())
        lines_actual = {**lines_actual, "port_costs": pda_by.get(vid, ZERO), "bunker": bunker_by.get(vid, ZERO)}
        lines_actual["commission"] = _commission(ch, vid)
        row = {
            "voyage_id": vid,
            "voyage_no": v.voyage_no,
            "status": v.status,
            "cargo": v.cargo,
            "estimated_revenue": float(round_half_up(est_rev, 2)),
            "estimated_cost": float(round_half_up(est_cost, 2)),
            "estimated_pnl": float(round_half_up(est_pnl, 2)),
            "estimated_tce": est_tce,
            "actual_revenue": float(round_half_up(act_rev, 2)),
            "actual_cost": float(round_half_up(act_cost, 2)),
            "actual_pnl": float(round_half_up(act_pnl, 2)),
            "variance_pnl": float(round_half_up(act_pnl - est_pnl, 2)),
            "paid_amount": float(round_half_up(paid_by.get(vid, ZERO), 2)),
            "port_cost": float(round_half_up(pda_by.get(vid, ZERO), 2)),
            "bunker_cost": float(round_half_up(bunker_by.get(vid, ZERO), 2)),
            "revenue": float(round_half_up(act_rev, 2)),
            "basis": basis,
            "lines_actual": _lines_out(lines_actual),
            "lines": _lines_out(lines_actual),
            # 已在发票金额里扣掉的佣金（P1-B2：引擎读 commission_basis）
            "commission_deducted": float(round_half_up(comm_deducted.get(vid, ZERO), 2)),
        }
        if basis == "accrual":
            lines_accrual = accrual_by.get(vid, _blank_lines())
            merged = {k: lines_actual[k] + lines_accrual.get(k, ZERO) for k in PNL_LINE_KEYS}
            accrual_net = sum((lines_accrual.get(k, ZERO) for k in _PNL_REVENUE_KEYS), ZERO) - sum(
                (lines_accrual.get(k, ZERO) for k in PNL_LINE_KEYS if k not in _PNL_REVENUE_KEYS), ZERO
            )
            row["lines_accrual"] = _lines_out(lines_accrual)
            row["lines"] = _lines_out(merged)
            row["accrual_net"] = float(round_half_up(accrual_net, 2))
            row["accrual_pnl"] = float(round_half_up(act_pnl + accrual_net, 2))
        out.append(row)
    if "unassigned" in rev_by:
        ua_lines = line_by.get("unassigned", _blank_lines())
        ua_rev = rev_by["unassigned"]
        unassigned = {
            "voyage_id": "unassigned",
            "voyage_no": "UNASSIGNED",
            "status": "—",
            "cargo": None,
            "estimated_revenue": 0,
            "estimated_cost": 0,
            "estimated_pnl": 0,
            "estimated_tce": None,
            "actual_revenue": float(round_half_up(ua_rev, 2)),
            "actual_cost": 0,
            "actual_pnl": float(round_half_up(ua_rev, 2)),
            "variance_pnl": float(round_half_up(ua_rev, 2)),
            "paid_amount": float(round_half_up(paid_by.get("unassigned", ZERO), 2)),
            "port_cost": 0,
            "bunker_cost": 0,
            "revenue": float(round_half_up(ua_rev, 2)),
            "basis": basis,
            "lines_actual": _lines_out(ua_lines),
            "lines": _lines_out(ua_lines),
            "commission_deducted": float(round_half_up(comm_deducted.get("unassigned", ZERO), 2)),
        }
        if basis == "accrual":
            lines_accrual = accrual_by.get("unassigned", _blank_lines())
            merged = {k: ua_lines[k] + lines_accrual.get(k, ZERO) for k in PNL_LINE_KEYS}
            accrual_net = sum((lines_accrual.get(k, ZERO) for k in _PNL_REVENUE_KEYS), ZERO) - sum(
                (lines_accrual.get(k, ZERO) for k in PNL_LINE_KEYS if k not in _PNL_REVENUE_KEYS), ZERO
            )
            unassigned["lines_accrual"] = _lines_out(lines_accrual)
            unassigned["lines"] = _lines_out(merged)
            unassigned["accrual_net"] = float(round_half_up(accrual_net, 2))
            unassigned["accrual_pnl"] = float(
                round_half_up(ua_rev + accrual_net, 2)
            )
        out.append(unassigned)
    return out


def voyage_pnl_row(db: Session, tenant_id: UUID, voyage_id: UUID, basis: str = "actual") -> dict | None:
    """Single-voyage view over voyage_pnl_rows (the aggregation is fleet-wide by design)."""
    vid = str(voyage_id)
    for row in voyage_pnl_rows(db, tenant_id, basis):
        if row["voyage_id"] == vid:
            return row
    return None
