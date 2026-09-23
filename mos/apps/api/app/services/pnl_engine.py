"""4-column P&L engine — estimate | actual | posted | variance.

Backwards-compatible with pnl.py (which stays in place).  Adds a proper
four-column comparison so the front-end can render side-by-side figures
without re-aggregating on the client.
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

PNL_LINE_KEYS = (
    "revenue", "hire", "demurrage", "port_costs", "canal",
    "bunker", "commission", "emissions", "other",
)

_PNL_REVENUE_KEYS = {"revenue", "hire", "demurrage", "other"}

_INVOICE_LINE = {
    "freight": "revenue",
    "hire": "hire",
    "demurrage": "demurrage",
    "other": "other",
    "credit_note": "revenue",
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


def _blank_lines() -> dict[str, float]:
    return {k: 0.0 for k in PNL_LINE_KEYS}


def _blank_columns() -> dict[str, dict[str, float]]:
    return {
        "estimate": _blank_lines(),
        "actual": _blank_lines(),
        "posted": _blank_lines(),
        "variance": _blank_lines(),
    }


def _f(val) -> float:
    """Coerce Decimal / None to float."""
    return float(val) if val is not None else 0.0


def _totals(lines: dict[str, float]) -> dict[str, float]:
    revenue = sum(lines.get(k, 0.0) for k in _PNL_REVENUE_KEYS)
    cost = sum(lines.get(k, 0.0) for k in PNL_LINE_KEYS if k not in _PNL_REVENUE_KEYS)
    return {"revenue": revenue, "cost": cost, "pnl": revenue - cost}


def _commission(charter: Charter | None, lines: dict[str, float]) -> float:
    if not charter:
        return 0.0
    pct = _f(charter.address_comm_pct) + _f(charter.brokerage_pct)
    return (lines["revenue"] + lines["hire"]) * pct / 100.0


def _load_estimate(db: Session, charter: Charter | None) -> tuple[dict[str, float], float | None]:
    """Return (estimate_lines, tce) from the charter's linked Estimate."""
    lines = _blank_lines()
    tce = None
    if not charter or not charter.estimate_id:
        return lines, tce
    est = db.get(Estimate, charter.estimate_id)
    if not est or not est.results:
        return lines, tce
    res = est.results
    lines["revenue"] = _f(res.get("total_revenue"))
    voyage_cost = _f(res.get("voyage_cost"))
    if voyage_cost:
        lines["other"] = voyage_cost
    tce_raw = res.get("tce")
    if tce_raw is not None:
        tce = float(tce_raw)
    return lines, tce


def _aggregate_actual(
    db: Session,
    tenant_id: UUID,
    voyage_filter: UUID | None = None,
) -> tuple[
    dict[str, dict[str, float]],
    dict[str, float],
    dict[str, float],
    dict[str, float],
]:
    """Aggregate invoices, PDAs, bunker orders per voyage.

    Returns (line_by, pda_by, bunker_by, paid_by).
    """
    inv_q = select(Invoice).where(Invoice.tenant_id == tenant_id)
    pda_q = select(PortDisbursement).where(PortDisbursement.tenant_id == tenant_id)
    bkr_q = select(BunkerOrder).where(BunkerOrder.tenant_id == tenant_id)

    if voyage_filter is not None:
        inv_q = inv_q.where((Invoice.voyage_id == voyage_filter) | (Invoice.voyage_id.is_(None)))
        pda_q = pda_q.where(PortDisbursement.voyage_id == voyage_filter)
        bkr_q = bkr_q.where(BunkerOrder.voyage_id == voyage_filter)

    invs = db.scalars(inv_q).all()
    pdas = db.scalars(pda_q).all()
    bunkers = db.scalars(bkr_q).all()

    line_by: dict[str, dict[str, float]] = {}
    paid_by: dict[str, float] = {}

    for i in invs:
        key = str(i.voyage_id) if i.voyage_id else "unassigned"
        amt = _f(getattr(i, "base_amount", None) or i.amount)
        paid_by[key] = paid_by.get(key, 0.0) + _f(i.paid_amount)
        mapped = _INVOICE_LINE.get(i.invoice_type)
        if mapped:
            lines = line_by.setdefault(key, _blank_lines())
            lines[mapped] += -amt if i.invoice_type == "credit_note" else amt

    pda_by: dict[str, float] = {}
    for p in pdas:
        if not p.voyage_id:
            continue
        key = str(p.voyage_id)
        pda_by[key] = pda_by.get(key, 0.0) + _f(p.fda_amount or p.pda_amount)

    bunker_by: dict[str, float] = {}
    for b in bunkers:
        if not b.voyage_id:
            continue
        key = str(b.voyage_id)
        qty = _f(b.qty_delivered or b.qty_ordered)
        price = _f(b.unit_price)
        bunker_by[key] = bunker_by.get(key, 0.0) + qty * price

    return line_by, pda_by, bunker_by, paid_by


