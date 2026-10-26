"""域事件总线：emit → 落 domain_events 日志 → 同步跑注册处理器。

事件驱动自动化的中枢——业务节点（航次完成 / lifting 固定 / 发票签发 …）
``emit`` 一个事件，处理器负责把「下一步该谁做什么」物化成：

- ``Task(source="system")`` 跟进任务（分派到角色 → 首个持有用户）；
- 站内 ``Notification``（notify_once 按日去重，防轰炸）；
- 日程清理 / GL 自动过账等副作用。

约定：
- 处理器不 commit —— 与业务写入同一事务（要么全成，要么全不成）；
- 处理器异常被捕获记入 ``DomainEvent.handler_errors``，**不回滚业务事务**
  （自动化失败不能把业务操作挡在门外，但要留痕可查）；
- ``ensure_task`` 幂等：同实体 + 同标题的活跃任务已存在则复用。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.models_ops import DomainEvent
from app.models_task import Task
from app.services.notifications import notify_once, role_recipients

log = logging.getLogger(__name__)

_HANDLERS: dict[str, list] = {}


def on(*kinds: str):
    """注册事件处理器：``@on("voyage.completed")`` → 函数签名 (db, ev)。"""

    def deco(fn):
        for k in kinds:
            _HANDLERS.setdefault(k, []).append(fn)
        return fn

    return deco


def emit(
    db: Session,
    tenant_id: UUID,
    kind: str,
    entity_type: str,
    entity_id: UUID | None,
    payload: dict | None = None,
    *,
    user_id: UUID | None = None,
    handlers: bool = True,
) -> DomainEvent:
    """落一行域事件并（默认）同步跑注册处理器。调用方负责 commit。"""
    ev = DomainEvent(
        tenant_id=tenant_id,
        kind=kind,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload or {},
        created_by=user_id,
    )
    db.add(ev)
    db.flush()
    if handlers:
        run_handlers(db, ev)
    return ev


def run_handlers(db: Session, ev: DomainEvent) -> None:
    errors: list[str] = []
    for fn in _HANDLERS.get(ev.kind, []):
        try:
            fn(db, ev)
        except Exception as exc:  # noqa: BLE001 —— 处理器失败不得回滚业务事务
            log.exception("domain event handler failed: kind=%s", ev.kind)
            errors.append(f"{getattr(fn, '__name__', 'handler')}: {exc}")
    if errors:
        ev.handler_errors = errors
        db.flush()


def ensure_task(
    db: Session,
    tenant_id: UUID,
    *,
    title: str,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    description: str | None = None,
    priority: str = "normal",
    due_at: datetime | None = None,
    due_days: int | None = None,
    assign_role: str | None = None,
    created_by: UUID | None = None,
) -> Task:
    """幂等创建系统跟进任务：同实体 + 同标题的活跃任务已存在则复用。

    ``assign_role`` 经 role_recipients 解析为该角色的首个在职用户；
    角色下无人时任务照建（assignee 为空，管理层视角仍可见）。
    """
    q = select(Task).where(
        Task.tenant_id == tenant_id,
        Task.status.in_(("todo", "in_progress")),
        Task.title == title,
    )
    if entity_type:
        q = q.where(Task.entity_type == entity_type)
        if entity_id is not None:
            q = q.where(Task.entity_id == entity_id)
        else:
            q = q.where(Task.entity_id.is_(None))
    else:
        q = q.where(Task.entity_type.is_(None))
    existing = db.scalar(q)
    if existing is not None:
        return existing
    if due_at is None and due_days is not None:
        due_at = datetime.now(timezone.utc) + timedelta(days=due_days)
    assignee = None
    if assign_role:
        users = role_recipients(db, tenant_id, (assign_role,))
        assignee = users[0].id if users else None
    task = Task(
        tenant_id=tenant_id,
        title=title,
        description=description,
        priority=priority,
        due_at=due_at,
        assignee_user_id=assignee,
        created_by=created_by,
        entity_type=entity_type,
        entity_id=entity_id,
        source="system",
    )
    db.add(task)
    db.flush()
    return task


def materialize_task_rules(
    db: Session,
    tenant_id: UUID,
    trigger_entity_type: str,
    context: dict,
    *,
    entity_id: UUID | None = None,
    created_by: UUID | None = None,
) -> list[Task]:
    """把 evaluate_task_rules 的 dry-run 结果真正物化成 Task 行。

    TaskRule（配置 → 任务）原本只有 dry-run 端点，没有物化入口——
    这里补齐：规则命中 → 按实体+标题幂等建任务 → 分派到规则指定角色。
    """
    from app.services.alert_engine import evaluate_task_rules

    created: list[Task] = []
    for spec in evaluate_task_rules(db, tenant_id, trigger_entity_type, context):
        due = datetime.fromisoformat(spec["due_date"]) if spec.get("due_date") else None
        created.append(
            ensure_task(
                db,
                tenant_id,
                title=spec["title"],
                description=spec.get("description"),
                entity_type=trigger_entity_type,
                entity_id=entity_id,
                due_at=due,
                assign_role=spec.get("assign_to_role"),
                created_by=created_by,
            )
        )
    return created


def notify_task(
    db: Session,
    tenant_id: UUID,
    task: Task,
    *,
    assign_role: str | None = None,
    level: str = "info",
    href: str | None = None,
) -> None:
    """给任务的承接方发一条去重通知（无 assignee 时按角色广播）。"""
    if task.assignee_user_id is not None:
        user = db.get(User, task.assignee_user_id)
        recipients = [user] if user is not None else []
    elif assign_role:
        recipients = role_recipients(db, tenant_id, (assign_role,))
    else:
        recipients = []
    notify_once(
        db,
        tenant_id,
        list(recipients),
        title=task.title,
        body=task.description or "",
        href=href or "/tasks",
        level=level,
    )
