"use client";

// Phase 4 Rate Tables — 运价/费率表密集工作台
// 左栏表目录（按 kind 过滤）+ 右栏行编辑 DataGrid / 运价矩阵（装港×卸港）
// + 定价模板（多表绑定报价配方）。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { FormPanel, FormSection, FieldRow } from "@/components/form/FormPanel";
import { RecordModal } from "@/components/RecordModal";
import { DateInput } from "@/components/DateInput";
import { StateView } from "@/components/StateView";
import { useToast } from "@/components/ToastProvider";
import { apiDelete, apiList, apiPatch, apiPost } from "@/lib/api";
import { downloadCsv, parseCsv } from "@/lib/csv";
import { useI18n } from "@/lib/i18n";

const RATE_KINDS = ["freight_matrix", "surcharge", "demurrage_rate", "laytime_hours_rate", "bunker_surcharge"] as const;
const RATE_UNITS = ["per_mt", "lumpsum", "per_day", "per_hour", "pct"] as const;
const DIM_ORDER = ["load_port", "disch_port", "route", "cargo_type"];

type RateTable = {
  id: string;
  name: string;
  kind: string;
  currency: string;
  valid_from: string | null;
  valid_to: string | null;
  description: string | null;
  is_active: boolean;
};

type RateRow = {
  id: string;
  rate_table_id: string;
  dims: Record<string, string>;
  value: number;
  unit: string | null;
  priority: number;
  notes: string | null;
};

type PricingTemplate = {
  id: string;
  name: string;
  description: string | null;
  rate_table_refs: Record<string, string>;
  rules: Record<string, unknown>;
  is_active: boolean;
};

type DimPair = { k: string; v: string };

