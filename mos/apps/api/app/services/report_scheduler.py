"""Report schedule runner — executes due ReportSchedule rows and emails results.

报告定时任务：``run_due_schedules`` 扫描到期的 ``ReportSchedule``，执行报表并按
``output_format`` 导出（csv/xlsx；pdf 回退 xlsx），经 :func:`app.services.identity.send_mail`
发送给收件人（附件）。``compute_next_run`` 计算下一次运行时间（daily/weekly/monthly
或 5 段 cron）。挂载点：job_queue 的 ``report.schedule_tick`` 任务（由
:func:`install_scheduler` 在 lifespan 注册）。
"""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models_report import ReportDefinition, ReportSchedule

log = logging.getLogger("marios.report_scheduler")

TICK_KIND = "report.schedule_tick"
TICK_INTERVAL = timedelta(minutes=5)


def _utc(dt: datetime | None) -> datetime | None:
    """Normalize to aware UTC (SQLite may hand back naive values)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ---------------------------------------------------------------------------
# Next-run computation
# ---------------------------------------------------------------------------


def _cron_field_values(field: str, lo: int, hi: int) -> set[int]:
    """Parse a single cron field: ``*``, ``n``, ``a-b``, ``*/n``, comma lists.

    Standard semantics: bare ``n`` is just ``n`` (not ``n..hi``); ``n/step``
    is ``n, n+step, ...`` up to ``hi``.
    """
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        has_step = False
        if "/" in part:
            part, step_s = part.split("/", 1)
            step = max(1, int(step_s))
            has_step = True
        if part in ("*", ""):
            values |= set(range(lo, hi + 1, step))
        elif "-" in part:
            a_s, b_s = part.split("-", 1)
            values |= set(range(int(a_s), int(b_s) + 1, step))
        else:
            start = int(part)
            if has_step:
                values |= set(range(start, hi + 1, step))
            else:
                values.add(start)
    return {v for v in values if lo <= v <= hi}


def _next_cron_run(cron: str, after: datetime) -> datetime | None:
    """Next matching time for a 5-field cron (minute hour dom month dow)."""
    fields = cron.split()
    if len(fields) != 5:
        return None
    try:
        minutes = _cron_field_values(fields[0], 0, 59)
        hours = _cron_field_values(fields[1], 0, 23)
        doms = _cron_field_values(fields[2], 1, 31)
        months = _cron_field_values(fields[3], 1, 12)
        dows = _cron_field_values(fields[4], 0, 6)
    except ValueError:
        return None
    if not (minutes and hours and doms and months and dows):
        return None

    # iterate minute-by-minute is too slow — step hour-by-hour then minute
    candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(366 * 24 * 2):  # ~2 years of hourly steps, safety cap
        if candidate.month not in months:
            # jump to the 1st of the next month
            if candidate.month == 12:
                candidate = candidate.replace(year=candidate.year + 1, month=1, day=1, hour=0, minute=0)
            else:
                candidate = candidate.replace(month=candidate.month + 1, day=1, hour=0, minute=0)
            continue
        dom_ok = candidate.day in doms
        cron_dow = (candidate.weekday() + 1) % 7  # python Mon=0 → cron Sun=0
        dow_ok = cron_dow in dows
        # standard cron: if both dom and dow are restricted, either may match
        dom_restricted = fields[2] != "*"
        dow_restricted = fields[4] != "*"
        if dom_restricted and dow_restricted:
            day_ok = dom_ok or dow_ok
        else:
            day_ok = dom_ok and dow_ok
        if not day_ok:
            candidate = (candidate + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if candidate.hour not in hours:
            candidate = (candidate + timedelta(hours=1)).replace(minute=0)
            continue
        if candidate.minute not in minutes:
            candidate += timedelta(minutes=1)
            continue
        return candidate
    return None


def compute_next_run(schedule: ReportSchedule, now: datetime | None = None) -> datetime | None:
    """Next run time for a schedule (None = on-demand / never).

    - ``cron_expression`` wins when present (5-field cron).
    - ``daily`` / ``weekly`` / ``monthly`` advance from ``now`` (or last_run_at)
      keeping the reference time-of-day.
    - ``on_demand`` → None.
    """
    now = _utc(now) or datetime.now(timezone.utc)
    kind = (schedule.schedule_type or "on_demand").lower()
    if kind == "on_demand" and not schedule.cron_expression:
        return None

    if schedule.cron_expression:
        nxt = _next_cron_run(schedule.cron_expression, _naive_utc(now) or now.replace(tzinfo=None))
        return nxt.replace(tzinfo=timezone.utc) if nxt else None

    ref = _utc(schedule.last_run_at) or now
    if ref < now:
        ref = now
    if kind == "daily":
        nxt = ref + timedelta(days=1)
    elif kind == "weekly":
        nxt = ref + timedelta(days=7)
    elif kind == "monthly":
        month = ref.month + 1
        year = ref.year
        if month > 12:
            month, year = 1, year + 1
        day = min(ref.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
        nxt = ref.replace(year=year, month=month, day=day)
    else:
        return None
    return nxt


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _attachment_payload(filename: str, content: bytes, content_type: str) -> dict[str, Any]:
    return {
        "filename": filename,
        "content_type": content_type,
        "size": len(content),
        "content_b64": base64.b64encode(content).decode("ascii"),
    }


def _build_attachment(result: dict, output_format: str, stamp: str) -> tuple[dict[str, Any], str]:
    """Return (send_mail attachment meta, human body note)."""
    from app.services.report_engine import export_report_csv, export_report_xlsx

    fmt = (output_format or "excel").lower()
    if fmt == "pdf":  # no PDF engine yet — fall back to xlsx
        fmt = "xlsx"
    if fmt in ("excel", "xlsx"):
        payload = export_report_xlsx(result)
        filename = f"report_{stamp}.xlsx"
        ctype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        payload = export_report_csv(result).encode("utf-8-sig")
        filename = f"report_{stamp}.csv"
        ctype = "text/csv"
    return _attachment_payload(filename, payload, ctype), filename


def run_due_schedules(db: Session, now: datetime | None = None) -> int:
    """Execute every due active schedule; returns the number processed.

    Per-schedule error isolation: one bad schedule never blocks the rest.
    """
    now = _utc(now) or datetime.now(timezone.utc)
    now_naive = now.replace(tzinfo=None)
    rows = db.scalars(
        select(ReportSchedule).where(
            ReportSchedule.is_active.is_(True),
            ReportSchedule.schedule_type != "on_demand",
            or_(
                ReportSchedule.next_run_at.is_(None),
                ReportSchedule.next_run_at <= now_naive,  # SQLite naive round-trip
                ReportSchedule.next_run_at <= now,  # tz-aware (Postgres)
            ),
        )
    ).all()

    processed = 0
    for schedule in rows:
        try:
            processed += _run_one(db, schedule, now)
        except Exception:  # noqa: BLE001 — 隔离单条失败
            log.exception("report schedule %s failed", schedule.id)
            db.rollback()
        db.commit()
    return processed


def _run_one(db: Session, schedule: ReportSchedule, now: datetime) -> int:
    from app.services.identity import send_mail
    from app.services.report_engine import execute_report

    report = db.get(ReportDefinition, schedule.report_id)
    if report is None:
        log.warning("report schedule %s points to missing report %s", schedule.id, schedule.report_id)
        schedule.next_run_at = compute_next_run(schedule, now)
        return 0

    result = execute_report(db, schedule.tenant_id, report, {})
    stamp = now.strftime("%Y%m%d_%H%M")
    attachment, filename = _build_attachment(result, schedule.output_format, stamp)

    recipients = [r for r in (schedule.recipients or []) if r]
    subject = f"[MariOS] Scheduled report: {report.report_name}"
    body = (
        f"Scheduled report '{report.report_name}' ({report.report_type}) finished "
        f"with {result.get('total_rows', 0)} rows.\n\n"
        f"Attachment: {filename}\n"
        f"Generated at {now.isoformat()} UTC."
    )
    for to in recipients:
        send_mail(
            db,
            to_email=to,
            subject=subject,
            body=body,
            purpose="report_schedule",
            tenant_id=schedule.tenant_id,
            meta={
                "schedule_id": str(schedule.id),
                "report_id": str(report.id),
            },
            attachments=[attachment],
        )

    schedule.last_run_at = now
    schedule.next_run_at = compute_next_run(schedule, now)
    return 1


# ---------------------------------------------------------------------------
# Job-queue wiring
# ---------------------------------------------------------------------------


def install_scheduler(db: Session) -> None:
    """Register the recurring tick job and bootstrap next_run_at on schedules."""
    from app.models_jobs import Job
    from app.services.job_queue import enqueue

    # bootstrap: schedules with no next_run_at become due at the next tick
    for schedule in db.scalars(
        select(ReportSchedule).where(
            ReportSchedule.is_active.is_(True),
            ReportSchedule.schedule_type != "on_demand",
            ReportSchedule.next_run_at.is_(None),
        )
    ).all():
        schedule.next_run_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()

    # only (re)enqueue when no live tick is already queued — the live-check is
    # the dedupe guard (a time-bucketed key would silently swallow a legitimate
    # re-bootstrap inside the same minute)
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
        idempotency_key=f"report-schedule-tick:bootstrap:{uuid.uuid4().hex[:12]}",
    )


def _tick(db: Session, _job: Any) -> None:
    """Job handler: run due schedules and re-enqueue the next tick."""
    from app.services.job_queue import enqueue

    run_due_schedules(db)
    db.commit()
    next_at = datetime.now(timezone.utc) + TICK_INTERVAL
    enqueue(
        db,
        TICK_KIND,
        {},
        run_after=next_at,
        idempotency_key=f"report-schedule-tick:{next_at.strftime('%Y%m%d%H%M')}",
    )


def register_handlers() -> None:
    from app.services.job_queue import job_handler

    job_handler(TICK_KIND)(_tick)
