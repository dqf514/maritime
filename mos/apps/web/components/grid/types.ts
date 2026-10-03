// DataGrid 类型定义 — 单元格中心的 Excel 式网格
// ColumnDef v2: 分离 value（原始值，用于编辑/聚合）和 render（显示）

import { ReactNode } from "react";

export type EditorType = "text" | "number" | "date" | "select" | "checkbox";

export type ColumnEditor = {
  type: EditorType;
  options?: { value: string; label: string }[];
  validate?: (value: unknown, row: Record<string, unknown>) => string | null;
  min?: number;
  max?: number;
  step?: number;
};

export type AggType = "sum" | "avg" | "count" | "min" | "max" | false;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type ColumnDef<T = any> = {
  key: string;
  title: string;
  width?: number;
  minWidth?: number;
  align?: "left" | "right" | "center";
  sortable?: boolean;
  /** 原始值提取器 — 用于编辑、聚合、排序 */
  value?: (row: T) => unknown;
  /** 显示渲染 — 仅影响视觉 */
  render?: (value: unknown, row: T, index: number) => ReactNode;
  /** 编辑器配置 — 有此项列可编辑 */
  editor?: ColumnEditor;
  /** 聚合函数 — 显示在 footer */
  agg?: AggType;
  /** 列分组标题 */
  group?: string;
  /** 固定列 */
  sticky?: boolean;
  hidden?: boolean;
};

export type CellPos = { row: number; col: number };
export type CellRange = { start: CellPos; end: CellPos };

export type GridSelection = {
  anchor: CellPos;
  focus: CellPos;
  ranges: CellRange[];
};

export type GroupByConfig = {
  keys: string[];
  collapsed: Set<string>;
};

export type DataGridProps<T = any> = {
  columns: ColumnDef<T>[];
  data: T[];
  /** 行唯一键 */
  rowKey: (row: T, index: number) => string;
  /** 可编辑 */
  editable?: boolean;
  /** 单元格保存回调 */
  onCellSave?: (rowKey: string, colKey: string, value: unknown, row: T) => void | Promise<void>;
  /** 行双击 */
  onRowDoubleClick?: (row: T, index: number) => void;
  /** 行点击 */
  onRowClick?: (row: T, index: number) => void;
  /** 选择变化 */
  onSelectionChange?: (sel: GridSelection) => void;
  /** 服务端排序 */
  onSortChange?: (key: string, dir: "asc" | "desc" | null) => void;
  /** 分组 */
  groupBy?: string[];
  /** 显示聚合 footer */
  showFooter?: boolean;
  /** 显示列管理 */
  showColumnMenu?: boolean;
  /** 行高 */
  rowHeight?: number;
  /** 虚拟滚动阈值（超过此行数启用） */
  virtualThreshold?: number;
  /** 外部控制选中行 */
  selectedKeys?: Set<string>;
  onSelectedKeysChange?: (keys: Set<string>) => void;
  /** 加载状态 */
  loading?: boolean;
  /** 空数据文案 */
  emptyText?: string;
  /** 存储列配置的 key */
  storageKey?: string;
  className?: string;
};