export default function RatesPage() {
  const { t } = useI18n();
  const toast = useToast();

  // —— 表目录 ——
  const [tables, setTables] = useState<RateTable[]>([]);
  const [kindFilter, setKindFilter] = useState("");
  const [tablesLoading, setTablesLoading] = useState(true);
  const [tablesErr, setTablesErr] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // —— 行数据 ——
  const [rows, setRows] = useState<RateRow[]>([]);
  const [rowsLoading, setRowsLoading] = useState(false);
  const [rowsErr, setRowsErr] = useState("");
  const [view, setView] = useState<"rows" | "matrix">("rows");

  // —— 新建表弹窗 ——
  const [tableModal, setTableModal] = useState(false);
  const [tableSaving, setTableSaving] = useState(false);
  const [tableForm, setTableForm] = useState({
    name: "",
    kind: "freight_matrix",
    currency: "USD",
    valid_from: "",
    valid_to: "",
    description: "",
    is_active: true,
  });

  // —— 新建行弹窗 ——
  const [rowModal, setRowModal] = useState(false);
  const [rowSaving, setRowSaving] = useState(false);
  const [rowForm, setRowForm] = useState({
    dims: [{ k: "load_port", v: "" }, { k: "disch_port", v: "" }] as DimPair[],
    value: "0",
    unit: "",
    priority: "0",
    notes: "",
  });

  // —— CSV 导入 ——
  const fileRef = useRef<HTMLInputElement>(null);

  // —— 定价模板 ——
  const [templates, setTemplates] = useState<PricingTemplate[]>([]);
  const [tplModal, setTplModal] = useState(false);
  const [tplSaving, setTplSaving] = useState(false);
  const [tplEditingId, setTplEditingId] = useState<string | null>(null);
  const [tplForm, setTplForm] = useState({
    name: "",
    description: "",
    is_active: true,
    refs: [{ role: "freight", tableId: "" }] as { role: string; tableId: string }[],
  });

  const selected = useMemo(() => tables.find((x) => x.id === selectedId) ?? null, [tables, selectedId]);

  // —— 加载 ——
  const loadTables = useCallback(async () => {
    setTablesLoading(true);
    setTablesErr("");
    try {
      const page = await apiList<RateTable>("/api/v1/rates/tables", {
        kind: kindFilter || null,
        limit: 200,
      });
      setTables(page.items);
      setSelectedId((cur) => {
        if (cur && page.items.some((x) => x.id === cur)) return cur;
        return page.items[0]?.id ?? null;
      });
    } catch (ex) {
      setTablesErr(String(ex));
    } finally {
      setTablesLoading(false);
    }
  }, [kindFilter]);

  const loadRows = useCallback(async (tableId: string | null) => {
    if (!tableId) {
      setRows([]);
      return;
    }
    setRowsLoading(true);
    setRowsErr("");
    try {
      const page = await apiList<RateRow>(`/api/v1/rates/tables/${tableId}/rows`, { limit: 200 });
      setRows(page.items);
    } catch (ex) {
      setRowsErr(String(ex));
    } finally {
      setRowsLoading(false);
    }
  }, []);

  const loadTemplates = useCallback(async () => {
    try {
      const page = await apiList<PricingTemplate>("/api/v1/rates/templates", { limit: 100 });
      setTemplates(page.items);
    } catch {
      setTemplates([]);
    }
  }, []);

  useEffect(() => {
    loadTables();
    loadTemplates();
  }, [loadTables, loadTemplates]);

  useEffect(() => {
    loadRows(selectedId);
  }, [selectedId, loadRows]);

  // —— 表 CRUD ——
  async function createTable() {
    if (!tableForm.name.trim()) {
      toast.error(t("page.rates.need_name", "请填写费率表名称"));
      return;
    }
    setTableSaving(true);
    try {
      const created = (await apiPost("/api/v1/rates/tables", {
        name: tableForm.name.trim(),
        kind: tableForm.kind,
        currency: (tableForm.currency || "USD").toUpperCase(),
        valid_from: tableForm.valid_from || null,
        valid_to: tableForm.valid_to || null,
        description: tableForm.description || null,
        is_active: tableForm.is_active,
      })) as RateTable;
      toast.success(t("page.rates.table_created", "Rate table created"));
      setTableModal(false);
      setTableForm({
        name: "",
        kind: "freight_matrix",
        currency: "USD",
        valid_from: "",
        valid_to: "",
        description: "",
        is_active: true,
      });
      await loadTables();
      if (created?.id) setSelectedId(created.id);
    } catch (ex) {
      toast.error(String(ex));
    } finally {
      setTableSaving(false);
    }
  }

  // —— 行编辑（DataGrid 内联） ——
  const saveCell = useCallback(
    async (rowId: string, colKey: string, value: unknown, row: RateRow) => {
      try {
        if (colKey.startsWith("dim.")) {
          const k = colKey.slice(4);
          const dims: Record<string, string> = { ...row.dims };
          if (value === null || value === undefined || value === "") delete dims[k];
          else dims[k] = String(value);
          await apiPatch(`/api/v1/rates/tables/${selectedId}/rows/${rowId}`, { dims });
        } else if (colKey === "value" || colKey === "priority") {
          await apiPatch(`/api/v1/rates/tables/${selectedId}/rows/${rowId}`, {
            [colKey]: value === null || value === "" ? 0 : Number(value),
          });
        } else {
          await apiPatch(`/api/v1/rates/tables/${selectedId}/rows/${rowId}`, {
            [colKey]: value === null || value === "" ? null : value,
          });
        }
        await loadRows(selectedId);
      } catch (ex) {
        toast.error(String(ex));
      }
    },
    [selectedId, loadRows, toast],
  );

  const deleteRow = useCallback(
    async (rowId: string) => {
      try {
        await apiDelete(`/api/v1/rates/tables/${selectedId}/rows/${rowId}`);
        toast.success(t("page.rates.row_deleted", "Rate row deleted"));
        await loadRows(selectedId);
      } catch (ex) {
        toast.error(String(ex));
      }
    },
    [selectedId, loadRows, toast, t],
  );

  async function createRow() {
    const dims: Record<string, string> = {};
    for (const { k, v } of rowForm.dims) {
      if (k.trim() && v.trim()) dims[k.trim()] = v.trim();
    }
    const value = Number(rowForm.value);
    if (!Number.isFinite(value)) {
      toast.error(t("page.rates.bad_value", "费率值必须是有效数字"));
      return;
    }
    setRowSaving(true);
    try {
      await apiPost(`/api/v1/rates/tables/${selectedId}/rows`, {
        dims,
        value,
        unit: rowForm.unit || null,
        priority: Number(rowForm.priority) || 0,
        notes: rowForm.notes || null,
      });
      toast.success(t("page.rates.row_created", "Rate row added"));
      setRowModal(false);
      await loadRows(selectedId);
    } catch (ex) {
      toast.error(String(ex));
    } finally {
      setRowSaving(false);
    }
  }

  // —— CSV 导入 / 导出 ——
  async function importCsv(file: File) {
    if (!selectedId) return;
    try {
      const matrix = parseCsv(await file.text());
      if (matrix.length < 2) {
        toast.error(t("page.rates.csv_empty", "CSV 无有效数据行"));
        return;
      }
      const headers = matrix[0].map((h) => h.trim());
      const idxField: Record<string, number> = { value: -1, unit: -1, priority: -1, notes: -1 };
      headers.forEach((h, i) => {
        if (h in idxField) idxField[h] = i;
      });
      let ok = 0;
      for (const line of matrix.slice(1)) {
        const dims: Record<string, string> = {};
        headers.forEach((h, i) => {
          if (h in idxField) return;
          const v = (line[i] ?? "").trim();
          if (h && v) dims[h] = v;
        });
        const rawVal = idxField.value >= 0 ? line[idxField.value] : "0";
        const value = Number(rawVal);
        if (!Number.isFinite(value)) continue;
        await apiPost(`/api/v1/rates/tables/${selectedId}/rows`, {
          dims,
          value,
          unit: idxField.unit >= 0 ? line[idxField.unit] || null : null,
          priority: idxField.priority >= 0 ? Number(line[idxField.priority]) || 0 : 0,
          notes: idxField.notes >= 0 ? line[idxField.notes] || null : null,
        });
        ok++;
      }
      toast.success(t("page.rates.csv_imported", "Imported {n} rows", { n: ok }));
      await loadRows(selectedId);
    } catch (ex) {
      toast.error(String(ex));
    }
  }

  function exportCsv() {
    const dimKeys = collectDimKeys(rows);
    const headers = [...dimKeys, "value", "unit", "priority", "notes"];
    downloadCsv(
      `${(selected?.name || "rates").replace(/\s+/g, "_")}_rows`,
      headers,
      rows.map((r) => [...dimKeys.map((k) => r.dims[k] ?? ""), r.value, r.unit ?? "", r.priority, r.notes ?? ""]),
    );
  }

  // —— 运价矩阵 ——
  const matrix = useMemo(() => buildMatrix(rows), [rows]);

  async function saveMatrixCell(loadPort: string, dischPort: string, raw: string, existing: RateRow | null) {
    if (!raw.trim()) return; // 空输入不动已有/不新建
    const value = Number(raw);
    if (!Number.isFinite(value)) return;
    if (existing && Number(existing.value) === value) return;
    try {
      if (existing) {
        await apiPatch(`/api/v1/rates/tables/${selectedId}/rows/${existing.id}`, { value });
      } else {
        await apiPost(`/api/v1/rates/tables/${selectedId}/rows`, {
          dims: { load_port: loadPort, disch_port: dischPort },
          value,
        });
      }
      await loadRows(selectedId);
    } catch (ex) {
      toast.error(String(ex));
    }
  }

  // —— 定价模板 ——
  function openTpl(tpl?: PricingTemplate) {
    if (tpl) {
      setTplEditingId(tpl.id);
      setTplForm({
        name: tpl.name,
        description: tpl.description ?? "",
        is_active: tpl.is_active,
        refs: Object.entries(tpl.rate_table_refs || {}).map(([role, tableId]) => ({ role, tableId })),
      });
    } else {
      setTplEditingId(null);
      setTplForm({ name: "", description: "", is_active: true, refs: [{ role: "freight", tableId: "" }] });
    }
    setTplModal(true);
  }

  async function saveTpl() {
    if (!tplForm.name.trim()) {
      toast.error(t("page.rates.need_tpl_name", "请填写模板名称"));
      return;
    }
    const refs: Record<string, string> = {};
    for (const { role, tableId } of tplForm.refs) {
      if (role.trim() && tableId) refs[role.trim()] = tableId;
    }
    setTplSaving(true);
    try {
      const body = {
        name: tplForm.name.trim(),
        description: tplForm.description || null,
        is_active: tplForm.is_active,
        rate_table_refs: refs,
      };
      if (tplEditingId) await apiPatch(`/api/v1/rates/templates/${tplEditingId}`, body);
      else await apiPost("/api/v1/rates/templates", body);
      toast.success(t("common.saved", "Saved"));
      setTplModal(false);
      await loadTemplates();
    } catch (ex) {
      toast.error(String(ex));
    } finally {
      setTplSaving(false);
    }
  }

  // —— 行网格列（dims 拍平成列） ——
  const dimKeys = useMemo(() => collectDimKeys(rows), [rows]);
  const columns = useMemo<ColumnDef<RateRow>[]>(() => {
    const dimCols: ColumnDef<RateRow>[] = dimKeys.map((k) => ({
      key: `dim.${k}`,
      title: k,
      width: 110,
      sortable: true,
      editor: { type: "text" },
      value: (r) => r.dims[k] ?? "",
    }));
    return [
      ...dimCols,
      {
        key: "value",
        title: t("page.rates.value", "Value"),
        width: 90,
        align: "right",
        sortable: true,
        agg: "sum",
        editor: { type: "number", step: 0.000001 },
        value: (r) => r.value,
      },
      {
        key: "unit",
        title: t("page.rates.unit", "Unit"),
        width: 100,
        editor: {
          type: "select",
          options: RATE_UNITS.map((u) => ({ value: u, label: u })),
        },
        value: (r) => r.unit ?? "",
      },
      {
        key: "priority",
        title: t("page.rates.priority", "Priority"),
        width: 80,
        align: "right",
        editor: { type: "number" },
        value: (r) => r.priority,
      },
      {
        key: "notes",
        title: t("page.rates.notes", "Notes"),
        width: 160,
        editor: { type: "text" },
        value: (r) => r.notes ?? "",
      },
      {
        key: "_del",
        title: "",
        width: 32,
        render: (_v, r) => (
          <button
            type="button"
            className="icon-btn-sm"
            title={t("common.delete", "Delete")}
            onClick={(e) => {
              e.stopPropagation();
              deleteRow(r.id);
            }}
          >
            ×
          </button>
        ),
      },
    ];
  }, [dimKeys, t, deleteRow]);

  const kindLabel = (k: string) => t(`page.rates.kind.${k}`, k.replace(/_/g, " "));

  return (
    <AppShell>
      <PageHeader
        title={t("page.rates.title", "Rate Tables")}
        subtitle={t("page.rates.sub", "运价/费率表与定价模板。选中表后在网格中直接编辑费率行。")}
      />

      <div className="rates-toolbar">
        <label className="field-inline" style={{ display: "inline-flex", alignItems: "center", gap: "var(--gap-xs)" }}>
          <span style={{ fontSize: "var(--font-label)", color: "var(--muted)" }}>
            {t("page.rates.kind_filter", "Kind")}
          </span>
          <select value={kindFilter} onChange={(e) => setKindFilter(e.target.value)}>
            <option value="">{t("page.rates.all_kinds", "All kinds")}</option>
            {RATE_KINDS.map((k) => (
              <option key={k} value={k}>
                {kindLabel(k)}
              </option>
            ))}
          </select>
        </label>
        <div className="spacer" />
        <button type="button" className="btn btn-primary" onClick={() => setTableModal(true)}>
          {t("page.rates.new_table", "New Table")}
        </button>
      </div>

      <div className="rates-layout">
        <aside className="panel rates-side-list">
          <StateView loading={tablesLoading} error={tablesErr} empty={!tables.length} onRetry={loadTables}>
            {tables.map((tb) => (
              <button
                key={tb.id}
                type="button"
                className={`rates-side-item${tb.id === selectedId ? " active" : ""}`}
                onClick={() => setSelectedId(tb.id)}
              >
                <span className="rates-side-name">{tb.name}</span>
                <span className="rates-side-meta">
                  <span className={`badge ${tb.is_active ? "badge-pass" : "badge-fail"}`}>{kindLabel(tb.kind)}</span>
                  <span>{tb.currency}</span>
                  <span>
                    {tb.valid_from ?? "…"} → {tb.valid_to ?? "…"}
                  </span>
                </span>
              </button>
            ))}
          </StateView>
        </aside>

        <section className="rates-main">
          <div className="rates-head">
            <span className="rates-head-title">{selected ? selected.name : t("page.rates.no_table", "No table selected")}</span>
            {selected ? (
              <span className="rates-head-meta">
                {kindLabel(selected.kind)} · {selected.currency}
                {selected.valid_from ? ` · ${selected.valid_from}` : ""}
                {selected.valid_to ? ` → ${selected.valid_to}` : ""}
              </span>
            ) : null}
            <div className="spacer" />
            {selected?.kind === "freight_matrix" ? (
              <div className="seg">
                <button type="button" className={view === "rows" ? "active" : ""} onClick={() => setView("rows")}>
                  {t("page.rates.rows_view", "Rows")}
                </button>
                <button type="button" className={view === "matrix" ? "active" : ""} onClick={() => setView("matrix")}>
                  {t("page.rates.matrix_view", "Freight Matrix")}
                </button>
              </div>
            ) : null}
            <button type="button" className="btn btn-ghost btn-sm" disabled={!selected} onClick={() => setRowModal(true)}>
              {t("page.rates.new_row", "New Row")}
            </button>
            <button type="button" className="btn btn-ghost btn-sm" disabled={!selected} onClick={() => fileRef.current?.click()}>
              {t("page.rates.import_csv", "Import CSV")}
            </button>
            <button type="button" className="btn btn-ghost btn-sm" disabled={!rows.length} onClick={exportCsv}>
              {t("page.rates.export_csv", "Export CSV")}
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,text/csv"
              style={{ display: "none" }}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) importCsv(f);
                e.target.value = "";
              }}
            />
          </div>

          <div className="rates-body">
            {!selected ? (
              <div className="state-view">
                <span className="state-view-text muted">
                  {t("page.rates.pick_table", "选择左侧费率表以编辑行数据")}
                </span>
              </div>
            ) : view === "matrix" && selected.kind === "freight_matrix" ? (
              <StateView loading={rowsLoading} error={rowsErr} empty={!matrix.cells.size} onRetry={() => loadRows(selectedId)}>
                <div className="rate-matrix-wrap">
                  <table className="rate-matrix">
                    <thead>
                      <tr>
                        <th className="matrix-corner">{t("page.rates.load_port", "Load port")} ＼ {t("page.rates.disch_port", "Disch port")}</th>
                        {matrix.dischPorts.map((dp) => (
                          <th key={dp}>{dp}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {matrix.loadPorts.map((lp) => (
                        <tr key={lp}>
                          <th className="matrix-row-head">{lp}</th>
                          {matrix.dischPorts.map((dp) => {
                            const cell = matrix.cells.get(`${lp}|${dp}`) ?? null;
                            return (
                              <td key={dp} className={cell ? "" : "matrix-empty"}>
                                <input
                                  key={`${lp}|${dp}|${cell?.value ?? ""}`}
                                  type="number"
                                  step="0.000001"
                                  defaultValue={cell ? String(cell.value) : ""}
                                  onBlur={(e) => saveMatrixCell(lp, dp, e.target.value, cell)}
                                  onKeyDown={(e) => {
                                    if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                                  }}
                                />
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </StateView>
            ) : (
              <StateView loading={rowsLoading} error={rowsErr} empty={!rows.length} onRetry={() => loadRows(selectedId)}>
                <DataGrid<RateRow>
                  columns={columns}
                  data={rows}
                  rowKey={(r) => r.id}
                  editable
                  onCellSave={saveCell}
                  storageKey={`rates_rows_${selected.id}`}
                  emptyText={t("common.empty", "No records")}
                />
              </StateView>
            )}
          </div>

          {/* 定价模板 */}
          <div className="rates-templates panel">
            <div style={{ display: "flex", alignItems: "center", gap: "var(--gap-md)", marginBottom: "var(--gap-sm)" }}>
              <h3 style={{ margin: 0 }}>{t("page.rates.templates", "Pricing Templates")}</h3>
              <span className="muted" style={{ fontSize: "var(--font-label)" }}>
                {t("page.rates.templates_hint", "把多张费率表绑成一套报价配方（freight / surcharge / demurrage…）")}
              </span>
              <div className="spacer" style={{ flex: 1 }} />
              <button type="button" className="btn btn-primary btn-sm" onClick={() => openTpl()}>
                {t("page.rates.new_template", "New Template")}
              </button>
            </div>
            <table className="table">
              <thead>
                <tr>
                  <th>{t("common.name", "Name")}</th>
                  <th>{t("common.description", "Description")}</th>
                  <th>{t("page.rates.linked_tables", "Linked rate tables")}</th>
                  <th>{t("common.status", "Status")}</th>
                </tr>
              </thead>
              <tbody>
                {templates.map((tpl) => (
                  <tr key={tpl.id} className="row-openable" onClick={() => openTpl(tpl)}>
                    <td>{tpl.name}</td>
                    <td className="muted">{tpl.description || "—"}</td>
                    <td>
                      {Object.entries(tpl.rate_table_refs || {}).length
                        ? Object.entries(tpl.rate_table_refs)
                            .map(([role, tid]) => {
                              const name = tables.find((x) => x.id === tid)?.name ?? tid.slice(0, 8);
                              return `${role}: ${name}`;
                            })
                            .join(" · ")
                        : "—"}
                    </td>
                    <td>
                      <span className={`badge ${tpl.is_active ? "badge-pass" : "badge-fail"}`}>
                        {tpl.is_active ? t("common.active", "Active") : t("common.inactive", "Inactive")}
                      </span>
                    </td>
                  </tr>
                ))}
                {!templates.length ? (
                  <tr>
                    <td colSpan={4} className="muted">
                      {t("common.empty", "No records")}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      {/* 新建费率表 */}
      <RecordModal
        open={tableModal}
        title={t("page.rates.new_table", "New Table")}
        onClose={() => setTableModal(false)}
        onSave={createTable}
        canDelete={false}
        saving={tableSaving}
      >
        <FormPanel>
          <FormSection title={t("page.rates.table_meta", "Table")}>
            <FieldRow label={t("common.name", "Name")}>
              <input
                value={tableForm.name}
                onChange={(e) => setTableForm({ ...tableForm, name: e.target.value })}
                required
              />
            </FieldRow>
            <FieldRow label={t("page.rates.kind", "Kind")}>
              <select value={tableForm.kind} onChange={(e) => setTableForm({ ...tableForm, kind: e.target.value })}>
                {RATE_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {kindLabel(k)}
                  </option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label={t("page.rates.currency", "Currency")}>
              <input
                value={tableForm.currency}
                onChange={(e) => setTableForm({ ...tableForm, currency: e.target.value })}
                maxLength={3}
              />
            </FieldRow>
            <FieldRow label={t("page.rates.valid_from", "Valid from")}>
              <DateInput value={tableForm.valid_from} onChange={(v) => setTableForm({ ...tableForm, valid_from: v })} />
            </FieldRow>
            <FieldRow label={t("page.rates.valid_to", "Valid to")}>
              <DateInput value={tableForm.valid_to} onChange={(v) => setTableForm({ ...tableForm, valid_to: v })} />
            </FieldRow>
            <FieldRow label={t("page.rates.is_active", "Active")}>
              <input
                type="checkbox"
                checked={tableForm.is_active}
                onChange={(e) => setTableForm({ ...tableForm, is_active: e.target.checked })}
                style={{ height: "var(--input-h)" }}
              />
            </FieldRow>
            <FieldRow label={t("common.description", "Description")} span={2}>
              <textarea
                value={tableForm.description}
                onChange={(e) => setTableForm({ ...tableForm, description: e.target.value })}
              />
            </FieldRow>
          </FormSection>
        </FormPanel>
      </RecordModal>

      {/* 新建费率行 */}
      <RecordModal
        open={rowModal}
        title={t("page.rates.new_row", "New Row")}
        onClose={() => setRowModal(false)}
        onSave={createRow}
        canDelete={false}
        saving={rowSaving}
      >
        <FormPanel>
          <FormSection title={t("page.rates.dimensions", "Dimensions")} dense>
            <div className="dim-editor">
              {rowForm.dims.map((pair, i) => (
                <div key={i} className="dim-editor-row">
                  <input
                    placeholder={t("page.rates.dim_key", "dim key")}
                    value={pair.k}
                    onChange={(e) => {
                      const dims = [...rowForm.dims];
                      dims[i] = { ...dims[i], k: e.target.value };
                      setRowForm({ ...rowForm, dims });
                    }}
                  />
                  <input
                    placeholder={t("page.rates.dim_value", "value")}
                    value={pair.v}
                    onChange={(e) => {
                      const dims = [...rowForm.dims];
                      dims[i] = { ...dims[i], v: e.target.value };
                      setRowForm({ ...rowForm, dims });
                    }}
                  />
                  <button
                    type="button"
                    className="icon-btn-sm"
                    onClick={() => setRowForm({ ...rowForm, dims: rowForm.dims.filter((_, j) => j !== i) })}
                  >
                    ×
                  </button>
                </div>
              ))}
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setRowForm({ ...rowForm, dims: [...rowForm.dims, { k: "", v: "" }] })}
              >
                + {t("page.rates.add_dim", "Add dimension")}
              </button>
            </div>
          </FormSection>
          <FormSection title={t("page.rates.rate_value", "Rate")}>
            <FieldRow label={t("page.rates.value", "Value")}>
              <input
                type="number"
                step="0.000001"
                value={rowForm.value}
                onChange={(e) => setRowForm({ ...rowForm, value: e.target.value })}
                required
              />
            </FieldRow>
            <FieldRow label={t("page.rates.unit", "Unit")}>
              <select value={rowForm.unit} onChange={(e) => setRowForm({ ...rowForm, unit: e.target.value })}>
                <option value="">{t("common.select", "Select…")}</option>
                {RATE_UNITS.map((u) => (
                  <option key={u} value={u}>
                    {u}
                  </option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label={t("page.rates.priority", "Priority")}>
              <input
                type="number"
                value={rowForm.priority}
                onChange={(e) => setRowForm({ ...rowForm, priority: e.target.value })}
              />
            </FieldRow>
            <FieldRow label={t("page.rates.notes", "Notes")}>
              <input value={rowForm.notes} onChange={(e) => setRowForm({ ...rowForm, notes: e.target.value })} />
            </FieldRow>
          </FormSection>
        </FormPanel>
      </RecordModal>

      {/* 定价模板 */}
      <RecordModal
        open={tplModal}
        title={tplEditingId ? t("page.rates.edit_template", "Edit Template") : t("page.rates.new_template", "New Template")}
        onClose={() => setTplModal(false)}
        onSave={saveTpl}
        canDelete={false}
        saving={tplSaving}
        size="lg"
      >
        <FormPanel>
          <FormSection title={t("page.rates.template_meta", "Template")}>
            <FieldRow label={t("common.name", "Name")}>
              <input value={tplForm.name} onChange={(e) => setTplForm({ ...tplForm, name: e.target.value })} required />
            </FieldRow>
            <FieldRow label={t("page.rates.is_active", "Active")}>
              <input
                type="checkbox"
                checked={tplForm.is_active}
                onChange={(e) => setTplForm({ ...tplForm, is_active: e.target.checked })}
                style={{ height: "var(--input-h)" }}
              />
            </FieldRow>
            <FieldRow label={t("common.description", "Description")} span={2}>
              <textarea value={tplForm.description} onChange={(e) => setTplForm({ ...tplForm, description: e.target.value })} />
            </FieldRow>
          </FormSection>
          <FormSection title={t("page.rates.rate_table_refs", "Rate table references")} dense>
            <div className="dim-editor">
              {tplForm.refs.map((pair, i) => (
                <div key={i} className="tpl-ref-row">
                  <input
                    placeholder={t("page.rates.role", "role")}
                    value={pair.role}
                    onChange={(e) => {
                      const refs = [...tplForm.refs];
                      refs[i] = { ...refs[i], role: e.target.value };
                      setTplForm({ ...tplForm, refs });
                    }}
                  />
                  <select
                    value={pair.tableId}
                    onChange={(e) => {
                      const refs = [...tplForm.refs];
                      refs[i] = { ...refs[i], tableId: e.target.value };
                      setTplForm({ ...tplForm, refs });
                    }}
                  >
                    <option value="">{t("common.select", "Select…")}</option>
                    {tables.map((tb) => (
                      <option key={tb.id} value={tb.id}>
                        {tb.name} ({kindLabel(tb.kind)})
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="icon-btn-sm"
                    onClick={() => setTplForm({ ...tplForm, refs: tplForm.refs.filter((_, j) => j !== i) })}
                  >
                    ×
                  </button>
                </div>
              ))}
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setTplForm({ ...tplForm, refs: [...tplForm.refs, { role: "", tableId: "" }] })}
              >
                + {t("page.rates.add_ref", "Add reference")}
              </button>
            </div>
          </FormSection>
        </FormPanel>
      </RecordModal>
    </AppShell>
  );
}

// —— helpers ——

/** dims 键并集：常见维度固定在前，其余按字母序。 */
function collectDimKeys(rows: RateRow[]): string[] {
  const set = new Set<string>();
  for (const r of rows) for (const k of Object.keys(r.dims || {})) set.add(k);
  const known = DIM_ORDER.filter((k) => set.has(k));
  const rest = [...set].filter((k) => !DIM_ORDER.includes(k)).sort();
  return [...known, ...rest];
}

/** 运价矩阵：装港行 × 卸港列（同一格多行时取维度最具体者）。 */
function buildMatrix(rows: RateRow[]) {
  const loadPorts = new Set<string>();
  const dischPorts = new Set<string>();
  const cells = new Map<string, RateRow>();
  for (const r of rows) {
    const lp = r.dims?.load_port;
    const dp = r.dims?.disch_port;
    if (!lp || !dp) continue;
    loadPorts.add(lp);
    dischPorts.add(dp);
    const key = `${lp}|${dp}`;
    const prev = cells.get(key);
    if (!prev || Object.keys(r.dims).length < Object.keys(prev.dims).length) cells.set(key, r);
  }
  return {
    loadPorts: [...loadPorts].sort(),
    dischPorts: [...dischPorts].sort(),
    cells,
  };
}
