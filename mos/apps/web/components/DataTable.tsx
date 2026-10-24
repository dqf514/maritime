"use client";

// DataTable — 兼容 shim，内部委托给新的 DataGrid
// 旧接口保持不变，逐步迁移到 DataGrid

import { useMemo } from "react";
import { DataGrid } from "./grid/DataGrid";
import type { ColumnDef as GridColumnDef } from "./grid/types";
import { useI18n } from "@/lib/i18n";

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
  // 说明：早期版本这里还有 `resizable`（列宽拖拽）与 `stickyHeader` 两个 prop，
  // 但 DataGrid 既不支持列宽拖拽、表头也**默认就是 sticky**，这两个 prop 从未
  // 被任何调用方传入、也从未被转发 —— 属于纯死 prop，已删除（避免调用方误以为
  // 传了会生效）。
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
  selectable,
  selectedIds,
  onSelectionChange,
  editable,
  storageKey,
  // 默认不显示汇总行：DataGrid 自身的默认是 true，但 DataTable 这层包装
  // 历史上未显式传值时不应凭空多出一行页脚。
  showFooter = false,
  paginatable,
  total,
  page,
  pageSize,
  onPageChange,
}: Props<T>) {
  const { t } = useI18n();
  const getKey = rowKey ?? ((row: T, i: number) => String((row as any)?.id ?? i));
  const gridColumns = useMemo<GridColumnDef[]>(
    () =>
      columns
        // hidden 列不渲染（否则隐藏列仍会出现在表格里）
        .filter((col) => !col.hidden)
        .map((col) => {
          const isEditable = editable?.keys.includes(col.key) ?? false;
          return {
            key: col.key,
            title: col.title,
            width: col.width,
            minWidth: col.minWidth,
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

  // 行选择：DataGrid 用字符串键，这里做 number|string → string 的双向转换。
  const selectedKeys = useMemo(
    () => (selectedIds ? new Set([...selectedIds].map((k) => String(k))) : undefined),
    [selectedIds],
  );
  const handleSelectionChange = useMemo(
    () =>
      onSelectionChange
        ? (keys: Set<string>) => onSelectionChange(new Set([...keys]))
        : undefined,
    [onSelectionChange],
  );

  // 分页：DataGrid 本身不分页，这里按 total/page/pageSize 渲染一个轻量翻页条。
  const pages = paginatable && total && pageSize ? Math.max(1, Math.ceil(total / pageSize)) : 1;
  const curPage = paginatable ? Math.min(Math.max(1, page ?? 1), pages) : 1;

  return (
    <>
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
        selectable={selectable}
        selectedKeys={selectedKeys}
        onSelectedKeysChange={handleSelectionChange}
      />
      {paginatable && pages > 1 ? (
        <div className="dt-pager">
          <button
            type="button"
            className="btn btn-sm btn-ghost"
            disabled={curPage <= 1}
            onClick={() => onPageChange?.(curPage - 1, pageSize)}
            aria-label={t("common.prev_page", "Previous page")}
          >
            ←
          </button>
          <span className="muted">
            {curPage} / {pages}
          </span>
          <button
            type="button"
            className="btn btn-sm btn-ghost"
            disabled={curPage >= pages}
            onClick={() => onPageChange?.(curPage + 1, pageSize)}
            aria-label={t("common.next_page", "Next page")}
          >
            →
          </button>
        </div>
      ) : null}
    </>
  );
}
