"""参考数据 API：下拉消费 + 管理员克隆/自定义。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.security import AuthContext, get_current_auth, require_module
from app.services import reference_data as refsvc

router = APIRouter(prefix="/reference", tags=["Reference Data"])


def _locale(auth: AuthContext, locale: str | None) -> str:
    if locale:
        return locale
    user_loc = getattr(auth.user, "locale", None)
    return user_loc or "zh-CN"


def _require_admin(auth: AuthContext) -> None:
    if "tenant_admin" not in auth.roles and "platform_admin" not in auth.roles:
        raise HTTPException(403, detail={"code": "ADMIN_REQUIRED", "message": "需要租户管理员"})


@router.get("/datasets")
def get_datasets(
    locale: str | None = None,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    return refsvc.list_datasets(db, auth.tenant_id, _locale(auth, locale))


@router.get("/{dataset_code}/items")
def get_items(
    dataset_code: str,
    q: str | None = None,
    locale: str | None = None,
    active_only: bool = Query(True),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    return refsvc.list_items(
        db,
        auth.tenant_id,
        dataset_code,
        locale=_locale(auth, locale),
        q=q,
        active_only=active_only,
        admin=False,
    )


@router.get("/{dataset_code}/admin/items")
def admin_items(
    dataset_code: str,
    q: str | None = None,
    locale: str | None = None,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_admin(auth)
    return refsvc.list_items(
        db,
        auth.tenant_id,
        dataset_code,
        locale=_locale(auth, locale),
        q=q,
        active_only=False,
        admin=True,
    )


@router.post("/{dataset_code}/clone")
def clone_dataset(
    dataset_code: str,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_admin(auth)
    try:
        result = refsvc.clone_dataset(db, auth.tenant_id, dataset_code)
    except ValueError as e:
        raise HTTPException(404 if str(e) == "DATASET_NOT_FOUND" else 400, detail={"code": str(e)})
    db.commit()
    return result


@router.post("/{dataset_code}/reset")
def reset_dataset(
    dataset_code: str,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_admin(auth)
    result = refsvc.reset_dataset(db, auth.tenant_id, dataset_code)
    db.commit()
    return result


class ModeIn(BaseModel):
    mode: str = Field(pattern="^(system|local)$")


@router.post("/{dataset_code}/mode")
def set_mode(
    dataset_code: str,
    body: ModeIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_admin(auth)
    try:
        result = refsvc.set_mode(db, auth.tenant_id, dataset_code, body.mode)
    except ValueError as e:
        raise HTTPException(400, detail={"code": str(e)})
    db.commit()
    return result


class ItemIn(BaseModel):
    code: str
    label_en: str
    label_zh: str
    sort_order: int = 0
    active: bool = True
    meta: dict = Field(default_factory=dict)


class ItemPatch(BaseModel):
    code: str | None = None
    label_en: str | None = None
    label_zh: str | None = None
    sort_order: int | None = None
    active: bool | None = None
    meta: dict | None = None


@router.post("/{dataset_code}/items")
def create_item(
    dataset_code: str,
    body: ItemIn,
    locale: str | None = None,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_admin(auth)
    try:
        row = refsvc.create_item(
            db,
            auth.tenant_id,
            dataset_code,
            code=body.code,
            label_en=body.label_en,
            label_zh=body.label_zh,
            sort_order=body.sort_order,
            meta=body.meta,
            active=body.active,
        )
    except ValueError as e:
        raise HTTPException(409 if str(e) == "CODE_EXISTS" else 400, detail={"code": str(e)})
    db.commit()
    db.refresh(row)
    return refsvc._serialize(row, _locale(auth, locale))


@router.patch("/items/{item_id}")
def patch_item(
    item_id: UUID,
    body: ItemPatch,
    locale: str | None = None,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_admin(auth)
    try:
        row = refsvc.update_item(
            db,
            auth.tenant_id,
            item_id,
            code=body.code,
            label_en=body.label_en,
            label_zh=body.label_zh,
            sort_order=body.sort_order,
            active=body.active,
            meta=body.meta,
        )
    except ValueError as e:
        code = str(e)
        raise HTTPException(404 if "NOT_FOUND" in code else 409, detail={"code": code})
    db.commit()
    db.refresh(row)
    return refsvc._serialize(row, _locale(auth, locale))


@router.delete("/items/{item_id}")
def remove_item(
    item_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_admin(auth)
    try:
        refsvc.delete_item(db, auth.tenant_id, item_id)
    except ValueError as e:
        raise HTTPException(404, detail={"code": str(e)})
    db.commit()
    return {"ok": True}


# ── Port Reference Data (Phase 4) ──

from app.services import port_reference as port_ref
from app.models_reference import PortHoliday, PortRate, PortRestriction


class HolidayOut(BaseModel):
    id: str
    port_unlocode: str
    country: str
    holiday_date: str
    holiday_name: str
    holiday_type: str
    recurring: bool


class HolidayIn(BaseModel):
    port_unlocode: str
    country: str
    holiday_date: str
    holiday_name: str
    holiday_type: str = "public"
    recurring: bool = False


@router.get("/ports/holidays")
def list_port_holidays(
    port_unlocode: str | None = Query(None),
    country: str | None = Query(None),
    year: int | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """List port holidays."""
    holidays = port_ref.get_port_holidays(db, port_unlocode, country, year)
    return [
        HolidayOut(
            id=str(h.id),
            port_unlocode=h.port_unlocode,
            country=h.country,
            holiday_date=h.holiday_date,
            holiday_name=h.holiday_name,
            holiday_type=h.holiday_type,
            recurring=h.recurring,
        )
        for h in holidays
    ]


@router.post("/ports/holidays", status_code=201)
def add_port_holiday(
    body: HolidayIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    """Add a port holiday."""
    holiday = port_ref.add_holiday(
        db,
        port_unlocode=body.port_unlocode,
        country=body.country,
        holiday_date=body.holiday_date,
        holiday_name=body.holiday_name,
        holiday_type=body.holiday_type,
        recurring=body.recurring,
    )
    return HolidayOut(
        id=str(holiday.id),
        port_unlocode=holiday.port_unlocode,
        country=holiday.country,
        holiday_date=holiday.holiday_date,
        holiday_name=holiday.holiday_name,
        holiday_type=holiday.holiday_type,
        recurring=holiday.recurring,
    )


@router.get("/ports/{port_unlocode}/is-holiday")
def check_port_holiday(
    port_unlocode: str,
    date: str = Query(..., description="YYYY-MM-DD"),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """Check if a date is a holiday at a port."""
    from datetime import date as date_type
    check = date_type.fromisoformat(date)
    is_hol, name = port_ref.is_holiday(db, port_unlocode, check)
    return {"port_unlocode": port_unlocode, "date": date, "is_holiday": is_hol, "holiday_name": name}


class PortRateOut(BaseModel):
    id: str
    port_unlocode: str
    rate_type: str
    vessel_size_band: str
    amount_usd: float
    currency: str
    basis: str
    source: str
    notes: str | None


class PortRateIn(BaseModel):
    port_unlocode: str
    rate_type: str
    amount_usd: float
    vessel_size_band: str = "medium"
    currency: str = "USD"
    basis: str = "per_call"
    effective_from: str | None = None
    source: str = "manual"
    notes: str | None = None


@router.get("/ports/rates")
def list_port_rates(
    port_unlocode: str = Query(...),
    rate_type: str | None = Query(None),
    vessel_size_band: str = Query("medium"),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """List port rate reference data."""
    from decimal import Decimal
    rates = port_ref.get_port_rates(db, port_unlocode, rate_type, vessel_size_band)
    return [
        PortRateOut(
            id=str(r.id),
            port_unlocode=r.port_unlocode,
            rate_type=r.rate_type,
            vessel_size_band=r.vessel_size_band,
            amount_usd=float(r.amount_usd),
            currency=r.currency,
            basis=r.basis,
            source=r.source,
            notes=r.notes,
        )
        for r in rates
    ]


@router.post("/ports/rates", status_code=201)
def add_port_rate(
    body: PortRateIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    """Add or update a port rate."""
    from decimal import Decimal
    rate = port_ref.add_port_rate(
        db,
        port_unlocode=body.port_unlocode,
        rate_type=body.rate_type,
        amount_usd=Decimal(str(body.amount_usd)),
        vessel_size_band=body.vessel_size_band,
        currency=body.currency,
        basis=body.basis,
        effective_from=body.effective_from,
        source=body.source,
        notes=body.notes,
    )
    return PortRateOut(
        id=str(rate.id),
        port_unlocode=rate.port_unlocode,
        rate_type=rate.rate_type,
        vessel_size_band=rate.vessel_size_band,
        amount_usd=float(rate.amount_usd),
        currency=rate.currency,
        basis=rate.basis,
        source=rate.source,
        notes=rate.notes,
    )


@router.get("/ports/{port_unlocode}/estimate-costs")
def estimate_port_costs(
    port_unlocode: str,
    vessel_size_band: str = Query("medium"),
    days: int = Query(1, ge=1),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """Estimate total port costs for a call."""
    return port_ref.estimate_port_costs(db, port_unlocode, vessel_size_band, days)


class RestrictionOut(BaseModel):
    port_unlocode: str
    max_draft_m: float | None
    max_loa_m: float | None
    max_beam_m: float | None
    max_dwt: float | None
    berth_types: list | None
    cargo_types: list | None
    working_hours: str | None
    night_work_allowed: bool
    sunday_work_allowed: bool
    requires_pilot: bool
    other_restrictions: str | None


class RestrictionIn(BaseModel):
    port_unlocode: str
    max_draft_m: float | None = None
    max_loa_m: float | None = None
    max_beam_m: float | None = None
    max_dwt: float | None = None
    berth_types: list | None = None
    cargo_types: list | None = None
    working_hours: str | None = None
    night_work_allowed: bool = True
    sunday_work_allowed: bool = False
    requires_pilot: bool = True
    other_restrictions: str | None = None


@router.get("/ports/{port_unlocode}/restrictions", response_model=RestrictionOut | None)
def get_port_restrictions(
    port_unlocode: str,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """Get port restrictions."""
    r = port_ref.get_port_restrictions(db, port_unlocode)
    if not r:
        return None
    return RestrictionOut(
        port_unlocode=r.port_unlocode,
        max_draft_m=float(r.max_draft_m) if r.max_draft_m else None,
        max_loa_m=float(r.max_loa_m) if r.max_loa_m else None,
        max_beam_m=float(r.max_beam_m) if r.max_beam_m else None,
        max_dwt=float(r.max_dwt) if r.max_dwt else None,
        berth_types=r.berth_types,
        cargo_types=r.cargo_types,
        working_hours=r.working_hours,
        night_work_allowed=r.night_work_allowed,
        sunday_work_allowed=r.sunday_work_allowed,
        requires_pilot=r.requires_pilot,
        other_restrictions=r.other_restrictions,
    )


@router.post("/ports/restrictions")
def set_port_restrictions(
    body: RestrictionIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    """Create or update port restrictions."""
    r = port_ref.set_port_restrictions(
        db,
        port_unlocode=body.port_unlocode,
        max_draft_m=body.max_draft_m,
        max_loa_m=body.max_loa_m,
        max_beam_m=body.max_beam_m,
        max_dwt=body.max_dwt,
        berth_types=body.berth_types,
        cargo_types=body.cargo_types,
        working_hours=body.working_hours,
        night_work_allowed=body.night_work_allowed,
        sunday_work_allowed=body.sunday_work_allowed,
        requires_pilot=body.requires_pilot,
        other_restrictions=body.other_restrictions,
    )
    return RestrictionOut(
        port_unlocode=r.port_unlocode,
        max_draft_m=float(r.max_draft_m) if r.max_draft_m else None,
        max_loa_m=float(r.max_loa_m) if r.max_loa_m else None,
        max_beam_m=float(r.max_beam_m) if r.max_beam_m else None,
        max_dwt=float(r.max_dwt) if r.max_dwt else None,
        berth_types=r.berth_types,
        cargo_types=r.cargo_types,
        working_hours=r.working_hours,
        night_work_allowed=r.night_work_allowed,
        sunday_work_allowed=r.sunday_work_allowed,
        requires_pilot=r.requires_pilot,
        other_restrictions=r.other_restrictions,
    )


@router.get("/ports/{port_unlocode}/vessel-check")
def check_vessel_port_compatibility(
    port_unlocode: str,
    draft_m: float = Query(...),
    loa_m: float = Query(...),
    dwt: float = Query(...),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """Check if a vessel can call at a port based on restrictions."""
    return port_ref.check_vessel_compatibility(db, port_unlocode, draft_m, loa_m, dwt)


# ── Fuel Zone Management (Phase 4) ──

from app.services import fuel_zone_service as fz_svc
from app.models_reference import FuelZone


class FuelZoneOut(BaseModel):
    id: str
    zone_name: str
    zone_type: str
    geometry: dict | None
    fuel_requirements: dict | None
    eu_ets_factor: float | None
    fueleu_limit: float | None
    is_active: bool
    effective_from: str | None
    effective_to: str | None


class FuelZoneIn(BaseModel):
    zone_name: str
    zone_type: str
    geometry: dict | None = None
    fuel_requirements: dict | None = None
    eu_ets_factor: float | None = None
    fueleu_limit: float | None = None
    is_active: bool = True
    effective_from: str | None = None
    effective_to: str | None = None


@router.get("/fuel-zones")
def list_fuel_zones(
    zone_type: str | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """List all fuel zones."""
    zones = fz_svc.list_zones(db, zone_type)
    return [
        FuelZoneOut(
            id=str(z.id),
            zone_name=z.zone_name,
            zone_type=z.zone_type,
            geometry=z.geometry,
            fuel_requirements=z.fuel_requirements,
            eu_ets_factor=float(z.eu_ets_factor) if z.eu_ets_factor else None,
            fueleu_limit=float(z.fueleu_limit) if z.fueleu_limit else None,
            is_active=z.is_active,
            effective_from=z.effective_from,
            effective_to=z.effective_to,
        )
        for z in zones
    ]


@router.post("/fuel-zones", status_code=201)
def create_fuel_zone(
    body: FuelZoneIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    """Create a fuel zone."""
    zone = fz_svc.create_zone(
        db,
        zone_name=body.zone_name,
        zone_type=body.zone_type,
        geometry=body.geometry,
        fuel_requirements=body.fuel_requirements,
        eu_ets_factor=body.eu_ets_factor,
        fueleu_limit=body.fueleu_limit,
        effective_from=body.effective_from,
        effective_to=body.effective_to,
    )
    return FuelZoneOut(
        id=str(zone.id),
        zone_name=zone.zone_name,
        zone_type=zone.zone_type,
        geometry=zone.geometry,
        fuel_requirements=zone.fuel_requirements,
        eu_ets_factor=float(zone.eu_ets_factor) if zone.eu_ets_factor else None,
        fueleu_limit=float(zone.fueleu_limit) if zone.fueleu_limit else None,
        is_active=zone.is_active,
        effective_from=zone.effective_from,
        effective_to=zone.effective_to,
    )


@router.get("/fuel-zones/position")
def zones_at_position(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """Find fuel zones at a given position."""
    return {"lat": lat, "lon": lon, "zones": fz_svc.get_zones_at_position(db, lat, lon)}


class RoutePointIn(BaseModel):
    lat: float
    lon: float


class RouteAnalysisIn(BaseModel):
    waypoints: list[RoutePointIn]


@router.post("/fuel-zones/route-transitions")
def analyze_route_transitions(
    body: RouteAnalysisIn,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """Analyze fuel zone transitions along a route."""
    points = [{"lat": wp.lat, "lon": wp.lon} for wp in body.waypoints]
    return {"waypoints_count": len(points), "transitions": fz_svc.get_zone_transitions(db, points)}


@router.get("/fuel-zones/compliance")
def check_fuel_zone_compliance(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    fuel_type: str = Query(...),
    sulfur_pct: float | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """Check fuel compliance at a position."""
    return fz_svc.check_fuel_compliance(db, lat, lon, fuel_type, sulfur_pct)


@router.post("/fuel-zones/seed-presets")
def seed_fuel_zone_presets(
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    """Seed preset fuel zones (Baltic ECA, North Sea ECA, EU ETS)."""
    return fz_svc.seed_preset_zones(db)
