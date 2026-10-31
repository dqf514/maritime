"""任务自动完成 —— 双通道。

用户诉求原文：「安排一个任务可能涉及某个系统里的动作，这个动作如果在系统里
做好了，就自动标记为完成」。本模块实现这条闭环。

**两条通道，同一份真相**

1. **事件即时通道**（主）：域事件到达时（``invoice.issued`` /
   ``voyage.completed`` / ``claim.settled`` …），若该事件登记了动作目录里的
   某些 ``action_code``，就去找绑定了这些动作、且绑定实体与事件相关的未完成
   任务，跑判定器，命中即勾完成 —— 即时、无轮询。
2. **判定器兜底通道**（补漏）：没发事件的动作（例如手工在别处改了单据状态），
   靠惰性刷新（读任务列表/详情时）与定时 tick（``job_queue``）跑判定器补上。

两条通道最终都走同一个 :func:`complete_task` —— 写 ``completed_at`` /
``completed_by`` / ``auto_completed``、写审计、通知创建人。

**人工永远可以覆盖**（沿用已签字口径「可以允许人工编辑就行」）：
自动完成后仍可 reopen；人工可手动勾选。人工勾选时若判定器未命中，
记 ``auto_completed=False`` 的人工完成。

判定器是**纯只读**的（``services/action_catalog``），绝不写库 —— 因此本模块
可以放心地在读路径上跑它。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.models_domain import (
    BunkerOrder,
    Claim,
    Invoice,
    LaytimeCalc,
    PortDisbursement,
    Voyage,
)
from app.models_ops import DomainEvent
from app.models_task import Task
from app.services.action_catalog import ACTIONS, ACTION_BY_CODE, ActionSpec
from app.services.audit import audit
from app.services.domain_events import on
from app.services.notifications import notify_once
from app.services.state_machine import TASK_TRANSITIONS, transition

log = logging.getLogger(__name__)

# 判定器扫描的单次上限（防 N+1 把读路径拖垮）
DETECTOR_SCAN_LIMIT = 50
TICK_SCAN_LIMIT = 200

# 事件实体类型 → 跨类型的"父实体"解析（收尾清单类动作挂在航次上）
_PARENT_RESOLVERS = {
    "claim": (Claim, "voyage_id"),
    "invoice": (Invoice, "voyage_id"),
    "bunker_order": (BunkerOrder, "voyage_id"),
    "laytime": (LaytimeCalc, "voyage_id"),
    "port_disbursement": (PortDisbursement, "voyage_id"),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _task_href(task: Task) -> str:
    return "/tasks"


# ── 完成动作（唯一出口） ─────────────────────────────────────────────────


def complete_task(
    db: Session,
    task: Task,
    *,
    actor_user_id: UUID | None = None,
    auto: bool = False,
    reason: str = "",
) -> bool:
    """把任务标记为完成。返回是否真的发生了变化。

    ``auto=True`` 表示由系统判定器判定（完成人留空 —— 不是某个人干的）；
    ``auto=False`` 表示人工勾选（完成人 = 操作人）。
    """
    if task.status == "done":
        return False
    try:
        transition("task", task.status, "done", TASK_TRANSITIONS)
    except Exception:  # noqa: BLE001 —— 非法状态直接不勾（别把整个读路径炸掉）
        return False
    task.status = "done"
    task.completed_at = _now()
    task.completed_by = None if auto else actor_user_id
    task.auto_completed = auto
    task.updated_at = _now()
    audit(
        db,
        action="task.auto_complete" if auto else "task.complete",
        tenant_id=task.tenant_id,
        actor_user_id=actor_user_id,
        entity_type="task",
        entity_id=task.id,
        detail={
            "title": task.title,
            "action_code": task.action_code,
            "auto": auto,
            "reason": reason,
        },
    )
    if auto:
        _notify_creator(db, task)
    return True


def reopen_task(db: Session, task: Task, *, actor_user_id: UUID | None = None) -> bool:
    """重开任务（人工覆盖系统的自动完成）。"""
    if task.status not in ("done", "cancelled"):
        return False
    try:
        transition("task", task.status, "todo", TASK_TRANSITIONS)
    except Exception:  # noqa: BLE001
        return False
    task.status = "todo"
    task.completed_at = None
    task.completed_by = None
    task.auto_completed = False
    task.updated_at = _now()
    audit(
        db,
        action="task.reopen",
        tenant_id=task.tenant_id,
        actor_user_id=actor_user_id,
        entity_type="task",
        entity_id=task.id,
        detail={"title": task.title},
    )
    return True


def _notify_creator(db: Session, task: Task) -> None:
    """系统自动完成 → 通知创建人（对方有权知情）。"""
    creator = db.get(User, task.created_by) if task.created_by else None
    if creator is None:
        return
    notify_once(
        db,
        task.tenant_id,
        [creator],
        title=task.title,
        body="该任务的系统动作已完成，任务已自动勾选完成。",
        href=_task_href(task),
        level="info",
    )


# ── 判定器刷新 ───────────────────────────────────────────────────────────


def _load_entity(db: Session, tenant_id: UUID, spec: ActionSpec, entity_id: UUID | None):
    if entity_id is None:
        return None
    model = _ENTITY_MODELS.get(spec.entity_type)
    if model is None:
        return None
    row = db.get(model, entity_id)
    if row is None or row.tenant_id != tenant_id:
        return None
    return row


def _detect(db: Session, tenant_id: UUID, task: Task) -> bool:
    """跑判定器：这条任务绑定的动作是不是已经做完了。"""
    spec = ACTION_BY_CODE.get(task.action_code or "")
    if spec is None:
        return False
    if task.entity_type and task.entity_type != spec.entity_type:
        return False
    entity = _load_entity(db, tenant_id, spec, task.entity_id)
    if entity is None:
        return False
    try:
        return bool(spec.detector(db, tenant_id, entity))
    except Exception:  # noqa: BLE001 —— 判定器异常不得影响业务读路径
        log.exception("action detector failed: action=%s task=%s", spec.code, task.id)
        return False


def refresh_task(db: Session, task: Task) -> bool:
    """单条任务的惰性刷新。命中判定器 → 自动完成。"""
    if task.status in ("done", "cancelled", "deleted"):
        return False
    if not task.action_code or not task.auto_complete:
        return False
    if not _detect(db, task.tenant_id, task):
        return False
    return complete_task(db, task, auto=True, reason=f"action:{task.action_code}")


def refresh_tasks(db: Session, tenant_id: UUID, tasks: list[Task]) -> int:
    """批量惰性刷新（读列表/详情时调用）。返回被自动完成的任务数。"""
    n = 0
    checked = 0
    for task in tasks:
        if not task.action_code or not task.auto_complete:
            continue
        if checked >= DETECTOR_SCAN_LIMIT:
            break
        checked += 1
        if refresh_task(db, task):
            n += 1
    return n


def scan_tenant(db: Session, tenant_id: UUID) -> int:
    """兜底扫描：找出该租户所有「绑了动作且未完成」的任务，跑判定器。

    给 ``job_queue`` 的定时 tick 用（每 5 分钟一次）。上限 200 条/轮。
    """
    rows = db.scalars(
        select(Task)
        .where(
            Task.tenant_id == tenant_id,
            Task.status.in_(("todo", "in_progress")),
            Task.action_code.is_not(None),
            Task.auto_complete.is_(True),
        )
        .order_by(Task.updated_at.asc())
        .limit(TICK_SCAN_LIMIT)
    ).all()
    n = 0
    for task in rows:
        if refresh_task(db, task):
            n += 1
    return n


# ── 事件即时通道 ─────────────────────────────────────────────────────────


def _event_related_ids(db: Session, spec: ActionSpec, ev: DomainEvent) -> set[UUID]:
    """事件与动作的绑定实体是否相关。

    * 事件实体类型与动作实体类型一致 → 就是它本身；
    * 否则沿 payload 里的 ``<entity_type>_id`` 找；
    * 再否则按"子单据 → 航次"解析（收尾清单类动作挂在航次上）。
    """
    out: set[UUID] = set()
    if ev.entity_type == spec.entity_type and ev.entity_id is not None:
        out.add(ev.entity_id)
        return out
    payload = ev.payload or {}
    key = f"{spec.entity_type}_id"
    raw = payload.get(key)
    if raw:
        try:
            out.add(UUID(str(raw)))
        except ValueError:
            pass
        if out:
            return out
    resolver = _PARENT_RESOLVERS.get(ev.entity_type or "")
    if resolver and ev.entity_id is not None:
        model, attr = resolver
        row = db.get(model, ev.entity_id)
        parent_id = getattr(row, attr, None) if row is not None else None
        if parent_id and spec.entity_type == "voyage":
            out.add(parent_id)
    return out


def _handle_event(db: Session, ev: DomainEvent) -> None:
    specs = [a for a in ACTIONS if ev.kind in a.event_kinds]
    if not specs:
        return
    for spec in specs:
        related = _event_related_ids(db, spec, ev)
        if not related:
            continue
        rows = db.scalars(
            select(Task).where(
                Task.tenant_id == ev.tenant_id,
                Task.action_code == spec.code,
                Task.status.in_(("todo", "in_progress")),
                Task.auto_complete.is_(True),
                Task.entity_id.in_(related),
            )
        ).all()
        for task in rows:
            refresh_task(db, task)


# 注册到域事件总线 —— 事件到达即勾完成
for _spec in ACTIONS:
    if _spec.event_kinds:
        on(*_spec.event_kinds)(_handle_event)


# ── 实体模型表（判定器加载绑定实体用） ───────────────────────────────────

from app.models_domain import CharterAmendment, CoaLifting  # noqa: E402
from app.models_ship import ShipCertificate  # noqa: E402

_ENTITY_MODELS = {
    "voyage": Voyage,
    "invoice": Invoice,
    "claim": Claim,
    "laytime": LaytimeCalc,
    "port_disbursement": PortDisbursement,
    "bunker_order": BunkerOrder,
    "charter_amendment": CharterAmendment,
    "coa_lifting": CoaLifting,
    "ship_certificate": ShipCertificate,
}
