"use client";

// C4-P3 数据字典 / UDF 管理 — user-defined field definitions (Excel-dense).
// 列表/筛选/新建/编辑/启停/删除；select 类型 options 以逗号分隔录入。

import { RefreshButton } from "@/components/RefreshButton";
import { msgOf } from "@/lib/errors";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { Toolbar } from "@/components/Toolbar";
import { RecordModal } from "@/components/RecordModal";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StateView } from "@/components/StateView";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiGet, apiPost, apiPatch, apiDelete } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type UdfDef = {
  id: string;
  entity: string;
  field_key: string;
  label_en: string | null;
  label_zh: string | null;
  field_type: string;
  options: { choices?: string[] } | string[] | null;
  required: boolean;
  active: boolean;
  sort_order: number;
};

type EntityOption = { entity: string; label: string };

const FIELD_TYPES = ["text", "number", "date", "select"] as const;

const EMPTY_FORM = {
  entity: "vessel",
  field_key: "",
  label_en: "",
  label_zh: "",
  field_type: "text",
  options_text: "",
  required: false,
  active: true,
  sort_order: "0",
};

function optionsToText(options: UdfDef["options"]): string {
  if (!options) return "";
  const list = Array.isArray(options) ? options : options.choices;
  return Array.isArray(list) ? list.join(", ") : "";
}

