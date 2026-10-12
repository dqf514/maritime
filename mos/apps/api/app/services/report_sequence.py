"""午报/活动报告阶段顺序校验 (IMOS Activity Report 审批顺序链).

IMOS/Veslink 活动报告链: arrival → in-port → cargo → bunker → departure → SOF.
普通航行午报属于链前/链间的 sea 阶段；同一挂靠周期结束后 sea/arrival 允许开新一轮。

NoonIn 没有显式 stage/event_type 字段，故从载荷内容推导阶段（见 derive_report_stage）。
校验规则：新报告阶段序号不得低于航次内最近一份已接受报告（同阶段允许重复）；
例外：上一份已收尾（departure/sof）且新阶段是链起点（sea/arrival）→ 新挂靠周期，放行。

逃逸开关：config flag `CFGRelaxReportSequence` = true 时跳过强校验（默认 false = 强制执行）。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import NoonReport, PortCall
from app.services.config_service import ConfigService

# 活动报告阶段序号（IMOS 链序；sea 是链前/链间的航行午报）
STAGE_ORDER: dict[str, int] = {
    "sea": 0,        # 航行中（en-route）
    "arrival": 1,    # 抵港 arrival
    "in_port": 2,    # 在港 in-port
    "cargo": 3,      # 货物作业 cargo ops
    "bunker": 4,     # 加油 bunkering
    "departure": 5,  # 离港 departure
    "sof": 6,        # SOF / 挂靠收尾
}

# 一轮挂靠周期的收尾/起始阶段（收尾后允许 sea/arrival 重新开链）
CYCLE_END: frozenset[str] = frozenset({"departure", "sof"})
CYCLE_START: frozenset[str] = frozenset({"sea", "arrival"})

# 停航/航行速度阈值（kn）
STOPPED_KN = 0.5
SEA_SPEED_KN = 1.0

# 备注关键词 → 阶段（操作员在 remarks 里写明作业阶段时的显式提示）。
# 按链序倒序检查，备注同时提到多阶段时取更晚阶段。
_REMARKS_STAGE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sof", ("statement of facts", "sof")),
    ("departure", ("departure", "departed", "sailed", "sailing", "left port")),
    ("bunker", ("bunker", "bunkering", "bunkered", "stem")),
    ("cargo", ("cargo", "loading", "discharge", "discharging", "cargo ops", "load ops")),
    ("in_port", ("in port", "inport", "alongside", "all fast", "at berth", "port stay")),
    ("arrival", ("arrival", "arrived", "arriving", "eosp", "nor tendered", "anchored", "anchor")),
)


class ReportSequenceError(HTTPException):
    """409 REPORT_SEQUENCE — 活动报告阶段回退（shape 对齐 state_machine.InvalidState）。"""

    def __init__(self, previous: str, stage: str, voyage_no: str | None = None):
        target = voyage_no or "voyage"
        super().__init__(
            status_code=409,
            detail={
                "code": "REPORT_SEQUENCE",
                "message": f"{target}: activity report stage cannot go backwards {previous} → {stage}",
                "previous": previous,
                "stage": stage,
                "chain": [k for k, _ in sorted(STAGE_ORDER.items(), key=lambda kv: kv[1])],
            },
        )


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _stage_from_remarks(remarks: str | None) -> str | None:
    """备注关键词提示（词边界匹配，避免 stem→system 之类误命中）。"""
    if not remarks:
        return None
    text = remarks.lower()
    for stage, keywords in _REMARKS_STAGE_HINTS:
        for kw in keywords:
            if re.search(rf"\b{re.escape(kw)}\b", text):
                return stage
    return None


def _covering_window(
    at: datetime, port_calls: Iterable[Any]
) -> tuple[datetime | None, datetime | None] | None:
    """返回覆盖 at 的挂靠时间窗 (start, end)；无时间信息的挂靠不参与推导。"""
    for pc in port_calls:
        start = _as_utc(pc.ata) if getattr(pc, "ata", None) else _as_utc(getattr(pc, "eta", None))
        end = _as_utc(pc.atd) if getattr(pc, "atd", None) else _as_utc(getattr(pc, "etd", None))
        if start is None and end is None:
            continue
        if start is not None and at < start:
            continue
        if end is not None and at > end:
            continue
        return (start, end)
    return None


def derive_report_stage(
    *,
    report_at: datetime,
    lat: float | None,
    lon: float | None,
    speed: float | int | None,
    remarks: str | None,
    port_calls: Sequence[Any] = (),
) -> str:
    """从午报载荷内容推导活动报告阶段（NoonIn 无显式 stage 字段）。

    推导优先级（文档化，勿凭空发明字段）：
    1. remarks 关键词 — 操作员备注里的阶段提示（cargo/bunker/discharge/sailed/sof/...），
       按链序倒序检查，先命中晚阶段。
    2. 速度 × 挂靠时间窗（timestamps + port calls）：
       - speed ≤ 0.5kn 且 report_at 落在 [ata|eta, atd|etd] 窗口前 → arrival（待泊/抵港）
       - speed ≤ 0.5kn 且落在窗口内（或无窗口但停航）→ in_port
       - speed > 1kn 且落在窗口内（尚未 atd/etd）→ departure（离泊开航）
       - speed > 1kn 且落在窗口后 → sea（已离港的航行午报）
    3. 兜底 — 无速度/备注等信号时视为普通航行午报 → sea（同阶段可重复，最安全）。
    """
    stage = _stage_from_remarks(remarks)
    if stage is not None:
        return stage

    at = _as_utc(report_at) or datetime.now(timezone.utc)
    win = _covering_window(at, port_calls)
    spd: float | None
    try:
        spd = float(speed) if speed is not None else None
    except (TypeError, ValueError):
        spd = None

    if spd is not None and spd <= STOPPED_KN:
        if win is not None:
            start, _end = win
            if start is not None and at < start:
                return "arrival"
            return "in_port"
        return "in_port"
    if spd is not None and spd > SEA_SPEED_KN:
        if win is not None:
            _start, end = win
            if end is not None and at > end:
                return "sea"
            return "departure"
        return "sea"
    return "sea"


def assert_report_sequence(
    db: Session,
    tenant_id,
    voyage_id,
    *,
    report_at: datetime,
    lat: float | None = None,
    lon: float | None = None,
    speed: float | int | None = None,
    remarks: str | None = None,
    voyage_no: str | None = None,
) -> str:
    """校验新午报阶段不回退；返回推导阶段。违规抛 409 REPORT_SEQUENCE。

    CFGRelaxReportSequence=true 时跳过强校验（仍返回推导阶段，便于响应可见）。
    """
    port_calls = list(
        db.scalars(select(PortCall).where(PortCall.voyage_id == voyage_id).order_by(PortCall.seq)).all()
    )
    stage = derive_report_stage(
        report_at=report_at,
        lat=lat,
        lon=lon,
        speed=speed,
        remarks=remarks,
        port_calls=port_calls,
    )

    relaxed = ConfigService.get(db, "CFGRelaxReportSequence", tenant_id=tenant_id, default=False)
    if relaxed:
        return stage

    prev = db.scalar(
        select(NoonReport)
        .where(NoonReport.tenant_id == tenant_id, NoonReport.voyage_id == voyage_id)
        .order_by(NoonReport.report_at.desc(), NoonReport.id.desc())
        .limit(1)
    )
    if prev is None:
        return stage

    prev_stage = derive_report_stage(
        report_at=prev.report_at,
        lat=prev.lat,
        lon=prev.lon,
        speed=prev.speed,
        remarks=prev.remarks,
        port_calls=port_calls,
    )
    prev_ord = STAGE_ORDER.get(prev_stage, 0)
    new_ord = STAGE_ORDER.get(stage, 0)
    if new_ord >= prev_ord:
        return stage  # 同阶段重复或向前
    # 新挂靠周期：上一链已收尾（departure/sof）且新阶段是链起点（sea/arrival）
    if prev_stage in CYCLE_END and stage in CYCLE_START:
        return stage
    raise ReportSequenceError(previous=prev_stage, stage=stage, voyage_no=voyage_no)
