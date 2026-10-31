"""任务到期口径 —— 后端分桶/过滤与前端展示必须是同一套。

口径：**UTC 自然日**（与前端 ``apps/web/lib/datetime.ts::utcDayDiff`` 一致）。

    逾期       到期日（UTC）< 今日（UTC）
    今日到期   到期日 == 今日
    本周       到期日在今日之后 7 天内（含第 7 天）
    稍后       其余，或没有到期时间

以前后端用「本地日期 + 时间戳比较」，前端用「UTC 日期比较」：
同一批任务在页签角标（后端计数）和列表（前端分桶）里会落到不同的桶 ——
角标写「逾期 12」，列表里却有 4 条排在「今日到期」，用户点进去才发现对不上。

现在全站统一走这里：``home.py`` 的面板分桶、``tasks.py`` 的 ``overdue``
筛选与统计都调用同一套函数，避免再分叉。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

BUCKETS = ("overdue", "today", "week", "later", "done")

# 本周窗口：今日之后 7 天（含第 7 天）
WEEK_SPAN_DAYS = 7


def utc_now() -> datetime:
    """当前 UTC 时间（aware）。"""
    return datetime.now(timezone.utc)


def utc_today(now: datetime | None = None) -> date:
    """今日（UTC 日期）—— 不要用 ``date.today()``，那是本地日期。"""
    return (now or utc_now()).date()


def utc_day_start(now: datetime | None = None) -> datetime:
    """今日 00:00 UTC（aware）—— 可直接用于 SQL 比较（SQLite / PG 都按 UTC 解释）。"""
    base = now or utc_now()
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _utc_date(dt: datetime) -> date:
    """取 UTC 日期 —— naive 按平台约定即 UTC，aware 先转成 UTC。"""
    if dt.tzinfo is None:
        return dt.date()
    return dt.astimezone(timezone.utc).date()


def bucket_of(due_at: datetime | None, now: datetime | None = None) -> str:
    """单个到期时间落在哪个桶（``later`` 表示无到期时间）。"""
    if due_at is None:
        return "later"
    now = now or utc_now()
    today = _utc_date(now)
    due_day = _utc_date(due_at)
    if due_day < today:
        return "overdue"
    if due_day == today:
        return "today"
    if due_day <= today + timedelta(days=WEEK_SPAN_DAYS):
        return "week"
    return "later"


def is_overdue(due_at: datetime | None, now: datetime | None = None) -> bool:
    """是否逾期（今日到期的**不算**逾期 —— 与前端 "Due today" 标签一致）。"""
    return bucket_of(due_at, now) == "overdue"


def is_due_today(due_at: datetime | None, now: datetime | None = None) -> bool:
    return bucket_of(due_at, now) == "today"