def _aggregate_posted(
    db: Session,
    tenant_id: UUID,
    voyage_filter: UUID | None = None,
) -> dict[str, dict[str, float]]:
    """Aggregate VoyageAccrual rows where status='posted'."""
    q = select(VoyageAccrual).where(
        VoyageAccrual.tenant_id == tenant_id,
        VoyageAccrual.status == "posted",
    )
    if voyage_filter is not None:
        q = q.where(VoyageAccrual.voyage_id == voyage_filter)

    accruals = db.scalars(q).all()
    posted_by: dict[str, dict[str, float]] = {}
    for a in accruals:
        key = str(a.voyage_id) if a.voyage_id else "unassigned"
        line_key = _ACCRUAL_LINE.get(a.line_type, "other")
        lines = posted_by.setdefault(key, _blank_lines())
        lines[line_key] += _f(a.amount)
    return posted_by


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

    line_by, pda_by, bunker_by, paid_by = _aggregate_actual(db, tenant_id, voyage_id)
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
        act = line_by.get(vid, _blank_lines())
        act["port_costs"] = pda_by.get(vid, 0.0)
        act["bunker"] = bunker_by.get(vid, 0.0)
        act["commission"] = _commission(ch, act)
        columns["actual"] = act

        # --- posted ---
        columns["posted"] = posted_by.get(vid, _blank_lines())

        # --- variance = actual - estimate ---
        columns["variance"] = {
            k: columns["actual"][k] - columns["estimate"][k] for k in PNL_LINE_KEYS
        }

        # --- totals per column ---
        totals = {}
        for col in ("estimate", "actual", "posted"):
            totals[col] = _totals(columns[col])
        totals["estimate"]["tce"] = est_tce

        out.append({
            "voyage_id": vid,
            "voyage_no": v.voyage_no,
            "status": v.status,
            "cargo": v.cargo,
            "columns": columns,
            "totals": totals,
            "paid_amount": paid_by.get(vid, 0.0),
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
            totals = {}
            for col in ("estimate", "actual", "posted"):
                totals[col] = _totals(columns[col])
            out.append({
                "voyage_id": "unassigned",
                "voyage_no": "UNASSIGNED",
                "status": "\u2014",
                "cargo": None,
                "columns": columns,
                "totals": totals,
                "paid_amount": paid_by.get(ua_key, 0.0),
            })

    return out


def fleet_pnl_summary(db: Session, tenant_id: UUID) -> dict:
    """Aggregate all voyage rows into fleet-wide totals per column."""
    rows = voyage_pnl_4col(db, tenant_id)

    fleet_columns: dict[str, dict[str, float]] = {
        "estimate": _blank_lines(),
        "actual": _blank_lines(),
        "posted": _blank_lines(),
        "variance": _blank_lines(),
    }
    fleet_totals: dict[str, dict[str, float]] = {
        "estimate": {"revenue": 0.0, "cost": 0.0, "pnl": 0.0, "tce": None},
        "actual": {"revenue": 0.0, "cost": 0.0, "pnl": 0.0},
        "posted": {"revenue": 0.0, "cost": 0.0, "pnl": 0.0},
    }
    total_paid = 0.0
    tce_sum = 0.0
    tce_count = 0

    for row in rows:
        for col in ("estimate", "actual", "posted", "variance"):
            for k in PNL_LINE_KEYS:
                fleet_columns[col][k] += row["columns"][col].get(k, 0.0)
        for col in ("estimate", "actual", "posted"):
            rt = row["totals"].get(col, {})
            fleet_totals[col]["revenue"] += rt.get("revenue", 0.0)
            fleet_totals[col]["cost"] += rt.get("cost", 0.0)
            fleet_totals[col]["pnl"] += rt.get("pnl", 0.0)
        est_tce = row["totals"].get("estimate", {}).get("tce")
        if est_tce is not None:
            tce_sum += float(est_tce)
            tce_count += 1
        total_paid += row.get("paid_amount", 0.0)

    if tce_count:
        fleet_totals["estimate"]["tce"] = tce_sum

    return {
        "voyage_count": len(rows),
        "columns": fleet_columns,
        "totals": fleet_totals,
        "paid_amount": total_paid,
    }
