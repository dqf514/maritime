"use client";

// 配置标志（CFG*）管理 — IMOS Configuration Flag List 同构。
// 租户 + 平台两级 flags：查看/搜索/新建/编辑/删除，bool 值内联开关。

import { FormEvent, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { SavedViews } from "@/components/SavedViews";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { StatusBadge } from "@/components/StatusBadge";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiDelete, apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";
import { useToast } from "@/components/ToastProvider";

type Flag = {
  id: string;
  flag_key: string;
  flag_value: string;
  value_type: string;
  category: string;
  scope_key: string;
  description: string | null;
  tenant_id: string | null;
  user_id: string | null;
};

const EMPTY_FORM = { key: "", value: "", value_type: "string", category: "general", description: "" };

function ConfigFlagsPage() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const { query, setQuery } = useListQuery();
  const q = query.q ?? "";
  const category = query.category ?? "";
  const [flags, setFlags] = useState<Flag[]>([]);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<Flag | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);

  const load = useCallback(async () => {
    const qs = category ? `?category=${encodeURIComponent(category)}` : "";
    const rows = (await apiGet(`/api/v1/config/flags${qs}`)) as Flag[];
    setFlags(rows);
  }, [category]);

  useEffect(() => {
    load().catch(() => setFlags([]));
  }, [load]);

  const categories = useMemo(() => Array.from(new Set(flags.map((f) => f.category))).sort(), [flags]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return flags;
    return flags.filter(
      (f) =>
        f.flag_key.toLowerCase().includes(needle) ||
        f.description?.toLowerCase().includes(needle) ||
        f.category.toLowerCase().includes(needle),
    );
  }, [flags, q]);

  function openCreate() {
    setForm(EMPTY_FORM);
    setCreating(true);
  }

  useListHotkeys(openCreate);

  function openEdit(row: Flag) {
    setForm({
      key: row.flag_key,
      value: row.flag_value,
      value_type: row.value_type,
      category: row.category,
      description: row.description || "",
    });
    setEditing(row);
  }

  async function save(e?: FormEvent) {
    e?.preventDefault();
    if (!form.key.trim()) return;
    setBusy(true);
    try {
      await apiPost("/api/v1/config/flags", {
        key: form.key.trim(),
        value: form.value,
        value_type: form.value_type,
        category: form.category || "general",
        description: form.description || null,
      });
      toast.success(t("flags.saved", "Flag saved"));
      setCreating(false);
      setEditing(null);
      await load();
    } catch (err) {
      toast.error(t("flags.save_fail", "Failed to save flag: {err}", { err: String(err) }));
    } finally {
      setBusy(false);
    }
  }

  async function toggleBool(row: Flag) {
    const next = /^(true|1|yes|on)$/i.test(row.flag_value) ? "false" : "true";
    try {
      await apiPost("/api/v1/config/flags", {
        key: row.flag_key,
        value: next,
        value_type: "bool",
        category: row.category,
        description: row.description,
      });
      setFlags((prev) => prev.map((f) => (f.id === row.id ? { ...f, flag_value: next } : f)));
    } catch (err) {
      toast.error(t("flags.save_fail", "Failed to save flag: {err}", { err: String(err) }));
    }
  }

  async function remove(row: Flag) {
    try {
      await apiDelete(`/api/v1/config/flags/${row.id}`);
      toast.success(t("flags.deleted", "Flag deleted"));
      setFlags((prev) => prev.filter((f) => f.id !== row.id));
    } catch (err) {
      toast.error(t("flags.delete_fail", "Failed to delete flag: {err}", { err: String(err) }));
    }
  }

  const columns: ColumnDef<Flag>[] = [
    {
      key: "flag_key",
      title: t("flags.col_key", "Flag"),
      width: 260,
      value: (r) => r.flag_key,
      render: (v, r) => (
        <button type="button" className="linklike" onClick={() => openEdit(r)} title={r.description || undefined}>
          {String(v)}
        </button>
      ),
    },
    {
      key: "flag_value",
      title: t("flags.col_value", "Value"),
      width: 170,
      value: (r) => r.flag_value,
      render: (v, r) =>
        r.value_type === "bool" ? (
          <button
            type="button"
            className="linklike"
            onClick={() => toggleBool(r)}
            title={t("flags.toggle_hint", "Click to toggle")}
          >
            <StatusBadge status={String(v)} tone={/^(true|1|yes|on)$/i.test(String(v)) ? "ok" : "muted"} label={/^(true|1|yes|on)$/i.test(String(v)) ? t("flags.on", "ON") : t("flags.off", "OFF")} />
          </button>
        ) : (
          <span title={String(v)}>{String(v)}</span>
        ),
    },
    { key: "value_type", title: t("flags.col_type", "Type"), width: 70, value: (r) => r.value_type },
    { key: "category", title: t("flags.col_category", "Category"), width: 110, value: (r) => r.category },
    {
      key: "scope_key",
      title: t("flags.col_scope", "Scope"),
      width: 80,
      value: (r) => r.scope_key,
      render: (v) => <StatusBadge status={String(v)} tone={v === "platform" ? "info" : "ok"} />,
    },
    {
      key: "description",
      title: t("flags.col_desc", "Description"),
      minWidth: 200,
      value: (r) => r.description || "",
    },
    {
      key: "_actions",
      title: "",
      width: 60,
      align: "right",
      render: (_v, r) => (
        <button
          type="button"
          className="btn btn-sm btn-danger"
          title={t("flags.delete", "Delete flag")}
          onClick={() => remove(r)}
        >
          ✕
        </button>
      ),
    },
  ];

  const formFields = (
    <>
      <label className="field">
        <span>{t("flags.field_key", "Key")}</span>
        <input
          className="input"
          value={form.key}
          required
          readOnly={!!editing}
          onChange={(e) => setForm((f) => ({ ...f, key: e.target.value }))}
          placeholder="CFGEnableFixedEstimateLocking"
        />
      </label>
      <label className="field">
        <span>{t("flags.field_type", "Value type")}</span>
        <select
          className="input"
          value={form.value_type}
          onChange={(e) => setForm((f) => ({ ...f, value_type: e.target.value }))}
        >
          <option value="string">string</option>
          <option value="bool">bool</option>
          <option value="number">number</option>
          <option value="json">json</option>
        </select>
      </label>
      <label className="field">
        <span>{t("flags.field_value", "Value")}</span>
        <input className="input" value={form.value} onChange={(e) => setForm((f) => ({ ...f, value: e.target.value }))} />
      </label>
      <label className="field">
        <span>{t("flags.field_category", "Category")}</span>
        <input
          className="input"
          value={form.category}
          onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
        />
      </label>
      <label className="field" style={{ gridColumn: "1 / -1" }}>
        <span>{t("flags.field_desc", "Description")}</span>
        <input
          className="input"
          value={form.description}
          onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
        />
      </label>
    </>
  );

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[
          { label: t("nav.settings_hub", "System settings"), href: "/settings" },
          { label: t("flags.title", "Configuration flags") },
        ]}
        title={t("flags.title", "Configuration flags")}
        subtitle={t("flags.sub", "Runtime switches at tenant and platform scope — CFG* catalogue")}
        actions={
          <SavedViews
            storageKey="settings_flags"
            onApply={(qs) => router.replace(`/settings/flags${qs}`)}
          />
        }
      />
      <Toolbar
        filterCount={(q ? 1 : 0) + (category ? 1 : 0)}
        onClearFilters={() => setQuery({ q: null, category: null }, { resetPage: true })}
        right={
          <>
            <select
              className="input input-sm"
              value={category}
              onChange={(e) => setQuery({ category: e.target.value || null }, { resetPage: true })}
              aria-label={t("flags.filter_category", "Category")}
            >
              <option value="">{t("flags.all_categories", "All categories")}</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <input
              className="input input-sm"
              style={{ width: 200 }}
              placeholder={t("flags.search", "Search flags…")}
              value={q}
              onChange={(e) => setQuery({ q: e.target.value || null }, { resetPage: true })}
            />
          </>
        }
      >
        <button type="button" className="btn btn-primary btn-sm" onClick={openCreate}>
          {t("flags.new", "New flag")}
        </button>
        <button type="button" className="btn btn-sm" onClick={() => load()} title={t("common.refresh", "Refresh")}>
          ↻
        </button>
        <span className="muted" style={{ fontSize: "var(--font-label)" }}>
          {filtered.length} / {flags.length}
        </span>
      </Toolbar>

      <DataGrid<Flag>
        columns={columns}
        data={filtered}
        rowKey={(r) => r.id}
        storageKey="settings_flags"
        onRowDoubleClick={(r) => openEdit(r)}
        emptyText={t("flags.empty", "No configuration flags")}
      />

      <RecordModal
        open={creating || !!editing}
        title={editing ? t("flags.edit_title", "Edit flag") : t("flags.new_title", "New flag")}
        onClose={() => {
          setCreating(false);
          setEditing(null);
        }}
        onSave={save}
        onDelete={editing ? () => remove(editing) : undefined}
        saving={busy}
        size="md"
      >
        <div className="form-grid">{formFields}</div>
      </RecordModal>
    </AppShell>
  );
}

// Next 16: useSearchParams（useListQuery）须位于 Suspense 边界内
export default function Page() {
  return (
    <Suspense fallback={null}>
      <ConfigFlagsPage />
    </Suspense>
  );
}
