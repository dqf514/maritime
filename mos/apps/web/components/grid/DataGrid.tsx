"use client";

// DataGrid — 单元格中心的 Excel 式数据网格
// 特性：单元格导航、范围选择、复制粘贴、聚合 footer、内联编辑、列管理、分组折叠

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { CellPos, ColumnDef, DataGridProps, GridSelection } from "./types";
import { useCellSelection } from "./useCellSelection";
import { useGridKeyboard } from "./useGridKeyboard";
import { GridFooter } from "./GridFooter";
import { copyToClipboard, readFromClipboard, coerceValue, fillSeries } from "./clipboard";
import { ConfirmDialog } from "@/components/ConfirmDialog";
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

/** 单元格校验错误 —— 按单元格存放，互不影响（P1-25）。 */
type CellError = { row: number; col: number; msg: string };

/** 一次批量清空的快照 —— 用于撤销（P1-11）。 */
type ClearedSnapshot = {
  rowKey: string;
  colKey: string;
  /** 清空前该单元格的原值 */
  value: unknown;
  /** 清空时该行在 data 中的下标（行可能被重排，撤销时优先按 rowKey 回找） */
  rowIdx: number;
};

function errorKey(row: number, col: number): string {
  return `${row}:${col}`;
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
  data: allData,
  pageSize,
  rowKey,
  editable = false,
  onCellSave,
  onRowDoubleClick,
  onRowClick,
  onRowOpen,
  onRowContextMenu,
  rowClassName,
  onSelectionChange,
  onSortChange,
  groupBy = [],
  showFooter = true,
  showColumnMenu = true,
  rowHeight,
  virtualThreshold = 500,
  selectedKeys,
  onSelectedKeysChange,
  selectable = false,
  loading,
  emptyText = "No records",
  storageKey,
  className = "",
}: DataGridProps<T>) {
  // status/state 类裸值的中文化翻译函数（无 provider 时 useI18n 返回直通实现）
  const { t } = useI18n();

  // ── 客户端分页（pageSize 设置时生效）──
  // data 重导出为「当前页切片」：行索引、选择、复制、编辑、聚合 footer、虚拟
  // 滚动全部自动按页计算，后续代码无需感知分页。
  // 页码连同「设置它时的数据长度」一起存：长度变了（换文件夹/筛选/同步刷新）
  // 即视为换了列表、派生回落第一页；同长度重排（排序）保持页码 —— 纯派生无 effect。
  const [pageState, setPageState] = useState(() => ({ p: 1, len: allData.length }));
  const pages = pageSize && pageSize > 0 ? Math.max(1, Math.ceil(allData.length / pageSize)) : 1;
  const safePage =
    pageState.len === allData.length ? Math.min(Math.max(1, pageState.p), pages) : 1;
  const data = useMemo(() => {
    if (!pageSize || pages <= 1) return allData;
    return allData.slice((safePage - 1) * pageSize, safePage * pageSize);
  }, [allData, pages, safePage, pageSize]);

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

  // ── 列宽拖动（表头右缘手柄）：覆盖值优先于 col.width，随 storageKey 持久化 ──
  // ref 为真源：drag/mouseup 回调里直接算好下一个对象，避免 setState updater 副作用
  const [colW, setColW] = useState<Record<string, number>>(() => {
    if (!storageKey) return {};
    try {
      const raw = localStorage.getItem(`marios_colw_${storageKey}`);
      return raw ? (JSON.parse(raw) as Record<string, number>) : {};
    } catch {
      return {};
    }
  });
  const colWRef = useRef(colW);
  const persistColW = useCallback(() => {
    if (storageKey) localStorage.setItem(`marios_colw_${storageKey}`, JSON.stringify(colWRef.current));
  }, [storageKey]);
  /** 拖动手柄后紧跟的 click 不应触发表头排序（mouseup 落回表头时 click 仍会冒泡） */
  const resizeClickGuard = useRef(false);
  const resizeState = useRef<{ key: string; startX: number; startW: number } | null>(null);

  const startResize = useCallback(
    (e: React.MouseEvent, key: string) => {
      e.preventDefault();
      e.stopPropagation();
      resizeClickGuard.current = true;
      const th = (e.currentTarget as HTMLElement).closest("th");
      resizeState.current = {
        key,
        startX: e.clientX,
        startW: th?.getBoundingClientRect().width ?? 120,
      };
      const onMove = (ev: MouseEvent) => {
        const st = resizeState.current;
        if (!st) return;
        const w = Math.max(60, Math.round(st.startW + (ev.clientX - st.startX)));
        const next = { ...colWRef.current, [st.key]: w };
        colWRef.current = next;
        setColW(next);
      };
      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        document.body.style.cursor = "";
        resizeState.current = null;
        persistColW();
        // click 在 mouseup 之后派发 —— 等它消费掉守卫再放行下一次表头点击
        setTimeout(() => {
          resizeClickGuard.current = false;
        }, 0);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
      document.body.style.cursor = "col-resize";
    },
    [persistColW],
  );

  const resetColWidth = useCallback(
    (key: string) => {
      const next = { ...colWRef.current };
      delete next[key];
      colWRef.current = next;
      setColW(next);
      persistColW();
    },
    [persistColW],
  );

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

  // 行是否"可点开" —— 有任一行级动作就该给指针光标（历史缺陷：只有双击才给）
  const rowClickable = Boolean(onRowClick || onRowDoubleClick || onRowOpen);

  // 排序
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc" | null>(null);

  const gridRef = useRef<HTMLDivElement>(null);
  const editingInputRef = useRef<HTMLInputElement | HTMLSelectElement>(null);
  // P1-11：Delete 的二次确认
  const [confirmDelete, setConfirmDelete] = useState(false);
  // P1-11：批量清空的快照栈（撤销用）。每次清空压入一条「操作」，Ctrl+Z 逐条回滚。
  const undoRef = useRef<ClearedSnapshot[][]>([]);
  const [canUndo, setCanUndo] = useState(false);

  // P1-25：单元格校验错误（此前被静默吞掉，只剩一行 TODO）——按单元格存放，
  // 一个单元格报错不影响其它单元格继续编辑。
  const [cellErrs, setCellErrs] = useState<Record<string, CellError>>({});
  // 错误提示的 DOM id 前缀（多网格共存时不能撞号）
  const gridId = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  // 当前处于校验错误状态的单元格数（状态条用）
  const errCount = Object.keys(cellErrs).length;

  // ── 虚拟滚动（virtualThreshold 此前声明未用；上千行 DOM 会卡顿） ──
  const scrollRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(0);
  const [measuredRowH, setMeasuredRowH] = useState(0);
  const virtual = data.length > virtualThreshold;
  // 行高优先用外部指定，其次实测，最后回退到紧凑密度默认值
  const rowH = rowHeight ?? measuredRowH ?? 26;
  const OVERSCAN = 8;
  const firstVisible = virtual ? Math.max(0, Math.floor(scrollTop / rowH) - OVERSCAN) : 0;
  const lastVisible = virtual
    ? Math.min(data.length, Math.ceil((scrollTop + (viewportH || 600)) / rowH) + OVERSCAN)
    : data.length;
  const visibleData = virtual ? data.slice(firstVisible, lastVisible) : data;
  const padTop = virtual ? firstVisible * rowH : 0;
  const padBottom = virtual ? Math.max(0, (data.length - lastVisible) * rowH) : 0;

  // 视口高度跟随容器尺寸变化
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onResize = () => setViewportH(el.clientHeight);
    onResize();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(onResize);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // 实测行高（密度切换会变），用于虚拟滚动的像素换算
  useEffect(() => {
    if (rowHeight) return;
    const el = scrollRef.current;
    if (!el) return;
    const firstRow = el.querySelector("tbody tr.grid-row");
    const h = firstRow ? firstRow.getBoundingClientRect().height : 0;
    if (h > 0) setMeasuredRowH(Math.round(h));
  }, [rowHeight, data.length, columns.length, visibleData.length]);

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
  // P1-11：Delete 直接清空所有选中单元格且无确认无撤销。
  // 现在：① 先弹 ConfirmDialog 确认；② 清空前把原值暂存，可撤销（Ctrl+Z / Undo 按钮）。
  // 选中范围里真正可编辑（清得动）的单元格数 —— 确认框里报这个数。
  const editableCellCount = useMemo(() => {
    if (!editable) return 0;
    let n = 0;
    for (const pos of sel.cellsInRange()) {
      if (columns[pos.col]?.editor) n++;
    }
    return n;
  }, [editable, sel, columns]);

  const clearCells = useCallback(() => {
    if (!editable) return;
    const snapshot: ClearedSnapshot[] = [];
    for (const pos of sel.cellsInRange()) {
      const col = columns[pos.col];
      if (!col?.editor) continue;
      const rowData = data[pos.row] as any;
      const rk = rowKey(data[pos.row] as any, pos.row);
      // 暂存原值 —— 撤销时原样写回
      snapshot.push({
        rowKey: rk,
        colKey: col.key,
        value: getCellValue(col, rowData),
        rowIdx: pos.row,
      });
      onCellSave?.(rk, col.key, null, rowData);
    }
    if (snapshot.length) {
      undoRef.current = [...undoRef.current, snapshot];
      setCanUndo(true);
    }
  }, [editable, sel, columns, data, rowKey, onCellSave]);

  const handleDelete = useCallback(() => {
    if (!editable) return;
    if (!editableCellCount) return;
    setConfirmDelete(true);
  }, [editable, editableCellCount]);

  // 撤销最近一次批量清空 —— 把暂存的值写回（Ctrl+Z 或点 Undo 按钮）
  const handleUndo = useCallback(() => {
    const stack = undoRef.current;
    const last = stack[stack.length - 1];
    if (!last || !last.length) return;
    undoRef.current = stack.slice(0, -1);
    setCanUndo(undoRef.current.length > 0);
    for (const s of last) {
      // 行可能被重排 —— 优先按 rowKey 回找，找不到再退回清空时的行下标
      let idx = -1;
      for (let i = 0; i < data.length; i++) {
        if (rowKey(data[i] as any, i) === s.rowKey) {
          idx = i;
          break;
        }
      }
      if (idx < 0) idx = s.rowIdx;
      const rowData = data[idx] as any;
      if (!rowData) continue;
      onCellSave?.(s.rowKey, s.colKey, s.value, rowData);
    }
  }, [data, rowKey, onCellSave]);

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
    const editing = sel.editing;
    if (!editing) return;
    const col = columns[editing.col];
    const input = editingInputRef.current;
    if (!col?.editor || !input) {
      sel.stopEdit();
      return;
    }
    const raw = input.value;
    const coerced = coerceValue(raw, col.editor.type);
    const rowData = data[editing.row];
    const rk = rowKey(data[editing.row] as any, editing.row);

    // 验证
    if (col.editor.validate) {
      const err = col.editor.validate(coerced, rowData);
      if (err) {
        // P1-25：校验错误必须让用户看见（此前直接吞掉）。
        // 错误按单元格存放：只挡住当前这一格，其它单元格照常编辑。
        const k = errorKey(editing.row, editing.col);
        setCellErrs((prev) => ({ ...prev, [k]: { row: editing.row, col: editing.col, msg: err } }));
        sel.stopEdit();
        return;
      }
    }

    // 该格校验通过 → 清掉这一格的错误（不影响其它格）
    const ek = errorKey(editing.row, editing.col);
    setCellErrs((prev) => {
      if (!prev[ek]) return prev;
      const next = { ...prev };
      delete next[ek];
      return next;
    });
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
    onUndo: handleUndo,
    // 可编辑的网格里 Enter 仍然是"进单元格编辑"；只有纯列表才把 Enter 让给"打开行"
    onRowOpen:
      onRowOpen && !editable
        ? (rowIdx: number) => {
            const row = data[rowIdx];
            if (row !== undefined) onRowOpen(row, rowIdx);
          }
        : undefined,
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

  // --- 行选择（复选框） ---
  // P1-27：此前 DataGrid 根本没有「选中行」的状态出口，调用方的 sel 永远为空，
  // 「导出选中」按钮因此永远禁用。这里补上受控/非受控两套。
  const [internalSelected, setInternalSelected] = useState<Set<string>>(new Set());
  const selected = selectedKeys ?? internalSelected;
  const setSelected = useCallback(
    (next: Set<string>) => {
      if (!selectedKeys) setInternalSelected(next);
      onSelectedKeysChange?.(next);
    },
    [selectedKeys, onSelectedKeysChange],
  );
  const showSelectCol = selectable || Boolean(onSelectedKeysChange);
  const rowKeyOf = useCallback(
    (row: T, idx: number) => String(rowKey(row as any, idx)),
    [rowKey],
  );
  const toggleRow = useCallback(
    (key: string) => {
      const next = new Set(selected);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      setSelected(next);
    },
    [selected, setSelected],
  );
  const allSelected = data.length > 0 && data.every((row, i) => selected.has(rowKeyOf(row, i)));
  const toggleAll = useCallback(() => {
    if (allSelected) {
      setSelected(new Set());
      return;
    }
    const next = new Set<string>();
    data.forEach((row, i) => next.add(rowKeyOf(row, i)));
    setSelected(next);
  }, [allSelected, data, rowKeyOf, setSelected]);

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
      // P1-25：本格的校验错误（其它格的错误不影响本格）
      const cellErr = cellErrs[errorKey(rowIdx, colIdx)];
      const cellErrId = `${gridId}-cerr-${rowIdx}-${colIdx}`;

      const cellClass = [
        isSelected ? "cell-selected" : "",
        isFocus ? "cell-focus" : "",
        col.align === "right" ? "dt-align-right" : "",
        col.align === "center" ? "dt-align-center" : "",
        col.truncate === true ? "dt-td-trunc" : "",
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

      // 截断列：true = 内容脱流（列宽只由表头宽度决定，长文本撑不宽列），hover td 出全文；
      // "block" = 限宽换行（跟随拖宽），行高随内容。title 对两种模式都给（原文提示）。
      const body = formatDisplay(col, row, rowIdx, t);
      let shown = body;
      if (col.truncate === true) {
        shown = (
          <span className="dt-trunc">
            <span className="dt-trunc-in">{body}</span>
          </span>
        );
      } else if (col.truncate === "block") {
        const w = colW[col.key] ?? col.width ?? col.minWidth;
        shown = w ? (
          <span className="dt-clamp" style={{ maxWidth: `calc(${w}px - 2 * var(--cell-pad-x, 6px))` }}>
            {body}
          </span>
        ) : (
          body
        );
      }
      const truncTitle = (() => {
        if (!col.truncate) return undefined;
        // 优先用屏幕上的文本（render 可能改写过值，如出站邮件的「→ 收件人」）；
        // render 返回结构化节点时退回原始 value 的字符串化。
        if (typeof body === "string") return body || undefined;
        const v = getCellValue(col, row);
        const s = v === null || v === undefined ? "" : String(v);
        return s || undefined;
      })();

      return (
        <td
          key={col.key}
          className={cellClass}
          title={truncTitle}
          // P1-25：出错单元格标红 + aria-describedby 指向错误文案，读屏也能听到。
          aria-invalid={cellErr ? true : undefined}
          aria-describedby={cellErr ? cellErrId : undefined}
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
          {shown}
          {cellErr ? (
            <span className="grid-cell-error" id={cellErrId} role="alert">
              {t(
                "grid.cell_invalid",
                { en: "Invalid value: {msg}", zh: "取值无效：{msg}" },
                { msg: cellErr.msg },
              )}
            </span>
          ) : null}
        </td>
      );
    },
    [sel, editable, commitEdit, columns, t, cellErrs, gridId, colW],
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
    <>
      <div className={`grid-wrapper ${className}`} ref={gridRef} tabIndex={0} onKeyDown={handleKeyDown}>
      {showColumnMenu && (
        <div className="dt-colmenu">
          <button
            type="button"
            className="btn btn-sm btn-ghost"
            onClick={() => setShowColMenu((v) => !v)}
            aria-label={t("grid.column_menu", "Column menu")}
          >
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

      <div
        className={`grid-scroll${virtual ? " grid-scroll--virtual" : ""}`}
        ref={scrollRef}
        onScroll={virtual ? (e) => setScrollTop(e.currentTarget.scrollTop) : undefined}
        style={
          virtual
            ? ({ "--vt": `${padTop}px`, "--vb": `${padBottom}px` } as React.CSSProperties)
            : undefined
        }
      >
        <table className="grid-table">
          <thead>
            <tr>
              {showSelectCol ? (
                <th className="dt-select-th">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={toggleAll}
                    aria-label={t("common.select_all", "Select all rows")}
                  />
                </th>
              ) : null}
              {columns.map((col) => {
                const override = colW[col.key];
                const baseW = col.width ?? col.minWidth;
                return (
                  <th
                    key={col.key}
                    className={`dt-sort-th${col.align === "right" ? " dt-align-right" : ""}${col.sticky ? " dt-sticky-col" : ""}`}
                    // 拖动覆盖值优先，且不再叠加 minWidth 兜底（否则 CSS min-width 会顶住拖窄）
                    style={
                      override != null
                        ? { width: override }
                        : baseW
                          ? { width: baseW, minWidth: col.minWidth ?? col.width }
                          : undefined
                    }
                    onClick={() => {
                      // 表头右缘拖宽后 mouseup 落回表头时会补一次 click —— 不应触发排序
                      if (resizeClickGuard.current) return;
                      handleSort(col.key);
                    }}
                  >
                    <span className="dt-th-inner">
                      <span className="dt-th-title">{col.title}</span>
                      {sortKey === col.key && <span className="dt-sort-icon">{sortDir === "asc" ? "↑" : "↓"}</span>}
                    </span>
                    <span
                      className="dt-resize-handle"
                      onMouseDown={(e) => startResize(e, col.key)}
                      onDoubleClick={(e) => {
                        e.stopPropagation();
                        resetColWidth(col.key);
                      }}
                    />
                  </th>
                );
              })}
            </tr>
          </thead>

          {groupBy.length > 0 && groupedData ? (
            <>
              {[...groupedData.entries()].map(([groupKey, rows]) => {
                const isCollapsed = collapsedGroups.has(groupKey);
                return (
                  <tbody key={groupKey} className="grid-group-body">
                    <tr className="grid-group-header" onClick={() => toggleGroup(groupKey)}>
                      <td colSpan={columns.length + (showSelectCol ? 1 : 0)}>
                        <span className="grid-group-toggle">{isCollapsed ? "▸" : "▾"}</span>
                        <strong>{groupKey}</strong>
                        <span className="muted"> ({rows.length})</span>
                      </td>
                    </tr>
                    {!isCollapsed &&
                      rows.map((row, ri) => {
                        const globalIdx = data.indexOf(row as T);
                        const rk = rowKeyOf(row, globalIdx);
                        return (
                          <tr
                            key={rowKey(row as T, globalIdx)}
                            className={`grid-row${rowClickable ? " dt-row-clickable" : ""}${rowClassName ? ` ${rowClassName(row as T, globalIdx)}` : ""}`}
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
                            {showSelectCol ? (
                              <td className="dt-select-cell">
                                <input
                                  type="checkbox"
                                  checked={selected.has(rk)}
                                  onChange={() => toggleRow(rk)}
                                  onClick={(e) => e.stopPropagation()}
                                  aria-label={t("common.select_row", "Select row")}
                                />
                              </td>
                            ) : null}
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
              {padTop > 0 ? (
                <tr className="grid-vspace grid-vspace-top" aria-hidden="true">
                  <td colSpan={columns.length + (showSelectCol ? 1 : 0)} />
                </tr>
              ) : null}
              {visibleData.map((row, vi) => {
                const ri = firstVisible + vi;
                const rk = rowKeyOf(row, ri);
                return (
                  <tr
                    key={rowKey(row as T, ri)}
                    className={`grid-row${rowClickable ? " dt-row-clickable" : ""}${rowClassName ? ` ${rowClassName(row as T, ri)}` : ""}`}
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
                    {showSelectCol ? (
                      <td className="dt-select-cell">
                        <input
                          type="checkbox"
                          checked={selected.has(rk)}
                          onChange={() => toggleRow(rk)}
                          onClick={(e) => e.stopPropagation()}
                          aria-label={t("common.select_row", "Select row")}
                        />
                      </td>
                    ) : null}
                    {columns.map((col, ci) => renderCell(col, row, ri, ci))}
                  </tr>
                );
              })}
              {padBottom > 0 ? (
                <tr className="grid-vspace grid-vspace-bottom" aria-hidden="true">
                  <td colSpan={columns.length + (showSelectCol ? 1 : 0)} />
                </tr>
              ) : null}
            </tbody>
          )}

          {showFooter && <GridFooter columns={columns} data={data as Record<string, unknown>[]} selection={sel.selection} />}
        </table>
      </div>
      {/* 客户端分页翻页条（pageSize 设置且超过一页时；样式复用站内 dt-pagination） */}
      {pages > 1 && pageSize ? (
        <div className="dt-pagination">
          <span className="dt-page-info">
            {t("common.page_of", "{from}-{to} of {n}", {
              from: (safePage - 1) * pageSize + 1,
              to: Math.min(safePage * pageSize, allData.length),
              n: allData.length,
            })}
          </span>
          <span className="dt-page-btns">
            <button
              type="button"
              onClick={() => setPageState({ p: safePage - 1, len: allData.length })}
              disabled={safePage <= 1}
              aria-label={t("common.prev_page", "Previous page")}
            >
              ‹
            </button>
            <button
              type="button"
              onClick={() => setPageState({ p: safePage + 1, len: allData.length })}
              disabled={safePage >= pages}
              aria-label={t("common.next_page", "Next page")}
            >
              ›
            </button>
          </span>
        </div>
      ) : null}
      {/* P1-11 撤销 + P1-25 校验状态条 */}
      {errCount > 0 || canUndo ? (
        <div className="dt-pager">
          {errCount > 0 ? (
            <span className="flash-err" role="status" aria-live="polite">
              {t(
                "grid.cell_errors",
                { en: "{n} cell(s) failed validation — see the highlighted cells.", zh: "有 {n} 个单元格未通过校验，请查看标红的单元格。" },
                { n: errCount },
              )}
            </span>
          ) : null}
          {canUndo ? (
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              onClick={handleUndo}
              title={t("grid.undo_clear_hint", { en: "Undo the last clear (Ctrl+Z)", zh: "撤销上一次清空（Ctrl+Z）" })}
            >
              {t("grid.undo_clear", { en: "Undo clear", zh: "撤销清空" })}
            </button>
          ) : null}
        </div>
      ) : null}
      </div>
      <ConfirmDialog
        open={confirmDelete}
        title={t("common.confirm", "Confirm")}
        message={t("grid.confirm_clear", "Clear the value of {n} selected cell(s)?", {
          n: editableCellCount,
        })}
        danger
        confirmLabel={t("common.clear", "Clear")}
        onConfirm={() => {
          setConfirmDelete(false);
          clearCells();
        }}
        onCancel={() => setConfirmDelete(false)}
      />
    </>
  );
}
