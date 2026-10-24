"""4-column P&L engine — estimate | actual | posted | variance.

Backwards-compatible with pnl.py (which stays in place).  Adds a proper
four-column comparison so the front-end can render side-by-side figures
without re-aggregating on the client.

金额口径（P2-B24）：**内部一律 ``Decimal`` 累加**，只在响应组装时统一量化一次
（显式 ``ROUND_HALF_UP``、两位小数）再转 ``float`` —— 浮点累加会把
``0.1 + 0.2`` 这类尾差一路带到报表上。逐行量化**不做**（那会让每一行都被
单独舍入，和"先求和后舍入"差一分）。与 ``services/pnl.py`` 保持同一口径。
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
    invoice_commission_basis,
    invoice_commission_deducted,
    invoice_gross_before_commission,
    invoice_type_code,
    money,
    round_half_up,
)
from app.services.observability import traced

PNL_LINE_KEYS = (
    "revenue", "hire", "demurrage", "port_costs", "canal",
    "bunker", "commission", "emissions", "other",
)

_PNL_REVENUE_KEYS = {"revenue", "hire", "demurrage", "other"}

# 规范发票类型 → P&L 行（历史别名同样能解析，见 services.invoice_types）
#
# **必须与 ``services/pnl.py::_INVOICE_LINE`` 逐字一致**（P0-B7）：两张映射
# 曾经漂移 —— 这里少了 ``XDIFF``，于是汇兑差异发票在 4 栏视图里**整行消失**
# （收入/成本分栏失真），而动态 P&L 报表里却有。两处现在共用同一套类型码。
_INVOICE_LINE = {
    "FRT": "revenue",
    "TCIP": "hire",
    "TCOB": "hire",
    "DEM": "demurrage",
    "XEXP": "other",
    "XREV": "revenue",
    # 汇兑差异（P0-B7）—— 重估金额带符号：正=汇兑收益、负=汇兑损失。
    "XDIFF": "other",
}

#: 计佣基数适用的 P&L 行。
_COMMISSION_LINES = {"revenue", "hire"}

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


def _blank_lines() -> dict[str, Decimal]:
    """一行 P&L（9 行）—— 零值用 ``Decimal``，避免浮点累加误差。"""
    return {k: ZERO for k in PNL_LINE_KEYS}


def _blank_columns() -> dict[str, dict[str, Decimal]]:
    return {
        "estimate": _blank_lines(),
        "actual": _blank_lines(),
        "posted": _blank_lines(),
        "variance": _blank_lines(),
    }


def _lines_out(lines: dict[str, Decimal]) -> dict[str, float]:
    """``Decimal`` 行 → JSON 里的 ``float``（统一量化到分，显式 ROUND_HALF_UP）。"""
    return {k: float(round_half_up(v, 2)) for k, v in lines.items()}


def _totals_out(totals: dict[str, Decimal]) -> dict[str, float]:
    """``Decimal`` 合计 → JSON 里的 ``float``（同上）。"""
    return {k: float(round_half_up(v, 2)) for k, v in totals.items()}


def _totals(lines: dict[str, Decimal]) -> dict[str, Decimal]:
    revenue = sum((lines.get(k, ZERO) for k in _PNL_REVENUE_KEYS), ZERO)
    cost = sum((lines.get(k, ZERO) for k in PNL_LINE_KEYS if k not in _PNL_REVENUE_KEYS), ZERO)
    return {"revenue": revenue, "cost": cost, "pnl": revenue - cost}


def _commission_dec(
    charter: Charter | None,
    addr_base: Decimal,
    broker_base: Decimal,
) -> Decimal:
    """佣金成本行 —— 每笔佣金**只算一次**（P1-B1/B2）。

    - 毛额发票：地址佣金 + 经纪佣金都算
    - 净额发票（``commission_basis="net"``）：地址佣金已从发票金额里扣掉，
      这里只算经纪佣金
    """
    if not charter:
        return ZERO
    # Decimal 口径（P2-B24）—— 浮点除法再落库会差分
    total = (
        dec(addr_base) * dec(charter.address_comm_pct) / dec(100)
        + dec(broker_base) * dec(charter.brokerage_pct) / dec(100)
    )
    return money(total)


def _commission(
    charter: Charter | None,
    addr_base,
    broker_base,
) -> float:
    """``_commission_dec`` 的 float 包装（历史签名保持不变）。"""
    return float(_commission_dec(charter, dec(addr_base), dec(broker_base)))


def _load_estimate(db: Session, charter: Charter | None) -> tuple[dict[str, Decimal], Decimal | None]:
    """Return (estimate_lines, tce) from the charter's linked Estimate."""
    lines = _blank_lines()
    tce = None
    if not charter or not charter.estimate_id:
        return lines, tce
    est = db.get(Estimate, charter.estimate_id)
    if not est or not est.results:
        return lines, tce
    res = est.results
    lines["revenue"] = dec(res.get("total_revenue"))
    voyage_cost = dec(res.get("voyage_cost"))
    if voyage_cost:
        lines["other"] = voyage_cost
    tce_raw = res.get("tce")
    if tce_raw is not None:
        tce = dec(tce_raw)
    return lines, tce


