"""自动备份调度器 — BackupSchedule 每租户一行，由 job_queue 周期 tick 驱动。

挂载点与 :mod:`app.services.report_scheduler` 同构：lifespan 注册
``backup.auto_tick`` 处理器并 enqueue 首个 tick；tick 扫描所有
``enabled`` 且 ``next_run_at <= now`` 的计划，执行**全量租户备份**
(:func:`app.services.tenant_backup.dump_tenant`)，按 ``keep_last``
裁剪旧自动备份文件与 BackupJob 记录，然后自续下一个 tick。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BackupJob, BackupSchedule
from app.security import redact_sensitive_fields

log = logging.getLogger("marios.backup_scheduler")

TICK_KIND = "backup.auto_tick"
TICK_INTERVAL = timedelta(hours=1)

FREQUENCIES: tuple[str, ...] = ("daily", "weekly")


def compute_next_run(schedule: BackupSchedule, now: datetime) -> datetime:
    """下次运行时刻（naive UTC）：daily=明天 hour_utc；weekly=下一个 weekday hour_utc。

    weekday 用 python 惯例 Mon=0 … Sun=6。
    """
    hour = max(0, min(23, int(schedule.hour_utc or 0)))
    # naive 输入按约定视为 UTC（与 run_due_schedules 一致）。
    # 注意不要对 naive 值直接 astimezone —— Python 会把它当本地时区解释，
    # 在 UTC+N 机器上会把「明天」算回今天（test_backup_scheduler_runs_due_schedule 曾踩中）。
    if now.tzinfo is None:
        now_utc = now
    else:
        now_utc = now.astimezone(timezone.utc).replace(tzinfo=None)
    candidate = (now_utc + timedelta(days=1)).replace(hour=hour, minute=0, second=0, microsecond=0)
    if schedule.frequency == "weekly":
        weekday = max(0, min(6, int(schedule.weekday or 0)))
        while candidate.weekday() != weekday:
            candidate += timedelta(days=1)
    return candidate


def _prune_old_auto_backups(db: Session, tenant_id, keep_last: int) -> int:
    """保留最近 keep_last 份 trigger=auto 的备份（文件 + 记录），返回删除数。"""
    if keep_last <= 0:
        return 0
    rows = db.scalars(
        select(BackupJob)
        .where(BackupJob.tenant_id == tenant_id, BackupJob.trigger == "auto")
        .order_by(BackupJob.created_at.desc())
    ).all()
    removed = 0
    for job in rows[keep_last:]:
        if job.storage_path:
            from pathlib import Path

            from app.services.tenant_backup import _data_root

            try:
                p = _data_root() / job.storage_path
                if p.is_file():
                    p.unlink()
            except OSError:  # pragma: no cover - 文件已不存在等
                pass
        db.delete(job)
        removed += 1
    return removed


def run_due_schedules(db: Session) -> int:
    """执行所有到期的自动备份计划；返回执行数。"""
    from app.services.tenant_backup import dump_tenant, write_backup_file

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    due = db.scalars(
        select(BackupSchedule).where(
            BackupSchedule.enabled.is_(True),
            BackupSchedule.next_run_at.is_not(None),
            BackupSchedule.next_run_at <= now,
        )
    ).all()
    ran = 0
    for schedule in due:
        try:
            payload = dump_tenant(db, schedule.tenant_id, trigger="auto")
            # P0-21：自动备份与手动备份同一套脱敏 —— 剔除 ``password_hash`` /
            # ``secret_ref`` / 明文密钥等敏感列（``security.redact_sensitive_fields``），
            # 否则定时任务落盘的仍是**全量口令哈希 + 明文 API Key**。
            redact_sensitive_fields(payload)
            write_backup_file(db, schedule.tenant_id, payload)
            _prune_old_auto_backups(db, schedule.tenant_id, schedule.keep_last or 14)
            schedule.last_run_at = now
            ran += 1
        except Exception:  # noqa: BLE001 — 单租户失败不阻塞其他租户
            log.exception("auto backup failed for tenant %s", schedule.tenant_id)
        schedule.next_run_at = compute_next_run(schedule, now)
    db.commit()
    if ran:
        log.info("auto backup ran for %d schedule(s)", ran)
    return ran


# ---------------------------------------------------------------------------
# Job-queue wiring（与 report_scheduler 同构）
# ---------------------------------------------------------------------------


def install_scheduler(db: Session) -> None:
    """Bootstrap next_run_at on enabled schedules and register the recurring tick."""
    from app.models_jobs import Job
    from app.services.job_queue import enqueue

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for schedule in db.scalars(
        select(BackupSchedule).where(BackupSchedule.enabled.is_(True), BackupSchedule.next_run_at.is_(None))
    ).all():
        schedule.next_run_at = compute_next_run(schedule, now)
    db.commit()

    live = db.scalar(
        select(Job.id).where(Job.kind == TICK_KIND, Job.status.in_(("pending", "running"))).limit(1)
    )
    if live is not None:
        return
    enqueue(
        db,
        TICK_KIND,
        {},
        run_after=datetime.now(timezone.utc),
        idempotency_key=f"backup-tick:bootstrap:{now.strftime('%Y%m%d%H%M')}",
    )


def _tick(db: Session, _job: Any) -> None:
    from app.services.job_queue import enqueue

    run_due_schedules(db)
    next_at = datetime.now(timezone.utc) + TICK_INTERVAL
    enqueue(
        db,
        TICK_KIND,
        {},
        run_after=next_at,
        idempotency_key=f"backup-tick:{next_at.strftime('%Y%m%d%H%M')}",
    )


def register_handlers() -> None:
    from app.services.job_queue import job_handler

    job_handler(TICK_KIND)(_tick)
