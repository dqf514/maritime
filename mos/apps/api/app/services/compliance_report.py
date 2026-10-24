"""合规申报导出（Phase 2 / D17）：MRV / EU ETS / FuelEU 申报口径的报表。

口径与 ``/emissions/fueleu_calc`` 完全同源（同一套 LHV/换算/target 公式），
按 EmissionRecord 汇总重算，输出 rows + totals + CSV（可直接申报的素材）。

- **mrv**：年度排放清单（per voyage/vessel：FO/DO/CO2 + 合计）
- **ets**：应清缴配额 = CO2e × EU 份额（per voyage 推断，缺省 1.0）
- **fueleu**：全队 GHG 强度 vs 目标轨迹 → 合规平衡（正=缺口）
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import EmissionRecord, PortCall, Voyage
from app.models_wave1 import Port
from app.services.money import round_half_up

# 与 fueleu_calc 同源的近似参数（LHV MJ/t、换算、2025 参考目标）
LHV_MJ_PER_T = 42700.0
TARGET_2025 = 89.34  # illustrative FuelEU reference gCO2e/MJ


def infer_eu_share(db: Session, tenant_id, voyage_id) -> float | None:
    """EU scope share（简化口径：未加权 leg 平均）：EU↔EU=1.0，EU↔非EU=0.5，非EU↔非EU=0。"""
    pcs = db.scalars(
        select(PortCall)
        .where(PortCall.tenant_id == tenant_id, PortCall.voyage_id == voyage_id)
        .order_by(PortCall.seq.asc())
    ).all()
    flags = []
    for pc in pcs:
        port = db.get(Port, pc.port_id) if pc.port_id else None
        flags.append(bool(port and port.is_eu))
    if len(flags) < 2:
        return None
    legs = [1.0 if a and b else 0.5 if a or b else 0.0 for a, b in zip(flags, flags[1:])]
    return sum(legs) / len(legs)


def _csv(headers: list[str], rows: list[list[Any]]) -> str:
    import io

    buf = io.StringIO()
    buf.write(",".join(headers) + "\n")
    for r in rows:
        buf.write(",".join("" if v is None else str(v) for v in r) + "\n")
    return buf.getvalue()


def compliance_report(db: Session, tenant_id, scheme: str, period: str | None = None) -> dict[str, Any]:
    if scheme not in ("mrv", "ets", "fueleu"):
        raise ValueError(f"unknown scheme {scheme}")
    stmt = select(EmissionRecord).where(EmissionRecord.tenant_id == tenant_id)
    if period:
        stmt = stmt.where(EmissionRecord.period == period)
    rows = db.scalars(stmt.order_by(EmissionRecord.period)).all()

    if scheme == "mrv":
        out_rows = [
            {
                "voyage_id": str(r.voyage_id) if r.voyage_id else None,
                "vessel_id": str(r.vessel_id) if r.vessel_id else None,
                "fo_mt": float(r.fo_mt or 0),
                "do_mt": float(r.do_mt or 0),
                "co2_mt": float(r.co2_mt or 0),
                "period": r.period,
            }
            for r in rows
        ]
        totals = {
            "fo_mt": float(round_half_up(sum(Decimal(str(x["fo_mt"])) for x in out_rows), 3)),
            "do_mt": float(round_half_up(sum(Decimal(str(x["do_mt"])) for x in out_rows), 3)),
            "co2_mt": float(round_half_up(sum(Decimal(str(x["co2_mt"])) for x in out_rows), 3)),
        }
        csv = _csv(
            ["voyage_id", "vessel_id", "fo_mt", "do_mt", "co2_mt", "period"],
            [[x["voyage_id"], x["vessel_id"], x["fo_mt"], x["do_mt"], x["co2_mt"], x["period"]] for x in out_rows],
        )
        return {"scheme": "mrv", "period": period, "rows": out_rows, "totals": totals, "csv": csv}

    if scheme == "ets":
        out_rows = []
        for r in rows:
            share = infer_eu_share(db, tenant_id, r.voyage_id) if r.voyage_id else 1.0
            share = 1.0 if share is None else share
            co2 = Decimal(str(r.co2_mt or 0))
            share_dec = Decimal(str(share))
            out_rows.append(
                {
                    "voyage_id": str(r.voyage_id) if r.voyage_id else None,
                    "co2_mt": float(co2),
                    "eu_share": float(round_half_up(share_dec, 4)),
                    "allowances_t": float(round_half_up(co2 * share_dec, 3)),
                }
            )
        total_allowances = float(
            round_half_up(sum(Decimal(str(x["allowances_t"])) for x in out_rows), 3)
        )
        csv = _csv(
            ["voyage_id", "co2_mt", "eu_share", "allowances_t"],
            [[x["voyage_id"], x["co2_mt"], x["eu_share"], x["allowances_t"]] for x in out_rows],
        )
        return {"scheme": "ets", "period": period, "rows": out_rows, "totals": {"allowances_t": total_allowances}, "csv": csv}

    # fueleu：全队强度 vs 目标（与 fueleu_calc 同公式）
    # 全部走 Decimal —— 申报数字要能跟外部系统对上，float 累加会漂。
    fo = sum((Decimal(str(r.fo_mt or 0)) for r in rows), Decimal("0"))
    do = sum((Decimal(str(r.do_mt or 0)) for r in rows), Decimal("0"))
    energy_mj = (fo + do) * Decimal(str(LHV_MJ_PER_T))
    co2e_t = fo * Decimal("3.114") + do * Decimal("3.206")
    intensity = (co2e_t * 1_000_000 / energy_mj) if energy_mj > 0 else Decimal("0")
    target = Decimal(str(TARGET_2025))
    compliance_balance_t = max(
        Decimal("0"), (intensity - target) / 1_000_000 * energy_mj
    )
    result = {
        "scheme": "fueleu",
        "period": period,
        "rows": [
            {
                "fo_mt": float(round_half_up(fo, 3)),
                "do_mt": float(round_half_up(do, 3)),
                "energy_mj": float(round_half_up(energy_mj, 1)),
                "intensity_gco2e_mj": float(round_half_up(intensity, 3)),
                "target_gco2e_mj": TARGET_2025,
                "compliance_balance_t": float(round_half_up(compliance_balance_t, 3)),
            }
        ],
        "totals": {
            "compliance_balance_t": float(round_half_up(compliance_balance_t, 3)),
            "intensity_gco2e_mj": float(round_half_up(intensity, 3)),
        },
    }
    result["csv"] = _csv(
        ["fo_mt", "do_mt", "energy_mj", "intensity_gco2e_mj", "target_gco2e_mj", "compliance_balance_t"],
        [[v for v in result["rows"][0].values()]],
    )
    return result
