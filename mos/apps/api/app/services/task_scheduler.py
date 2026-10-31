"""任务自动完成的兜底扫描调度器。

**为什么要它**：任务绑定的系统动作若是在别处手工改的状态（例如财务直接在
单据上勾了「已过账」，没有走会发域事件的端点），事件即时通道就收不到信号。
这条 tick 每 5 分钟跑一遍判定器，把这类漏网的补上。

与 :mod:`app.services.task_completion` 的关系：
tick 只负责"排下一次 + 调 :func:`scan_tenant`"，判定与完成逻辑全在
task_completion 里 —— 单一实现。

幂等性：``scan_tenant`` 只在判定器命中且任务未完成时才写库，重复跑无害。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

log = logging.getLogger("marios.task_scheduler")

#: 兜底扫描 tick
TICK_KIND = "task.completion_tick"
TICK_INTERVAL = timedelta(minutes=5)


def _has_live_tick(db: Session, kind: str) -> bool:
    from app.models_jobs import Job

    return (
        db.scalar(
            select(Job.id).where(Job.kind == kind, Job.status.in_(("pending", "running"))).limit(1)
        )
        is not None
    )


def _tick(db: Session, _job: Any) -> None:
    """Job handler：先排下一次 tick，再干活。

    先排后干是本仓 tick 的统一写法 —— 否则本次抛异常时整条链就断了
    （job_queue 只会重试同一个 job，不会补排下一次）。
    """
    from app.models import Tenant
    from app.services.job_queue import enqueue
    from app.services.task_completion import scan_tenant

    next_at = datetime.now(timezone.utc) + TICK_INTERVAL
    enqueue(
        db,
        TICK_KIND,
        {},
        run_after=next_at,
        idempotency_key=f"task-tick:{next_at.strftime('%Y%m%d%H%M')}",
    )
    total = 0
    for tenant_id in db.scalars(select(Tenant.id).where(Tenant.status != "deleted")).all():
        try:
            total += scan_tenant(db, tenant_id)
        except Exception:  # noqa: BLE001 — 隔离单租户失败
            log.exception("task completion scan failed: tenant=%s", tenant_id)
            db.rollback()
    if total:
        log.info("task completion tick auto-completed %s task(s)", total)
    db.commit()


def register_handlers() -> None:
    from app.services.job_queue import job_handler

    job_handler(TICK_KIND)(_tick)


def install_scheduler(db: Session) -> None:
    """注册周期 tick（幂等 —— 已有活跃 tick 就不再排队）。"""
    from app.services.job_queue import enqueue

    if _has_live_tick(db, TICK_KIND):
        return
    enqueue(
        db,
        TICK_KIND,
        {},
        run_after=datetime.now(timezone.utc),
        idempotency_key=f"task-tick:bootstrap:{uuid.uuid4().hex[:12]}",
    )
