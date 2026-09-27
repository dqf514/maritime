"""ETA 监控（Phase 2 / D7）：午报 ETA 偏差看板 + 延误预警。

数据源走 ais_adapter 的 AisProvider 接口（默认午报内建源）。
``eta_deviation_hours`` 为午报自带的偏差字段（+ = 预计延误）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import Voyage
from app.services.ais_adapter import NoonAisProvider, default_provider


def eta_watch(
    db: Session,
    tenant_id: Any,
    *,
    deviation_threshold_h: float = 12.0,
    voyage_ids: list[str] | None = None,
) -> dict[str, Any]:
    provider = default_provider()
    positions = (
        provider.positions_from_db(db, tenant_id, voyage_ids)
        if isinstance(provider, NoonAisProvider)
        else provider.get_positions(tenant_id, voyage_ids)
    )
    open_voyages = {
        str(v.id): v
        for v in db.scalars(
            select(Voyage).where(Voyage.tenant_id == tenant_id, Voyage.status.in_(["planned", "in_progress"]))
        ).all()
    }
    items = []
    alerts = []
    for pos in positions:
        if pos.voyage_id not in open_voyages:
            continue
        dev = pos.eta_deviation_hours
        item = {
            "voyage_id": pos.voyage_id,
            "vessel_id": pos.vessel_id,
            "observed_at": pos.observed_at.isoformat(),
            "lat": pos.lat,
            "lon": pos.lon,
            "speed_kn": pos.speed_kn,
            "eta_next": pos.eta_next.isoformat() if pos.eta_next else None,
            "eta_deviation_hours": dev,
            "source": pos.source,
        }
        items.append(item)
        if dev is not None and abs(dev) >= deviation_threshold_h:
            alerts.append({**item, "severity": "critical" if dev >= deviation_threshold_h * 2 else "warning"})
    return {
        "threshold_hours": deviation_threshold_h,
        "items": items,
        "alerts": sorted(alerts, key=lambda a: -(a["eta_deviation_hours"] or 0)),
    }
