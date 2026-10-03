"""Centralized fleet scheduling (Phase 3) — ScheduleBlock 运营中心.

把散落在 commercial/ship_mgmt 的排程块 (ScheduleBlock) 操作集中到一处:
列表/创建/移动/缩放/删除 + 冲突检测 + 空档船期 (open positions) + 货盘簿 +
泊位窗口视图。

冲突策略 (与路由约定一致):
- ``create_block`` — 允许重叠但打标: 新块与所有重叠对方的 ``hard_conflict``
  置 True (沿用 legacy ``POST /schedules`` 语义, 200 + 标志位);
- ``move_block`` / ``resize_block`` — 目标窗口与同船他块重叠视为 **硬冲突**,
  直接拒绝 (HTTP 409 ``SCHEDULE_CONFLICT``); 成功后重算该船全部标志位。

All functions are tenant-scoped and commit their own transaction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_cargo import Cargo
from app.models_domain import BerthWindow, ScheduleBlock, Voyage
from app.models_wave1 import Vessel
from app.pagination import paginate
from app.services.cargo import OPEN_STATUSES, cargo_public
from app.services.tenant_guard import scoped_get, scoped_query

BLOCK_TYPES = ("voyage", "repair", "offhire")


def _aware(dt: datetime) -> datetime:
    """Naive datetimes (SQLite round-trip) are treated as UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    # Python-side compares must be tz-consistent (SQLite round-trips are naive).
    a_start, a_end = _aware(a_start), _aware(a_end)
    b_start, b_end = _aware(b_start), _aware(b_end)
    return a_start < b_end and a_end > b_start


def block_public(row: ScheduleBlock) -> dict:
    return {
        "id": str(row.id),
        "vessel_id": str(row.vessel_id),
        "block_type": row.block_type,
        "title": row.title,
        "start_at": _aware(row.start_at).isoformat() if row.start_at else None,
        "end_at": _aware(row.end_at).isoformat() if row.end_at else None,
        "voyage_id": str(row.voyage_id) if row.voyage_id else None,
        "hard_conflict": bool(row.hard_conflict),
        "meta": row.meta or {},
    }


def _validate_window(start: datetime, end: datetime) -> None:
    if _aware(end) <= _aware(start):
        raise HTTPException(400, "end_at must be after start_at")


def _assert_vessel(db: Session, tenant_id: UUID, vessel_id: UUID) -> Vessel:
    vessel = scoped_get(db, Vessel, vessel_id, tenant_id)
    if vessel is None:
        raise HTTPException(404, "Vessel not found")
    return vessel


def _assert_voyage(db: Session, tenant_id: UUID, voyage_id: UUID | None) -> None:
    if voyage_id is not None and scoped_get(db, Voyage, voyage_id, tenant_id) is None:
        raise HTTPException(404, "Voyage not found")


def _overlapping(
    db: Session,
    tenant_id: UUID,
    vessel_id: UUID,
    start: datetime,
    end: datetime,
    *,
    exclude_id: UUID | None = None,
) -> list[ScheduleBlock]:
    stmt = select(ScheduleBlock).where(
        ScheduleBlock.tenant_id == tenant_id,
        ScheduleBlock.vessel_id == vessel_id,
        ScheduleBlock.start_at < end,
        ScheduleBlock.end_at > start,
    )
    if exclude_id is not None:
        stmt = stmt.where(ScheduleBlock.id != exclude_id)
    return list(db.scalars(stmt).all())


def _refresh_conflict_flags(db: Session, tenant_id: UUID, vessel_id: UUID) -> None:
    """Recompute ``hard_conflict`` for every block of the vessel (pairwise overlap)."""
    blocks = list(
        db.scalars(
            select(ScheduleBlock).where(
                ScheduleBlock.tenant_id == tenant_id, ScheduleBlock.vessel_id == vessel_id
            )
        ).all()
    )
    for block in blocks:
        block.hard_conflict = any(
            other.id != block.id
            and _overlaps(block.start_at, block.end_at, other.start_at, other.end_at)
            for other in blocks
        )


# ── CRUD ─────────────────────────────────────────────────────────────


def list_blocks(
    db: Session,
    tenant_id: UUID,
    *,
    vessel_id: UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    block_type: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[ScheduleBlock], int]:
    """Schedule blocks for a tenant; date filters use overlap semantics."""
    stmt = scoped_query(db, ScheduleBlock, tenant_id).order_by(ScheduleBlock.start_at, ScheduleBlock.id)
    if vessel_id is not None:
        stmt = stmt.where(ScheduleBlock.vessel_id == vessel_id)
    if block_type is not None:
        stmt = stmt.where(ScheduleBlock.block_type == block_type)
    if date_from is not None:
        stmt = stmt.where(ScheduleBlock.end_at > date_from)
    if date_to is not None:
        stmt = stmt.where(ScheduleBlock.start_at < date_to)
    return paginate(db, stmt, limit, offset)


