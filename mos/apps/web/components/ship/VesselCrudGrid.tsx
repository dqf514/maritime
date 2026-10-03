"use client";

// VesselCrudGrid — generic CRUD table + modal for vessel child resources
// (/api/v1/vessels/{id}/{path}: contacts / routes / tugs / tanks / performance /
// tce-targets / vettings / loadline-zones). Table + RecordModal patterns follow
// masterdata/counterparties.

import { FormEvent, ReactNode, useCallback, useEffect, useState } from "react";
import { RecordModal } from "@/components/RecordModal";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";

export type FieldDef = {
  key: string;
  label: string;
  type: "text" | "number" | "date" | "select";
  options?: { value: string; label: string }[];
  required?: boolean;
  span?: boolean;
  step?: string;
};

export type ColumnDef = {
  key: string;
  label: string;
  render?: (row: Record<string, unknown>) => ReactNode;
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
};

type Row = Record<string, unknown> & { id: string };

export function VesselCrudGrid({
  vesselId,
  path,
  title,
  columns,
  fields,
  addLabel,
  emptyText,
  canAdd = true,
}: Props) {
  const { t } = useI18n();
  const toast = useToast();
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Row | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);

  const base = `/api/v1/vessels/${vesselId}/${path}`;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet(base);
      setRows(Array.isArray(data) ? data : []);
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => {
    let alive = true;
    apiGet(base).then(
      (data) => {
        if (!alive) return;
        setRows(Array.isArray(data) ? data : []);
        setLoading(false);
      },
      () => {
        if (!alive) return;
        setRows([]);
        setLoading(false);
      },
    );
    return () => {
      alive = false;
    };
  }, [base]);

  function openCreate() {
    const init: Record<string, unknown> = {};
    for (const f of fields) {
      init[f.key] = f.type === "number" ? "" : f.type === "select" ? (f.options?.[0]?.value ?? "") : "";
    }
    setDraft(init);
    setEditing(null);
    setFormOpen(true);
  }

  function openEdit(row: Row) {
    const init: Record<string, unknown> = {};
    for (const f of fields) {
      const v = row[f.key];
      init[f.key] = v === null || v === undefined ? "" : v;
    }
    setDraft(init);
    setEditing(row);
    setFormOpen(true);
  }

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
        } else if (v === "") {
          v = null;
        }
        if (!editing && (v === null || v === undefined) && !f.required) continue;
        payload[f.key] = v;
      }
      if (editing) {
        await apiPatch(`${base}/${editing.id}`, payload);
      } else {
        await apiPost(base, payload);
      }
      toast.success(t("common.saved", "Saved"));
      setFormOpen(false);
      setEditing(null);
      await load();
    } catch (err: any) {
      toast.error(err?.message || t("common.failed", "Failed"));
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
    } catch (err: any) {
      toast.error(err?.message || t("common.failed", "Failed"));
    }
  }

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
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key}>{c.label}</th>
            ))}
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              {columns.map((c) => (
                <td key={c.key}>{c.render ? c.render(r) : (r[c.key] as ReactNode) ?? "—"}</td>
              ))}
              <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                <button type="button" className="btn btn-ghost" style={{ fontSize: "0.75rem", padding: "0.1rem 0.4rem" }} onClick={() => openEdit(r)}>
                  {t("common.edit", "Edit")}
                </button>
                <button
                  type="button"
                  className="btn btn-ghost"
                  style={{ fontSize: "0.75rem", padding: "0.1rem 0.4rem", color: "var(--danger)" }}
                  onClick={async () => {
                    try {
                      await apiDelete(`${base}/${r.id}`);
                      toast.success(t("common.deleted", "Deleted"));
                      await load();
                    } catch (err: any) {
                      toast.error(err?.message || t("common.failed", "Failed"));
                    }
                  }}
                >
                  {t("common.delete", "Delete")}
                </button>
              </td>
            </tr>
          ))}
          {!loading && !rows.length ? (
            <tr>
              <td colSpan={columns.length + 1} className="muted">
                {emptyText}
              </td>
            </tr>
          ) : null}
          {loading ? (
            <tr>
              <td colSpan={columns.length + 1} className="muted">
                {t("common.loading", "Loading…")}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>

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
      >
        {fields.map((f) => (
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
            ) : (
              <input
                type={f.type === "number" ? "number" : f.type === "date" ? "date" : "text"}
                step={f.step}
                value={String(draft[f.key] ?? "")}
                onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                required={f.required}
              />
            )}
          </label>
        ))}
      </RecordModal>
    </div>
  );
}
