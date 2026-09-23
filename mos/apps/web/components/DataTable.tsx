"use client";

import {
  ComponentType,
  KeyboardEvent,
  ReactNode,
  useCallback,
  useMemo,
  useRef,
  useState,
} from "react";

export type ColumnDef<T> = {
  key: string;
  title: string;
  width?: number;
  align?: "left" | "center" | "right";
  sortable?: boolean;
  render?: (value: unknown, row: T, index: number) => ReactNode;
  sticky?: boolean;
};

export type DataTableProps<T extends { id: string | number }> = {
  data: T[];
  columns: ColumnDef<T>[];
  sortable?: boolean;
  selectable?: boolean;
  paginatable?: boolean;
  resizable?: boolean;
  stickyHeader?: boolean;
  pageSize?: number;
  emptyText?: string;
  onRowClick?: (row: T) => void;
  onRowContextMenu?: (row: T, e: React.MouseEvent) => void;
  selectedIds?: Set<string | number>;
  onSelectionChange?: (ids: Set<string | number>) => void;
};

type SortDir = "asc" | "desc";

function getNestedValue(obj: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((acc, part) => {
    if (acc == null) return undefined;
    return (acc as Record<string, unknown>)[part];
  }, obj);
}

function compareValues(a: unknown, b: unknown): number {
  if (a == null && b == null) return 0;
  if (a == null) return -1;
  if (b == null) return 1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

export function DataTable<T extends { id: string | number }>({
  data,
  columns,
  sortable: globalSortable = false,
  selectable = false,
  paginatable = false,
  resizable = false,
  stickyHeader = false,
  pageSize = 25,
  emptyText = "No records",
  onRowClick,
  onRowContextMenu,
  selectedIds: controlledSelected,
  onSelectionChange,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [page, setPage] = useState(1);
  const [internalSelected, setInternalSelected] = useState<Set<string | number>>(new Set());
  const [colWidths, setColWidths] = useState<Record<string, number>>({});
  const [focusRow, setFocusRow] = useState(-1);
  const tbodyRef = useRef<HTMLTableSectionElement>(null);

  const selectedIds = controlledSelected ?? internalSelected;
  const setSelectedIds = useCallback(
    (ids: Set<string | number>) => {
      if (onSelectionChange) onSelectionChange(ids);
      setInternalSelected(ids);
    },
    [onSelectionChange],
  );

  function handleSort(key: string) {
    if (sortKey === key) {
      if (sortDir === "asc") setSortDir("desc");
      else {
        setSortKey(null);
        setSortDir("asc");
      }
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
    setPage(1);
  }

  const sorted = useMemo(() => {
    if (!sortKey) return data;
    const col = columns.find((c) => c.key === sortKey);
    const isSortable = col?.sortable !== false && (col?.sortable || globalSortable);
    if (!isSortable) return data;

    const arr = [...data];
    arr.sort((a, b) => {
      const va = getNestedValue(a, sortKey);
      const vb = getNestedValue(b, sortKey);
      return compareValues(va, vb);
    });
    if (sortDir === "desc") arr.reverse();
    return arr;
  }, [data, sortKey, sortDir, columns, globalSortable]);

  const totalPages = paginatable ? Math.max(1, Math.ceil(sorted.length / pageSize)) : 1;
  const safePage = Math.min(page, totalPages);

  const pageData = useMemo(() => {
    if (!paginatable) return sorted;
    const start = (safePage - 1) * pageSize;
    return sorted.slice(start, start + pageSize);
  }, [sorted, paginatable, safePage, pageSize]);

  const allPageIds = pageData.map((r) => r.id);
  const allChecked = allPageIds.length > 0 && allPageIds.every((id) => selectedIds.has(id));
  const someChecked = allPageIds.some((id) => selectedIds.has(id)) && !allChecked;

  function toggleAll(checked: boolean) {
    const next = new Set(selectedIds);
    if (checked) allPageIds.forEach((id) => next.add(id));
    else allPageIds.forEach((id) => next.delete(id));
    setSelectedIds(next);
  }

  function toggleRow(id: string | number) {
    const next = new Set(selectedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedIds(next);
  }

  function handleRowKeyDown(e: KeyboardEvent<HTMLTableSectionElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setFocusRow((prev) => Math.min(prev + 1, pageData.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setFocusRow((prev) => Math.max(prev - 1, 0));
    } else if (e.key === "Enter" && focusRow >= 0 && onRowClick) {
      onRowClick(pageData[focusRow]);
    } else if (e.key === "Escape") {
      setSelectedIds(new Set());
      setFocusRow(-1);
    }
  }

  function startResize(key: string, e: React.MouseEvent) {
    e.preventDefault();
    const th = (e.target as HTMLElement).closest("th") as HTMLElement;
    if (!th) return;
    const startX = e.clientX;
    const startW = th.offsetWidth;

    function onMove(ev: MouseEvent) {
      const w = Math.max(50, startW + (ev.clientX - startX));
      setColWidths((prev) => ({ ...prev, [key]: w }));
    }
    function onUp() {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  const tableClass = [
    "dt-table",
    stickyHeader ? "dt-sticky" : "",
    resizable ? "dt-resizable" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="dt-wrapper">
      <div className="dt-scroll">
        <table className={tableClass}>
          <colgroup>
            {selectable && <col style={{ width: 40 }} />}
            {columns.map((col) => (
              <col
                key={col.key}
                style={{
                  width: colWidths[col.key] || col.width || undefined,
                }}
              />
            ))}
          </colgroup>
          <thead>
            <tr>
              {selectable && (
                <th className="dt-th-check">
                  <input
                    type="checkbox"
                    checked={allChecked}
                    ref={(el) => {
                      if (el) el.indeterminate = someChecked;
                    }}
                    onChange={(e) => toggleAll(e.target.checked)}
                    aria-label="Select all"
                  />
                </th>
              )}
              {columns.map((col) => {
                const canSort =
                  col.sortable !== false && (col.sortable || globalSortable);
                const isSorted = sortKey === col.key;
                const cls = [
                  canSort ? "dt-sort-th" : "",
                  col.align ? `dt-align-${col.align}` : "",
                  col.sticky ? "dt-sticky-col" : "",
                ]
                  .filter(Boolean)
                  .join(" ");
                return (
                  <th
                    key={col.key}
                    className={cls || undefined}
                    style={{ width: colWidths[col.key] || col.width || undefined }}
                    onClick={() => canSort && handleSort(col.key)}
                    aria-sort={
                      isSorted
                        ? sortDir === "asc"
                          ? "ascending"
                          : "descending"
                        : undefined
                    }
                  >
                    <span className="dt-th-inner">
                      <span>{col.title}</span>
                      {canSort && (
                        <span className="dt-sort-icon" aria-hidden>
                          {isSorted ? (sortDir === "asc" ? "▲" : "▼") : "⇅"}
                        </span>
                      )}
                    </span>
                    {resizable && (
                      <span
                        className="dt-resize-handle"
                        onMouseDown={(e) => startResize(col.key, e)}
                        onClick={(e) => e.stopPropagation()}
                      />
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody
            ref={tbodyRef}
            tabIndex={0}
            onKeyDown={handleRowKeyDown}
          >
            {pageData.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length + (selectable ? 1 : 0)}
                  className="dt-empty"
                >
                  {emptyText}
                </td>
              </tr>
            ) : (
              pageData.map((row, i) => {
                const isSelected = selectedIds.has(row.id);
                const isFocused = focusRow === i;
                const cls = [
                  onRowClick ? "dt-row-clickable" : "",
                  isSelected ? "dt-row-selected" : "",
                  isFocused ? "dt-row-focused" : "",
                ]
                  .filter(Boolean)
                  .join(" ");
                return (
                  <tr
                    key={row.id}
                    className={cls || undefined}
                    onClick={() => onRowClick?.(row)}
                    onContextMenu={(e) => onRowContextMenu?.(row, e)}
                  >
                    {selectable && (
                      <td className="dt-td-check" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleRow(row.id)}
                          aria-label={`Select row ${row.id}`}
                        />
                      </td>
                    )}
                    {columns.map((col) => {
                      const val = getNestedValue(row, col.key);
                      const cls = [
                        col.align ? `dt-align-${col.align}` : "",
                        col.sticky ? "dt-sticky-col" : "",
                      ]
                        .filter(Boolean)
                        .join(" ");
                      return (
                        <td key={col.key} className={cls || undefined}>
                          {col.render
                            ? col.render(val, row, i)
                            : val != null
                              ? String(val)
                              : ""}
                        </td>
                      );
                    })}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
      {paginatable && sorted.length > 0 && (
        <div className="dt-pagination">
          <div className="dt-page-size">
            <span>Rows per page:</span>
            <select
              value={pageSize}
              onChange={(e) => {
                setPage(1);
              }}
            >
              {[10, 25, 50, 100].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
          <div className="dt-page-info">
            {(safePage - 1) * pageSize + 1}–
            {Math.min(safePage * pageSize, sorted.length)} of {sorted.length}
          </div>
          <div className="dt-page-btns">
            <button
              type="button"
              disabled={safePage <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              aria-label="Previous page"
            >
              ‹
            </button>
            <button
              type="button"
              disabled={safePage >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              aria-label="Next page"
            >
              ›
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
