// 键盘快捷键映射 — Excel 风格的键位

import { useCallback } from "react";
import type { CellPos, ColumnDef, GridSelection } from "./types";

type KeyboardContext = {
  selection: GridSelection;
  editing: CellPos | null;
  rowCount: number;
  colCount: number;
  columns: ColumnDef[];
  moveFocus: (dRow: number, dCol: number, opts?: { shift?: boolean }) => void;
  selectAll: () => void;
  startEdit: (pos?: CellPos) => void;
  stopEdit: () => void;
  commitEdit: () => void;
  onCopy: () => void;
  onPaste: () => void;
  onDelete: () => void;
  onFillDown: () => void;
  onFillRight: () => void;
};

export function useGridKeyboard(ctx: KeyboardContext) {
  return useCallback(
    (e: React.KeyboardEvent) => {
      const { selection, editing, rowCount, colCount, moveFocus, selectAll, startEdit, stopEdit, commitEdit } = ctx;

      // 编辑状态下的按键
      if (editing) {
        if (e.key === "Escape") {
          e.preventDefault();
          stopEdit();
          return;
        }
        if (e.key === "Enter") {
          e.preventDefault();
          commitEdit();
          moveFocus(1, 0);
          return;
        }
        if (e.key === "Tab") {
          e.preventDefault();
          commitEdit();
          moveFocus(0, e.shiftKey ? -1 : 1);
          return;
        }
        return; // 其他按键交给输入框
      }

      // 非编辑状态
      const ctrl = e.ctrlKey || e.metaKey;
      const shift = e.shiftKey;

      switch (e.key) {
        case "ArrowUp":
          e.preventDefault();
          moveFocus(-1, 0, { shift });
          break;
        case "ArrowDown":
          e.preventDefault();
          moveFocus(1, 0, { shift });
          break;
        case "ArrowLeft":
          e.preventDefault();
          moveFocus(0, -1, { shift });
          break;
        case "ArrowRight":
          e.preventDefault();
          moveFocus(0, 1, { shift });
          break;
        case "Tab":
          e.preventDefault();
          moveFocus(0, shift ? -1 : 1);
          break;
        case "Home":
          e.preventDefault();
          if (ctrl) {
            // Ctrl+Home → 第一个单元格
            ctx.moveFocus(-rowCount, -colCount);
          } else {
            // Home → 行首
            for (let i = 0; i < colCount; i++) {
              if (selection.focus.col === 0) break;
              moveFocus(0, -1);
            }
          }
          break;
        case "End":
          e.preventDefault();
          if (ctrl) {
            // Ctrl+End → 最后一个单元格
            ctx.moveFocus(rowCount, colCount);
          } else {
            // End → 行尾
            const distToLast = colCount - 1 - selection.focus.col;
            for (let i = 0; i < distToLast; i++) {
              moveFocus(0, 1);
            }
          }
          break;
        case "PageUp":
          e.preventDefault();
          for (let i = 0; i < 20; i++) moveFocus(-1, 0, { shift });
          break;
        case "PageDown":
          e.preventDefault();
          for (let i = 0; i < 20; i++) moveFocus(1, 0, { shift });
          break;
        case "Enter":
        case "F2":
          e.preventDefault();
          startEdit(selection.focus);
          break;
        case "a":
        case "A":
          if (ctrl) {
            e.preventDefault();
            selectAll();
          }
          break;
        case "c":
        case "C":
          if (ctrl) {
            e.preventDefault();
            ctx.onCopy();
          }
          break;
        case "v":
        case "V":
          if (ctrl) {
            e.preventDefault();
            ctx.onPaste();
          }
          break;
        case "Delete":
        case "Backspace":
          e.preventDefault();
          ctx.onDelete();
          break;
        case "d":
        case "D":
          if (ctrl) {
            e.preventDefault();
            ctx.onFillDown();
          }
          break;
        case "r":
        case "R":
          if (ctrl) {
            e.preventDefault();
            ctx.onFillRight();
          }
          break;
        default:
          // 数字/字母直接开始编辑（替换内容）
          if (e.key.length === 1 && !ctrl) {
            e.preventDefault();
            startEdit(selection.focus);
          }
          break;
      }
    },
    [ctx],
  );
}
