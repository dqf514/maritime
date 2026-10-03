"""Vessel detail APIs — 船舶管理明细（DWT/吃水、联系人、航线、拖轮、油舱、装卸、TCE、检验、载重线）.

Closes the vessel-module gap vs IMOS: every tab of the vessel card gets a
tenant-scoped CRUD resource under ``/vessels/{vessel_id}/…`` plus two derived
views (max-lift calculation, full summary). Access goes through
``app.services.tenant_guard`` — foreign tenant ids always 404.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_vessel_ext import (
    LoadlineZone,
    VesselContact,
    VesselPerformance,
    VesselRoute,
    VesselTank,
    VesselTceTarget,
    VesselTug,
    VesselVetting,
)
from app.models_wave1 import Vessel
from app.security import AuthContext, require_module
from app.services.tenant_guard import scoped_get, scoped_query

router = APIRouter(tags=["Vessel Detail"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _vessel_or_404(db: Session, tenant_id: UUID, vessel_id: UUID) -> Vessel:
    v = scoped_get(db, Vessel, vessel_id, tenant_id)
    if not v:
        raise HTTPException(404, "Vessel not found")
    return v


def _num(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


# ─────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────


class DwtDraftTabIn(BaseModel):
    summer_dwt: Decimal | None = None
    tropical_dwt: Decimal | None = None
    winter_dwt: Decimal | None = None
    summer_draft: Decimal | None = None
    tropical_draft: Decimal | None = None
    winter_draft: Decimal | None = None
    lightship: Decimal | None = None
    deadweight_scale: list[dict] | None = None  # [{draft_m, deadweight_mt}]


class VesselTypeDetailIn(BaseModel):
    hull_type: str | None = None
    build_year: int | None = None
    build_yard: str | None = None
    flag_state: str | None = None
    ism_manager: str | None = None
    isps_manager: str | None = None


class ConsumptionDetailIn(BaseModel):
    sea_speed_25: Decimal | None = None
    sea_speed_75: Decimal | None = None
    sea_speed_100: Decimal | None = None
    port_working: Decimal | None = None
    port_idle: Decimal | None = None
    port_maneuvering: Decimal | None = None
    ifo_mdo_ratio: Decimal | None = None


class CapacityIn(BaseModel):
    max_lift_qty: Decimal | None = None
    stowage_factor: Decimal | None = None
    design_speed: Decimal | None = None
    tank_capacity_total: Decimal | None = None


class SpecPatchIn(BaseModel):
    """Flat partial update of all vessel-extension columns (only provided fields are written)."""

    # dwt / draft
    summer_dwt: Decimal | None = None
    tropical_dwt: Decimal | None = None
    winter_dwt: Decimal | None = None
    summer_draft: Decimal | None = None
    tropical_draft: Decimal | None = None
    winter_draft: Decimal | None = None
    lightship: Decimal | None = None
    deadweight_scale: list[dict] | None = None
    # type detail
    hull_type: str | None = None
    build_year: int | None = None
    build_yard: str | None = None
    flag_state: str | None = None
    ism_manager: str | None = None
    isps_manager: str | None = None
    # consumption
    sea_speed_25: Decimal | None = None
    sea_speed_75: Decimal | None = None
    sea_speed_100: Decimal | None = None
    port_working: Decimal | None = None
    port_idle: Decimal | None = None
    port_maneuvering: Decimal | None = None
    ifo_mdo_ratio: Decimal | None = None
    # capacity
    max_lift_qty: Decimal | None = None
    stowage_factor: Decimal | None = None
    design_speed: Decimal | None = None
    tank_capacity_total: Decimal | None = None


class ContactIn(BaseModel):
    contact_role: str = "captain"
    name: str
    email: str | None = None
    phone: str | None = None


class ContactPatchIn(BaseModel):
    contact_role: str | None = None
    name: str | None = None
    email: str | None = None
    phone: str | None = None


class RouteIn(BaseModel):
    route_name: str
    from_area: str | None = None
    to_area: str | None = None
    typical_speed: Decimal | None = None
    distance_nm: Decimal | None = None
    notes: str | None = None


class RoutePatchIn(BaseModel):
    route_name: str | None = None
    from_area: str | None = None
    to_area: str | None = None
    typical_speed: Decimal | None = None
    distance_nm: Decimal | None = None
    notes: str | None = None


class TugIn(BaseModel):
    tug_name: str
    port_id: UUID | None = None
    power_hp: int | None = None
    notes: str | None = None


class TugPatchIn(BaseModel):
    tug_name: str | None = None
    port_id: UUID | None = None
    power_hp: int | None = None
    notes: str | None = None


class TankIn(BaseModel):
    tank_name: str
    tank_type: str = "fuel"
    capacity_mt: Decimal | None = None
    max_fill_pct: Decimal | None = None
    notes: str | None = None


class TankPatchIn(BaseModel):
    tank_name: str | None = None
    tank_type: str | None = None
    capacity_mt: Decimal | None = None
    max_fill_pct: Decimal | None = None
    notes: str | None = None


class PerformanceIn(BaseModel):
    cargo_type: str
    load_rate_mt_hr: Decimal | None = None
    discharge_rate_mt_hr: Decimal | None = None
    stowage_factor: Decimal | None = None
    notes: str | None = None


class PerformancePatchIn(BaseModel):
    cargo_type: str | None = None
    load_rate_mt_hr: Decimal | None = None
    discharge_rate_mt_hr: Decimal | None = None
    stowage_factor: Decimal | None = None
    notes: str | None = None


class TceTargetIn(BaseModel):
    year_month: str = Field(pattern=r"^\d{4}-\d{2}$")
    target_tce_usd: Decimal | None = None
    notes: str | None = None


class TceTargetPatchIn(BaseModel):
    year_month: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    target_tce_usd: Decimal | None = None
    notes: str | None = None


class VettingIn(BaseModel):
    vetting_type: str = "sire"
    vetting_date: date | None = None
    result: str = "pass"
    expiry_date: date | None = None
    inspector: str | None = None
    notes: str | None = None


class VettingPatchIn(BaseModel):
    vetting_type: str | None = None
    vetting_date: date | None = None
    result: str | None = None
    expiry_date: date | None = None
    inspector: str | None = None
    notes: str | None = None


class LoadlineZoneIn(BaseModel):
    zone_name: str = "summer"
    max_draft_m: Decimal | None = None
    valid_from: date | None = None
    valid_to: date | None = None


class LoadlineZonePatchIn(BaseModel):
    zone_name: str | None = None
    max_draft_m: Decimal | None = None
    valid_from: date | None = None
    valid_to: date | None = None


# ─────────────────────────────────────────────────────────────────────
# Generic per-vessel CRUD factory
# ─────────────────────────────────────────────────────────────────────


def _row_out(row: Any, fields: tuple[str, ...]) -> dict:
    out: dict[str, Any] = {"id": str(row.id), "vessel_id": str(row.vessel_id)}
    for f in fields:
        v = getattr(row, f)
        if isinstance(v, Decimal):
            v = float(v)
        elif isinstance(v, (date, datetime)):
            v = v.isoformat()
        elif isinstance(v, uuid.UUID):
            v = str(v)
        out[f] = v
    return out


def _register_crud(
    *,
    path: str,
    model: type,
    in_model: type,
    patch_model: type,
    fields: tuple[str, ...],
    order_by: Any,
    label: str,
) -> None:
    """Register GET/POST/PATCH/DELETE for a vessel child resource."""

    def _serialize(row: Any) -> dict:
        return _row_out(row, fields)

    def list_rows(
        vessel_id: UUID,
        auth: AuthContext = Depends(require_module("masterdata")),
        db: Session = Depends(get_db),
    ) -> list[dict]:
        _vessel_or_404(db, auth.tenant_id, vessel_id)
        rows = db.scalars(
            scoped_query(db, model, auth.tenant_id).where(model.vessel_id == vessel_id).order_by(order_by)
        ).all()
        return [_serialize(r) for r in rows]

    def create_row(
        vessel_id: UUID,
        body: in_model,  # noqa: N803
        auth: AuthContext = Depends(require_module("masterdata")),
        db: Session = Depends(get_db),
    ) -> dict:
        _vessel_or_404(db, auth.tenant_id, vessel_id)
        row = model(tenant_id=auth.tenant_id, vessel_id=vessel_id, **body.model_dump())
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize(row)

    def patch_row(
        vessel_id: UUID,
        row_id: UUID,
        body: patch_model,  # noqa: N803
        auth: AuthContext = Depends(require_module("masterdata")),
        db: Session = Depends(get_db),
    ) -> dict:
        _vessel_or_404(db, auth.tenant_id, vessel_id)
        row = scoped_get(db, model, row_id, auth.tenant_id)
        if not row or row.vessel_id != vessel_id:
            raise HTTPException(404, f"{label} not found")
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(row, k, v)
        row.updated_at = _now()
        db.commit()
        db.refresh(row)
        return _serialize(row)

    def delete_row(
        vessel_id: UUID,
        row_id: UUID,
        auth: AuthContext = Depends(require_module("masterdata")),
        db: Session = Depends(get_db),
    ) -> dict:
        _vessel_or_404(db, auth.tenant_id, vessel_id)
        row = scoped_get(db, model, row_id, auth.tenant_id)
        if not row or row.vessel_id != vessel_id:
            raise HTTPException(404, f"{label} not found")
        db.delete(row)
        db.commit()
        return {"ok": True}

    base = f"/vessels/{{vessel_id}}/{path}"
    list_rows.__name__ = f"list_{path.replace('-', '_')}"
    create_row.__name__ = f"create_{path.replace('-', '_')}"
    patch_row.__name__ = f"patch_{path.replace('-', '_')}"
    delete_row.__name__ = f"delete_{path.replace('-', '_')}"
    router.get(base, name=list_rows.__name__)(list_rows)
    router.post(base, name=create_row.__name__)(create_row)
    router.patch(f"{base}/{{row_id}}", name=patch_row.__name__)(patch_row)
    router.delete(f"{base}/{{row_id}}", name=delete_row.__name__)(delete_row)


_register_crud(
    path="contacts",
    model=VesselContact,
    in_model=ContactIn,
    patch_model=ContactPatchIn,
    fields=("contact_role", "name", "email", "phone"),
    order_by=VesselContact.name,
    label="Contact",
)
_register_crud(
    path="routes",
    model=VesselRoute,
    in_model=RouteIn,
    patch_model=RoutePatchIn,
    fields=("route_name", "from_area", "to_area", "typical_speed", "distance_nm", "notes"),
    order_by=VesselRoute.route_name,
    label="Route",
)
_register_crud(
    path="tugs",
    model=VesselTug,
    in_model=TugIn,
    patch_model=TugPatchIn,
    fields=("tug_name", "port_id", "power_hp", "notes"),
    order_by=VesselTug.tug_name,
    label="Tug",
)
_register_crud(
    path="tanks",
    model=VesselTank,
    in_model=TankIn,
    patch_model=TankPatchIn,
    fields=("tank_name", "tank_type", "capacity_mt", "max_fill_pct", "notes"),
    order_by=VesselTank.tank_name,
    label="Tank",
)
_register_crud(
    path="performance",
    model=VesselPerformance,
    in_model=PerformanceIn,
    patch_model=PerformancePatchIn,
    fields=("cargo_type", "load_rate_mt_hr", "discharge_rate_mt_hr", "stowage_factor", "notes"),
    order_by=VesselPerformance.cargo_type,
    label="Performance",
)
_register_crud(
    path="tce-targets",
    model=VesselTceTarget,
    in_model=TceTargetIn,
    patch_model=TceTargetPatchIn,
    fields=("year_month", "target_tce_usd", "notes"),
    order_by=VesselTceTarget.year_month.desc(),
    label="TCE target",
)
_register_crud(
    path="vettings",
    model=VesselVetting,
    in_model=VettingIn,
    patch_model=VettingPatchIn,
    fields=("vetting_type", "vetting_date", "result", "expiry_date", "inspector", "notes"),
    order_by=VesselVetting.vetting_date.desc(),
    label="Vetting",
)
_register_crud(
    path="loadline-zones",
    model=LoadlineZone,
    in_model=LoadlineZoneIn,
    patch_model=LoadlineZonePatchIn,
    fields=("zone_name", "max_draft_m", "valid_from", "valid_to"),
    order_by=LoadlineZone.zone_name,
    label="Loadline zone",
)


# ─────────────────────────────────────────────────────────────────────
# Spec block (dwt/draft + type + consumption + capacity)
# ─────────────────────────────────────────────────────────────────────

_DWT_DRAFT_FIELDS = (
    "summer_dwt",
    "tropical_dwt",
    "winter_dwt",
    "summer_draft",
    "tropical_draft",
    "winter_draft",
    "lightship",
    "deadweight_scale",
)
_TYPE_FIELDS = ("hull_type", "build_year", "build_yard", "flag_state", "ism_manager", "isps_manager")
_CONSUMPTION_FIELDS = (
    "sea_speed_25",
    "sea_speed_75",
    "sea_speed_100",
    "port_working",
    "port_idle",
    "port_maneuvering",
    "ifo_mdo_ratio",
)
_CAPACITY_FIELDS = ("max_lift_qty", "stowage_factor", "design_speed", "tank_capacity_total")


def _spec_out(v: Vessel) -> dict:
    return {
        "vessel_id": str(v.id),
        "dwt_draft": {f: _num(getattr(v, f)) if f != "deadweight_scale" else getattr(v, f) for f in _DWT_DRAFT_FIELDS},
        "vessel_type_detail": {f: getattr(v, f) for f in _TYPE_FIELDS},
        "consumption_detail": {f: _num(getattr(v, f)) for f in _CONSUMPTION_FIELDS},
        "capacity": {f: _num(getattr(v, f)) for f in _CAPACITY_FIELDS},
    }


@router.get("/vessels/{vessel_id}/dwt-draft")
def get_dwt_draft(
    vessel_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    """Draft / spec details: DWT draft tab, type detail, consumption, capacity."""
    v = _vessel_or_404(db, auth.tenant_id, vessel_id)
    return _spec_out(v)


@router.patch("/vessels/{vessel_id}/dwt-draft")
def patch_dwt_draft(
    vessel_id: UUID,
    body: SpecPatchIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    """Partial update of the vessel spec block — only provided fields are written."""
    v = _vessel_or_404(db, auth.tenant_id, vessel_id)
    for k, val in body.model_dump(exclude_unset=True).items():
        setattr(v, k, val)
    v.updated_at = _now()
    db.commit()
    db.refresh(v)
    return _spec_out(v)


# ─────────────────────────────────────────────────────────────────────
# Max lift calculation
# ─────────────────────────────────────────────────────────────────────


def _interp_deadweight(scale: list[dict] | None, draft: float) -> float | None:
    """Linear interpolation of the deadweight scale at a given draft (m)."""
    pts: list[tuple[float, float]] = []
    for p in scale or []:
        d = p["draft_m"] if "draft_m" in p else None
        w = p["deadweight_mt"] if "deadweight_mt" in p else None
        if d is None or w is None:
            continue
        pts.append((float(d), float(w)))
    pts.sort()
    if not pts:
        return None
    if draft <= pts[0][0]:
        return pts[0][1]
    if draft >= pts[-1][0]:
        return pts[-1][1]
    for (d0, w0), (d1, w1) in zip(pts, pts[1:]):
        if d0 <= draft <= d1:
            if d1 == d0:
                return w1
            return w0 + (w1 - w0) * (draft - d0) / (d1 - d0)
    return pts[-1][1]


@router.get("/vessels/{vessel_id}/max-lift")
def max_lift(
    vessel_id: UUID,
    cargo_type: str | None = Query(default=None),
    draft: float | None = Query(default=None, description="Load-port draft limitation (m)"),
    bunkers_mt: float = Query(default=0),
    stores_mt: float = Query(default=0),
    fresh_water_mt: float = Query(default=0),
    stowage_factor: float | None = Query(default=None, description="Override m3/MT"),
    hold_capacity_cbm: float | None = Query(default=None, description="Override hold capacity (m3)"),
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    """Max cargo lift = min(deadweight, draft-limited DWT, hold volume, gear cap).

    - deadweight: DWT − bunkers − stores − freshwater
    - draft: deadweight at the load-port draft limit (scale curve, else linear
      from summer draft) further clamped by the deepest loadline zone
    - hold volume: hold_capacity_cbm / stowage_factor (cargo_type lookup → vessel default)
    - gear cap: ``max_lift_qty``
    """
    v = _vessel_or_404(db, auth.tenant_id, vessel_id)

    base_dwt = _num(v.summer_dwt) or _num(v.dwt)
    if base_dwt is None:
        raise HTTPException(422, "Vessel has no DWT on file")

    consumables = float(bunkers_mt) + float(stores_mt) + float(fresh_water_mt)
    warnings: list[str] = []

    # — draft limitation —
    draft_limit: float | None = None
    effective_draft: float | None = None
    if draft is not None:
        effective_draft = float(draft)
        zones = db.scalars(
            scoped_query(db, LoadlineZone, auth.tenant_id)
            .where(LoadlineZone.vessel_id == vessel_id, LoadlineZone.max_draft_m.is_not(None))
        ).all()
        if zones:
            zone_cap = max(float(z.max_draft_m) for z in zones)
            if effective_draft > zone_cap:
                warnings.append(
                    f"draft {effective_draft}m exceeds deepest loadline zone {zone_cap}m — clamped"
                )
                effective_draft = zone_cap
        dwt_at_draft = _interp_deadweight(v.deadweight_scale, effective_draft)
        if dwt_at_draft is None:
            summer_draft = _num(v.summer_draft)
            if summer_draft:
                dwt_at_draft = base_dwt * min(effective_draft / summer_draft, 1.0)
            else:
                warnings.append("no deadweight scale or summer draft — draft limitation skipped")
        if dwt_at_draft is not None:
            draft_limit = max(dwt_at_draft - consumables, 0.0)

    deadweight_limit = max(base_dwt - consumables, 0.0)

    # — stowage / hold volume —
    sf = float(stowage_factor) if stowage_factor is not None else None
    if sf is None and cargo_type:
        perf = db.scalar(
            scoped_query(db, VesselPerformance, auth.tenant_id).where(
                VesselPerformance.vessel_id == vessel_id,
                VesselPerformance.cargo_type == cargo_type,
            )
        )
        if perf and perf.stowage_factor is not None:
            sf = float(perf.stowage_factor)
    if sf is None:
        sf = _num(v.stowage_factor)

    hold_cap = float(hold_capacity_cbm) if hold_capacity_cbm is not None else None
    volume_limit: float | None = None
    if hold_cap is not None and sf:
        volume_limit = hold_cap / sf
    elif hold_cap is not None and not sf:
        warnings.append("hold capacity given but no stowage factor — volume limitation skipped")

    gear_limit = _num(v.max_lift_qty)

    candidates: list[tuple[str, float]] = [("deadweight", deadweight_limit)]
    if draft_limit is not None:
        candidates.append(("draft", draft_limit))
    if volume_limit is not None:
        candidates.append(("hold_volume", volume_limit))
    if gear_limit is not None:
        candidates.append(("gear", gear_limit))
    limiting_factor, max_lift_mt = min(candidates, key=lambda kv: kv[1])

    return {
        "vessel_id": str(vessel_id),
        "cargo_type": cargo_type,
        "inputs": {
            "draft_m": effective_draft,
            "bunkers_mt": float(bunkers_mt),
            "stores_mt": float(stores_mt),
            "fresh_water_mt": float(fresh_water_mt),
            "stowage_factor": sf,
            "hold_capacity_cbm": hold_cap,
        },
        "base_dwt_mt": base_dwt,
        "available_deadweight_mt": deadweight_limit,
        "draft_limited_deadweight_mt": draft_limit,
        "hold_volume_limit_mt": volume_limit,
        "gear_limit_mt": gear_limit,
        "max_lift_mt": max_lift_mt,
        "limiting_factor": limiting_factor,
        "cargo_volume_cbm": (max_lift_mt * sf) if sf else None,
        "warnings": warnings,
    }


# ─────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────


@router.get("/vessels/{vessel_id}/summary")
def vessel_summary(
    vessel_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    """Full vessel card — every detail tab aggregated in one payload."""
    v = _vessel_or_404(db, auth.tenant_id, vessel_id)
    tid = auth.tenant_id

    def _all(model: type, order: Any) -> list[dict]:
        rows = db.scalars(
            scoped_query(db, model, tid).where(model.vessel_id == vessel_id).order_by(order)
        ).all()
        fields_by_model: dict[type, tuple[str, ...]] = {
            VesselContact: ("contact_role", "name", "email", "phone"),
            VesselRoute: ("route_name", "from_area", "to_area", "typical_speed", "distance_nm", "notes"),
            VesselTug: ("tug_name", "port_id", "power_hp", "notes"),
            VesselTank: ("tank_name", "tank_type", "capacity_mt", "max_fill_pct", "notes"),
            VesselPerformance: ("cargo_type", "load_rate_mt_hr", "discharge_rate_mt_hr", "stowage_factor", "notes"),
            VesselTceTarget: ("year_month", "target_tce_usd", "notes"),
            VesselVetting: ("vetting_type", "vetting_date", "result", "expiry_date", "inspector", "notes"),
            LoadlineZone: ("zone_name", "max_draft_m", "valid_from", "valid_to"),
        }
        return [_row_out(r, fields_by_model[model]) for r in rows]

    contacts = _all(VesselContact, VesselContact.name)
    routes = _all(VesselRoute, VesselRoute.route_name)
    tugs = _all(VesselTug, VesselTug.tug_name)
    tanks = _all(VesselTank, VesselTank.tank_name)
    performance = _all(VesselPerformance, VesselPerformance.cargo_type)
    tce_targets = _all(VesselTceTarget, VesselTceTarget.year_month.desc())
    vettings = _all(VesselVetting, VesselVetting.vetting_date.desc())
    loadline_zones = _all(LoadlineZone, LoadlineZone.zone_name)

    spec = _spec_out(v)
    return {
        "vessel": {
            "id": str(v.id),
            "name": v.name,
            "imo": v.imo,
            "mmsi": v.mmsi,
            "flag": v.flag,
            "vessel_type": v.vessel_type,
            "dwt": _num(v.dwt),
            "speed_knots": _num(v.speed_knots),
            "consumption_sea": _num(v.consumption_sea),
            "consumption_port": _num(v.consumption_port),
            "status": v.status,
        },
        "spec": spec,
        "contacts": contacts,
        "routes": routes,
        "tugs": tugs,
        "tanks": tanks,
        "performance": performance,
        "tce_targets": tce_targets,
        "vettings": vettings,
        "loadline_zones": loadline_zones,
        "counts": {
            "contacts": len(contacts),
            "routes": len(routes),
            "tugs": len(tugs),
            "tanks": len(tanks),
            "performance": len(performance),
            "tce_targets": len(tce_targets),
            "vettings": len(vettings),
            "loadline_zones": len(loadline_zones),
        },
    }