def create_block(
    db: Session,
    tenant_id: UUID,
    *,
    vessel_id: UUID,
    title: str,
    start_at: datetime,
    end_at: datetime,
    block_type: str = "voyage",
    voyage_id: UUID | None = None,
    meta: dict | None = None,
) -> ScheduleBlock:
    """Create a schedule block. Overlaps are allowed but flag ``hard_conflict``."""
    _validate_window(start_at, end_at)
    _assert_vessel(db, tenant_id, vessel_id)
    _assert_voyage(db, tenant_id, voyage_id)
    row = ScheduleBlock(
        tenant_id=tenant_id,
        vessel_id=vessel_id,
        block_type=block_type,
        title=title,
        start_at=start_at,
        end_at=end_at,
        voyage_id=voyage_id,
        meta=meta or {},
        hard_conflict=False,
    )
    db.add(row)
    db.flush()
    _refresh_conflict_flags(db, tenant_id, vessel_id)
    db.commit()
    db.refresh(row)
    return row


def get_block(db: Session, tenant_id: UUID, block_id: UUID) -> ScheduleBlock | None:
    return scoped_get(db, ScheduleBlock, block_id, tenant_id)


def update_block(db: Session, tenant_id: UUID, block: ScheduleBlock, **fields) -> ScheduleBlock:
    """Patch non-timing fields (timing goes through move/resize)."""
    if fields.get("title") is not None:
        block.title = fields["title"]
    if fields.get("block_type") is not None:
        block.block_type = fields["block_type"]
    if fields.get("meta") is not None:
        block.meta = fields["meta"]
    if "voyage_id" in fields:
        _assert_voyage(db, tenant_id, fields["voyage_id"])
        block.voyage_id = fields["voyage_id"]
    db.commit()
    db.refresh(block)
    return block


def move_block(db: Session, block_id: UUID, new_start: datetime, new_end: datetime) -> ScheduleBlock:
    """Move a block to a new window; overlapping the same vessel → 409 hard conflict.

    Caller must have tenant-scoped the block first (router uses ``scoped_get``);
    the lookup here is by primary key only.
    """
    block = db.get(ScheduleBlock, block_id)
    if block is None:
        raise HTTPException(404, "Schedule block not found")
    _validate_window(new_start, new_end)
    clash = _overlapping(db, block.tenant_id, block.vessel_id, new_start, new_end, exclude_id=block.id)
    if clash:
        raise HTTPException(
            409,
            detail={
                "code": "SCHEDULE_CONFLICT",
                "message": "Target window overlaps existing schedule blocks",
                "conflicts": [str(b.id) for b in clash],
            },
        )
    block.start_at = new_start
    block.end_at = new_end
    db.flush()
    _refresh_conflict_flags(db, block.tenant_id, block.vessel_id)
    db.commit()
    db.refresh(block)
    return block


def resize_block(
    db: Session,
    block_id: UUID,
    new_start: datetime | None = None,
    new_end: datetime | None = None,
) -> ScheduleBlock:
    """Resize a block window (either edge); overlapping the same vessel → 409."""
    block = db.get(ScheduleBlock, block_id)
    if block is None:
        raise HTTPException(404, "Schedule block not found")
    start = new_start if new_start is not None else block.start_at
    end = new_end if new_end is not None else block.end_at
    _validate_window(start, end)
    clash = _overlapping(db, block.tenant_id, block.vessel_id, start, end, exclude_id=block.id)
    if clash:
        raise HTTPException(
            409,
            detail={
                "code": "SCHEDULE_CONFLICT",
                "message": "Resized window overlaps existing schedule blocks",
                "conflicts": [str(b.id) for b in clash],
            },
        )
    block.start_at = start
    block.end_at = end
    db.flush()
    _refresh_conflict_flags(db, block.tenant_id, block.vessel_id)
    db.commit()
    db.refresh(block)
    return block


def delete_block(db: Session, block_id: UUID) -> dict:
    """Hard-delete a schedule block (no soft-delete column on the model)."""
    block = db.get(ScheduleBlock, block_id)
    if block is None:
        raise HTTPException(404, "Schedule block not found")
    tenant_id, vessel_id = block.tenant_id, block.vessel_id
    db.delete(block)
    db.flush()
    _refresh_conflict_flags(db, tenant_id, vessel_id)
    db.commit()
    return {"ok": True, "id": str(block_id)}


# ── 冲突 / 空档 / 货盘簿 / 泊位 ────────────────────────────────────────


