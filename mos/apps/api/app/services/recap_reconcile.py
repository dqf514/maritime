"""Recap 双向对账（长尾 / D3）：邮件 Fixture Recap 解析字段 ↔ 租约（CP）字段。

对可比字段做逐项差异（数值容差 0.01；字符串去空白不区分大小写），
差异清单回流人工确认（与 D25 的 _rule_diffs 同一确认语义）。
"""

from __future__ import annotations

from typing import Any

from app.models_domain import Charter

# recap 字段 → 租约属性（数值）
NUMERIC_MAP = {
    "freight_rate": "freight_rate",
    "demurrage_rate": "demurrage_rate",
    "despatch_rate": "despatch_rate",
    "commission": "commission_pct",
}
# recap 字段 → (租约属性, 字符串比较)
STRING_MAP = {
    "cp_form": "cp_form",
    "laytime_load": None,  # 数值但单位为天/时，租约无单列，跳过
}


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def reconcile_recap(recap: dict[str, Any], charter: Charter) -> dict[str, Any]:
    field_diffs = []
    matched = 0
    for recap_key, attr in NUMERIC_MAP.items():
        if recap_key not in recap or recap[recap_key] is None:
            continue
        charter_val = getattr(charter, attr, None)
        if charter_val is None:
            continue
        try:
            a = float(recap[recap_key])
            b = float(charter_val)
        except (TypeError, ValueError):
            continue
        if abs(a - b) <= 0.01:
            matched += 1
        else:
            field_diffs.append({"field": recap_key, "recap_value": a, "charter_value": b, "delta": round(a - b, 2)})

    # 字符串字段（cp_form 等）
    if recap.get("cp_form") and charter.cp_form:
        if _norm(recap["cp_form"]) == _norm(charter.cp_form):
            matched += 1
        else:
            field_diffs.append({"field": "cp_form", "recap_value": recap["cp_form"], "charter_value": charter.cp_form, "delta": None})

    return {
        "match": not field_diffs,
        "matched_fields": matched,
        "field_diffs": field_diffs,
    }
