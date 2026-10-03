"use client";

// DataTable — 兼容 shim，内部委托给新的 DataGrid
// 旧接口保持不变，逐步迁移到 DataGrid

import { useMemo } from "react";
import { DataGrid } from "./grid/DataGrid";
import type { ColumnDef as GridColumnDef } from "./grid/types";

export type ColumnDef<T = any> = {
  key: string;
  title: string;
  render?: (value: any, row: T, index: number) => React.ReactNode;
  sortable?: boolean;
  align?: "left" | "right" | "center";
  width?: number;
  minWidth?: number;
  sticky?: boolean;
  hidden?: boolean;
};

type Props<T> = {
  columns: ColumnDef<T>[];
  data: T[];
  rowKey?: (row: T, index: number) => string;
  onRowClick?: (row: T) => void;
  onRowDoubleClick?: (row: T) => void;
  onSortChange?: (key: string, dir: "asc" | "desc" | null) => void;
  loading?: boolean;
  emptyText?: string;
  selectable?: boolean;
  selectedIds?: Set<string | number>;
  onSelectionChange?: (ids: Set<string | number>) => void;
  editable?: { keys: string[]; onSave: (rowKey: string, colKey: string, value: unknown) => void };
  resizable?: boolean;
  stickyHeader?: boolean;
  storageKey?: string;
  showFooter?: boolean;
  paginatable?: boolean;
  total?: number;
  page?: number;
  pageSize?: number;
  onPageChange?: (page: number, pageSize?: number) => void;
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function DataTable<T extends Record<string, any>>({
  columns,
  data,
  rowKey,
  onRowClick,
  onRowDoubleClick,
  onSortChange,
  loading,
  emptyText,
  editable,
  storageKey,
  showFooter,
}: Props<T>) {
  const getKey = rowKey ?? ((row: T, i: number) => String((row as any)?.id ?? i));
  const gridColumns = useMemo<GridColumnDef[]>(
    () =>
      columns.map((col) => {
        const isEditable = editable?.keys.includes(col.key) ?? false;
        return {
          key: col.key,
          title: col.title,
          width: col.width,
          align: col.align,
          sortable: col.sortable,
          sticky: col.sticky,
          render: col.render as GridColumnDef["render"],
          editor: isEditable ? { type: "text" as const } : undefined,
          agg: (showFooter ? "sum" : false) as GridColumnDef["agg"],
        };
      }),
    [columns, editable, showFooter],
  );

  return (
    <DataGrid
      columns={gridColumns}
      data={data}
      rowKey={getKey as (row: any, i: number) => string}
      editable={Boolean(editable)}
      onCellSave={
        editable
          ? (rk, ck, val) => editable.onSave(rk, ck, val)
          : undefined
      }
      onRowClick={onRowClick as any}
      onRowDoubleClick={onRowDoubleClick as any}
      onSortChange={onSortChange}
      loading={loading}
      emptyText={emptyText}
      storageKey={storageKey}
      showFooter={showFooter}
    />
  );
}
