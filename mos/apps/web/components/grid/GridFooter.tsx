// 聚合 footer — Excel 风格的底部汇总行（sum/avg/count/min/max）

import { useMemo } from "react";
import type { ColumnDef, GridSelection } from "./types";

type Props = {
  columns: ColumnDef<any>[];
  data: any[];
  selection: GridSelection;
  showSelectionStats?: boolean;
};

function getCellRawValue(col: ColumnDef<any>, row: any): unknown {
  return col.value ? col.value(row) : row[col.key];
}

function formatAggValue(value: number, type: string): string {
  if (isNaN(value) || !isFinite(value)) return "";
  if (type === "count") return String(Math.round(value));
  if (Number.isInteger(value)) return value.toLocaleString();
  return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function GridFooter({ columns, data, selection, showSelectionStats = true }: Props) {
  const { selectionStats, columnAggs } = useMemo(() => {
    // 选择范围内的统计
    const r = {
      start: {
        row: Math.min(selection.anchor.row, selection.focus.row),
        col: Math.min(selection.anchor.col, selection.focus.col),
      },
      end: {
        row: Math.max(selection.anchor.row, selection.focus.row),
        col: Math.max(selection.anchor.col, selection.focus.col),
      },
    };

    // 列聚合（全表）
    const aggs: Record<string, string> = {};
    for (const col of columns) {
      if (!col.agg) continue;
      const nums = data
        .map((row) => Number(getCellRawValue(col, row)))
        .filter((n) => !isNaN(n) && isFinite(n));
      if (nums.length === 0 && col.agg !== "count") continue;

      switch (col.agg) {
        case "sum":
          aggs[col.key] = `Σ ${formatAggValue(nums.reduce((a: number, b: number) => a + b, 0), "sum")}`;
          break;
        case "avg":
          aggs[col.key] = `x̄ ${formatAggValue(nums.reduce((a: number, b: number) => a + b, 0) / nums.length, "avg")}`;
          break;
        case "count":
          aggs[col.key] = `n=${data.length}`;
          break;
        case "min":
          aggs[col.key] = `↓ ${formatAggValue(Math.min(...nums), "min")}`;
          break;
        case "max":
          aggs[col.key] = `↑ ${formatAggValue(Math.max(...nums), "max")}`;
          break;
      }
    }

    // 选区统计
    let selStats = "";
    if (showSelectionStats && (r.end.row > r.start.row || r.end.col > r.start.col)) {
      const selValues: number[] = [];
      for (let row = r.start.row; row <= r.end.row; row++) {
        for (let col = r.start.col; col <= r.end.col; col++) {
          const c = columns[col];
          if (!c) continue;
          const v = Number(getCellRawValue(c, data[row] ?? {}));
          if (!isNaN(v) && isFinite(v)) selValues.push(v);
        }
      }
      if (selValues.length > 0) {
        const sum = selValues.reduce((a, b) => a + b, 0);
        const avg = sum / selValues.length;
        selStats = `Sum: ${formatAggValue(sum, "sum")} | Avg: ${formatAggValue(avg, "avg")} | Count: ${selValues.length}`;
      }
    }

    return { selectionStats: selStats, columnAggs: aggs };
  }, [columns, data, selection, showSelectionStats]);

  return (
    <tfoot className="grid-footer">
      <tr>
        {columns.map((col, i) => (
          <td key={col.key} className={col.align === "right" ? "dt-align-right" : ""}>
            {i === 0 && selectionStats ? (
              <span className="grid-footer-selection">{selectionStats}</span>
            ) : (
              columnAggs[col.key] || ""
            )}
          </td>
        ))}
      </tr>
    </tfoot>
  );
}
