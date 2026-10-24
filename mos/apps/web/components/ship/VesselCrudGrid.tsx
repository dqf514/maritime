"use client";

// VesselCrudGrid — generic CRUD table + modal for vessel child resources
// (/api/v1/vessels/{id}/{path}: contacts / routes / tugs / tanks / performance /
// tce-targets / vettings / loadline-zones). Table + RecordModal patterns follow
// masterdata/counterparties.

import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { RecordModal } from "@/components/RecordModal";
import { DataGrid } from "@/components/grid";
import type { ColumnDef as GridColumnDef } from "@/components/grid/types";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { StateView } from "@/components/StateView";
import { ConfirmDialog } from "@/components/ConfirmDialog";

export type FieldDef = {
  key: string;
  label: string;
  /** kv = 对象字段，用 "KEY=VAL; KEY=VAL" 文本编辑（航速油耗曲线的每油品日耗）；checkbox = 布尔开关 */
  type: "text" | "number" | "date" | "select" | "kv" | "checkbox";
  options?: { value: string; label: string }[];
  required?: boolean;
  span?: boolean;
  step?: string;
  placeholder?: string;
};

export type ColumnDef = {
  key: string;
  label: string;
  render?: (row: Record<string, unknown>) => ReactNode;
  /** 传给 DataGrid：数值列右对齐，窄列给固定宽（油耗矩阵列很多，全靠内容自适应会挤） */
  width?: number;
  minWidth?: number;
  align?: "left" | "right" | "center";
};

type Props = {
  vesselId: string;
  path: string;
  title: string;
  columns: ColumnDef[];
  fields: FieldDef[];
  addLabel: string;
  emptyText: string;
  canAdd?: boolean;
  /** 覆盖默认的 /api/v1/vessels/{id}/{path}（masterdata 子资源走另一个前缀） */
  basePath?: string;
  /** 新建时随表单一并提交的固定字段（如银行账户的 counterparty_id —— 父级外键不给用户编辑） */
  defaults?: Record<string, unknown>;
  /** 仅挂在列表 GET 上的查询串（"?counterparty_id=…"）；增删改走 /{id}，不能带它 */
  query?: string;
  /** 字段多的弹窗（如 17 个工况字段的停泊油耗矩阵）用 xl，否则单列堆叠太高 */
  size?: "md" | "lg" | "xl";
};

type Row = Record<string, unknown> & { id: string };

/** "VLF=15.2; LSG=0.1" ↔ {VLF: 15.2, LSG: 0.1} —— 对象字段的可读文本表示。 */
export function parseKv(text: string): Record<string, number> | null {
  const s = (text || "").trim();
  if (!s) return null;
  const out: Record<string, number> = {};
  for (const part of s.split(/[;\n]/)) {
    const seg = part.trim();
    if (!seg) continue;
    const i = seg.indexOf("=");
    const k = i > 0 ? seg.slice(0, i).trim() : "";
    const v = i > 0 ? Number(seg.slice(i + 1).trim()) : NaN;
    if (!k || Number.isNaN(v)) throw new Error(seg);
    out[k] = v;
  }
  return Object.keys(out).length ? out : null;
}

export function formatKv(v: unknown): string {
  if (!v || typeof v !== "object" || Array.isArray(v)) return "";
  return Object.entries(v as Record<string, unknown>)
    .map(([k, val]) => `${k}=${val ?? ""}`)
    .join("; ");
}

