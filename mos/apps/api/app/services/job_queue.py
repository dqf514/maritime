"""Background job queue (Phase 0) — enqueue / claim / retry with backoff.

用法：
    from app.services.job_queue import enqueue, job_handler

    enqueue(db, "webhook.deliver", {"delivery_id": ...}, tenant_id=tid,
            idempotency_key=f"webhook:{delivery_id}")

    @job_handler("my.kind")
    def _handle(db: Session, job: Job) -> None:
        ...  # 抛异常即重试（指数退避），attempts 耗尽转 dead

语义：at-least-once —— handler 必须幂等（用 idempotency_key 去重入队，
handler 内对已完成状态短路）。单进程 worker 以 pending→running 转移为租约；
worker 崩溃留下的 running 任务由 reclaim_stale() 按超时回收。
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_jobs import Job

log = logging.getLogger("marios.jobs")

Handler = Callable[[Session, Job], None]
HANDLERS: dict[str, Handler] = {}

# running 超过该时长视为 worker 崩溃遗留，回收重跑
STALE_RUNNING = timedelta(minutes=15)


def job_handler(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return deco


def enqueue(
    db: Session,
    kind: str,
    payload: dict[str, Any],
    *,
    tenant_id: Any = None,
    run_after: datetime | None = None,
    max_attempts: int = 5,
    idempotency_key: str | None = None,
) -> Job:
    if idempotency_key:
        existing = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
        if existing is not None:
            return existing
    job = Job(
        tenant_id=tenant_id,
        kind=kind,
        payload=payload,
        run_after=run_after or datetime.now(timezone.utc),
        max_attempts=max_attempts,
        idempotency_key=idempotency_key,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(300, 5 * (2 ** max(0, attempts - 1))))


def reclaim_stale(db: Session) -> int:
    """回收崩溃遗留的 running 任务（租约超时）。"""
    cutoff = datetime.now(timezone.utc) - STALE_RUNNING
    stale = db.scalars(select(Job).where(Job.status == "running", Job.updated_at < cutoff)).all()
    for job in stale:
        job.status = "pending"
        job.last_error = (job.last_error or "") + " [reclaimed stale running]"
    db.commit()
    return len(stale)


def _claim_next(db: Session) -> Job | None:
    now = datetime.now(timezone.utc)
    job = db.scalar(
        select(Job)
        .where(Job.status == "pending", Job.run_after <= now)
        .order_by(Job.run_after)
        .limit(1)
    )
    if job is None:
        return None
    job.status = "running"
    db.commit()
    db.refresh(job)
    return job


def _run_job(db: Session, job: Job) -> None:
    handler = HANDLERS.get(job.kind)
    if handler is None:
        job.status = "dead"
        job.last_error = f"no handler registered for kind={job.kind}"
        db.commit()
        return
    try:
        handler(db, job)
        job.status = "done"
        job.attempts += 1
        job.last_error = None
        db.commit()
    except Exception as exc:  # noqa: BLE001 — 所有 handler 异常都进重试路径
        job.attempts += 1
        job.last_error = f"{type(exc).__name__}: {exc}"[:2000]
        if job.attempts >= job.max_attempts:
            job.status = "dead"
            log.error("job %s (%s) dead after %s attempts: %s", job.id, job.kind, job.attempts, job.last_error)
        else:
            job.status = "pending"
            job.run_after = datetime.now(timezone.utc) + _backoff(job.attempts)
            log.warning("job %s (%s) attempt %s failed, retrying: %s", job.id, job.kind, job.attempts, job.last_error)
        db.commit()


def process_pending(db: Session, *, max_jobs: int = 20) -> int:
    """消费到期任务；返回处理数量。"""
    worked = 0
    for _ in range(max_jobs):
        job = _claim_next(db)
        if job is None:
            break
        _run_job(db, job)
        worked += 1
    return worked


def run_worker(stop: threading.Event, *, interval: float = 2.0, max_jobs: int = 20) -> None:
    """worker 线程主循环（lifespan 启动；测试默认关闭 job_worker_enabled）。"""
    from app.db import SessionLocal

    reclaim_every = timedelta(minutes=5)
    last_reclaim = datetime.min.replace(tzinfo=timezone.utc)
    while not stop.is_set():
        try:
            with SessionLocal() as db:
                if datetime.now(timezone.utc) - last_reclaim > reclaim_every:
                    reclaim_stale(db)
                    last_reclaim = datetime.now(timezone.utc)
                worked = process_pending(db, max_jobs=max_jobs)
            if worked == 0:
                stop.wait(interval)
        except Exception:  # noqa: BLE001 — worker 不允许因单次异常退出
            log.exception("job worker tick failed")
            stop.wait(interval * 5)
