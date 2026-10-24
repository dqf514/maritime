"use client";

// DataGrid — 单元格中心的 Excel 式数据网格
// 特性：单元格导航、范围选择、复制粘贴、聚合 footer、内联编辑、列管理、分组折叠

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CellPos, ColumnDef, DataGridProps, GridSelection } from "./types";
import { useCellSelection } from "./useCellSelection";
import { useGridKeyboard } from "./useGridKeyboard";
import { GridFooter } from "./GridFooter";
import { copyToClipboard, readFromClipboard, coerceValue, fillSeries } from "./clipboard";
import { parseUtc } from "@/lib/datetime";
import { useI18n } from "@/lib/i18n";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function getCellValue(col: ColumnDef<any>, row: Record<string, unknown>): unknown {
  return col.value ? col.value(row as any) : row[col.key];
}

/**
 * 复制到剪贴板的文本 —— 必须与「用户看到的」一致。
 *
 * 下拉列（editor.type === "select"）存的是 id（port_id / status_code …），
 * 直接复制原始值会把 UUID 粘进 Excel，粘回来也存不进去。
 * 这里按 options 把 id 映射成 label，粘贴时再映射回 value（见 handlePaste）。
 */
function copyTextFor(col: ColumnDef<any>, row: Record<string, unknown>): string {
  const raw = getCellValue(col, row);
  if (col?.editor?.type === "select" && col.editor.options?.length) {
    const opt = col.editor.options.find((o) => String(o.value) === String(raw));
    if (opt) return opt.label;
  }
  return raw === null || raw === undefined ? "" : String(raw);
}

/**
 * 编辑器输入框的初值：datetime 用 UTC 墙钟 YYYY-MM-DDTHH:MM（datetime-local 要求的格式；
 * 后端存的就是 UTC naive 串，提交时原样回传，故这里取 UTC 分量，编辑不会引入时区偏移）。
 */
function toInputValue(col: ColumnDef, row: Record<string, unknown>): string {
  const val = getCellValue(col, row);
  if (val === null || val === undefined) return "";
  if (col.editor?.type === "datetime") {
    const d = parseUtc(val as string | number);
    if (!d) return "";
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
  }
  return String(val);
}