export function VesselCrudGrid({
  vesselId,
  path,
  title,
  columns,
  fields,
  addLabel,
  emptyText,
  canAdd = true,
  basePath,
  defaults,
  query,
  size = "md",
}: Props) {
  const { t } = useI18n();
  const toast = useToast();
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Row | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  /** 主列表加载失败 */
  const [err, setErr] = useState<string | null>(null);
  /** 待确认删除的行 */
  const [pendingDel, setPendingDel] = useState<Row | null>(null);

  const base = basePath ?? `/api/v1/vessels/${vesselId}/${path}`;
  const listUrl = query ? `${base}${query}` : base;

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const data = await apiGet(listUrl);
      setRows(Array.isArray(data) ? data : []);
    } catch (ex) {
      // 取数失败 ≠ 没有记录：保留错误态，交由 StateView 显示并可重试
      setRows([]);
      setErr(msgOf(ex));
    } finally {
      setLoading(false);
    }
  }, [listUrl]);

  useEffect(() => {
    void load();
  }, [load]);

  function openCreate() {
    const init: Record<string, unknown> = {};
    for (const f of fields) {
      init[f.key] =
        f.type === "checkbox" ? false : f.type === "select" ? (f.options?.[0]?.value ?? "") : "";
    }
    setDraft(init);
    setEditing(null);
    setFormOpen(true);
  }

  const openEdit = useCallback((row: Row) => {
    const init: Record<string, unknown> = {};
    for (const f of fields) {
      const v = row[f.key];
      init[f.key] =
        f.type === "checkbox"
          ? Boolean(v)
          : v === null || v === undefined
            ? ""
            : f.type === "kv"
              ? formatKv(v)
              : v;
    }
    setDraft(init);
    setEditing(row);
    setFormOpen(true);
  }, [fields]);

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {};
      for (const f of fields) {
        let v = draft[f.key];
        if (f.type === "number") {
          if (v === "" || v === null || v === undefined) v = null;
          else v = Number(v);
        } else if (f.type === "checkbox") {
          v = Boolean(v);
        } else if (f.type === "kv") {
          try {
            v = parseKv(String(v ?? ""));
          } catch {
            toast.error(t("page.vessel.kv_bad", "Expected KEY=VALUE pairs separated by ';'"));
            setSaving(false);
            return;
          }
        } else if (v === "") {
          v = null;
        }
        if (!editing && (v === null || v === undefined) && !f.required) continue;
        payload[f.key] = v;
      }
      if (!editing && defaults) Object.assign(payload, defaults);
      if (editing) {
        await apiPatch(`${base}/${editing.id}`, payload);
      } else {
        await apiPost(base, payload);
      }
      toast.success(t("common.saved", "Saved"));
      setFormOpen(false);
      setEditing(null);
      await load();
    } catch (ex: any) {
      toast.error(msgOf(ex, t("common.failed", "Failed")));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!editing) return;
    try {
      await apiDelete(`${base}/${editing.id}`);
      toast.success(t("common.deleted", "Deleted"));
      setFormOpen(false);
      setEditing(null);
      await load();
    } catch (ex: any) {
      toast.error(msgOf(ex, t("common.failed", "Failed")));
    }
  }

  async function removeRow(r: Row) {
    try {
      await apiDelete(`${base}/${r.id}`);
      toast.success(t("common.deleted", "Deleted"));
      await load();
    } catch (ex: any) {
      toast.error(msgOf(ex, t("common.failed", "Failed")));
    }
  }

  const gridColumns = useMemo<GridColumnDef<Row>[]>(() => [
    ...columns.map((c) => ({
      key: c.key,
      title: c.label,
      width: c.width,
      minWidth: c.minWidth,
      align: c.align,
      value: (r: Row) => r[c.key],
      render: (_v: unknown, r: Row) => (c.render ? c.render(r) : ((r[c.key] as ReactNode) ?? "—")),
    })),
    {
      key: "_actions",
      title: "",
      width: 110,
      align: "right",
      render: (_v: unknown, r: Row) => (
        <>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => openEdit(r)}>
            {t("common.edit", "Edit")}
          </button>
          <button type="button" className="btn btn-ghost btn-sm btn-danger-text" onClick={() => setPendingDel(r)}>
            {t("common.delete", "Delete")}
          </button>
        </>
      ),
    },
  ], [columns, openEdit, t]);

  return (
    <div className="panel">
      <div className="desk-toolbar" style={{ marginTop: 0, justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>{title}</h2>
        {canAdd ? (
          <button type="button" className="btn btn-primary btn-sm" onClick={openCreate}>
            + {addLabel}
          </button>
        ) : null}
      </div>
      <StateView
        loading={loading}
        error={err ?? undefined}
        empty={false}
        emptyText={emptyText}
        onRetry={() => void load()}
      >
        <DataGrid<Row>
          columns={gridColumns}
          data={rows}
          rowKey={(r) => r.id}
          loading={loading}
          emptyText={emptyText}
          onRowDoubleClick={(r) => openEdit(r)}
          storageKey={`vessel_${path}_grid`}
        />
      </StateView>

      <RecordModal
        open={formOpen}
        title={editing ? t("common.edit_record", "Edit record") : addLabel}
        onClose={() => {
          setFormOpen(false);
          setEditing(null);
        }}
        onSave={save}
        onDelete={editing ? remove : undefined}
        saving={saving}
        size={size}
      >
        <div className="form-grid">
          {fields.map((f) =>
            f.type === "checkbox" ? (
              <label key={f.key} className="check-row span-all">
                <input
                  type="checkbox"
                  checked={Boolean(draft[f.key])}
                  onChange={(e) => setDraft({ ...draft, [f.key]: e.target.checked })}
                />
                {f.label}
              </label>
            ) : (
              <label key={f.key} style={f.span ? { gridColumn: "1 / -1" } : undefined}>
                {f.label}
                {f.type === "select" ? (
                  <select
                    value={String(draft[f.key] ?? "")}
                    onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                    required={f.required}
                  >
                    {(f.options ?? []).map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                ) : f.type === "kv" ? (
                  <textarea
                    rows={2}
                    value={String(draft[f.key] ?? "")}
                    onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                    placeholder={f.placeholder || "VLF=15.20; LSG=0.10"}
                    required={f.required}
                  />
                ) : (
                  <input
                    type={f.type === "number" ? "number" : f.type === "date" ? "date" : "text"}
                    step={f.step}
                    value={String(draft[f.key] ?? "")}
                    onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                    placeholder={f.placeholder}
                    required={f.required}
                  />
                )}
              </label>
            ),
          )}
        </div>
      </RecordModal>

      <ConfirmDialog
        open={pendingDel !== null}
        title={t("common.confirm", "Confirm")}
        message={t("page.vessel.confirm_delete_row", "Delete this record? It will move to the recycle bin and can be restored.")}
        confirmLabel={t("common.delete", "Delete")}
        danger
        onConfirm={() => {
          const r = pendingDel;
          setPendingDel(null);
          if (r) void removeRow(r);
        }}
        onCancel={() => setPendingDel(null)}
      />
    </div>
  );
}
