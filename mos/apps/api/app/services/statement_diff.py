"""Laytime statement 对账（Phase 1 / D12）：我方 vs 对手方计算书差异。

输入为 ``compute_laytime_statement`` 同构的结算单 JSON（对手方版本通常来自
邮件解析 parse_laytime_statement 或人工誊录）。输出：
- ``field_diffs``：口径字段（allowed/used/excluded/balance/amount）差异；
- ``event_diffs``：按 (start,end) 对齐的事件小时差异。
"""

from __future__ import annotations

from typing import Any

COMPARE_FIELDS = ("allowed_hours", "used_hours", "excluded_hours", "balance_hours", "amount")


def _num_eq(a: Any, b: Any, tol: float = 0.01) -> bool:
    if a is None or b is None:
        return a == b
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return a == b


def diff_statements(mine: dict[str, Any], theirs: dict[str, Any]) -> dict[str, Any]:
    field_diffs = []
    for f in COMPARE_FIELDS:
        a, b = mine.get(f), theirs.get(f)
        if a is None and b is None:
            continue
        if not _num_eq(a, b):
            delta = None
            try:
                delta = round(float(b) - float(a), 2)
            except (TypeError, ValueError):
                pass
            field_diffs.append({"field": f, "mine": a, "theirs": b, "delta": delta})

    def _event_map(st: dict[str, Any]) -> dict[tuple, dict]:
        out = {}
        for ev in st.get("events") or []:
            out[(str(ev.get("start")), str(ev.get("end")))] = ev
        return out

    mine_ev = _event_map(mine)
    theirs_ev = _event_map(theirs)
    event_diffs = []
    for key in sorted(set(mine_ev) | set(theirs_ev)):
        a, b = mine_ev.get(key), theirs_ev.get(key)
        if a is None:
            event_diffs.append({"start": key[0], "end": key[1], "mine": None, "theirs": b.get("counted_hours"), "delta": None, "issue": "only_theirs"})
            continue
        if b is None:
            event_diffs.append({"start": key[0], "end": key[1], "mine": a.get("counted_hours"), "theirs": None, "delta": None, "issue": "only_mine"})
            continue
        if not _num_eq(a.get("counted_hours"), b.get("counted_hours")):
            delta = round(float(b.get("counted_hours") or 0) - float(a.get("counted_hours") or 0), 2)
            event_diffs.append({"start": key[0], "end": key[1], "mine": a.get("counted_hours"), "theirs": b.get("counted_hours"), "delta": delta, "issue": "hours"})

    return {
        "match": not field_diffs and not event_diffs,
        "field_diffs": field_diffs,
        "event_diffs": event_diffs,
    }