// status/state 类列的裸值走 status.* 词表翻译（seed_i18n_extra.py）；其余列原样显示
function isStatusKey(key: string): boolean {
  return key === "status" || key === "state" || key.endsWith("_status") || key.endsWith("_state");
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function formatDisplay(
  col: ColumnDef<any>,
  row: Record<string, unknown>,
  index: number,
  tr?: (key: string, fallback?: string) => string,
): React.ReactNode {
  const val = getCellValue(col, row);
  if (col.render) return col.render(val, row as any, index);
  if (val === null || val === undefined) return "";
  const s = String(val);
  if (tr && isStatusKey(col.key) && /^[a-z][a-z0-9_]*$/i.test(s)) {
    return tr(`status.${s}`, s.replace(/_/g, " "));
  }
  return s;
}

export function DataGrid<T extends Record<string, any>>({
  columns: allColumns,
  data,
  rowKey,
  editable = false,
  onCellSave,
  onRowDoubleClick,
  onRowClick,
  onRowContextMenu,
  onSelectionChange,
  onSortChange,
  groupBy = [],
  showFooter = true,
  showColumnMenu = true,
  rowHeight,
  virtualThreshold = 500,
  selectedKeys,
  onSelectedKeysChange,
  loading,
  emptyText = "No records",
  storageKey,
  className = "",
}: DataGridProps<T>) {
  // status/state 类裸值的中文化翻译函数（无 provider 时 useI18n 返回直通实现）
  const { t: tr } = useI18n();
  // 列可见性（支持 storageKey 持久化）
  const [hiddenCols, setHiddenCols] = useState<Set<string>>(() => {
    if (!storageKey) return new Set();
    try {
      const raw = localStorage.getItem(`marios_cols_${storageKey}`);
      return raw ? new Set(JSON.parse(raw)) : new Set();
    } catch {
      return new Set();
    }
  });
  const [showColMenu, setShowColMenu] = useState(false);

  const columns = useMemo(
    () => allColumns.filter((c) => !c.hidden && !hiddenCols.has(c.key)),
    [allColumns, hiddenCols],
  );

  // 分组折叠状态
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  // 选择模型
  const rowCount = data.length;
  const colCount = columns.length;
  const sel = useCellSelection(rowCount, colCount);

  // 排序
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc" | null>(null);

  const gridRef = useRef<HTMLDivElement>(null);
  const editingInputRef = useRef<HTMLInputElement | HTMLSelectElement>(null);

  // 聚焦到网格容器以接收键盘事件
  // 注意 preventScroll：默认 focus() 会把容器滚动进视野，实测在网格里按下鼠标会让
  // 整个列表上跳 ~85px，行内按钮被挪离指针 → click 落空（按钮「点了没反应」）。
  useEffect(() => {
    const el = gridRef.current;
    if (el && document.activeElement !== el && el.contains(document.activeElement)) {
      el.focus({ preventScroll: true });
    }
  }, []);

  // 编辑时聚焦输入框
  useEffect(() => {
    if (sel.editing && editingInputRef.current) {
      editingInputRef.current.focus();
      if (editingInputRef.current instanceof HTMLInputElement) {
        editingInputRef.current.select();
      }
    }
  }, [sel.editing]);

  // 通知选择变化
  useEffect(() => {
    onSelectionChange?.(sel.selection);
  }, [sel.selection, onSelectionChange]);

  // --- 复制 ---
  const handleCopy = useCallback(async () => {
    const range = sel.activeRange();
    const matrix: string[][] = [];
    for (let r = range.start.row; r <= range.end.row; r++) {
      const row: string[] = [];
      for (let c = range.start.col; c <= range.end.col; c++) {
        const col = columns[c];
        const val = col ? copyTextFor(col, data[r] ?? {}) : "";
        row.push(val);
      }
      matrix.push(row);
    }
    await copyToClipboard(matrix);
  }, [sel, columns, data]);

  // --- 粘贴 ---
  const handlePaste = useCallback(async () => {
    if (!editable) return;
    const matrix = await readFromClipboard();
    if (!matrix.length) return;

    const start = sel.selection.focus;
    for (let r = 0; r < matrix.length; r++) {
      const targetRow = start.row + r;
      if (targetRow >= data.length) break;
      for (let c = 0; c < matrix[r].length; c++) {
        const targetCol = start.col + c;
        if (targetCol >= columns.length) break;
        const col = columns[targetCol];
        if (!col.editor) continue;
        let coerced: unknown = coerceValue(matrix[r][c], col.editor.type);
        // 下拉列：粘贴的是 label（复制时写出的就是 label）→ 还原成 value 再落库。
        if (col.editor.type === "select" && col.editor.options?.length) {
          const txt = String(matrix[r][c] ?? "").trim();
          const opt = col.editor.options.find((o) => o.label === txt || String(o.value) === txt);
          if (opt) coerced = opt.value;
        }
        const rowData = data[targetRow] as Record<string, unknown>;
        const rk = rowKey(data[targetRow] as any, targetRow);
        onCellSave?.(rk, col.key, coerced, rowData as any);
      }
    }
  }, [editable, sel, columns, data, rowKey, onCellSave]);

  // --- 删除 ---
  const handleDelete = useCallback(() => {
    if (!editable) return;
    for (const pos of sel.cellsInRange()) {
      const col = columns[pos.col];
      if (!col?.editor) continue;
      const rowData = data[pos.row] as any;
      const rk = rowKey(data[pos.row] as any, pos.row);
      onCellSave?.(rk, col.key, null, rowData);
    }
  }, [editable, sel, columns, data, rowKey, onCellSave]);

  // --- 填充 ---
  const handleFillDown = useCallback(() => {
    if (!editable) return;
    const range = sel.activeRange();
    if (range.start.row === range.end.row) return;
    for (let c = range.start.col; c <= range.end.col; c++) {
      const col = columns[c];
      if (!col?.editor) continue;
      const sourceVal = getCellValue(col, data[range.start.row] ?? {});
      for (let r = range.start.row + 1; r <= range.end.row; r++) {
        const rk = rowKey(data[r] as any, r);
        onCellSave?.(rk, col.key, sourceVal, data[r] as any);
      }
    }
  }, [editable, sel, columns, data, rowKey, onCellSave]);

  const handleFillRight = useCallback(() => {
    if (!editable) return;
    const range = sel.activeRange();
    if (range.start.col === range.end.col) return;
    for (let r = range.start.row; r <= range.end.row; r++) {
      const sourceCol = columns[range.start.col];
      if (!sourceCol?.editor) continue;
      const sourceVal = getCellValue(sourceCol, data[r] ?? {});
      for (let c = range.start.col + 1; c <= range.end.col; c++) {
        const col = columns[c];
        if (!col?.editor) continue;
        const rk = rowKey(data[r] as any, r);
        onCellSave?.(rk, col.key, sourceVal, data[r] as any);
      }
    }
  }, [editable, sel, columns, data, rowKey, onCellSave]);

  // --- 提交编辑 ---
  const commitEdit = useCallback(() => {
    if (!sel.editing) return;
    const col = columns[sel.editing.col];
    const input = editingInputRef.current;
    if (!col?.editor || !input) {
      sel.stopEdit();
      return;
    }
    const raw = input.value;
    const coerced = coerceValue(raw, col.editor.type);
    const rowData = data[sel.editing.row];
    const rk = rowKey(data[sel.editing.row] as any, sel.editing.row);

    // 验证
    if (col.editor.validate) {
      const err = col.editor.validate(coerced, rowData);
      if (err) {
        // TODO: 显示验证错误
        sel.stopEdit();
        return;
      }
    }

    onCellSave?.(rk, col.key, coerced, rowData as any);
    sel.stopEdit();
  }, [sel, columns, data, rowKey, onCellSave]);

  // --- 键盘 ---
  const handleKeyDown = useGridKeyboard({
    selection: sel.selection,
    editing: sel.editing,
    rowCount,
    colCount,
    columns,
    moveFocus: sel.moveFocus,
    selectAll: sel.selectAll,
    startEdit: sel.startEdit,
    stopEdit: sel.stopEdit,
    commitEdit,
    onCopy: handleCopy,
    onPaste: handlePaste,
    onDelete: handleDelete,
    onFillDown: handleFillDown,
    onFillRight: handleFillRight,
  });

  // --- 排序 ---
  const handleSort = useCallback(
    (key: string) => {
      const col = columns.find((c) => c.key === key);
      if (!col?.sortable) return;
      let newDir: "asc" | "desc" | null;
      if (sortKey === key) {
        newDir = sortDir === "asc" ? "desc" : sortDir === "desc" ? null : "asc";
      } else {
        newDir = "asc";
      }
      setSortKey(newDir ? key : null);
      setSortDir(newDir);
      onSortChange?.(key, newDir);
    },
    [columns, sortKey, sortDir, onSortChange],
  );

  // --- 列可见性 ---
  const toggleCol = useCallback(
    (key: string) => {
      setHiddenCols((prev) => {
        const next = new Set(prev);
        if (next.has(key)) next.delete(key);
        else next.add(key);
        if (storageKey) {
          localStorage.setItem(`marios_cols_${storageKey}`, JSON.stringify([...next]));
        }
        return next;
      });
    },
    [storageKey],
  );

  // --- 分组 ---
  const groupedData = useMemo(() => {
    if (!groupBy.length) return null;
    const groups = new Map<string, T[]>();
    for (const row of data) {
      const key = groupBy.map((k) => String(getCellValue(columns.find((c) => c.key === k) ?? ({ key: k } as any), row) ?? "")).join(" | ");
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(row as T);
    }
    return groups;
  }, [data, groupBy, columns]);

  const toggleGroup = useCallback((key: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  // 单元格渲染
  const renderCell = useCallback(
    (col: ColumnDef, row: Record<string, unknown>, rowIdx: number, colIdx: number) => {
      const isEditing = sel.editing?.row === rowIdx && sel.editing?.col === colIdx;
      const isSelected = sel.isInRange(rowIdx, colIdx);
      const isFocus = sel.selection.focus.row === rowIdx && sel.selection.focus.col === colIdx;

      const cellClass = [
        isSelected ? "cell-selected" : "",
        isFocus ? "cell-focus" : "",
        col.align === "right" ? "dt-align-right" : "",
        col.align === "center" ? "dt-align-center" : "",
      ]
        .filter(Boolean)
        .join(" ");

      if (isEditing && col.editor) {
        return (
          <td key={col.key} className={cellClass} style={{ padding: 0 }}>
            {col.editor.type === "select" ? (
              <select
                ref={editingInputRef as React.RefObject<HTMLSelectElement>}
                className="grid-cell-input"
                defaultValue={toInputValue(col, row)}
                onBlur={commitEdit}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    commitEdit();
                    sel.moveFocus(1, 0);
                  }
                  if (e.key === "Escape") sel.stopEdit();
                }}
              >
                {col.editor.options?.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            ) : (
              <input
                ref={editingInputRef as React.RefObject<HTMLInputElement>}
                className="grid-cell-input"
                type={
                  col.editor.type === "number"
                    ? "number"
                    : col.editor.type === "date"
                      ? "date"
                      : col.editor.type === "datetime"
                        ? "datetime-local"
                        : "text"
                }
                step={col.editor.step}
                min={col.editor.min}
                max={col.editor.max}
                defaultValue={toInputValue(col, row)}
                onBlur={commitEdit}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    commitEdit();
                    sel.moveFocus(1, 0);
                  }
                  if (e.key === "Escape") sel.stopEdit();
                  e.stopPropagation();
                }}
              />
            )}
          </td>
        );
      }

      return (
        <td
          key={col.key}
          className={cellClass}
          onMouseDown={(e) => {
            // 行内交互控件（按钮/链接/输入）不触发单元格选中：否则会重绘并滚动列表，
            // 按钮在 mouseup 之前被挪走，click 事件落空。
            const target = e.target as HTMLElement | null;
            if (target?.closest?.("button, a, input, select, textarea, [role='button']")) return;
            sel.selectCell(rowIdx, colIdx, { shift: e.shiftKey, ctrl: e.ctrlKey || e.metaKey });
            gridRef.current?.focus({ preventScroll: true });
          }}
          onDoubleClick={() => {
            if (editable && col.editor) sel.startEdit({ row: rowIdx, col: colIdx });
          }}
        >
          {formatDisplay(col, row, rowIdx, tr)}
        </td>
      );
    },
    [sel, editable, commitEdit, columns, tr],
  );

  // 空状态
  if (!loading && data.length === 0) {
    return (
      <div className={`grid-wrapper ${className}`} ref={gridRef} tabIndex={0} onKeyDown={handleKeyDown}>
        <div className="dt-empty">{emptyText}</div>
      </div>
    );
  }

  return (
    <div className={`grid-wrapper ${className}`} ref={gridRef} tabIndex={0} onKeyDown={handleKeyDown}>
      {showColumnMenu && (
        <div className="dt-colmenu">
          <button type="button" className="btn btn-sm btn-ghost" onClick={() => setShowColMenu((v) => !v)}>
            ☰
          </button>
          {showColMenu && (
            <div className="dt-colmenu-pop">
              {allColumns.map((col) => (
                <label key={col.key}>
                  <input
                    type="checkbox"
                    checked={!hiddenCols.has(col.key) && !col.hidden}
                    onChange={() => toggleCol(col.key)}
                  />
                  {col.title}
                </label>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="grid-scroll">
        <table className="grid-table">
          <thead>
            <tr>
              {columns.map((col, ci) => (
                <th
                  key={col.key}
                  className={`dt-sort-th${col.align === "right" ? " dt-align-right" : ""}${col.sticky ? " dt-sticky-col" : ""}`}
                  style={col.width ?? col.minWidth ? { width: col.width ?? col.minWidth, minWidth: col.minWidth ?? col.width } : undefined}
                  onClick={() => handleSort(col.key)}
                >
                  <span className="dt-th-inner">
                    <span className="dt-th-title">{col.title}</span>
                    {sortKey === col.key && <span className="dt-sort-icon">{sortDir === "asc" ? "↑" : "↓"}</span>}
                  </span>
                </th>
              ))}
            </tr>
          </thead>

          {groupBy.length > 0 && groupedData ? (
            <>
              {[...groupedData.entries()].map(([groupKey, rows]) => {
                const isCollapsed = collapsedGroups.has(groupKey);
                return (
                  <tbody key={groupKey} className="grid-group-body">
                    <tr className="grid-group-header" onClick={() => toggleGroup(groupKey)}>
                      <td colSpan={columns.length}>
                        <span className="grid-group-toggle">{isCollapsed ? "▸" : "▾"}</span>
                        <strong>{groupKey}</strong>
                        <span className="muted"> ({rows.length})</span>
                      </td>
                    </tr>
                    {!isCollapsed &&
                      rows.map((row, ri) => {
                        const globalIdx = data.indexOf(row as T);
                        return (
                          <tr
                            key={rowKey(row as T, globalIdx)}
                            className={`grid-row${onRowDoubleClick ? " dt-row-clickable" : ""}`}
                            onDoubleClick={() => onRowDoubleClick?.(row as T, globalIdx)}
                            onClick={() => onRowClick?.(row as T, globalIdx)}
                            onContextMenu={
                              onRowContextMenu
                                ? (e) => {
                                    e.preventDefault();
                                    onRowContextMenu(row as T, globalIdx, e);
                                  }
                                : undefined
                            }
                          >
                            {columns.map((col, ci) => renderCell(col, row, globalIdx, ci))}
                          </tr>
                        );
                      })}
                  </tbody>
                );
              })}
            </>
          ) : (
            <tbody>
              {data.map((row, ri) => (
                <tr
                  key={rowKey(row as T, ri)}
                  className={`grid-row${onRowDoubleClick ? " dt-row-clickable" : ""}`}
                  onDoubleClick={() => onRowDoubleClick?.(row as T, ri)}
                  onClick={() => onRowClick?.(row as T, ri)}
                  onContextMenu={
                    onRowContextMenu
                      ? (e) => {
                          e.preventDefault();
                          onRowContextMenu(row as T, ri, e);
                        }
                      : undefined
                  }
                >
                  {columns.map((col, ci) => renderCell(col, row, ri, ci))}
                </tr>
              ))}
            </tbody>
          )}

          {showFooter && <GridFooter columns={columns} data={data as Record<string, unknown>[]} selection={sel.selection} />}
        </table>
      </div>
    </div>
  );
}
