"""Fuel zone management service.

Provides zone lookup by position, route transition analysis,
and compliance checking for ECA/EU ETS/FuelEU zones.
"""

from __future__ import annotations

import math
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.models_reference import FuelZone


# ── Point-in-Polygon (Ray Casting) ──


def _point_in_polygon(lat: float, lon: float, polygon: list[list[list[float]]]) -> bool:
    """Check if a point (lat, lon) is inside a GeoJSON polygon.

    Uses ray casting algorithm. Polygon coords are [lon, lat] per GeoJSON spec.
    """
    for ring in polygon:
        n = len(ring)
        if n < 3:
            continue
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = ring[i][0], ring[i][1]  # lon, lat
            xj, yj = ring[j][0], ring[j][1]
            if ((yi > lon) != (yj > lon)) and (
                lat < (xj - xi) * (lon - yi) / (yj - yi) + xi
            ):
                inside = not inside
            j = i
        if inside:
            return True
    return False


def _point_in_zone(lat: float, lon: float, geometry: dict) -> bool:
    """Check if a point is inside a zone's GeoJSON geometry."""
    if not geometry:
        return False
    geom_type = geometry.get("type", "")
    coords = geometry.get("coordinates", [])

    if geom_type == "Polygon":
        return _point_in_polygon(lat, lon, coords)
    elif geom_type == "MultiPolygon":
        return any(_point_in_polygon(lat, lon, poly) for poly in coords)
    return False


# ── Zone Lookup ──


def get_active_zones(db: Session, zone_type: str | None = None) -> list[FuelZone]:
    """Get all active fuel zones."""
    stmt = select(FuelZone).where(FuelZone.is_active.is_(True))
    if zone_type:
        stmt = stmt.where(FuelZone.zone_type == zone_type)
    return list(db.scalars(stmt).all())


def get_zones_at_position(db: Session, lat: float, lon: float) -> list[dict]:
    """Find all fuel zones containing a given position.

    Returns list of matching zones with their properties.
    """
    zones = get_active_zones(db)
    matches = []
    for zone in zones:
        if zone.geometry and _point_in_zone(lat, lon, zone.geometry):
            matches.append({
                "id": str(zone.id),
                "zone_name": zone.zone_name,
                "zone_type": zone.zone_type,
                "fuel_requirements": zone.fuel_requirements,
                "eu_ets_factor": float(zone.eu_ets_factor) if zone.eu_ets_factor else None,
                "fueleu_limit": float(zone.fueleu_limit) if zone.fueleu_limit else None,
            })
    return matches


def get_zone_transitions(
    db: Session, route_points: list[dict]
) -> list[dict]:
    """Analyze fuel zone transitions along a route.

    Input: list of {lat, lon} waypoints along the route.
    Output: list of segments with zone info and transition points.
    """
    if not route_points:
        return []

    zones = get_active_zones(db)
    segments = []
    current_zones = set()

    for i, point in enumerate(route_points):
        lat, lon = point.get("lat"), point.get("lon")
        if lat is None or lon is None:
            continue

        point_zones = set()
        for zone in zones:
            if zone.geometry and _point_in_zone(lat, lon, zone.geometry):
                point_zones.add(zone.id)

        entered = point_zones - current_zones
        exited = current_zones - point_zones

        if entered or exited or i == 0:
            segment = {
                "waypoint_index": i,
                "lat": lat,
                "lon": lon,
                "zones_entered": [str(z) for z in entered],
                "zones_exited": [str(z) for z in exited],
                "active_zones": [str(z) for z in point_zones],
            }
            # Enrich with zone details
            zone_details = []
            for zone in zones:
                if zone.id in point_zones:
                    zone_details.append({
                        "id": str(zone.id),
                        "zone_name": zone.zone_name,
                        "zone_type": zone.zone_type,
                        "fuel_requirements": zone.fuel_requirements,
                    })
            segment["zone_details"] = zone_details
            segments.append(segment)

        current_zones = point_zones

    return segments


