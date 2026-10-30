"""午报（Noon report）写入服务层。

原先创建逻辑在路由里（``routers/operations.py::create_noon``），例行任务中枢的
写回腿（人工确认后落库）需要在**没有 HTTP 上下文**时落一份午报，所以下沉到服务层：

- 路由端点行为**零变化**（404/409 语义、ETA 偏差 ≥6h 的 TwinAlert、审计字段都不变）；
- 新增 ``fields`` 参数：**字段子集**语义 —— 例行任务里人只确认了部分字段时，
  未确认的字段不落库（也不参与 ETA 偏差计算，避免拿半个 ETA 算出个假偏差）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import NoonReport, PortCall, TwinAlert, Voyage
from app.services.report_sequence import assert_report_sequence

log = logging.getLogger("marios.noon_service")

#: ETA 偏差达到该小时数即落 TwinAlert（与建报口径一致）
ETA_DEVIATION_ALERT_HOURS = Decimal("6")


def compute_eta_deviation(
    db: Session, tenant_id: UUID, voyage_id: UUID, eta_next: datetime | None
) -> Decimal | None:
    """ETA 偏差 = 首个挂靠港 ETA vs eta_next（与建报/改报同一口径）。"""
    if eta_next is None:
        return None
    pc = db.scalar(
        select(PortCall)
        .where(PortCall.voyage_id == voyage_id, PortCall.deleted_at.is_(None))
        .order_by(PortCall.seq)
        .limit(1)
    )
    if pc is None or not pc.eta:
        return None
    eta = pc.eta if pc.eta.tzinfo else pc.eta.replace(tzinfo=timezone.utc)
    next_eta = eta_next if eta_next.tzinfo else eta_next.replace(tzinfo=timezone.utc)
    return Decimal(str((next_eta - eta).total_seconds() / 3600.0))


def create_noon_report(
    db: Session,
    *,
    tenant_id: UUID,
    voyage_id: UUID,
    report_at: datetime,
    lat: float | None = None,
    lon: float | None = None,
    speed: float | None = None,
    rob_fo: float | None = None,
    rob_do: float | None = None,
    eta_next: datetime | None = None,
    remarks: str | None = None,
    wind_bf: float | None = None,
    sea_state: str | None = None,
    current_kn: float | None = None,
    user_id: UUID | None = None,
    fields: set[str] | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """落一份午报 —— 返回 ``{id, stage, eta_deviation_hours, voyage_no, voyage_id}``。

    ``fields`` 为**字段子集**（None = 全量）：不在集合里的字段一律不落库，
    且 ``eta_next`` 未被确认时不计算偏差、不写 ``eta_deviation_hours``。
    """
    keep = None if fields is None else set(fields)
    if keep is not None:
        lat = lat if "lat" in keep else None
        lon = lon if "lon" in keep else None
        speed = speed if "speed" in keep else None
        rob_fo = rob_fo if "rob_fo" in keep else None
        rob_do = rob_do if "rob_do" in keep else None
        remarks = remarks if "remarks" in keep else None
        wind_bf = wind_bf if "wind_bf" in keep else None
        sea_state = sea_state if "sea_state" in keep else None
        current_kn = current_kn if "current_kn" in keep else None
        eta_next = eta_next if "eta_next" in keep else None

    v = db.get(Voyage, voyage_id)
    if not v or v.tenant_id != tenant_id:
        raise HTTPException(404, "Voyage not found")
    # Activity Report 审批顺序链：阶段不得回退（同阶段可重复；CFGRelaxReportSequence 可关）
    stage = assert_report_sequence(
        db,
        tenant_id,
        v.id,
        report_at=report_at,
        lat=lat,
        lon=lon,
        speed=speed,
        remarks=remarks,
        voyage_no=v.voyage_no,
    )
    deviation = None
    # ETA deviation vs first port call ETA
    pc = db.scalar(
        select(PortCall)
        .where(PortCall.voyage_id == v.id, PortCall.deleted_at.is_(None))
        .order_by(PortCall.seq)
        .limit(1)
    )
    if pc and pc.eta and eta_next:
        eta = pc.eta if pc.eta.tzinfo else pc.eta.replace(tzinfo=timezone.utc)
        next_eta = eta_next if eta_next.tzinfo else eta_next.replace(tzinfo=timezone.utc)
        deviation = Decimal(str((next_eta - eta).total_seconds() / 3600.0))
        if abs(deviation) >= ETA_DEVIATION_ALERT_HOURS:
            db.add(
                TwinAlert(
                    tenant_id=tenant_id,
                    level="warn",
                    title=f"ETA deviation {float(deviation):.1f}h",
                    body=f"Voyage {v.voyage_no} noon ETA drift",
                    href=f"/operations/voyages/{v.id}",
                    vessel_id=v.vessel_id,
                    voyage_id=v.id,
                )
            )
    row = NoonReport(
        tenant_id=tenant_id,
        voyage_id=voyage_id,
        report_at=report_at,
        lat=lat,
        lon=lon,
        speed=speed,
        rob_fo=rob_fo,
        rob_do=rob_do,
        eta_next=eta_next,
        remarks=remarks,
        wind_bf=wind_bf,
        sea_state=sea_state,
        current_kn=current_kn,
        eta_deviation_hours=deviation,
    )
    db.add(row)
    if commit:
        db.commit()
    else:
        db.flush()
    return {
        "id": row.id,
        "voyage_id": v.id,
        "voyage_no": v.voyage_no,
        "stage": stage,
        "eta_deviation_hours": float(deviation) if deviation is not None else None,
    }
