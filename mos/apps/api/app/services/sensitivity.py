"""Sensitivity analysis + break-even point (BEP) calculation.

Perturbs estimate parameters by ±N% and recalculates P&L impact.
Returns tornado chart data and BEP freight rate / BEP cargo qty.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import Estimate, Voyage, Charter


def _f(val) -> float:
    """Coerce Decimal / None to float."""
    return float(val) if val is not None else 0.0


def _recalculate_pnl(
    base_revenue: float,
    base_costs: dict[str, float],
    perturbation: str,
    factor: float,
) -> float:
    """Recalculate P&L after perturbing a parameter.

    Args:
        base_revenue: Base revenue
        base_costs: Dict of cost line items
        perturbation: Which parameter to perturb
        factor: Multiplication factor (e.g., 1.1 for +10%)

    Returns:
        New P&L after perturbation
    """
    revenue = base_revenue
    costs = dict(base_costs)

    if perturbation == "freight_rate":
        revenue = base_revenue * factor
    elif perturbation == "bunker_price":
        costs["bunker"] = costs.get("bunker", 0.0) * factor
    elif perturbation == "port_costs":
        costs["port_costs"] = costs.get("port_costs", 0.0) * factor
    elif perturbation == "canal_costs":
        costs["canal"] = costs.get("canal", 0.0) * factor
    elif perturbation == "commission":
        costs["commission"] = costs.get("commission", 0.0) * factor
    elif perturbation == "voyage_days":
        # Longer voyage = more bunker + port costs (simplified)
        costs["bunker"] = costs.get("bunker", 0.0) * factor
        costs["port_costs"] = costs.get("port_costs", 0.0) * factor

    total_cost = sum(costs.values())
    return revenue - total_cost


def sensitivity_analysis(
    db: Session,
    tenant_id: UUID,
    estimate_id: UUID,
    pct: float = 10.0,
) -> dict:
    """Run sensitivity analysis on an estimate.

    Perturbs key parameters by ±pct% and returns tornado chart data.

    Args:
        db: Database session
        tenant_id: Tenant UUID
        estimate_id: Estimate UUID
        pct: Percentage to perturb (default 10%)

    Returns:
        {
            "estimate_id": str,
            "base_pnl": float,
            "base_revenue": float,
            "base_cost": float,
            "perturbations": [
                {
                    "parameter": str,
                    "label": str,
                    "pct_change": float,
                    "pnl_up": float,
                    "pnl_down": float,
                    "impact_up": float,
                    "impact_down": float,
                    "max_impact": float,
                },
                ...
            ],
            "tornado": [
                {"parameter": str, "label": str, "max_impact": float},
                ...
            ],
        }
    """
    est = db.get(Estimate, estimate_id)
    if not est or est.tenant_id != tenant_id:
        raise ValueError("Estimate not found")

    results = est.results or {}
    line_items = results.get("lines", {})

    # Extract base values
    revenue_keys = {"revenue", "hire", "demurrage", "other"}
    base_revenue = sum(line_items.get(k, 0.0) for k in revenue_keys)
    base_costs = {
        k: line_items.get(k, 0.0)
        for k in line_items
        if k not in revenue_keys
    }
    base_cost = sum(base_costs.values())
    base_pnl = base_revenue - base_cost

    # Parameters to perturb
    parameters = [
        ("freight_rate", "Freight Rate"),
        ("bunker_price", "Bunker Price"),
        ("port_costs", "Port Costs"),
        ("canal_costs", "Canal Costs"),
        ("commission", "Commission"),
        ("voyage_days", "Voyage Days"),
    ]

    factor_up = 1.0 + pct / 100.0
    factor_down = 1.0 - pct / 100.0

    perturbations = []
    for param_key, param_label in parameters:
        pnl_up = _recalculate_pnl(base_revenue, base_costs, param_key, factor_up)
        pnl_down = _recalculate_pnl(base_revenue, base_costs, param_key, factor_down)

        impact_up = pnl_up - base_pnl
        impact_down = pnl_down - base_pnl
        max_impact = max(abs(impact_up), abs(impact_down))

        perturbations.append({
            "parameter": param_key,
            "label": param_label,
            "pct_change": pct,
            "pnl_up": round(pnl_up, 2),
            "pnl_down": round(pnl_down, 2),
            "impact_up": round(impact_up, 2),
            "impact_down": round(impact_down, 2),
            "max_impact": round(max_impact, 2),
        })

    # Sort by max_impact descending for tornado chart
    tornado = sorted(perturbations, key=lambda x: x["max_impact"], reverse=True)
    tornado_chart = [
        {
            "parameter": p["parameter"],
            "label": p["label"],
            "max_impact": p["max_impact"],
            "impact_up": p["impact_up"],
            "impact_down": p["impact_down"],
        }
        for p in tornado
    ]

    return {
        "estimate_id": str(estimate_id),
        "base_pnl": round(base_pnl, 2),
        "base_revenue": round(base_revenue, 2),
        "base_cost": round(base_cost, 2),
        "perturbation_pct": pct,
        "perturbations": perturbations,
        "tornado": tornado_chart,
    }


def calculate_bep(
    db: Session,
    tenant_id: UUID,
    estimate_id: UUID,
) -> dict:
    """Calculate break-even point (BEP) freight rate and cargo qty.

    Args:
        db: Database session
        tenant_id: Tenant UUID
        estimate_id: Estimate UUID

    Returns:
        {
            "estimate_id": str,
            "bep_freight_rate": float | None,
            "bep_cargo_qty": float | None,
            "current_freight_rate": float,
            "current_cargo_qty": float,
            "base_pnl": float,
        }
    """
    est = db.get(Estimate, estimate_id)
    if not est or est.tenant_id != tenant_id:
        raise ValueError("Estimate not found")

    # Load linked voyage + charter for current rates
    voyage = db.execute(
        select(Voyage).where(Voyage.estimate_id == estimate_id)
    ).scalar_one_or_none()

    charter = None
    if voyage:
        charter = db.execute(
            select(Charter).where(Charter.estimate_id == estimate_id)
        ).scalar_one_or_none()

    results = est.results or {}
    inputs = est.inputs or {}
    line_items = results.get("lines", {})

    # Extract base values
    revenue_keys = {"revenue", "hire", "demurrage", "other"}
    base_revenue = sum(line_items.get(k, 0.0) for k in revenue_keys)
    base_costs = {
        k: line_items.get(k, 0.0)
        for k in line_items
        if k not in revenue_keys
    }
    base_cost = sum(base_costs.values())
    base_pnl = base_revenue - base_cost

    # Current values
    current_freight_rate = _f(charter.freight_rate) if charter else _f(inputs.get("freight_rate"))
    current_cargo_qty = _f(charter.cargo_qty) if charter else _f(inputs.get("cargo_qty"))

    bep_freight_rate = None
    bep_cargo_qty = None

    # BEP freight rate: revenue needed = base_cost, so freight_rate = base_cost / cargo_qty
    if current_cargo_qty > 0:
        bep_freight_rate = base_cost / current_cargo_qty

    # BEP cargo qty: cargo_qty = base_cost / freight_rate
    if current_freight_rate > 0:
        bep_cargo_qty = base_cost / current_freight_rate

    return {
        "estimate_id": str(estimate_id),
        "bep_freight_rate": round(bep_freight_rate, 2) if bep_freight_rate else None,
        "bep_cargo_qty": round(bep_cargo_qty, 3) if bep_cargo_qty else None,
        "current_freight_rate": round(current_freight_rate, 2),
        "current_cargo_qty": round(current_cargo_qty, 3),
        "base_pnl": round(base_pnl, 2),
        "base_revenue": round(base_revenue, 2),
        "base_cost": round(base_cost, 2),
    }
