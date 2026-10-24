"""CSV / Excel 公式注入防护（P0-16 / P0-17）。

**规则与前端 ``apps/web/lib/csv.ts`` 完全一致**，三处必须同步改：

    = + @ \\t \\r 开头 → 前置单引号
    以 ``-`` 开头但不是纯数字（``-12`` / ``-12.50`` 除外）→ 前置单引号

为什么需要：CSV 是纯文本，客户用 Excel 打开时，``=HYPERLINK("http://evil","点击")``
这类单元格会被 Excel **当成公式执行**（钓鱼链接、DDE 外部引用）。租户可以自由
填写对手方名 / 备注 / 货名 —— 这些字段直接落到导出文件里。

历史事故：报表设计器导出（``services/report_engine.export_report_csv``）与
XLSX 导出都绕过了 ``routers/exports.py`` 里已有的防护，导出的对手方名如果以
``=`` 开头，在 Excel 里点开就是一条可执行公式。
"""

from __future__ import annotations

import re
from typing import Any

#: 与前端 ``lib/csv.ts`` 的 ``guardFormula`` 同一套规则
_FORMULA_PREFIX = re.compile(r"^[=+@\t\r]")
_NUMERIC_MINUS = re.compile(r"^-\d+(?:\.\d+)?$")


def is_formula_like(value: str) -> bool:
    """这个字符串在 Excel 里会不会被当成公式？"""
    if not value:
        return False
    if _FORMULA_PREFIX.match(value):
        return True
    return value.startswith("-") and not _NUMERIC_MINUS.match(value)


def guard_csv_cell(value: Any) -> Any:
    """CSV 单元格公式注入防护（非字符串原样返回）。"""
    if not isinstance(value, str) or not value:
        return value
    if is_formula_like(value):
        return "'" + value
    return value


def guard_csv_row(row: list[Any]) -> list[Any]:
    return [guard_csv_cell(v) for v in row]


def guard_csv_rows(rows: list[list[Any]]) -> list[list[Any]]:
    return [guard_csv_row(r) for r in rows]


def force_text_cell(cell) -> None:
    """openpyxl 专用：把单元格强制写成**文本**而不是公式。

    openpyxl 见到以 ``=`` 开头的字符串会自己把 ``data_type`` 设成 ``f``
    （公式）。写完值再把 ``data_type`` 压回 ``'s'``，值本身不变，但 Excel
    打开时不会再执行它。
    """
    try:
        cell.data_type = "s"
    except Exception:  # pragma: no cover - openpyxl 内部结构变化时的兜底
        pass