def detect_conflicts(
    db: Session, tenant_id: UUID, vessel_id: UUID | None = None
) -> list[dict[str, Any]]:
    """Blocks currently overlapping another block on the same vessel (live scan)."""
    stmt = scoped_query(db, ScheduleBlock, tenant_id).order_by(ScheduleBlock.vessel_id, ScheduleBlock.start_at)
    if vessel_id is not None:
        stmt = stmt.where(ScheduleBlock.vessel_id == vessel_id)
    blocks = list(db.scalars(stmt).all())
    out: list[dict[str, Any]] = []
    for i, block in enumerate(blocks):
        clash = [
            other.id
            for j, other in enumerate(blocks)
            if i != j
            and other.vessel_id == block.vessel_id
            and _overlaps(block.start_at, block.end_at, other.start_at, other.end_at)
        ]
        if clash:
            item = block_public(block)
            item["conflicts_with"] = [str(c) for c in clash]
            out.append(item)
    return out


def open_positions(
    db: Session,
    tenant_id: UUID,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[dict[str, Any]]:
    """Vessels with availability gaps in the window (merged unoccupied intervals)."""
    start = date_from or datetime.now(timezone.utc)
    end = date_to
    if end is not None and _aware(end) <= _aware(start):
        raise HTTPException(400, "date_to must be after date_from")

    vessels = list(
        db.scalars(
            scoped_query(db, Vessel, tenant_id).order_by(Vessel.name)
        ).all()
    )
    out: list[dict[str, Any]] = []
    for vessel in vessels:
        stmt = select(ScheduleBlock).where(
            ScheduleBlock.tenant_id == tenant_id,
            ScheduleBlock.vessel_id == vessel.id,
        )
        if end is not None:
            stmt = stmt.where(ScheduleBlock.start_at < end)
        stmt = stmt.where(ScheduleBlock.end_at > start)
        blocks = list(db.scalars(stmt).all())

        # Clip occupied intervals to the window and merge.
        occupied: list[tuple[datetime, datetime]] = []
        for block in blocks:
            b_start = max(_aware(block.start_at), _aware(start))
            b_end = min(_aware(block.end_at), _aware(end)) if end is not None else _aware(block.end_at)
            if b_end > b_start:
                occupied.append((b_start, b_end))
        occupied.sort()
        merged: list[tuple[datetime, datetime]] = []
        for s, e in occupied:
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))

        # Complement → gaps.
        gaps = []
        cursor = _aware(start)
        window_end = _aware(end) if end is not None else None
        for s, e in merged:
            if s > cursor:
                gaps.append((cursor, s))
            cursor = max(cursor, e)
        if window_end is None:
            # Open-ended window: an unbounded tail gap is reported with end=None.
            gaps.append((cursor, None))  # type: ignore[arg-type]
        elif cursor < window_end:
            gaps.append((cursor, window_end))

        if not gaps:
            continue
        gap_rows = [
            {
                "start": g_start.isoformat(),
                "end": g_end.isoformat() if g_end is not None else None,
                "days": round((g_end - g_start).total_seconds() / 86400, 2) if g_end is not None else None,
            }
            for g_start, g_end in gaps
        ]
        # g_start/g_end are already _aware()-normalized → isoformat carries the offset
        open_days = sum((g["days"] or 0) for g in gap_rows)
        out.append(
            {
                "vessel_id": str(vessel.id),
                "vessel_name": vessel.name,
                "imo": vessel.imo,
                "gaps": gap_rows,
                "open_days": round(open_days, 2),
            }
        )
    return out


def cargo_book(db: Session, tenant_id: UUID) -> dict:
    """Open cargo + laycan (cargo book view for the scheduling desk)."""
    rows = db.scalars(
        scoped_query(db, Cargo, tenant_id)
        .where(Cargo.status.in_(OPEN_STATUSES))
        .order_by(Cargo.laycan_from, Cargo.cargo_no)
    ).all()
    return {"items": [cargo_public(r) for r in rows], "total": len(rows), "statuses": list(OPEN_STATUSES)}


def berth_windows(db: Session, tenant_id: UUID, port_id: UUID | None = None) -> list[dict[str, Any]]:
    """Berth slots (reserved windows) for a tenant, optionally per port."""
    stmt = scoped_query(db, BerthWindow, tenant_id).order_by(BerthWindow.start_at)
    if port_id is not None:
        stmt = stmt.where(BerthWindow.port_id == port_id)
    rows = list(db.scalars(stmt).all())
    return [
        {
            "id": str(r.id),
            "port_id": str(r.port_id) if r.port_id else None,
            "berth_name": r.berth_name,
            "start_at": _aware(r.start_at).isoformat() if r.start_at else None,
            "end_at": _aware(r.end_at).isoformat() if r.end_at else None,
            "voyage_id": str(r.voyage_id) if r.voyage_id else None,
            "status": r.status,
        }
        for r in rows
    ]
