"""银行核销（Phase 2 / D21）：银行流水 ↔ 未结发票 的配对建议与入账。

配对评分：
- 金额一致 且 reference 含发票号 → 1.0（强匹配）
- 金额一致 且 reference 含对手方名片段 → 0.8
- 仅金额一致 → 0.6（需人工确认）
金额容差 0.01；一笔流水只建议一个最佳候选（贪心），落选流水进 unmatched。

**币种必须一致**：同额不同币种不是同一笔钱（P1-B14）。流水行带 ``currency``
（或 ``ccy``）时按币种硬比较；流水行没带币种时无法核对币种，建议里会带上
``currency_verified=false`` 提醒人工确认。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.models_domain import Invoice

# 文档承诺的金额容差
_AMOUNT_TOLERANCE = Decimal("0.01")


def _norm(s: str | None) -> str:
    return (s or "").lower().replace(" ", "")


def _ccy(v: Any) -> str:
    return str(v or "").strip().upper()


def score_line(
    line: dict[str, Any],
    inv: Invoice,
    counterparty_name: str | None,
    *,
    default_currency: str | None = None,
) -> float | None:
    """Score one bank line against one invoice; ``None`` = 不匹配。

    - 币种必须相同（流水行没给币种时无法核对，按未知处理）；
    - 金额在 0.01 容差内即算一致（文档口径，之前根本没实现，是精确相等）。
    """
    try:
        amt = Decimal(str(line.get("amount")))
    except Exception:  # noqa: BLE001
        return None
    inv_total = Decimal(str(inv.amount)) + Decimal(str(inv.tax_amount or 0))
    inv_ccy = _ccy(getattr(inv, "currency", None) or "USD")
    line_ccy = _ccy(line.get("currency") or line.get("ccy")) or _ccy(default_currency)
    if line_ccy and line_ccy != inv_ccy:
        return None
    if abs(amt - inv_total) > _AMOUNT_TOLERANCE:
        return None
    ref = _norm(line.get("reference"))
    if ref and inv.invoice_no and inv.invoice_no.lower() in ref:
        return 1.0
    if ref and counterparty_name and _norm(counterparty_name) in ref:
        return 0.8
    return 0.6


def suggest_matches(
    lines: list[dict[str, Any]],
    invoices: list[Invoice],
    counterparty_names: dict[str, str] | None = None,
    *,
    default_currency: str | None = None,
) -> dict[str, list]:
    """返回 {suggestions: [{line_index, invoice_id, invoice_no, score, reason}], unmatched: [line_index]}。"""
    counterparty_names = counterparty_names or {}
    suggestions: list[dict[str, Any]] = []
    unmatched: list[int] = []
    used_invoices: set[str] = set()
    # 先按分数从高到低贪心配对
    candidates: list[tuple[float, int, Invoice]] = []
    for idx, line in enumerate(lines):
        for inv in invoices:
            if str(inv.id) in used_invoices:
                continue
            s = score_line(
                line,
                inv,
                counterparty_names.get(str(inv.counterparty_id or "")),
                default_currency=default_currency,
            )
            if s is not None:
                candidates.append((s, idx, inv))
    used_lines: set[int] = set()
    for s, idx, inv in sorted(candidates, key=lambda c: (-c[0], c[1])):
        if idx in used_lines or str(inv.id) in used_invoices:
            continue
        used_lines.add(idx)
        used_invoices.add(str(inv.id))
        reason = "amount+invoice_no" if s >= 1.0 else "amount+counterparty" if s >= 0.8 else "amount_only"
        line_ccy = _ccy(lines[idx].get("currency") or lines[idx].get("ccy")) or _ccy(default_currency)
        suggestions.append(
            {
                "line_index": idx,
                "invoice_id": str(inv.id),
                "invoice_no": inv.invoice_no,
                "score": s,
                "reason": reason,
                "currency": _ccy(getattr(inv, "currency", None) or "USD"),
                # 流水行没带币种时币种无法核对 → 人工确认时必须看得见
                "currency_verified": bool(line_ccy),
            }
        )
    for idx in range(len(lines)):
        if idx not in used_lines:
            unmatched.append(idx)
    return {"suggestions": suggestions, "unmatched": unmatched}
