"""Phase 6 — Compliance dashboard API endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.security import AuthContext, require_module
from app.services.carbon_calculator import (
    calculate_cii_rating,
    calculate_eu_ets_cost,
    calculate_fueleu_compliance,
    calculate_voyage_emissions,
    get_fleet_compliance_summary,
    get_voyage_compliance,
)

router = APIRouter(prefix="/compliance", tags=["Compliance"])


class EmissionsCalcIn(BaseModel):
    fuel_consumption_mt: float
    fuel_type: str = "VLSFO"
    distance_nm: float = 0
    cargo_mt: float = 0


class EuEtsCalcIn(BaseModel):
    co2_tonnes: float
    voyage_year: int = 2025
    is_eu_voyage: bool = True
    ets_responsibility_pct: float = 100.0


class FuelEuCalcIn(BaseModel):
    fuel_consumption_mt: float
    fuel_type: str = "VLSFO"
    distance_nm: float = 0
    cargo_mt: float = 0
    year: int = 2025


class CiiCalcIn(BaseModel):
    co2_tonnes: float
    distance_nm: float
    dwt: float
    vessel_type: str = "bulk_carrier"


@router.get("/summary")
def fleet_compliance_summary(
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """Fleet-wide compliance summary (EU ETS + FuelEU + CII overview)."""
    return get_fleet_compliance_summary(db, auth.tenant_id)


@router.get("/voyage/{voyage_id}")
def voyage_compliance_detail(
    voyage_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """Compliance breakdown for a single voyage."""
    return get_voyage_compliance(db, auth.tenant_id, voyage_id)


@router.post("/calculate/emissions")
def calc_emissions(
    body: EmissionsCalcIn,
    auth: AuthContext = Depends(require_module("operations")),
):
    """Calculate CO2 emissions for given fuel consumption."""
    return calculate_voyage_emissions(
        body.fuel_consumption_mt, body.fuel_type, body.distance_nm, body.cargo_mt
    )


@router.post("/calculate/eu-ets")
def calc_eu_ets(
    body: EuEtsCalcIn,
    auth: AuthContext = Depends(require_module("operations")),
):
    """Calculate EU ETS compliance cost."""
    return calculate_eu_ets_cost(
        body.co2_tonnes, body.voyage_year, body.is_eu_voyage, body.ets_responsibility_pct
    )


@router.post("/calculate/fueleu")
def calc_fueleu(
    body: FuelEuCalcIn,
    auth: AuthContext = Depends(require_module("operations")),
):
    """Calculate FuelEU Maritime compliance."""
    return calculate_fueleu_compliance(
        body.fuel_consumption_mt, body.fuel_type, body.distance_nm, body.cargo_mt, body.year
    )


@router.post("/calculate/cii")
def calc_cii(
    body: CiiCalcIn,
    auth: AuthContext = Depends(require_module("operations")),
):
    """Calculate CII rating."""
    return calculate_cii_rating(body.co2_tonnes, body.distance_nm, body.dwt, body.vessel_type)


@router.get("/fuel-factors")
def list_fuel_factors(
    auth: AuthContext = Depends(require_module("operations")),
):
    """List emission factors for all supported fuel types."""
    from app.services.carbon_calculator import FUEL_FACTORS
    return {
        fuel: {
            "co2_factor_tonnes_per_tonne": f["co2_factor"],
            "energy_density_mj_per_kg": f["energy_density"],
        }
        for fuel, f in FUEL_FACTORS.items()
    }