def _aggregate_actual(
    db: Session,
    tenant_id: UUID,
    voyage_filter: UUID | None = None,
) -> tuple[
    dict[str, dict[str, Decimal]],
    dict[str, Decimal],
    dict[str, Decimal],
    dict[str, Decimal],
    dict[str, Decimal],
    dict[str, Decimal],
    dict[str, Decimal],
]:
    """Aggregate invoices, PDAs, bunker orders per voyage.

    Returns (line_by, pda_by, bunker_by, paid_by, addr_base, broker_base,
    comm_deducted) —— 全部 ``Decimal``（P2-B24：汇总不再走 float）。
    """
    inv_q = select(Invoice).where(
        Invoice.tenant_id == tenant_id,
        Invoice.status.in_(REVENUE_STATUSES),
    )
    pda_q = select(PortDisbursement).where(PortDisbursement.tenant_id == tenant_id)
    bkr_q = select(BunkerOrder).where(BunkerOrder.tenant_id == tenant_id)

    if voyage_filter is not None:
        inv_q = inv_q.where((Invoice.voyage_id == voyage_filter) | (Invoice.voyage_id.is_(None)))
        pda_q = pda_q.where(PortDisbursement.voyage_id == voyage_filter)
        bkr_q = bkr_q.where(BunkerOrder.voyage_id == voyage_filter)

    invs = db.scalars(inv_q).all()
    pdas = db.scalars(pda_q).all()
    bunkers = db.scalars(bkr_q).all()

    # 航次 → 租约（地址佣金率在租约上）；净额发票要按地址佣金率反推毛额基数
    voy_q = select(Voyage).where(Voyage.tenant_id == tenant_id)
    if voyage_filter is not None:
        voy_q = voy_q.where(Voyage.id == voyage_filter)
    charter_by_voyage: dict[str, Charter] = {}
    for v in db.scalars(voy_q).all():
        if v.charter_id:
            ch = db.get(Charter, v.charter_id)
            if ch is not None:
                charter_by_voyage[str(v.id)] = ch

    line_by: dict[str, dict[str, Decimal]] = {}
    paid_by: dict[str, Decimal] = {}
    addr_base: dict[str, Decimal] = {}
    broker_base: dict[str, Decimal] = {}
    comm_deducted: dict[str, Decimal] = {}

    for i in invs:
        key = str(i.voyage_id) if i.voyage_id else "unassigned"
        amt = invoice_base_amount(i)
        paid_by[key] = paid_by.get(key, ZERO) + dec(i.paid_amount)
        mapped = _INVOICE_LINE.get(invoice_type_code(i))
        if not mapped:
            continue
        lines = line_by.setdefault(key, _blank_lines())
        # 红冲发票金额本身为负 —— 不再额外取负
        lines[mapped] += amt
        if mapped in _COMMISSION_LINES:
            if invoice_commission_basis(i) == "net":
                ch = charter_by_voyage.get(key)
                addr_pct = dec(ch.address_comm_pct) if ch else ZERO
                broker_base[key] = broker_base.get(key, ZERO) + invoice_gross_before_commission(i, addr_pct)
                comm_deducted[key] = comm_deducted.get(key, ZERO) + invoice_commission_deducted(i)
            else:
                addr_base[key] = addr_base.get(key, ZERO) + amt
                broker_base[key] = broker_base.get(key, ZERO) + amt

    pda_by: dict[str, Decimal] = {}
    for p in pdas:
        if not p.voyage_id:
            continue
        key = str(p.voyage_id)
        pda_by[key] = pda_by.get(key, ZERO) + dec(p.fda_amount or p.pda_amount)

    bunker_by: dict[str, Decimal] = {}
    for b in bunkers:
        if not b.voyage_id:
            continue
        key = str(b.voyage_id)
        qty = dec(b.qty_delivered or b.qty_ordered)
        price = dec(b.unit_price)
        bunker_by[key] = bunker_by.get(key, ZERO) + qty * price

    return line_by, pda_by, bunker_by, paid_by, addr_base, broker_base, comm_deducted


