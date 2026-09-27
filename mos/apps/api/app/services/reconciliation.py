"""银行核销（Phase 2 / D21）：银行流水 ↔ 未结发票 的配对建议与入账。

配对评分：
- 金额一致 且 reference 含发票号 → 1.0（强匹配）
- 金额一致 且 reference 含对手方名片段 → 0.8
- 仅金额一致 → 0.6（需人工确认）
金额容差 0.01；一笔流水只建议一个最佳候选（贪心），落选流水进 unmatched。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.models_domain import Invoice


def _norm(s: str | None) -> str:
    return (s or "").lower().replace(" ", "")


def score_line(line: dict[str, Any], inv: Invoice, counterparty_name: str | None) -> float | None:
    try:
        amt = Decimal(str(line.get("amount"))).quantize(Decimal("0.01"))
    except Exception:  # noqa: BLE001
        return None
    inv_total = Decimal(str(inv.amount)) + Decimal(str(inv.tax_amount or 0))
    if amt != inv_total.quantize(Decimal("0.01")):
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
            s = score_line(line, inv, counterparty_names.get(str(inv.counterparty_id or "")))
            if s is not None:
                candidates.append((s, idx, inv))
    used_lines: set[int] = set()
    for s, idx, inv in sorted(candidates, key=lambda c: (-c[0], c[1])):
        if idx in used_lines or str(inv.id) in used_invoices:
            continue
        used_lines.add(idx)
        used_invoices.add(str(inv.id))
        reason = "amount+invoice_no" if s >= 1.0 else "amount+counterparty" if s >= 0.8 else "amount_only"
        suggestions.append(
            {"line_index": idx, "invoice_id": str(inv.id), "invoice_no": inv.invoice_no, "score": s, "reason": reason}
        )
    for idx in range(len(lines)):
        if idx not in used_lines:
            unmatched.append(idx)
    return {"suggestions": suggestions, "unmatched": unmatched}