def check_fuel_compliance(
    db: Session,
    lat: float,
    lon: float,
    fuel_type: str,
    sulfur_pct: float | None = None,
) -> dict:
    """Check if current fuel meets zone requirements at a position.

    Returns compliance status and any violations.
    """
    zones = get_zones_at_position(db, lat, lon)
    violations = []

    for zone in zones:
        reqs = zone.get("fuel_requirements") or {}
        if "sulfur_max" in reqs and sulfur_pct is not None:
            if sulfur_pct > reqs["sulfur_max"]:
                violations.append(
                    f"Zone '{zone['zone_name']}': sulfur {sulfur_pct}% exceeds max {reqs['sulfur_max']}%"
                )
        if "fuel_type" in reqs:
            allowed = reqs["fuel_type"]
            if isinstance(allowed, list):
                if fuel_type not in allowed:
                    violations.append(
                        f"Zone '{zone['zone_name']}': fuel type '{fuel_type}' not in allowed {allowed}"
                    )
            elif fuel_type != allowed:
                violations.append(
                    f"Zone '{zone['zone_name']}': fuel type '{fuel_type}' not allowed (requires {allowed})"
                )

    return {
        "lat": lat,
        "lon": lon,
        "zones": zones,
        "fuel_type": fuel_type,
        "sulfur_pct": sulfur_pct,
        "compliant": len(violations) == 0,
        "violations": violations,
    }


# ── Zone CRUD ──


def create_zone(
    db: Session,
    zone_name: str,
    zone_type: str,
    geometry: dict | None = None,
    fuel_requirements: dict | None = None,
    eu_ets_factor: float | None = None,
    fueleu_limit: float | None = None,
    effective_from: str | None = None,
    effective_to: str | None = None,
    description: str | None = None,
) -> FuelZone:
    """Create a new fuel zone."""
    zone = FuelZone(
        zone_name=zone_name,
        zone_type=zone_type,
        geometry=geometry,
        fuel_requirements=fuel_requirements,
        eu_ets_factor=Decimal(str(eu_ets_factor)) if eu_ets_factor else None,
        fueleu_limit=Decimal(str(fueleu_limit)) if fueleu_limit else None,
        effective_from=effective_from,
        effective_to=effective_to,
        description=description,
    )
    db.add(zone)
    db.commit()
    db.refresh(zone)
    return zone


def get_zone(db: Session, zone_id: UUID) -> FuelZone | None:
    """Get a fuel zone by ID."""
    return db.get(FuelZone, zone_id)


def list_zones(db: Session, zone_type: str | None = None) -> list[FuelZone]:
    """List all fuel zones."""
    stmt = select(FuelZone)
    if zone_type:
        stmt = stmt.where(FuelZone.zone_type == zone_type)
    return list(db.scalars(stmt).all())


# ── Preset zones ──

BALTIC_ECA_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[
        [10.0, 54.0], [25.0, 54.0], [30.0, 60.0], [30.0, 66.0],
        [20.0, 66.0], [10.0, 60.0], [10.0, 54.0]
    ]],
}

NORTH_SEA_ECA_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[
        [-5.0, 48.0], [10.0, 48.0], [10.0, 54.0], [8.0, 62.0],
        [-5.0, 62.0], [-5.0, 48.0]
    ]],
}

EU_ETS_GEOMETRY = {
    "type": "MultiPolygon",
    "coordinates": [
        [[[-10.0, 35.0], [35.0, 35.0], [35.0, 72.0], [-10.0, 72.0], [-10.0, 35.0]]],
    ],
}


def seed_preset_zones(db: Session):
    """Seed preset fuel zones (Baltic ECA, North Sea ECA, EU ETS)."""
    presets = [
        {
            "zone_name": "Baltic Sea ECA",
            "zone_type": "eca",
            "geometry": BALTIC_ECA_GEOMETRY,
            "fuel_requirements": {"sulfur_max": 0.1, "fuel_type": "MGO"},
            "description": "Baltic Sea Emission Control Area — 0.1% sulfur limit",
        },
        {
            "zone_name": "North Sea ECA",
            "zone_type": "eca",
            "geometry": NORTH_SEA_ECA_GEOMETRY,
            "fuel_requirements": {"sulfur_max": 0.1, "fuel_type": "MGO"},
            "description": "North Sea Emission Control Area — 0.1% sulfur limit",
        },
        {
            "zone_name": "EU ETS Zone",
            "zone_type": "eu_ets",
            "geometry": EU_ETS_GEOMETRY,
            "eu_ets_factor": 80.0,  # EUR/tCO2 approximate
            "description": "EU Emissions Trading System — covers EU/EEA waters",
        },
    ]

    for preset in presets:
        existing = db.scalars(
            select(FuelZone).where(FuelZone.zone_name == preset["zone_name"])
        ).first()
        if not existing:
            create_zone(db, **preset)
