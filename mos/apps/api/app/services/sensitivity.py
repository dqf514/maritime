"""Sensitivity analysis + break-even point (BEP) calculation.

Perturbs estimate parameters by ±N% and recalculates P&L impact.
Returns tornado chart data and BEP freight rate / BEP cargo qty.

金额口径（审计 P1-B3）：内部**全程 Decimal**，出口才转 float。

以前整段是 float + 裸 ``round()`` —— 裸 round 走**银行家舍入**
（``.5`` 往偶数靠），与系统其余口径（``services.money`` 的显式
``ROUND_HALF_UP``）不一致：同一笔账在敏感性图 / 盈亏平衡表与单据上
能差半分（0.125 → 0.12 而不是 0.13）。现在：

- 收入 / 成本 / 损益 / 运费率 / 货量全部用 ``Decimal`` 计算；
- 对外仍是**同样的 JSON 形状**（float），但数值按 ``ROUND_HALF_UP`` 量化；
- 情景语义（扰动哪些科目、怎么扰）**没有变**，只换了数值类型与舍入方式。
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import Estimate, Voyage, Charter
from app.services.money import dec, round_half_up

#: 金额 / 数量的零 —— Decimal，不是 float（float 零没有"精确"可言）。
_ZERO = Decimal("0")


def _d(val) -> Decimal:
    """任意数值 → Decimal（**不**做分位量化；比率/吨位这类量也要精确）。

    脏数据不抛异常 —— 估值结果里混进字符串时按 0 处理，与旧实现一致。
    """
    if val is None:
        return _ZERO
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except Exception:  # noqa: BLE001 — 脏数据不应让整页崩掉
        return _ZERO


def _extract_pnl(results: dict, inputs: dict) -> tuple[Decimal, dict[str, Decimal]]:
    """把估价结果还原成「收入 / 成本科目」，供敏感性扰动使用。

    估价引擎（``estimate_engine.compute_estimate``）输出的是**扁平**结构::

        total_revenue / voyage_cost / bunker_cost / hire_cost
        commission / address_commission / brokerage / emissions_cost

    早期版本把明细放在 ``results["lines"]`` 里 —— 两种结构都要兼容，否则
    base_revenue / base_cost 恒为 0，敏感性图与盈亏平衡点全是零。

    成本科目命名沿用 ``_recalculate_pnl`` 的约定：bunker / port_costs /
    canal / commission —— 这四个才是会被扰动的科目。
    """
    lines = results.get("lines")
    if isinstance(lines, dict) and lines:
        revenue_keys = {"revenue", "hire", "demurrage", "other"}
        base_revenue = sum((_d(lines.get(k)) for k in revenue_keys), _ZERO)
        base_costs = {k: _d(v) for k, v in lines.items() if k not in revenue_keys}
        return base_revenue, base_costs

    total_revenue = _d(results.get("total_revenue"))
    voyage_cost = _d(results.get("voyage_cost"))
    bunker = _d(results.get("bunker_cost"))
    hire = _d(results.get("hire_cost"))
    emissions = _d(results.get("emissions_cost"))
    commission = (
        _d(results.get("commission"))
        + _d(results.get("address_commission"))
        + _d(results.get("brokerage"))
    )
    port_costs = _d(inputs.get("port_costs"))
    canal = _d(inputs.get("canal_costs"))
    # voyage_cost = bunker + port + canal + other + eca_extra + brokerage + emissions
    other = voyage_cost - bunker - port_costs - canal - commission - emissions
    base_costs = {
        "bunker": bunker,
        "port_costs": port_costs,
        "canal": canal,
        "commission": commission,
        "other": other,
        "hire": hire,
    }
    return total_revenue, base_costs


def _recalculate_pnl(
    base_revenue: Decimal,
    base_costs: dict[str, Decimal],
    perturbation: str,
    factor: Decimal,
) -> Decimal:
    """Recalculate P&L after perturbing a parameter.

    Args:
        base_revenue: Base revenue
        base_costs: Dict of cost line items
        perturbation: Which parameter to perturb
        factor: Multiplication factor (e.g., 1.1 for +10%)

    Returns:
        New P&L after perturbation（Decimal）
    """
    revenue = base_revenue
    costs = dict(base_costs)

    if perturbation == "freight_rate":
        revenue = base_revenue * factor
    elif perturbation == "bunker_price":
        costs["bunker"] = costs.get("bunker", _ZERO) * factor
    elif perturbation == "port_costs":
        costs["port_costs"] = costs.get("port_costs", _ZERO) * factor
    elif perturbation == "canal_costs":
        costs["canal"] = costs.get("canal", _ZERO) * factor
    elif perturbation == "commission":
        costs["commission"] = costs.get("commission", _ZERO) * factor
    elif perturbation == "voyage_days":
        # Longer voyage = more bunker + port costs (simplified)
        costs["bunker"] = costs.get("bunker", _ZERO) * factor
        costs["port_costs"] = costs.get("port_costs", _ZERO) * factor

    total_cost = sum(costs.values(), _ZERO)
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

    数值全部按 ``ROUND_HALF_UP`` 量化到分（JSON 出口才转 float）。
    """
    est = db.get(Estimate, estimate_id)
    if not est or est.tenant_id != tenant_id:
        raise ValueError("Estimate not found")

    results = est.results or {}
    base_revenue, base_costs = _extract_pnl(results, est.inputs or {})
    base_cost = sum(base_costs.values(), _ZERO)
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

    pct_d = dec(pct)
    factor_up = Decimal("1") + pct_d / Decimal("100")
    factor_down = Decimal("1") - pct_d / Decimal("100")

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
            "pct_change": float(pct),
            "pnl_up": float(round_half_up(pnl_up, 2)),
            "pnl_down": float(round_half_up(pnl_down, 2)),
            "impact_up": float(round_half_up(impact_up, 2)),
            "impact_down": float(round_half_up(impact_down, 2)),
            "max_impact": float(round_half_up(max_impact, 2)),
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
        "base_pnl": float(round_half_up(base_pnl, 2)),
        "base_revenue": float(round_half_up(base_revenue, 2)),
        "base_cost": float(round_half_up(base_cost, 2)),
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
            "has_cost_base": bool,
            "current_freight_rate": float,
            "current_cargo_qty": float,
            "base_pnl": float,
        }
    """
    est = db.get(Estimate, estimate_id)
    if not est or est.tenant_id != tenant_id:
        raise ValueError("Estimate not found")

    # Load linked voyage + charter for current rates.
    # Voyage 没有 estimate_id 列 —— 链路是 Estimate → Charter.estimate_id → Voyage.charter_id。
    voyage = db.execute(
        select(Voyage)
        .join(Charter, Voyage.charter_id == Charter.id)
        .where(Charter.estimate_id == estimate_id, Voyage.tenant_id == tenant_id)
    ).scalars().first()

    charter = None
    if voyage:
        charter = db.execute(
            select(Charter).where(
                Charter.estimate_id == estimate_id, Charter.tenant_id == tenant_id
            )
        ).scalars().first()

    results = est.results or {}
    inputs = est.inputs or {}
    base_revenue, base_costs = _extract_pnl(results, inputs)
    base_cost = sum(base_costs.values(), _ZERO)
    base_pnl = base_revenue - base_cost

    # Current values
    current_freight_rate = _d(charter.freight_rate) if charter else _d(inputs.get("freight_rate"))
    current_cargo_qty = _d(charter.cargo_qty) if charter else _d(inputs.get("cargo_qty"))

    # 没有成本基数（估价只填了收入侧）时，盈亏平衡点无意义：任何运价都不亏，
    # 算出来是 0。与其回一个会被误读成「盈亏平衡运价为 0」的数字，不如显式说明。
    has_cost_base = base_cost > 0

    bep_freight_rate = None
    bep_cargo_qty = None

    if has_cost_base:
        # BEP freight rate: revenue needed = base_cost, so freight_rate = base_cost / cargo_qty
        if current_cargo_qty > 0:
            bep_freight_rate = base_cost / current_cargo_qty

        # BEP cargo qty: cargo_qty = base_cost / freight_rate
        if current_freight_rate > 0:
            bep_cargo_qty = base_cost / current_freight_rate

    return {
        "estimate_id": str(estimate_id),
        "bep_freight_rate": (
            float(round_half_up(bep_freight_rate, 2)) if bep_freight_rate is not None else None
        ),
        "bep_cargo_qty": (
            float(round_half_up(bep_cargo_qty, 3)) if bep_cargo_qty is not None else None
        ),
        "has_cost_base": has_cost_base,
        "current_freight_rate": float(round_half_up(current_freight_rate, 2)),
        "current_cargo_qty": float(round_half_up(current_cargo_qty, 3)),
        "base_pnl": float(round_half_up(base_pnl, 2)),
        "base_revenue": float(round_half_up(base_revenue, 2)),
        "base_cost": float(round_half_up(base_cost, 2)),
    }
