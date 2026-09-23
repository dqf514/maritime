"""Port-to-port distance lookup and multi-leg route calculation."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models_reference import PortDistance

_D = Decimal
_ZERO = _D("0")


def _f(val) -> _D:
    if val is None:
        return _ZERO
    return _D(str(val))


def get_distance(
    db: Session,
    from_port: str,
    to_port: str,
    route_preference: Literal["shortest", "canal", "cape"] = "shortest",
) -> dict | None:
    """Look up the distance between two ports.

    Returns the best matching route or None if no route exists.
    """
    from_code = from_port.upper()
    to_code = to_port.upper()

    rows = db.scalars(
        select(PortDistance).where(
            PortDistance.from_port_unlocode == from_code,
            PortDistance.to_port_unlocode == to_code,
        )
    ).all()

    if not rows:
        rev = db.scalars(
            select(PortDistance).where(
                PortDistance.from_port_unlocode == to_code,
                PortDistance.to_port_unlocode == from_code,
            )
        ).all()
        rows = rev

    if not rows:
        return None

    if route_preference == "canal":
        canal = [r for r in rows if r.route_type == "canal"]
        if canal:
            return _format(canal[0])
    elif route_preference == "cape":
        cape = [r for r in rows if r.route_type == "cape"]
        if cape:
            return _format(cape[0])

    best = min(rows, key=lambda r: _f(r.distance_nm))
    return _format(best)


def get_route(
    db: Session,
    port_sequence: list[str],
    route_preference: Literal["shortest", "canal", "cape"] = "shortest",
) -> dict:
    """Calculate total distance for a multi-leg voyage.

    port_sequence: ["CNSHA", "SGSIN", "JPTYO"] → legs CNSHA→SGSIN, SGSIN→JPTYO.
    """
    legs: list[dict] = []
    total_nm = _ZERO
    all_found = True

    for i in range(len(port_sequence) - 1):
        leg = get_distance(db, port_sequence[i], port_sequence[i + 1], route_preference)
        if leg:
            legs.append(leg)
            total_nm += _f(leg["distance_nm"])
        else:
            all_found = False
            legs.append({
                "from": port_sequence[i],
                "to": port_sequence[i + 1],
                "distance_nm": None,
                "route_type": None,
                "status": "not_found",
            })

    return {
        "ports": port_sequence,
        "legs": legs,
        "total_distance_nm": float(total_nm) if all_found else None,
        "all_legs_found": all_found,
        "leg_count": len(legs),
    }


def _format(row: PortDistance) -> dict:
    return {
        "from": row.from_port_unlocode,
        "to": row.to_port_unlocode,
        "distance_nm": float(_f(row.distance_nm)),
        "route_type": row.route_type,
        "canal_transit": row.canal_transit,
        "canal_toll": float(_f(row.canal_toll)) if row.canal_toll else None,
        "transit_days": float(_f(row.transit_days)) if row.transit_days else None,
    }