def _aggregate_posted(
    db: Session,
    tenant_id: UUID,
    voyage_filter: UUID | None = None,
) -> dict[str, dict[str, Decimal]]:
    """Aggregate VoyageAccrual rows where status='posted'."""
    q = select(VoyageAccrual).where(
        VoyageAccrual.tenant_id == tenant_id,
        VoyageAccrual.status == "posted",
    )
    if voyage_filter is not None:
        q = q.where(VoyageAccrual.voyage_id == voyage_filter)

    accruals = db.scalars(q).all()
    posted_by: dict[str, dict[str, Decimal]] = {}
    for a in accruals:
        key = str(a.voyage_id) if a.voyage_id else "unassigned"
        line_key = _ACCRUAL_LINE.get(a.line_type, "other")
        lines = posted_by.setdefault(key, _blank_lines())
        lines[line_key] += dec(a.amount)
    return posted_by


@traced("pnl")
def voyage_pnl_4col(
    db: Session,
    tenant_id: UUID,
    voyage_id: UUID | None = None,
) -> list[dict]:
    """4-column P&L rows: estimate | actual | posted | variance."""
    voyages_q = select(Voyage).where(Voyage.tenant_id == tenant_id)
    if voyage_id is not None:
        voyages_q = voyages_q.where(Voyage.id == voyage_id)
    voyages = db.scalars(voyages_q).all()

    line_by, pda_by, bunker_by, paid_by, addr_base, broker_base, comm_deducted = _aggregate_actual(
        db, tenant_id, voyage_id
    )
    posted_by = _aggregate_posted(db, tenant_id, voyage_id)

    out: list[dict] = []

    for v in voyages:
        vid = str(v.id)
        columns = _blank_columns()

        # --- estimate ---
        ch = db.get(Charter, v.charter_id) if v.charter_id else None
        est_lines, est_tce = _load_estimate(db, ch)
        columns["estimate"] = est_lines

        # --- actual ---
        act = dict(line_by.get(vid, _blank_lines()))
        act["port_costs"] = pda_by.get(vid, ZERO)
        act["bunker"] = bunker_by.get(vid, ZERO)
        act["commission"] = _commission_dec(
            ch, addr_base.get(vid, ZERO), broker_base.get(vid, ZERO)
        )
        columns["actual"] = act

        # --- posted ---
        columns["posted"] = posted_by.get(vid, _blank_lines())

        # --- variance = actual - estimate ---
        columns["variance"] = {
            k: columns["actual"][k] - columns["estimate"][k] for k in PNL_LINE_KEYS
        }

        # --- totals per column ---
        totals = {col: _totals(columns[col]) for col in ("estimate", "actual", "posted")}

        out.append({
            "voyage_id": vid,
            "voyage_no": v.voyage_no,
            "status": v.status,
            "cargo": v.cargo,
            "columns": {
                col: _lines_out(columns[col])
                for col in ("estimate", "actual", "posted", "variance")
            },
            "totals": {
                "estimate": {
                    **_totals_out(totals["estimate"]),
                    "tce": float(est_tce) if est_tce is not None else None,
                },
                "actual": _totals_out(totals["actual"]),
                "posted": _totals_out(totals["posted"]),
            },
            "paid_amount": float(round_half_up(paid_by.get(vid, ZERO), 2)),
            "commission_deducted": float(round_half_up(comm_deducted.get(vid, ZERO), 2)),
        })

    # unassigned invoices (voyage_id IS NULL)
    if voyage_id is None:
        ua_key = "unassigned"
        if ua_key in line_by or ua_key in posted_by:
            columns = _blank_columns()
            columns["actual"] = line_by.get(ua_key, _blank_lines())
            columns["posted"] = posted_by.get(ua_key, _blank_lines())
            columns["variance"] = {
                k: columns["actual"][k] - columns["estimate"][k] for k in PNL_LINE_KEYS
            }
            totals = {col: _totals(columns[col]) for col in ("estimate", "actual", "posted")}
            out.append({
                "voyage_id": "unassigned",
                "voyage_no": "UNASSIGNED",
                "status": "—",  # em dash（未分配）
                "cargo": None,
                "columns": {
                    col: _lines_out(columns[col])
                    for col in ("estimate", "actual", "posted", "variance")
                },
                "totals": {
                    "estimate": {
                        **_totals_out(totals["estimate"]),
                        "tce": None,
                    },
                    "actual": _totals_out(totals["actual"]),
                    "posted": _totals_out(totals["posted"]),
                },
                "paid_amount": float(round_half_up(paid_by.get(ua_key, ZERO), 2)),
            })

    return out


