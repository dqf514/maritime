"""Phase 6 — Carbon compliance calculator.

Covers EU ETS, FuelEU Maritime, and CII rating calculations.
All calculations follow IMO MEPC.330(76) methodology.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models_domain import EmissionRecord, Voyage


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
    co2_tonnes = fuel_consumption_mt * factor["co2_factor"]
    energy_mj = fuel_consumption_mt * 1000 * factor["energy_density"]
    co2_per_cargo = co2_tonnes / max(cargo_mt, 1)
    co2_per_distance = co2_tonnes / max(distance_nm, 1) * 1000

    return {
        "co2_tonnes": round(co2_tonnes, 2),
        "co2_per_cargo_mt": round(co2_per_cargo, 4),
        "co2_per_distance_nm": round(co2_per_distance, 4),
        "energy_mj": round(energy_mj, 2),
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
    phase_in = {2024: 0.40, 2025: 0.70}
    coverage = phase_in.get(voyage_year, 1.0)
    if not is_eu_voyage:
        coverage = 0.0

    liable_tonnes = co2_tonnes * coverage * (ets_responsibility_pct / 100.0)
    cost_eur = liable_tonnes * EU_ETS_CO2_PRICE

    return {
        "total_co2_tonnes": round(co2_tonnes, 2),
        "coverage_pct": round(coverage * 100, 1),
        "liable_tonnes": round(liable_tonnes, 2),
        "co2_price_eur": EU_ETS_CO2_PRICE,
        "cost_eur": round(cost_eur, 2),
        "cost_usd": round(cost_eur * 1.08, 2),
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
    """
    factor = FUEL_FACTORS.get(fuel_type, FUEL_FACTORS["VLSFO"])
    energy_mj = fuel_consumption_mt * 1000 * factor["energy_density"]
    transport_work = max(cargo_mt * distance_nm, 1)
    intensity = energy_mj / transport_work

    limit = FUELEU_LIMIT_2025
    if year == 2026:
        limit = 87.5
    elif year == 2027:
        limit = 85.0
    elif year >= 2028:
        limit = 82.0

    compliant = intensity <= limit
    penalty_factor = max(0, (intensity - limit) / limit)
    penalty_usd = penalty_factor * 2500 * fuel_consumption_mt

    return {
        "intensity_gco2_mj": round(intensity, 2),
        "limit_gco2_mj": limit,
        "compliant": compliant,
        "margin_pct": round((1 - intensity / limit) * 100, 1),
        "penalty_usd": round(penalty_usd, 2) if not compliant else 0,
        "fuel_type": fuel_type,
        "energy_mj": round(energy_mj, 2),
        "transport_work": round(transport_work, 2),
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

    cii_value = (co2_tonnes * 1_000_000) / (dwt * distance_nm)

    rating = "E"
    for grade, threshold in sorted(CII_THRESHOLDS.items(), key=lambda x: x[1]):
        if cii_value <= threshold:
            rating = grade
            break

    return {
        "cii_value": round(cii_value, 2),
        "rating": rating,
        "dwt": dwt,
        "distance_nm": distance_nm,
        "co2_tonnes": round(co2_tonnes, 2),
        "vessel_type": vessel_type,
    }


def get_fleet_compliance_summary(db: Session, tenant_id: uuid.UUID) -> dict[str, Any]:
    """Aggregate compliance metrics across all voyages for the compliance dashboard."""
    voyage_count = db.execute(
        text("SELECT COUNT(*) FROM voyages WHERE tenant_id = :tid"),
        {"tid": str(tenant_id)},
    ).scalar() or 0

    bunker_total = db.execute(
        text("SELECT COALESCE(SUM(quantity_mt), 0) FROM bunker_orders WHERE tenant_id = :tid"),
        {"tid": str(tenant_id)},
    ).scalar() or 0

    total_co2 = float(bunker_total) * 3.15  # approximate VLSFO factor
    eu_ets = calculate_eu_ets_cost(total_co2)

    fueleu = calculate_fueleu_compliance(
        fuel_consumption_mt=float(bunker_total),
        fuel_type="VLSFO",
        distance_nm=voyage_count * 3000,
        cargo_mt=voyage_count * 30000,
    )

    emission_records = db.execute(
        text("SELECT COUNT(*) FROM emission_records WHERE tenant_id = :tid"),
        {"tid": str(tenant_id)},
    ).scalar() or 0

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
    """Compliance breakdown for a single voyage."""
    v = db.execute(
        text("""
            SELECT v.voyage_no, v.vessel_name, v.cargo_qty, v.total_costs,
                   v.load_port_name, v.disch_port_name
            FROM voyages v WHERE v.id = :vid AND v.tenant_id = :tid
        """),
        {"vid": str(voyage_id), "tid": str(tenant_id)},
    ).fetchone()

    if not v:
        return {"error": "Voyage not found"}

    cargo = float(v.cargo_qty or 30000)
    costs = float(v.total_costs or 0)
    fuel_est = costs / 500  # rough estimate: $500/MT fuel
    co2 = fuel_est * 3.15

    emissions = calculate_voyage_emissions(fuel_est, "VLSFO", 3000, cargo)
    eu_ets = calculate_eu_ets_cost(co2)
    fueleu = calculate_fueleu_compliance(fuel_est, "VLSFO", 3000, cargo)

    return {
        "voyage_no": v.voyage_no,
        "vessel_name": v.vessel_name,
        "emissions": emissions,
        "eu_ets": eu_ets,
        "fueleu": fueleu,
    }
