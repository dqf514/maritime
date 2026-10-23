"""Personal view-state — tab 未读上标 (unread badges) + mark-seen.

设计：轻量 per-user "last seen" 标记（``UserViewState``），配合各实体的
created_at 计算未读。通用实体注册表 ``TAB_REGISTRIES`` —— 加新实体只需在
表里挂一个 {(tab_key): (Model, owner_column)} 映射，badge 端点即刻生效。
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_domain import Voyage
from app.models_task import UserViewState
from app.models_voyage_ext import VoyageInstruction, VoyageNote
from app.security import AuthContext, get_current_auth

router = APIRouter(tags=["UserState"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ViewedIn(BaseModel):
    entity_type: str
    entity_id: UUID
    tab: str


# 实体注册表：tab_key → (Model, 实体外键列名, owner_column)。
# owner 非本人创建的行才可能算未读；外键列用于把行挂到 entity_id 上。
TAB_REGISTRIES: dict[str, dict[str, tuple[type, str, object]]] = {
    "voyage": {
        "notes": (VoyageNote, "voyage_id", VoyageNote.created_by),
        "instructions": (VoyageInstruction, "voyage_id", VoyageInstruction.created_by),
    },
}


@router.post("/me/viewed")
def mark_viewed(
    body: ViewedIn,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """记录「当前用户已看过该实体的该 tab」——未读上标据此归零。"""
    if body.tab not in TAB_REGISTRIES.get(body.entity_type, {}):
        # 未注册的 tab 静默接受（前端可预打点），但不参与未读计算
        pass
    now = _now()
    row = db.scalar(
        select(UserViewState).where(
            UserViewState.tenant_id == auth.tenant_id,
            UserViewState.user_id == auth.user_id,
            UserViewState.entity_type == body.entity_type,
            UserViewState.entity_id == body.entity_id,
            UserViewState.tab_key == body.tab,
        )
    )
    if row:
        row.last_seen_at = now
    else:
        db.add(
            UserViewState(
                tenant_id=auth.tenant_id,
                user_id=auth.user_id,
                entity_type=body.entity_type,
                entity_id=body.entity_id,
                tab_key=body.tab,
                last_seen_at=now,
            )
        )
    db.commit()
    return {"ok": True, "last_seen_at": now.isoformat()}


@router.get("/me/unread")
def unread_badges(
    entity_type: str,
    entity_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """按 tab 返回 {count, unread}。unread = 他人创建且晚于 last_seen_at 的行。"""
    registry = TAB_REGISTRIES.get(entity_type)
    if not registry:
        return {}
    if entity_type == "voyage":
        v = db.get(Voyage, entity_id)
        if not v or v.tenant_id != auth.tenant_id:
            raise HTTPException(404, "Voyage not found")

    seen = {
        r.tab_key: r.last_seen_at
        for r in db.scalars(
            select(UserViewState).where(
                UserViewState.tenant_id == auth.tenant_id,
                UserViewState.user_id == auth.user_id,
                UserViewState.entity_type == entity_type,
                UserViewState.entity_id == entity_id,
                UserViewState.tab_key.in_(list(registry)),
            )
        ).all()
    }

    out: dict[str, dict[str, int]] = {}
    for tab, (model, fk_col, owner_col) in registry.items():
        base = [
            model.tenant_id == auth.tenant_id,
            model.deleted_at.is_(None),
            getattr(model, fk_col) == entity_id,
        ]
        total = int(db.scalar(select(func.count()).select_from(model).where(*base)) or 0)
        unread = 0
        if total:
            uq = select(func.count()).select_from(model).where(
                *base,
                or_(owner_col != auth.user_id, owner_col.is_(None)),
            )
            last = seen.get(tab)
            if last is not None:
                uq = uq.where(model.created_at > last)
            unread = int(db.scalar(uq) or 0)
        out[tab] = {"count": total, "unread": unread}
    return out
