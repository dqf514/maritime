// 单元格选择模型 — anchor + focus，支持范围选择、Ctrl 多选、Shift 扩展

import { useCallback, useRef, useState } from "react";
import type { CellPos, CellRange, GridSelection } from "./types";

export function useCellSelection(rowCount: number, colCount: number) {
  const [selection, setSelection] = useState<GridSelection>({
    anchor: { row: 0, col: 0 },
    focus: { row: 0, col: 0 },
    ranges: [],
  });
  const [editing, setEditing] = useState<CellPos | null>(null);
  const fillHandleRef = useRef(false);

  /** 当前活动范围 */
  const activeRange = useCallback((): CellRange => {
    const { anchor, focus } = selection;
    return {
      start: { row: Math.min(anchor.row, focus.row), col: Math.min(anchor.col, focus.col) },
      end: { row: Math.max(anchor.row, focus.row), col: Math.max(anchor.col, focus.col) },
    };
  }, [selection]);

  /** 点击单元格 */
  const selectCell = useCallback(
    (row: number, col: number, opts?: { shift?: boolean; ctrl?: boolean }) => {
      setSelection((prev) => {
        if (opts?.shift) {
          return { ...prev, focus: { row, col } };
        }
        if (opts?.ctrl) {
          return {
            anchor: { row, col },
            focus: { row, col },
            ranges: [...prev.ranges, { start: prev.focus, end: prev.focus }],
          };
        }
        return { anchor: { row, col }, focus: { row, col }, ranges: [] };
      });
    },
    [],
  );

  /** 移动焦点 */
  const moveFocus = useCallback(
    (dRow: number, dCol: number, opts?: { shift?: boolean }) => {
      setSelection((prev) => {
        const newRow = Math.max(0, Math.min(rowCount - 1, prev.focus.row + dRow));
        const newCol = Math.max(0, Math.min(colCount - 1, prev.focus.col + dCol));
        if (opts?.shift) {
          return { ...prev, focus: { row: newRow, col: newCol } };
        }
        return { anchor: { row: newRow, col: newCol }, focus: { row: newRow, col: newCol }, ranges: [] };
      });
    },
    [rowCount, colCount],
  );

  /** 全选 */
  const selectAll = useCallback(() => {
    setSelection({
      anchor: { row: 0, col: 0 },
      focus: { row: rowCount - 1, col: colCount - 1 },
      ranges: [],
    });
  }, [rowCount, colCount]);

  /** 选中整行 */
  const selectRow = useCallback(
    (row: number, ctrl?: boolean) => {
      setSelection((prev) => {
        const range = { start: { row, col: 0 }, end: { row, col: colCount - 1 } };
        if (ctrl) {
          return { ...prev, ranges: [...prev.ranges, range] };
        }
        return { anchor: { row, col: 0 }, focus: { row, col: colCount - 1 }, ranges: [range] };
      });
    },
    [colCount],
  );

  /** 是否在选择范围内 */
  const isInRange = useCallback(
    (row: number, col: number): boolean => {
      const r = activeRange();
      if (row >= r.start.row && row <= r.end.row && col >= r.start.col && col <= r.end.col) return true;
      return selection.ranges.some((range) => {
        const sr = Math.min(range.start.row, range.end.row);
        const er = Math.max(range.start.row, range.end.row);
        const sc = Math.min(range.start.col, range.end.col);
        const ec = Math.max(range.start.col, range.end.col);
        return row >= sr && row <= er && col >= sc && col <= ec;
      });
    },
    [selection, activeRange],
  );

  /** 选择范围内的所有单元格坐标 */
  const cellsInRange = useCallback((): CellPos[] => {
    const r = activeRange();
    const cells: CellPos[] = [];
    for (let row = r.start.row; row <= r.end.row; row++) {
      for (let col = r.start.col; col <= r.end.col; col++) {
        cells.push({ row, col });
      }
    }
    return cells;
  }, [activeRange]);

  /** 开始编辑 */
  const startEdit = useCallback((pos?: CellPos) => {
    setEditing(pos ?? { row: 0, col: 0 });
  }, []);

  /** 结束编辑 */
  const stopEdit = useCallback(() => {
    setEditing(null);
  }, []);

  return {
    selection,
    editing,
    fillHandleRef,
    activeRange,
    selectCell,
    moveFocus,
    selectAll,
    selectRow,
    isInRange,
    cellsInRange,
    startEdit,
    stopEdit,
    setSelection,
  };
}
