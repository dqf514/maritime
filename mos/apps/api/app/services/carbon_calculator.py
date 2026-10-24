"""Phase 6 — Carbon compliance calculator.

Covers EU ETS, FuelEU Maritime, and CII rating calculations.
All calculations follow IMO MEPC.330(76) methodology.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models_domain import BunkerOrder, EmissionRecord, Voyage
from app.services.observability import traced


FUEL_FACTORS = {
    "HFO": {"co2_factor": 3.114, "energy_density": 1.016},
    "MGO": {"co2_factor": 3.206, "energy_density": 1.044},
    "LNG": {"co2_factor": 2.750, "energy_density": 1.380},
    "Methanol": {"co2_factor": 1.375, "energy_density": 0.555},
    "Ammonia": {"co2_factor": 0.000, "energy_density": 0.527},
    "VLSFO": {"co2_factor": 3.151, "energy_density": 1.028},
}

EU_ETS_CO2_PRICE = 80.0  # EUR/tonne CO2
FUELEU_LIMIT_2025 = 89.9  # gCO2e/MJ (decreasing yearly)
CII_THRESHOLDS = {
    "A": 0.60,
    "B": 0.80,
    "C": 1.00,
    "D": 1.20,
    "E": 999.0,
}


def _dec(value: Any) -> Decimal:
    """float → Decimal（走 ``str``，避免二进制尾数）。"""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal("0")
    return Decimal(str(value))


def _q(value: Decimal, places: str) -> float:
    """Decimal → float，显式 ROUND_HALF_UP。

    Python 内建 ``round()`` 用的是**银行家舍入**（.5 往偶数靠），与本系统
    统一的「四舍五入」口径不一致 —— 金额上就是 1 分钱的差。这里所有
    碳排/能耗/成本出口都显式走 ROUND_HALF_UP。
    """
    return float(value.quantize(Decimal(places), rounding=ROUND_HALF_UP))


@traced("carbon")
def calculate_voyage_emissions(
    fuel_consumption_mt: float,
    fuel_type: str = "VLSFO",
    distance_nm: float = 0,
    cargo_mt: float = 0,
) -> dict[str, float]:
    """Calculate CO2 emissions for a voyage segment.

    Returns total CO2 tonnes, per-cargo intensity, and energy efficiency.
    """
    factor = FUEL_FACTORS.get(fuel_type, FUEL_FACTORS["VLSFO"])
    fuel = _dec(fuel_consumption_mt)
    co2_tonnes = fuel * _dec(factor["co2_factor"])
    energy_mj = fuel * 1000 * _dec(factor["energy_density"])
    co2_per_cargo = co2_tonnes / max(_dec(cargo_mt), Decimal("1"))
    co2_per_distance = co2_tonnes / max(_dec(distance_nm), Decimal("1")) * 1000

    return {
        "co2_tonnes": _q(co2_tonnes, "0.01"),
        "co2_per_cargo_mt": _q(co2_per_cargo, "0.0001"),
        "co2_per_distance_nm": _q(co2_per_distance, "0.0001"),
        "energy_mj": _q(energy_mj, "0.01"),
        "fuel_type": fuel_type,
        "fuel_consumed_mt": fuel_consumption_mt,
    }


def calculate_eu_ets_cost(
    co2_tonnes: float,
    voyage_year: int = 2025,
    is_eu_voyage: bool = True,
    ets_responsibility_pct: float = 100.0,
) -> dict[str, float]:
    """Calculate EU ETS compliance cost.

    2024: 40% of emissions, 2025: 70%, 2026+: 100%
    """
    phase_in = {2024: Decimal("0.40"), 2025: Decimal("0.70")}
    coverage = phase_in.get(voyage_year, Decimal("1"))
    if not is_eu_voyage:
        coverage = Decimal("0")

    co2 = _dec(co2_tonnes)
    liable_tonnes = co2 * coverage * (_dec(ets_responsibility_pct) / 100)
    cost_eur = liable_tonnes * _dec(EU_ETS_CO2_PRICE)

    return {
        "total_co2_tonnes": _q(co2, "0.01"),
        "coverage_pct": _q(coverage * 100, "0.1"),
        "liable_tonnes": _q(liable_tonnes, "0.01"),
        "co2_price_eur": EU_ETS_CO2_PRICE,
        "cost_eur": _q(cost_eur, "0.01"),
        "cost_usd": _q(cost_eur * _dec("1.08"), "0.01"),
    }


def calculate_fueleu_compliance(
    fuel_consumption_mt: float,
    fuel_type: str,
    distance_nm: float,
    cargo_mt: float = 0,
    year: int = 2025,
) -> dict[str, Any]:
    """Calculate FuelEU Maritime compliance.

    Energy Efficiency = (fuel_mt * energy_density_MJ/kg * 1000) / (cargo_mt * distance_nm)
    Compared against annual GHG intensity limit.

    罚金只在**确实存在缺口**（intensity > limit）且运输功可测（cargo_mt ×
    distance_nm > 0）时产生。零输入以前会造出九位数罚款
    （calculate_fueleu_compliance(100,"VLSFO",0,0) → 285,623,192.44 USD），
    现在无缺口一律 0，并带上 assessable 标记说明结论是否可评估（P1-B15）。
    """
    if fuel_consumption_mt is None or float(fuel_consumption_mt) < 0:
        raise ValueError("fuel_consumption_mt must be >= 0")
    if distance_nm is None or float(distance_nm) < 0:
        raise ValueError("distance_nm must be >= 0")
    if cargo_mt is None or float(cargo_mt) < 0:
        raise ValueError("cargo_mt must be >= 0")

    factor = FUEL_FACTORS.get(fuel_type, FUEL_FACTORS["VLSFO"])
    fuel = _dec(fuel_consumption_mt)
    energy_mj = fuel * 1000 * _dec(factor["energy_density"])
    transport_work = _dec(cargo_mt) * _dec(distance_nm)

    limit = _dec(FUELEU_LIMIT_2025)
    if year == 2026:
        limit = _dec("87.5")
    elif year == 2027:
        limit = _dec("85.0")
    elif year >= 2028:
        limit = _dec("82.0")

    assessable = transport_work > 0 and fuel > 0
    penalty_usd = Decimal("0.00")
    if assessable:
        intensity = energy_mj / transport_work
        compliant = intensity <= limit
        margin_pct = (1 - intensity / limit) * 100
        if not compliant:
            penalty_usd = (
                (intensity - limit)
                / limit
                * Decimal("2500")
                * fuel
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        # 无运输功 / 无油耗 → 没有可评估的缺口：罚金 0，不编造数字
        intensity = Decimal("0")
        compliant = True
        margin_pct = Decimal("100")

    return {
        "intensity_gco2_mj": _q(intensity, "0.01"),
        "limit_gco2_mj": float(limit),
        "compliant": compliant,
        "margin_pct": _q(margin_pct, "0.1"),
        "penalty_usd": penalty_usd,
        "fuel_type": fuel_type,
        "energy_mj": _q(energy_mj, "0.01"),
        "transport_work": _q(transport_work, "0.01"),
        "assessable": assessable,
        **(
            {}
            if assessable
            else {
                "message": (
                    "no transport work (cargo_mt × distance_nm = 0) or no fuel burnt — "
                    "no FuelEU gap is assessable, penalty is 0"
                )
            }
        ),
    }


def calculate_cii_rating(
    co2_tonnes: float,
    distance_nm: float,
    dwt: float,
    vessel_type: str = "bulk_carrier",
) -> dict[str, Any]:
    """Calculate CII (Carbon Intensity Indicator) rating A-E.

    CII = (annual CO2 tonnes * 1e6) / (DWT * distance_nm)
    """
    if distance_nm <= 0 or dwt <= 0:
        return {"rating": "N/A", "cii_value": 0, "message": "Insufficient data"}

    cii_value = (_dec(co2_tonnes) * 1_000_000) / (_dec(dwt) * _dec(distance_nm))

    rating = "E"
    for grade, threshold in sorted(CII_THRESHOLDS.items(), key=lambda x: x[1]):
        if cii_value <= threshold:
            rating = grade
            break

    return {
        "cii_value": _q(cii_value, "0.01"),
        "rating": rating,
        "dwt": dwt,
        "distance_nm": distance_nm,
        "co2_tonnes": _q(_dec(co2_tonnes), "0.01"),
        "vessel_type": vessel_type,
    }


def get_fleet_compliance_summary(db: Session, tenant_id: uuid.UUID) -> dict[str, Any]:
    """Aggregate compliance metrics across all voyages for the compliance dashboard.

    全部走 ORM：raw text() 里 str(uuid) 带连字符，而 SQLite 的 Uuid 列存的是
    无连字符 hex，参数永远匹配不上（计数全 0）；ORM 绑定由类型处理器负责格式。
    """
    voyage_count = db.scalar(
        select(func.count()).select_from(Voyage).where(Voyage.tenant_id == tenant_id)
    ) or 0

    # bunker_orders 没有 quantity_mt 列（模型字段为 qty_ordered / qty_delivered）——
    # 已交付优先，未交付回落到订购量；列名写错会让 /compliance/summary 直接 500
    bunker_total = db.scalar(
        select(func.coalesce(func.sum(func.coalesce(BunkerOrder.qty_delivered, BunkerOrder.qty_ordered)), 0)).where(
            BunkerOrder.tenant_id == tenant_id
        )
    ) or 0

    total_co2 = float(bunker_total) * 3.15  # approximate VLSFO factor
    eu_ets = calculate_eu_ets_cost(total_co2)

    fueleu = calculate_fueleu_compliance(
        fuel_consumption_mt=float(bunker_total),
        fuel_type="VLSFO",
        distance_nm=voyage_count * 3000,
        cargo_mt=voyage_count * 30000,
    )

    emission_records = db.scalar(
        select(func.count()).select_from(EmissionRecord).where(EmissionRecord.tenant_id == tenant_id)
    ) or 0

    return {
        "voyage_count": voyage_count,
        "total_bunker_mt": round(float(bunker_total), 2),
        "total_co2_tonnes": round(total_co2, 2),
        "eu_ets": eu_ets,
        "fueleu": fueleu,
        "emission_records": emission_records,
        "compliance_status": "compliant" if fueleu["compliant"] else "non_compliant",
    }


def get_voyage_compliance(db: Session, tenant_id: uuid.UUID, voyage_id: uuid.UUID) -> dict[str, Any]:
    """Compliance breakdown for a single voyage.

    旧实现 raw SQL 引用 voyages 不存在的列（vessel_name/cargo_qty/total_costs/
    load_port_name/disch_port_name），命中即 OperationalError —— 改走 ORM 关联。
    燃料估算改为该航次加油订单实数（原先 costs/500 的成本列也不存在）。
    """
    from app.models_wave1 import Vessel

    v = db.execute(
        select(Voyage.voyage_no, Voyage.cargo, Vessel.name, Vessel.dwt)
        .outerjoin(Vessel, Voyage.vessel_id == Vessel.id)
        .where(Voyage.id == voyage_id, Voyage.tenant_id == tenant_id)
    ).first()

    if not v:
        return {"error": "Voyage not found"}

    fuel_mt = float(
        db.scalar(
            select(
                func.coalesce(func.sum(func.coalesce(BunkerOrder.qty_delivered, BunkerOrder.qty_ordered)), 0)
            ).where(BunkerOrder.voyage_id == voyage_id, BunkerOrder.tenant_id == tenant_id)
        )
        or 0
    )
    cargo = 30000.0  # demo 缺货量数值字段时的兜底运输工作量
    co2 = fuel_mt * 3.15

    emissions = calculate_voyage_emissions(fuel_mt, "VLSFO", 3000, cargo)
    eu_ets = calculate_eu_ets_cost(co2)
    fueleu = calculate_fueleu_compliance(fuel_mt, "VLSFO", 3000, cargo)

    return {
        "voyage_no": v.voyage_no,
        "vessel_name": v.name,
        "emissions": emissions,
        "eu_ets": eu_ets,
        "fueleu": fueleu,
    }


# ── IMO 2020 / SOx / ECA sulphur compliance ──
# MARPOL Annex VI Reg. 14 fuel sulphur limits (% m/m):
#   global cap 3.50% pre-2020 → 0.50% from 2020-01-01 (IMO 2020)
#   ECA cap 0.10% since 2015-01-01 (SOx ECA: Baltic / North Sea / North America /
#   US Caribbean + 中国长三角/珠三角/环渤海 (2019) + 台湾海域 (Taiwan ECA))
from app.services.fuel_zone_service import (  # noqa: E402
    ECA_SULFUR_CAP,
    IMO2020_GLOBAL_SULFUR_CAP,
    preset_eca_matches,
    route_eca_matches,
)

SOX_2015_ECA_CAP = ECA_SULFUR_CAP  # 0.10 — binding since 2015-01-01
SOX_PRE2020_GLOBAL_CAP = 3.50

# Typical sulphur content by grade (% m/m) — used when no measured sulphur_pct is given.
FUEL_SULFUR_PCT = {
    "HSFO": 3.50,
    "HFO": 3.50,
    "IFO380": 3.50,
    "IFO180": 3.50,
    "VLSFO": 0.50,
    "LSFO": 0.50,
    "MGO": 0.10,
    "MDO": 0.10,
    "LSMGO": 0.10,
    "LNG": 0.00,
    "METHANOL": 0.00,
    "AMMONIA": 0.00,
}


def _normalize_route(route: Any) -> list[dict]:
    """Accept [{lat, lon}, ...], [[lat, lon], ...] or a single {lat, lon} point."""
    if route is None:
        return []
    if isinstance(route, dict):
        route = [route]
    points: list[dict] = []
    for item in route:
        if isinstance(item, dict):
            lat, lon = item.get("lat"), item.get("lon")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            lat, lon = item[0], item[1]
        else:
            continue
        if lat is None or lon is None:
            continue
        points.append({"lat": float(lat), "lon": float(lon)})
    return points


def _fuel_sulfur(fuel_type: str | None, sulfur_pct: float | None) -> float | None:
    if sulfur_pct is not None:
        return float(sulfur_pct)
    if fuel_type:
        key = str(fuel_type).strip().upper()
        if key in FUEL_SULFUR_PCT:
            return FUEL_SULFUR_PCT[key]
        for name, pct in FUEL_SULFUR_PCT.items():
            if name in key or key in name:
                return pct
    return None


def eca_compliance(
    vessel_id: Any = None,
    route: Any = None,
    fuel_type: str | None = None,
    sulfur_pct: float | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    """ECA sulphur compliance along a route (含中国长三角/珠三角/环渤海与台湾 ECA).

    In-zone fuel must be ≤ 0.10% sulphur (0.1% since 2015; Chinese ECAs from
    2019 with 0.10% binding from 2020). ``route`` is a list of {lat, lon} points.
    """
    points = _normalize_route(route)
    sulfur = _fuel_sulfur(fuel_type, sulfur_pct)
    per_point = route_eca_matches(points)
    if db is not None:
        # Merge DB-defined zones (multi-tenant custom zones) with the presets.
        from app.services.fuel_zone_service import get_zones_at_position

        for entry in per_point:
            for z in get_zones_at_position(db, entry["lat"], entry["lon"]):
                if z.get("zone_type") != "eca":
                    continue
                if all(z["zone_name"] != e["zone_name"] for e in entry["zones"]):
                    entry["zones"].append(
                        {
                            "zone_name": z["zone_name"],
                            "zone_type": z["zone_type"],
                            "fuel_requirements": z.get("fuel_requirements") or {},
                        }
                    )
            entry["in_eca"] = bool(entry["zones"])

    zone_names: list[str] = []
    for entry in per_point:
        for z in entry["zones"]:
            if z["zone_name"] not in zone_names:
                zone_names.append(z["zone_name"])

    violations: list[str] = []
    points_in_eca = sum(1 for e in per_point if e["in_eca"])
    if points_in_eca and sulfur is not None and sulfur > ECA_SULFUR_CAP:
        violations.append(
            f"Fuel sulphur {sulfur}% exceeds ECA limit {ECA_SULFUR_CAP}% "
            f"(zones: {', '.join(zone_names) or 'ECA'})"
        )
    return {
        "vessel_id": str(vessel_id) if vessel_id is not None else None,
        "fuel_type": fuel_type,
        "sulfur_pct": sulfur,
        "eca_sulfur_cap": ECA_SULFUR_CAP,
        "eca_zones": zone_names,
        "points_total": len(per_point),
        "points_in_eca": points_in_eca,
        "in_eca": points_in_eca > 0,
        "compliant": not violations,
        "violations": violations,
        "route": per_point,
    }


def imo2020_compliance(
    vessel_id: Any = None,
    fuel_type: str | None = None,
    route: Any = None,
    sulfur_pct: float | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    """IMO 2020 global 0.50% sulphur cap (+ ECA 0.10% where applicable).

    Non-compliant when the fuel exceeds the 0.50% global cap anywhere, or the
    0.10% cap inside an ECA (which implies the stricter of the two applies).
    """
    points = _normalize_route(route)
    sulfur = _fuel_sulfur(fuel_type, sulfur_pct)
    violations: list[str] = []
    if sulfur is not None and sulfur > IMO2020_GLOBAL_SULFUR_CAP:
        violations.append(
            f"Fuel sulphur {sulfur}% exceeds IMO 2020 global cap {IMO2020_GLOBAL_SULFUR_CAP}%"
        )
    eca = eca_compliance(vessel_id=vessel_id, route=points, fuel_type=fuel_type, sulfur_pct=sulfur, db=db)
    violations.extend(eca["violations"])
    # Deduplicate while keeping order
    seen: set[str] = set()
    uniq = [v for v in violations if not (v in seen or seen.add(v))]
    return {
        "vessel_id": str(vessel_id) if vessel_id is not None else None,
        "fuel_type": fuel_type,
        "sulfur_pct": sulfur,
        "global_cap": IMO2020_GLOBAL_SULFUR_CAP,
        "eca_cap": ECA_SULFUR_CAP,
        "imo2020_compliant": not uniq,
        "compliant": not uniq,
        "violations": uniq,
        "eca": eca,
    }


def sox_compliance(
    vessel_id: Any = None,
    fuel_type: str | None = None,
    route: Any = None,
    sulfur_pct: float | None = None,
    year: int = 2020,
    db: Session | None = None,
) -> dict[str, Any]:
    """SOx (MARPOL Annex VI Reg. 14) compliance for a voyage year.

    2015 rules: ECA sulphur cap 0.10% (from 2015-01-01). The global cap is
    3.50% before 2020 and 0.50% from 2020 (IMO 2020).
    """
    points = _normalize_route(route)
    sulfur = _fuel_sulfur(fuel_type, sulfur_pct)
    global_cap = IMO2020_GLOBAL_SULFUR_CAP if int(year) >= 2020 else SOX_PRE2020_GLOBAL_CAP
    violations: list[str] = []
    if sulfur is not None and sulfur > global_cap:
        violations.append(f"Fuel sulphur {sulfur}% exceeds global cap {global_cap}% for year {year}")
    eca = eca_compliance(vessel_id=vessel_id, route=points, fuel_type=fuel_type, sulfur_pct=sulfur, db=db)
    violations.extend(eca["violations"])
    seen: set[str] = set()
    uniq = [v for v in violations if not (v in seen or seen.add(v))]
    return {
        "vessel_id": str(vessel_id) if vessel_id is not None else None,
        "fuel_type": fuel_type,
        "sulfur_pct": sulfur,
        "year": int(year),
        "global_cap": global_cap,
        "eca_cap": SOX_2015_ECA_CAP,
        "compliant": not uniq,
        "violations": uniq,
        "eca_zones": eca["eca_zones"],
        "in_eca": eca["in_eca"],
    }
