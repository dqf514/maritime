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
from decimal import Decimal
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
    """注册事件处理器：``@on("voyage.completed")`` → 函数签名 (db, ev)。

    ``@on("*")`` 注册**通配处理器** —— 任何事件到达都会跑（跑在专用处理器之后）。
    """

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
    # 具体 kind 的处理器先跑，通配 "*" 的处理器后跑（通用兜底）。
    handlers = list(_HANDLERS.get(ev.kind, [])) + list(_HANDLERS.get("*", []))
    for fn in handlers:
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
    action_code: str | None = None,
    dedupe_key: str | None = None,
    weight: Decimal | None = None,
    auto_complete: bool | None = None,
    assign_strategy: str = "role",
    assign_user_id: UUID | None = None,
    assign_unit_id: UUID | None = None,
) -> Task:
    """幂等创建系统跟进任务：同实体 + 同标题的活跃任务已存在则复用。

    幂等优先按 ``dedupe_key``（真正的不变键 —— 改标题也不重复建），
    没有 dedupe_key 时退回"同实体 + 同标题"的旧口径。

    承接人经 :mod:`app.services.assignment` 的策略解析器决定：
    ``role`` 策略在角色下有多人时**负载最低优先**（取代旧代码"第一个用户"
    的任意规则）；角色下无人时任务照建（assignee 为空，管理层视角仍可见）。
    """
    if dedupe_key:
        existing = db.scalar(
            select(Task).where(
                Task.tenant_id == tenant_id,
                Task.dedupe_key == dedupe_key,
                # 回收站里删掉的任务不该再挡住重建（否则系统任务删掉后永远建不回来）
                Task.status != "deleted",
            )
        )
        if existing is not None:
            return existing
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
    if assign_user_id is not None:
        strategy, role_code, user_id, unit_id = "user", None, assign_user_id, None
    elif assign_role:
        strategy, role_code, user_id, unit_id = assign_strategy, assign_role, None, assign_unit_id
    elif assign_strategy in ("manager", "self"):
        # 这两个策略不依赖角色："manager"=触发人上级，"self"=触发人自己
        strategy, role_code, user_id, unit_id = assign_strategy, None, None, None
    else:
        strategy = None
    if strategy is not None:
        from app.services.assignment import resolve_assignment

        assignment = resolve_assignment(
            db,
            tenant_id,
            strategy=strategy,
            role_code=role_code,
            user_id=user_id,
            unit_id=unit_id,
            actor_user_id=created_by,
        )
        assignee = assignment.assignee_user_id
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
        action_code=action_code,
        dedupe_key=dedupe_key,
        weight=weight if weight is not None else Decimal("1"),
        auto_complete=bool(auto_complete) if auto_complete is not None else bool(action_code),
    )
    db.add(task)
    db.flush()
    # 审计补齐：系统生成的任务以前完全不留痕 —— 现在建任务即留痕
    # （动作目录、绑定实体、承接人、幂等键都要可追溯）。
    from app.services.audit import audit

    audit(
        db,
        action="task.create.system",
        tenant_id=tenant_id,
        actor_user_id=created_by,
        entity_type="task",
        entity_id=task.id,
        detail={
            "title": task.title,
            "entity_type": entity_type,
            "entity_id": str(entity_id) if entity_id else None,
            "assignee_user_id": str(assignee) if assignee else None,
            "action_code": action_code,
            "dedupe_key": dedupe_key,
            "source": "system",
        },
    )
    return task


def materialize_task_rules(
    db: Session,
    tenant_id: UUID,
    trigger_entity_type: str,
    context: dict,
    *,
    entity_id: UUID | None = None,
    created_by: UUID | None = None,
    round_key: str | None = None,
) -> list[Task]:
    """把 evaluate_task_rules 的 dry-run 结果真正物化成 Task 行。

    TaskRule（配置 → 任务）原本只有 dry-run 端点，没有物化入口——
    这里补齐：规则命中 → 按实体+标题幂等建任务 → 分派到规则指定角色。

    幂等键用 ``rule:<rule_id>:<entity_type>:<entity_id>[:<轮次>]``（真不变键）：
    规则标题改了也不会重复建同一条任务；``round_key`` 区分"同一实体的不同轮次"
    （例如航次重开后再次完成）。
    """
    from app.services.alert_engine import evaluate_task_rules

    created: list[Task] = []
    for spec in evaluate_task_rules(db, tenant_id, trigger_entity_type, context):
        due = datetime.fromisoformat(spec["due_date"]) if spec.get("due_date") else None
        rule_id = spec.get("rule_id") or "?"
        # 幂等键带"轮次"：同一实体重新走一轮（航次重开后再次完成）应再出一条
        # 跟进任务，而不是被上一轮的任务永久挡住。
        dedupe_key = f"rule:{rule_id}:{trigger_entity_type}:{entity_id or 'none'}"
        if round_key:
            dedupe_key = f"{dedupe_key}:{round_key}"
        weight = spec.get("weight")
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
                action_code=spec.get("action_code"),
                dedupe_key=dedupe_key,
                weight=Decimal(str(weight)) if weight is not None else None,
                assign_strategy=spec.get("assign_strategy") or "role",
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