function textToOptions(text: string, fieldType: string): string[] | null {
  const list = text
    .split(/[,，\n]/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (fieldType !== "select") return null;
  return list.length ? list : null;
}

export default function UdfDictionaryPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [defs, setDefs] = useState<UdfDef[]>([]);
  const [entities, setEntities] = useState<EntityOption[]>([]);
  const [q, setQ] = useState("");
  const [entityFilter, setEntityFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<UdfDef | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  // 参考数据（实体下拉）失败：局部提示，不阻断整页
  const [entitiesErr, setEntitiesErr] = useState<string | null>(null);
  const [pending, setPending] = useState<{ message: string; danger?: boolean; action: () => void } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const rows = (await apiGet("/api/v1/udf?include_inactive=true")) as UdfDef[];
      setDefs(Array.isArray(rows) ? rows : []);
    } catch (ex) {
      setErr(msgOf(ex));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadEntities = useCallback(async () => {
    setEntitiesErr(null);
    try {
      const rows = (await apiGet("/api/v1/udf/entities")) as EntityOption[];
      setEntities(Array.isArray(rows) ? rows : []);
    } catch (ex) {
      setEntitiesErr(msgOf(ex));
      setEntities([]);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- async load; same pattern as settings/flags
    load();
    loadEntities();
  }, [load, loadEntities]);

  const entityLabel = useCallback(
    (key: string) => entities.find((e) => e.entity === key)?.label || key,
    [entities],
  );

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return defs.filter((d) => {
      if (entityFilter && d.entity !== entityFilter) return false;
      if (!needle) return true;
      return (
        d.field_key.toLowerCase().includes(needle) ||
        (d.label_en || "").toLowerCase().includes(needle) ||
        (d.label_zh || "").toLowerCase().includes(needle) ||
        d.entity.toLowerCase().includes(needle)
      );
    });
  }, [defs, q, entityFilter]);

  function openCreate() {
    setForm({ ...EMPTY_FORM, entity: entityFilter || "vessel" });
    setCreating(true);
    setEditing(null);
  }

  const openEdit = useCallback((row: UdfDef) => {
    setForm({
      entity: row.entity,
      field_key: row.field_key,
      label_en: row.label_en || "",
      label_zh: row.label_zh || "",
      field_type: row.field_type,
      options_text: optionsToText(row.options),
      required: row.required,
      active: row.active,
      sort_order: String(row.sort_order ?? 0),
    });
    setEditing(row);
    setCreating(false);
  }, []);

  async function save(e?: FormEvent) {
    e?.preventDefault();
    if (!form.field_key.trim()) return;
    // 数值校验：sort_order 非法输入 → 中止提交（不静默变 0；0 本身合法）
    const sortOrderRaw = String(form.sort_order ?? "").trim();
    const sortOrder = sortOrderRaw === "" ? 0 : Number(sortOrderRaw);
    if (!Number.isFinite(sortOrder)) {
      toast.error(t("page.udf.invalid_sort_order", "Sort order must be a number."));
      return;
    }
    setBusy(true);
    try {
      const payload = {
        label_en: form.label_en.trim() || null,
        label_zh: form.label_zh.trim() || null,
        field_type: form.field_type,
        options: textToOptions(form.options_text, form.field_type),
        required: form.required,
        active: form.active,
        sort_order: sortOrder,
      };
      if (editing) {
        await apiPatch(`/api/v1/udf/${editing.id}`, payload);
        toast.success(t("page.udf.saved", "Field saved"));
      } else {
        await apiPost("/api/v1/udf", {
          entity: form.entity,
          field_key: form.field_key.trim(),
          ...payload,
        });
        toast.success(t("page.udf.saved", "Field saved"));
      }
      setCreating(false);
      setEditing(null);
      await load();
    } catch (err) {
      toast.error(t("page.udf.save_fail", "Failed to save field: {err}", { err: msgOf(err) }));
    } finally {
      setBusy(false);
    }
  }

  const toggleActive = useCallback(async (row: UdfDef) => {
    try {
      const updated = (await apiPatch(`/api/v1/udf/${row.id}`, { active: !row.active })) as UdfDef;
      setDefs((prev) => prev.map((d) => (d.id === row.id ? { ...d, active: updated.active } : d)));
    } catch (err) {
      toast.error(t("page.udf.save_fail", "Failed to save field: {err}", { err: msgOf(err) }));
    }
  }, [t, toast]);

  const remove = useCallback(async (row: UdfDef) => {
    try {
      await apiDelete(`/api/v1/udf/${row.id}`);
      toast.success(t("page.udf.deleted", "Field deleted"));
      setDefs((prev) => prev.filter((d) => d.id !== row.id));
    } catch (err) {
      toast.error(t("page.udf.delete_fail", "Failed to delete field: {err}", { err: msgOf(err) }));
    }
  }, [t, toast]);

  /** 删除字段不可逆 → ConfirmDialog 二次确认（指名字段） */
  const askRemove = useCallback((row: UdfDef) => {
    setPending({
      message: t(
        "page.udf.confirm_delete",
        "删除字段 {key}（{entity}）？该字段的已录入数据将不可恢复。",
        { key: row.field_key, entity: row.entity },
      ),
      danger: true,
      action: () => {
        remove(row).catch((ex) => toast.error(t("page.udf.delete_fail", "Failed to delete field: {err}", { err: msgOf(ex) })));
      },
    });
  }, [remove, t, toast]);

  const columns = useMemo<ColumnDef<UdfDef>[]>(() => [
    {
      key: "entity",
      title: t("page.udf.col_entity", "Entity"),
      width: 120,
      value: (r) => r.entity,
      render: (v) => entityLabel(String(v)),
    },
    {
      key: "field_key",
      title: t("page.udf.col_field", "Field key"),
      width: 180,
      value: (r) => r.field_key,
      render: (v, r) => (
        <button type="button" className="linklike" onClick={() => openEdit(r)}>
          {String(v)}
        </button>
      ),
    },
    {
      key: "label_en",
      title: t("page.udf.col_label_en", "Label (EN)"),
      minWidth: 150,
      value: (r) => r.label_en || "",
    },
    {
      key: "label_zh",
      title: t("page.udf.col_label_zh", "Label (ZH)"),
      minWidth: 150,
      value: (r) => r.label_zh || "",
    },
    {
      key: "field_type",
      title: t("page.udf.col_type", "Type"),
      width: 90,
      value: (r) => r.field_type,
    },
    {
      key: "required",
      title: t("page.udf.col_required", "Required"),
      width: 80,
      value: (r) => r.required,
      render: (v) => (v ? t("page.udf.yes", "Yes") : t("page.udf.no", "No")),
    },
    {
      key: "active",
      title: t("page.udf.col_active", "Active"),
      width: 80,
      value: (r) => r.active,
      render: (v, r) => (
        <button
          type="button"
          className="linklike"
          title={t("page.udf.toggle_hint", "Click to toggle")}
          onClick={() => toggleActive(r)}
        >
          {v ? t("page.udf.on", "ON") : t("page.udf.off", "OFF")}
        </button>
      ),
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
          title={t("page.udf.delete", "Delete field")}
          aria-label={t("page.udf.delete", "Delete field")}
          onClick={() => askRemove(r)}
        >
          ✕
        </button>
      ),
    },
  ], [t, entityLabel, openEdit, toggleActive, askRemove]);

  const formFields = (
    <>
      <label className="field">
        <span>{t("page.udf.field_entity", "Entity")}</span>
        <select
          className="input"
          value={form.entity}
          disabled={!!editing}
          onChange={(e) => setForm((f) => ({ ...f, entity: e.target.value }))}
        >
          {entities.map((ent) => (
            <option key={ent.entity} value={ent.entity}>
              {ent.label}
            </option>
          ))}
          {!entities.some((ent) => ent.entity === form.entity) ? (
            <option value={form.entity}>{form.entity}</option>
          ) : null}
        </select>
      </label>
      <label className="field">
        <span>{t("page.udf.field_key", "Field key")}</span>
        <input
          className="input"
          value={form.field_key}
          required
          readOnly={!!editing}
          onChange={(e) => setForm((f) => ({ ...f, field_key: e.target.value }))}
          placeholder="custom_grade"
        />
      </label>
      <label className="field">
        <span>{t("page.udf.field_label_en", "Label (EN)")}</span>
        <input
          className="input"
          value={form.label_en}
          onChange={(e) => setForm((f) => ({ ...f, label_en: e.target.value }))}
        />
      </label>
      <label className="field">
        <span>{t("page.udf.field_label_zh", "Label (ZH)")}</span>
        <input
          className="input"
          value={form.label_zh}
          onChange={(e) => setForm((f) => ({ ...f, label_zh: e.target.value }))}
        />
      </label>
      <label className="field">
        <span>{t("page.udf.field_type", "Type")}</span>
        <select
          className="input"
          value={form.field_type}
          onChange={(e) => setForm((f) => ({ ...f, field_type: e.target.value }))}
        >
          {FIELD_TYPES.map((ft) => (
            <option key={ft} value={ft}>
              {ft}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>{t("page.udf.field_sort", "Sort order")}</span>
        <input
          className="input"
          type="number"
          value={form.sort_order}
          onChange={(e) => setForm((f) => ({ ...f, sort_order: e.target.value }))}
        />
      </label>
      {form.field_type === "select" ? (
        <label className="field" style={{ gridColumn: "1 / -1" }}>
          <span>{t("page.udf.field_options", "Options (comma-separated)")}</span>
          <input
            className="input"
            value={form.options_text}
            onChange={(e) => setForm((f) => ({ ...f, options_text: e.target.value }))}
            placeholder="bulk, tanker, container"
          />
        </label>
      ) : null}
      <label className="field">
        <span>{t("page.udf.field_required", "Required")}</span>
        <input
          type="checkbox"
          checked={form.required}
          onChange={(e) => setForm((f) => ({ ...f, required: e.target.checked }))}
        />
      </label>
      <label className="field">
        <span>{t("page.udf.field_active", "Active")}</span>
        <input
          type="checkbox"
          checked={form.active}
          onChange={(e) => setForm((f) => ({ ...f, active: e.target.checked }))}
        />
      </label>
    </>
  );

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[
          { label: t("nav.settings", "Settings"), href: "/settings" },
          { label: t("page.udf.title", "User-defined fields") },
        ]}
        title={t("page.udf.title", "User-defined fields")}
        subtitle={t("page.udf.sub", "Tenant custom fields for standard entities (数据字典 / UDF)")}
        actions={
          <button type="button" className="btn btn-primary btn-sm" onClick={openCreate}>
            {t("page.udf.new", "New field")}
          </button>
        }
      />
      <Toolbar
        filterCount={(q ? 1 : 0) + (entityFilter ? 1 : 0)}
        onClearFilters={() => {
          setQ("");
          setEntityFilter("");
        }}
        right={
          <>
            <select
              className="input input-sm"
              value={entityFilter}
              onChange={(e) => setEntityFilter(e.target.value)}
              aria-label={t("page.udf.filter_entity", "Entity")}
            >
              <option value="">{t("page.udf.all_entities", "All entities")}</option>
              {entities.map((ent) => (
                <option key={ent.entity} value={ent.entity}>
                  {ent.label}
                </option>
              ))}
            </select>
            <input
              className="input input-sm"
              style={{ width: 200 }}
              placeholder={t("page.udf.search", "Search fields…")}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </>
        }
      >
        <RefreshButton label={t("common.refresh", "Refresh")} className="btn btn-sm" onClick={() => load()} />
        <span className="muted" style={{ fontSize: "var(--font-label)" }}>
          {filtered.length} / {defs.length}
        </span>
      </Toolbar>

      {entitiesErr ? <p className="text-danger">{entitiesErr}</p> : null}
      <StateView
        loading={loading}
        error={err ?? undefined}
        empty={!filtered.length}
        onRetry={() => load()}
        emptyText={t("page.udf.empty", "No user-defined fields")}
      >
        <DataGrid<UdfDef>
          columns={columns}
          data={filtered}
          rowKey={(r) => r.id}
          storageKey="settings_udf_grid"
          onRowDoubleClick={(r) => openEdit(r)}
          emptyText={t("page.udf.empty", "No user-defined fields")}
        />
      </StateView>

      <RecordModal
        open={creating || !!editing}
        title={editing ? t("page.udf.edit_title", "Edit field") : t("page.udf.new_title", "New field")}
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

      <ConfirmDialog
        open={Boolean(pending)}
        title={t("common.confirm", "Confirm")}
        message={pending?.message || ""}
        danger={pending?.danger}
        onConfirm={() => {
          const fn = pending?.action;
          setPending(null);
          fn?.();
        }}
        onCancel={() => setPending(null)}
      />
    </AppShell>
  );
}
