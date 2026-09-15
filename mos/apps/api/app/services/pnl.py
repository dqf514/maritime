"""Voyage P&L aggregation — estimate vs actual revenue/cost drivers.

Extracted from routers/finance_ext.py so the report endpoint, the exception
centre and the voyage 360 overview share one aggregation.
"""

from __future__ import annotations

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

# P&L line items. Revenue side: revenue/hire/demurrage/other; cost side the rest.
PNL_LINE_KEYS = ("revenue", "hire", "demurrage", "port_costs", "canal", "bunker", "commission", "emissions", "other")
_PNL_REVENUE_KEYS = {"revenue", "hire", "demurrage", "other"}
# bunker/port_disbursement invoices are intentionally not line-mapped: those costs
# come from bunker orders and PDAs (avoiding double count); they stay in actual_revenue.
_INVOICE_LINE = {"freight": "revenue", "hire": "hire", "demurrage": "demurrage", "other": "other", "credit_note": "revenue"}
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


def _blank_lines() -> dict[str, float]:
    return {k: 0.0 for k in PNL_LINE_KEYS}


def voyage_pnl_rows(db: Session, tenant_id: UUID, basis: str = "actual") -> list[dict]:
    """Dynamic voyage P&L rows.

    basis=actual (default): booked invoices / PDAs / bunker orders.
    basis=accrual: additionally merges non-reversed VoyageAccrual rows into the
    line items (`lines_accrual`, `lines` merged, `accrual_net`, `accrual_pnl`).
    """
    voyages = db.scalars(select(Voyage).where(Voyage.tenant_id == tenant_id)).all()
    invs = db.scalars(select(Invoice).where(Invoice.tenant_id == tenant_id)).all()
    pdas = db.scalars(select(PortDisbursement).where(PortDisbursement.tenant_id == tenant_id)).all()
    bunkers = db.scalars(select(BunkerOrder).where(BunkerOrder.tenant_id == tenant_id)).all()

    rev_by: dict[str, float] = {}
    paid_by: dict[str, float] = {}
    line_by: dict[str, dict[str, float]] = {}
    for i in invs:
        key = str(i.voyage_id) if i.voyage_id else "unassigned"
        # Multi-currency: aggregate in base currency when the invoice carries one.
        rev = float(getattr(i, "base_amount", None) or i.amount or 0)
        rev_by[key] = rev_by.get(key, 0) + rev
        paid_by[key] = paid_by.get(key, 0) + float(i.paid_amount or 0)
        line = _INVOICE_LINE.get(i.invoice_type)
        if line:
            lines = line_by.setdefault(key, _blank_lines())
            lines[line] += -rev if i.invoice_type == "credit_note" else rev

    pda_by: dict[str, float] = {}
    for p in pdas:
        if not p.voyage_id:
            continue
        key = str(p.voyage_id)
        amt = float(p.fda_amount or p.pda_amount or 0)
        pda_by[key] = pda_by.get(key, 0) + amt

    bunker_by: dict[str, float] = {}
    for b in bunkers:
        if not b.voyage_id:
            continue
        key = str(b.voyage_id)
        qty = float(b.qty_delivered or b.qty_ordered or 0)
        price = float(b.unit_price or 0)
        bunker_by[key] = bunker_by.get(key, 0) + qty * price

    accrual_by: dict[str, dict[str, float]] = {}
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
            lines[line] += float(a.amount or 0)

    def _commission(charter: Charter | None, lines: dict[str, float]) -> float:
        """Address + brokerage commission estimated off the charter's percentages."""
        if not charter:
            return 0.0
        pct = float(charter.address_comm_pct or 0) + float(charter.brokerage_pct or 0)
        return (lines["revenue"] + lines["hire"]) * pct / 100.0

    out = []
    for v in voyages:
        vid = str(v.id)
        est_rev = 0.0
        est_cost = 0.0
        est_tce = None
        ch = db.get(Charter, v.charter_id) if v.charter_id else None
        if ch and ch.estimate_id:
            est = db.get(Estimate, ch.estimate_id)
            if est and est.results:
                est_rev = float(est.results.get("total_revenue") or 0)
                est_cost = float(est.results.get("voyage_cost") or 0)
                est_tce = est.results.get("tce")
        act_rev = rev_by.get(vid, 0.0)
        act_cost = pda_by.get(vid, 0.0) + bunker_by.get(vid, 0.0)
        act_pnl = act_rev - act_cost
        est_pnl = est_rev - est_cost
        lines_actual = line_by.get(vid, _blank_lines())
        lines_actual = {**lines_actual, "port_costs": pda_by.get(vid, 0.0), "bunker": bunker_by.get(vid, 0.0)}
        lines_actual["commission"] = _commission(ch, lines_actual)
        row = {
            "voyage_id": vid,
            "voyage_no": v.voyage_no,
            "status": v.status,
            "cargo": v.cargo,
            "estimated_revenue": est_rev,
            "estimated_cost": est_cost,
            "estimated_pnl": est_pnl,
            "estimated_tce": est_tce,
            "actual_revenue": act_rev,
            "actual_cost": act_cost,
            "actual_pnl": act_pnl,
            "variance_pnl": act_pnl - est_pnl,
            "paid_amount": paid_by.get(vid, 0.0),
            "port_cost": pda_by.get(vid, 0.0),
            "bunker_cost": bunker_by.get(vid, 0.0),
            "revenue": act_rev,
            "basis": basis,
            "lines_actual": lines_actual,
            "lines": lines_actual,
        }
        if basis == "accrual":
            lines_accrual = accrual_by.get(vid, _blank_lines())
            merged = {k: lines_actual[k] + lines_accrual.get(k, 0.0) for k in PNL_LINE_KEYS}
            accrual_net = sum(lines_accrual.get(k, 0.0) for k in _PNL_REVENUE_KEYS) - sum(
                lines_accrual.get(k, 0.0) for k in PNL_LINE_KEYS if k not in _PNL_REVENUE_KEYS
            )
            row["lines_accrual"] = lines_accrual
            row["lines"] = merged
            row["accrual_net"] = accrual_net
            row["accrual_pnl"] = act_pnl + accrual_net
        out.append(row)
    if "unassigned" in rev_by:
        unassigned = {
            "voyage_id": "unassigned",
            "voyage_no": "UNASSIGNED",
            "status": "—",
            "cargo": None,
            "estimated_revenue": 0,
            "estimated_cost": 0,
            "estimated_pnl": 0,
            "estimated_tce": None,
            "actual_revenue": rev_by["unassigned"],
            "actual_cost": 0,
            "actual_pnl": rev_by["unassigned"],
            "variance_pnl": rev_by["unassigned"],
            "paid_amount": paid_by.get("unassigned", 0),
            "port_cost": 0,
            "bunker_cost": 0,
            "revenue": rev_by["unassigned"],
            "basis": basis,
            "lines_actual": line_by.get("unassigned", _blank_lines()),
            "lines": line_by.get("unassigned", _blank_lines()),
        }
        if basis == "accrual":
            lines_accrual = accrual_by.get("unassigned", _blank_lines())
            merged = {k: unassigned["lines_actual"][k] + lines_accrual.get(k, 0.0) for k in PNL_LINE_KEYS}
            accrual_net = sum(lines_accrual.get(k, 0.0) for k in _PNL_REVENUE_KEYS) - sum(
                lines_accrual.get(k, 0.0) for k in PNL_LINE_KEYS if k not in _PNL_REVENUE_KEYS
            )
            unassigned["lines_accrual"] = lines_accrual
            unassigned["lines"] = merged
            unassigned["accrual_net"] = accrual_net
            unassigned["accrual_pnl"] = unassigned["actual_pnl"] + accrual_net
        out.append(unassigned)
    return out


def voyage_pnl_row(db: Session, tenant_id: UUID, voyage_id: UUID, basis: str = "actual") -> dict | None:
    """Single-voyage view over voyage_pnl_rows (the aggregation is fleet-wide by design)."""
    vid = str(voyage_id)
    for row in voyage_pnl_rows(db, tenant_id, basis):
        if row["voyage_id"] == vid:
            return row
    return None
