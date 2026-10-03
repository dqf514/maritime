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
            # Ray cast in +lon direction at the query latitude (py=lat, px=lon).
            if ((yi > lat) != (yj > lat)) and (
                lon < (xj - xi) * (lat - yi) / (yj - yi) + xi
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

# 中国沿海船舶排放控制区（长三角/珠三角/环渤海，2019-01-01 起实施，0.1% 硫限值
# —— 2019 为 0.5% 过渡限值，2020 起全区 0.1%）。几何为示意多边形（覆盖核心水域）。
CHINA_YANGTZE_ECA_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[
        [118.0, 27.0], [123.5, 27.0], [123.5, 33.5], [118.0, 33.5], [118.0, 27.0]
    ]],
}

CHINA_PEARL_RIVER_ECA_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[
        [110.0, 20.0], [117.5, 20.0], [117.5, 24.5], [110.0, 24.5], [110.0, 20.0]
    ]],
}

CHINA_BOHAI_ECA_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[
        [117.0, 37.0], [122.5, 37.0], [122.5, 41.0], [117.0, 41.0], [117.0, 37.0]
    ]],
}

# 台湾海域排放控制区（ECA）——示意多边形，覆盖台湾本岛周边水域。
TAIWAN_ECA_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[
        [118.0, 20.5], [123.5, 20.5], [123.5, 26.5], [118.0, 26.5], [118.0, 20.5]
    ]],
}

EU_ETS_GEOMETRY = {
    "type": "MultiPolygon",
    "coordinates": [
        [[[-10.0, 35.0], [35.0, 35.0], [35.0, 72.0], [-10.0, 72.0], [-10.0, 35.0]]],
    ],
}

# IMO 2020 全球硫限值（MARPOL Annex VI Reg. 14）：0.50% m/m 全球上限，
# ECA 内仍为 0.10%（2015-01-01 起）。
IMO2020_GLOBAL_SULFUR_CAP = 0.50
ECA_SULFUR_CAP = 0.10

# ECA 预置（纯函数检测用，与 seed_preset_zones 同源）
PRESET_ECA_ZONES = [
    {
        "zone_name": "Baltic Sea ECA",
        "zone_type": "eca",
        "geometry": BALTIC_ECA_GEOMETRY,
        "fuel_requirements": {"sulfur_max": ECA_SULFUR_CAP, "fuel_type": "MGO"},
        "effective_from": "2010-07-01",
        "description": "Baltic Sea Emission Control Area — 0.1% sulfur limit",
    },
    {
        "zone_name": "North Sea ECA",
        "zone_type": "eca",
        "geometry": NORTH_SEA_ECA_GEOMETRY,
        "fuel_requirements": {"sulfur_max": ECA_SULFUR_CAP, "fuel_type": "MGO"},
        "effective_from": "2007-11-22",
        "description": "North Sea Emission Control Area — 0.1% sulfur limit",
    },
    {
        "zone_name": "China Yangtze River Delta ECA",
        "zone_type": "eca",
        "geometry": CHINA_YANGTZE_ECA_GEOMETRY,
        "fuel_requirements": {"sulfur_max": ECA_SULFUR_CAP},
        "effective_from": "2019-01-01",
        "description": "中国长三角船舶排放控制区（2019-01-01 生效，2020 起 0.1% 硫限值）",
    },
    {
        "zone_name": "China Pearl River Delta ECA",
        "zone_type": "eca",
        "geometry": CHINA_PEARL_RIVER_ECA_GEOMETRY,
        "fuel_requirements": {"sulfur_max": ECA_SULFUR_CAP},
        "effective_from": "2019-01-01",
        "description": "中国珠三角船舶排放控制区（2019-01-01 生效，2020 起 0.1% 硫限值）",
    },
    {
        "zone_name": "China Bohai Rim ECA",
        "zone_type": "eca",
        "geometry": CHINA_BOHAI_ECA_GEOMETRY,
        "fuel_requirements": {"sulfur_max": ECA_SULFUR_CAP},
        "effective_from": "2019-01-01",
        "description": "中国环渤海船舶排放控制区（2019-01-01 生效，2020 起 0.1% 硫限值）",
    },
    {
        "zone_name": "Taiwan ECA",
        "zone_type": "eca",
        "geometry": TAIWAN_ECA_GEOMETRY,
        "fuel_requirements": {"sulfur_max": ECA_SULFUR_CAP},
        "effective_from": "2019-01-01",
        "description": "台湾海域排放控制区 (Taiwan ECA) — 0.1% sulfur limit",
    },
]


def preset_eca_matches(lat: float, lon: float) -> list[dict]:
    """Pure (DB-free) preset ECA lookup — used by IMO 2020 / SOx compliance checks."""
    matches = []
    for zone in PRESET_ECA_ZONES:
        if _point_in_zone(lat, lon, zone.get("geometry") or {}):
            matches.append(
                {
                    "zone_name": zone["zone_name"],
                    "zone_type": zone["zone_type"],
                    "fuel_requirements": zone.get("fuel_requirements") or {},
                    "effective_from": zone.get("effective_from"),
                }
            )
    return matches


def route_eca_matches(route_points: list[dict]) -> list[dict]:
    """ECA detection along a route: [{lat, lon}, ...] → per-point matched zones.

    Combines preset zones (always) with DB-defined zones (when present in the
    geometry library — pass points through get_zones_at_position for DB-only).
    """
    out: list[dict] = []
    for i, point in enumerate(route_points or []):
        lat, lon = point.get("lat"), point.get("lon")
        if lat is None or lon is None:
            continue
        zones = preset_eca_matches(float(lat), float(lon))
        out.append(
            {
                "index": i,
                "lat": float(lat),
                "lon": float(lon),
                "in_eca": bool(zones),
                "zones": zones,
            }
        )
    return out


def seed_preset_zones(db: Session):
    """Seed preset fuel zones (IMO/China/Taiwan ECAs + EU ETS)."""
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
            "zone_name": "China Yangtze River Delta ECA",
            "zone_type": "eca",
            "geometry": CHINA_YANGTZE_ECA_GEOMETRY,
            "fuel_requirements": {"sulfur_max": 0.1},
            "effective_from": "2019-01-01",
            "description": "中国长三角船舶排放控制区（2019-01-01 生效）— 0.1% sulfur limit",
        },
        {
            "zone_name": "China Pearl River Delta ECA",
            "zone_type": "eca",
            "geometry": CHINA_PEARL_RIVER_ECA_GEOMETRY,
            "fuel_requirements": {"sulfur_max": 0.1},
            "effective_from": "2019-01-01",
            "description": "中国珠三角船舶排放控制区（2019-01-01 生效）— 0.1% sulfur limit",
        },
        {
            "zone_name": "China Bohai Rim ECA",
            "zone_type": "eca",
            "geometry": CHINA_BOHAI_ECA_GEOMETRY,
            "fuel_requirements": {"sulfur_max": 0.1},
            "effective_from": "2019-01-01",
            "description": "中国环渤海船舶排放控制区（2019-01-01 生效）— 0.1% sulfur limit",
        },
        {
            "zone_name": "Taiwan ECA",
            "zone_type": "eca",
            "geometry": TAIWAN_ECA_GEOMETRY,
            "fuel_requirements": {"sulfur_max": 0.1},
            "effective_from": "2019-01-01",
            "description": "台湾海域排放控制区 (Taiwan ECA) — 0.1% sulfur limit",
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
