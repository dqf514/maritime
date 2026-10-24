"""CSV / Excel 公式注入防护（P0-16）。

回归点：
- 报表设计器的 CSV 导出以前**绕过**了 ``routers/exports.py`` 里已有的防护；
- XLSX 导出更隐蔽：openpyxl 见到 ``=`` 开头的字符串会自己写成公式。
"""

from __future__ import annotations

from app.services.csv_safety import (
    force_text_cell,
    guard_csv_cell,
    is_formula_like,
)
from app.services.report_engine import export_report_csv, export_report_xlsx


def test_guard_blocks_formula_prefixes():
    assert guard_csv_cell('=1+1') == "'=1+1"
    assert guard_csv_cell('+SUM(A1)') == "'+SUM(A1)"
    assert guard_csv_cell('@evil') == "'@evil"
    assert guard_csv_cell('\tx') == "'\tx"
    assert guard_csv_cell('\rx') == "'\rx"
    assert guard_csv_cell('-cmd|calc') == "'-cmd|calc"


def test_guard_keeps_plain_numbers_and_text():
    assert guard_csv_cell('-12') == '-12'
    assert guard_csv_cell('-12.50') == '-12.50'
    assert guard_csv_cell('123.45') == '123.45'
    assert guard_csv_cell('Pacific Steel Mills') == 'Pacific Steel Mills'
    assert guard_csv_cell('') == ''
    assert guard_csv_cell(None) is None
    assert guard_csv_cell(42) == 42


def test_is_formula_like():
    assert is_formula_like('=x')
    assert not is_formula_like('-3')
    assert not is_formula_like('')


def test_report_csv_export_neutralises_formulas():
    result = {
        "columns": [{"key": "counterparty", "label": "Counterparty"}],
        "rows": [{"counterparty": '=HYPERLINK("http://evil","click")'}],
    }
    text = export_report_csv(result)
    # 单元格前置撇号 → Excel 打开时当文本，不会执行
    import csv
    import io

    rows = list(csv.reader(io.StringIO(text)))
    assert rows[1][0].startswith("'=")
    assert rows[1][0] == '\'=HYPERLINK("http://evil","click")'


def test_report_xlsx_export_writes_text_not_formula():
    import io

    from openpyxl import load_workbook

    result = {
        "columns": [{"key": "counterparty", "label": "Counterparty"}],
        "rows": [{"counterparty": '=1+1'}],
    }
    blob = export_report_xlsx(result)
    wb = load_workbook(io.BytesIO(blob))
    cell = wb.active.cell(row=2, column=1)
    assert cell.data_type == 's', "xlsx cell must not be written as a formula"
    assert cell.value == '=1+1'


def test_force_text_cell_is_idempotent():
    class _FakeCell:
        data_type = 'f'

    cell = _FakeCell()
    force_text_cell(cell)
    assert cell.data_type == 's'
