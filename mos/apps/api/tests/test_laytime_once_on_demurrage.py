"""D9 条款语义：once on demurrage, always on demurrage。

金样手工推演：
- allowed 24h（无 turn time）；terms SHEX（周六/日除外）
- E1: 2026-01-05(一) 00:00 → 01-06 00:00 = 24h 工作时间 → used=24，恰好用尽
- E2: 2026-01-10(六) 00:00 → 01-11 00:00 = 24h 条款除外
  · 默认：E2 不计 → balance=0 → amount=0
  · once_on_demurrage：已达允许时间，E2 挂钟时间全计 → used=48
    balance=24h → 滞期 1 天 × 24000 = 24000
"""

from __future__ import annotations

from app.services.laytime_engine import compute_laytime, compute_laytime_statement

EVENTS = [
    {"start": "2026-01-05T00:00:00", "end": "2026-01-06T00:00:00", "excluded": False},
    {"start": "2026-01-10T00:00:00", "end": "2026-01-11T00:00:00", "excluded": False},
]

BASE = {
    "allowed_hours": 24,
    "demurrage_rate_per_day": 24000,
    "terms": "SHEX",
    "events": EVENTS,
}


def test_default_behavior_unchanged():
    r = compute_laytime(BASE)
    assert r["used_hours"] == 24.0
    assert r["result_type"] == "on_time"
    assert r["amount"] == 0.0


def test_once_on_demurrage_counts_excepted_time():
    r = compute_laytime({**BASE, "once_on_demurrage": True})
    assert r["used_hours"] == 48.0
    assert r["result_type"] == "demurrage"
    assert r["amount"] == 24000.0


def test_once_on_demurrage_mid_event_crossing():
    """过界发生在事件中段：过界后的除外时段也要计。"""
    # E1: 周一 00:00 → 周二 00:00，24h 全计 → used=24=allowed，进入 demurrage
    # E2: 跨周六（除外日）+ 周日的 48h → 全计
    r = compute_laytime(
        {
            "allowed_hours": 24,
            "demurrage_rate_per_day": 12000,
            "terms": "SHEX",
            "once_on_demurrage": True,
            "events": [
                {"start": "2026-01-05T00:00:00", "end": "2026-01-06T00:00:00", "excluded": False},
                {"start": "2026-01-09T12:00:00", "end": "2026-01-11T12:00:00", "excluded": False},
            ],
        }
    )
    assert r["used_hours"] == 72.0  # 24 + 48
    assert r["amount"] == 24000.0  # 48h balance → 2 days × 12000


def test_once_on_demurrage_caller_excluded_still_stops_clock():
    """调用方显式 excluded 的中断仍然不计（过界后也一样）。"""
    r = compute_laytime(
        {
            "allowed_hours": 24,
            "demurrage_rate_per_day": 24000,
            "terms": "SHINC",
            "once_on_demurrage": True,
            "events": [
                {"start": "2026-01-05T00:00:00", "end": "2026-01-06T00:00:00", "excluded": False},  # used=24
                {"start": "2026-01-06T00:00:00", "end": "2026-01-07T00:00:00", "excluded": True},  # 停表 24h
                {"start": "2026-01-07T00:00:00", "end": "2026-01-08T00:00:00", "excluded": False},  # +24
            ],
        }
    )
    assert r["used_hours"] == 48.0
    assert r["amount"] == 24000.0


def test_statement_rows_reflect_rule():
    st = compute_laytime_statement({**BASE, "once_on_demurrage": True})
    rows = st["events"]
    assert rows[0]["counted_hours"] == 24.0
    assert rows[1]["counted_hours"] == 24.0  # 除外时段过界后全计
    assert rows[1]["cumulative_hours"] == 48.0
