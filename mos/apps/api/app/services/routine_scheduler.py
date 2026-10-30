"""例行任务调度器 —— 两个 tick。

* ``routine.tick`` —— 扫描到期的例行任务（入站邮件腿），产出待确认草稿。
* ``email.sync_tick`` —— 定时拉取 Graph 邮箱（新邮件进来才有机会被例行任务命中）。

两条腿都挂在 :mod:`app.services.job_queue` 上（at-least-once），因此
**handler 必须幂等**：

* 例行任务腿靠 ``(tenant_id, dedupe_key)`` 唯一约束挡重复草稿；
* 同步腿靠 ``EmailMessage.message_id`` 去重。

单进程 worker 已在 :func:`app.services.job_queue.run_worker` 里跑，compose
只部署一个 API 副本 —— 但即便多副本，幂等键也保证不产生重复草稿。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_routine import RoutineTask
from app.models_wave1 import EmailAccount

log = logging.getLogger("marios.routine_scheduler")

#: 例行任务 tick（分钟）
TICK_KIND = "routine.tick"
TICK_INTERVAL = timedelta(minutes=5)

#: 邮箱同步 tick（分钟）—— 拉邮件比跑任务重，间隔更大
EMAIL_SYNC_TICK_KIND = "email.sync_tick"
EMAIL_SYNC_INTERVAL = timedelta(minutes=10)

#: 单个 tick 内处理的任务数上限
MAX_TASKS_PER_TICK = 50


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------


def run_due_routine_tasks(db: Session, now: datetime | None = None) -> int:
    """跑一遍所有启用的例行任务 —— 返回本次产生的草稿数。

    单任务失败隔离：一条任务炸了不影响其它任务（失败落 ``status="failed"`` 的草稿，
    由 :mod:`app.services.routine_engine` 负责显性化）。
    """
    from app.services.routine_engine import run_task

    now = now or datetime.now(timezone.utc)
    tasks = db.scalars(
        select(RoutineTask)
        .where(
            RoutineTask.enabled.is_(True),
            RoutineTask.deleted_at.is_(None),
        )
        .order_by(RoutineTask.code)
        .limit(MAX_TASKS_PER_TICK)
    ).all()

    produced = 0
    for task in tasks:
        try:
            drafts = run_task(db, tenant_id=task.tenant_id, task=task)
            produced += len(drafts)
        except Exception:  # noqa: BLE001 — 隔离单条任务失败
            log.exception("routine task %s failed", task.code)
            db.rollback()
    db.commit()
    return produced


def sync_all_accounts(db: Session) -> int:
    """拉一遍所有 Graph 邮箱 —— 返回新同步的邮件数。

    只有 ``provider`` 命中 Graph 且 ``status`` 非 disabled 的账户才拉。
    """
    from app.services.email_sync import GRAPH_PROVIDERS, sync_graph_mails

    accounts = db.scalars(
        select(EmailAccount).where(EmailAccount.provider.in_(tuple(GRAPH_PROVIDERS)))
    ).all()
    total = 0
    for account in accounts:
        if (account.status or "active").lower() not in ("active", "connected", "enabled"):
            continue
        try:
            outcome = sync_graph_mails(db, tenant_id=account.tenant_id, account=account)
            total += len(outcome.new_message_db_ids)
            account.last_sync_at = datetime.now(timezone.utc)
        except Exception:  # noqa: BLE001 — 隔离单账户失败
            log.warning("routine_scheduler: email sync failed for account %s", account.id, exc_info=True)
            db.rollback()
    db.commit()
    return total


# ---------------------------------------------------------------------------
# Job-queue wiring
# ---------------------------------------------------------------------------


def _has_live_tick(db: Session, kind: str) -> bool:
    from app.models_jobs import Job

    return (
        db.scalar(
            select(Job.id).where(Job.kind == kind, Job.status.in_(("pending", "running"))).limit(1)
        )
        is not None
    )


def install_scheduler(db: Session) -> None:
    """注册两个周期 tick（幂等 —— 已有活跃 tick 就不再排队）。"""
    from app.services.job_queue import enqueue

    now = datetime.now(timezone.utc)
    if not _has_live_tick(db, TICK_KIND):
        enqueue(
            db,
            TICK_KIND,
            {},
            run_after=now,
            idempotency_key=f"routine-tick:bootstrap:{uuid.uuid4().hex[:12]}",
        )
    if not _has_live_tick(db, EMAIL_SYNC_TICK_KIND):
        enqueue(
            db,
            EMAIL_SYNC_TICK_KIND,
            {},
            run_after=now,
            idempotency_key=f"email-sync-tick:bootstrap:{uuid.uuid4().hex[:12]}",
        )


def _tick(db: Session, _job: Any) -> None:
    """Job handler: 跑例行任务并排下一次 tick。

    **先排下一次再干活** —— 否则本次处理抛异常时整条 tick 链就断了
    （job_queue 把异常转成重试，但重试的是同一个 job，不会补排下一次）。
    """
    from app.services.job_queue import enqueue

    next_at = datetime.now(timezone.utc) + TICK_INTERVAL
    enqueue(
        db,
        TICK_KIND,
        {},
        run_after=next_at,
        idempotency_key=f"routine-tick:{next_at.strftime('%Y%m%d%H%M')}",
    )
    run_due_routine_tasks(db)


def _sync_tick(db: Session, _job: Any) -> None:
    """Job handler: 拉邮箱并排下一次 tick（同上：先排后干）。"""
    from app.services.job_queue import enqueue

    next_at = datetime.now(timezone.utc) + EMAIL_SYNC_INTERVAL
    enqueue(
        db,
        EMAIL_SYNC_TICK_KIND,
        {},
        run_after=next_at,
        idempotency_key=f"email-sync-tick:{next_at.strftime('%Y%m%d%H%M')}",
    )
    sync_all_accounts(db)


def register_handlers() -> None:
    from app.services.job_queue import job_handler

    job_handler(TICK_KIND)(_tick)
    job_handler(EMAIL_SYNC_TICK_KIND)(_sync_tick)