def fleet_pnl_summary(db: Session, tenant_id: UUID) -> dict:
    """Aggregate all voyage rows into fleet-wide totals per column."""
    rows = voyage_pnl_4col(db, tenant_id)

    fleet_columns: dict[str, dict[str, Decimal]] = {
        "estimate": _blank_lines(),
        "actual": _blank_lines(),
        "posted": _blank_lines(),
        "variance": _blank_lines(),
    }
    fleet_totals: dict[str, dict[str, Decimal | None]] = {
        "estimate": {"revenue": ZERO, "cost": ZERO, "pnl": ZERO, "tce": None},
        "actual": {"revenue": ZERO, "cost": ZERO, "pnl": ZERO},
        "posted": {"revenue": ZERO, "cost": ZERO, "pnl": ZERO},
    }
    total_paid = ZERO
    tce_sum = ZERO
    tce_count = 0

    for row in rows:
        for col in ("estimate", "actual", "posted", "variance"):
            for k in PNL_LINE_KEYS:
                fleet_columns[col][k] += dec(row["columns"][col].get(k, 0.0))
        for col in ("estimate", "actual", "posted"):
            rt = row["totals"].get(col, {})
            fleet_totals[col]["revenue"] += dec(rt.get("revenue", 0.0))
            fleet_totals[col]["cost"] += dec(rt.get("cost", 0.0))
            fleet_totals[col]["pnl"] += dec(rt.get("pnl", 0.0))
        est_tce = row["totals"].get("estimate", {}).get("tce")
        if est_tce is not None:
            tce_sum += dec(est_tce)
            tce_count += 1
        total_paid += dec(row.get("paid_amount", 0.0))

    est_fleet = {k: float(round_half_up(v, 2)) for k, v in fleet_totals["estimate"].items() if k != "tce"}
    est_fleet["tce"] = float(tce_sum) if tce_count else None

    return {
        "voyage_count": len(rows),
        "columns": {col: _lines_out(fleet_columns[col]) for col in fleet_columns},
        "totals": {
            "estimate": est_fleet,
            "actual": _totals_out(fleet_totals["actual"]),  # type: ignore[arg-type]
            "posted": _totals_out(fleet_totals["posted"]),  # type: ignore[arg-type]
        },
        "paid_amount": float(round_half_up(total_paid, 2)),
    }
