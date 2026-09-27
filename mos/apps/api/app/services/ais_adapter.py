"""AIS 数据源适配层（Phase 2 / D7）。

提供统一 ``AisProvider`` 接口，两个实现：

- :class:`NoonAisProvider` —— 内建数据源：从午报推算船位/航速/ETA
  （无外部依赖，永远可用）；
- :class:`HttpAisProvider` —— 外部 AIS 供应商接入位（配置 `ais_base_url` +
  `ais_api_key` 后启用；未配置时 :meth:`get_positions` 抛配置错误）。

业务层（eta_service）只依赖接口，未来换供应商不动业务代码。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import NoonReport, Voyage


@dataclass
class VesselPosition:
    voyage_id: str | None
    vessel_id: str | None
    observed_at: datetime
    lat: float | None
    lon: float | None
    speed_kn: float | None
    eta_next: datetime | None
    eta_deviation_hours: float | None
    source: str


class AisProvider(Protocol):
    def get_positions(self, tenant_id: Any, voyage_ids: list[str] | None = None) -> list[VesselPosition]: ...


class NoonAisProvider:
    """午报内建源：每个航次取最新一条午报作为船位快照。"""

    source = "noon"

    def get_positions(self, tenant_id: Any, voyage_ids: list[str] | None = None) -> list[VesselPosition]:
        raise RuntimeError("NoonAisProvider needs a db session; use eta_service.eta_watch")

    def positions_from_db(self, db: Session, tenant_id: Any, voyage_ids: list[str] | None = None) -> list[VesselPosition]:
        stmt = (
            select(NoonReport, Voyage.vessel_id)
            .join(Voyage, NoonReport.voyage_id == Voyage.id, isouter=True)
            .where(NoonReport.tenant_id == tenant_id)
            .order_by(NoonReport.report_at.desc())
        )
        seen: set[str] = set()
        out: list[VesselPosition] = []
        for rep, vessel_id in db.execute(stmt).all():
            vid = str(rep.voyage_id)
            if voyage_ids is not None and vid not in voyage_ids:
                continue
            if vid in seen:
                continue  # desc 排序 → 首见即最新
            seen.add(vid)
            out.append(
                VesselPosition(
                    voyage_id=vid,
                    vessel_id=str(vessel_id) if vessel_id else None,
                    observed_at=rep.report_at,
                    lat=float(rep.lat) if rep.lat is not None else None,
                    lon=float(rep.lon) if rep.lon is not None else None,
                    speed_kn=float(rep.speed) if rep.speed is not None else None,
                    eta_next=rep.eta_next,
                    eta_deviation_hours=float(rep.eta_deviation_hours) if rep.eta_deviation_hours is not None else None,
                    source=self.source,
                )
            )
        return out


class HttpAisProvider:
    """外部 AIS 供应商接入位（配置后启用）。"""

    source = "ais-http"

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key

    def get_positions(self, tenant_id: Any, voyage_ids: list[str] | None = None) -> list[VesselPosition]:
        raise NotImplementedError(
            "HttpAisProvider: wire the vendor REST contract here (base_url configured); "
            "until then use NoonAisProvider"
        )


def default_provider() -> AisProvider:
    from app.config import get_settings

    s = get_settings()
    if getattr(s, "ais_base_url", "") and getattr(s, "ais_api_key", ""):
        return HttpAisProvider(s.ais_base_url, s.ais_api_key)
    return NoonAisProvider()
