"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { RecordModal } from "@/components/RecordModal";
import { clearLookupCache } from "@/components/LookupSelect";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Dataset = {
  code: string;
  name: string;
  description: string;
  mode: string;
  system_count: number;
  local_count: number;
  active_local_count: number;
};

type Item = {
  id: string;
  code: string;
  label: string;
  label_en: string;
  label_zh: string;
  sort_order: number;
  active: boolean;
  source: string;
};

export default function ReferenceAdminPage() {
  const { t, locale } = useI18n();
  const loc = locale?.startsWith("zh") ? "zh-CN" : "en";
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [selected, setSelected] = useState<string>("countries");
  const [items, setItems] = useState<Item[]>([]);
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<Item | null>(null);
  const [creating, setCreating] = useState(false);
  const [edit, setEdit] = useState({
    code: "",
    label_en: "",
    label_zh: "",
    sort_order: "0",
    active: true,
  });

  const loadDatasets = useCallback(async () => {
    const rows = await apiGet(`/api/v1/reference/datasets?locale=${loc}`);
    setDatasets(rows);
    if (rows.length && !rows.find((d: Dataset) => d.code === selected)) {
      setSelected(rows[0].code);
    }
  }, [loc, selected]);

  const loadItems = useCallback(async () => {
    if (!selected) return;
    const qs = new URLSearchParams({ locale: loc });
    if (q.trim()) qs.set("q", q.trim());
    const rows = await apiGet(`/api/v1/reference/${encodeURIComponent(selected)}/admin/items?${qs}`);
    setItems(rows);
  }, [selected, loc, q]);

  useEffect(() => {
    loadDatasets().catch(() => setDatasets([]));
  }, [loadDatasets]);

  useEffect(() => {
    loadItems().catch(() => setItems([]));
  }, [loadItems]);

  const current = datasets.find((d) => d.code === selected);

  async function clone() {
    setBusy(true);
    try {
      const res = await apiPost(`/api/v1/reference/${selected}/clone`);
      setMsg(t("page.ref.cloned", "Cloned to local: {n} items", { n: String(res.cloned) }));
      clearLookupCache(selected);
      await loadDatasets();
      await loadItems();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    if (!window.confirm(t("page.ref.confirm_reset", "Delete the local copy and switch back to the system pack?"))) return;
    setBusy(true);
    try {
      await apiPost(`/api/v1/reference/${selected}/reset`);
      setMsg(t("page.ref.reset_ok", "Restored system pack"));
      clearLookupCache(selected);
      await loadDatasets();
      await loadItems();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  function openCreate() {
    setCreating(true);
    setOpen(null);
    setEdit({ code: "", label_en: "", label_zh: "", sort_order: "0", active: true });
  }

  function openEdit(r: Item) {
    setCreating(false);
    setOpen(r);
    setEdit({
      code: r.code,
      label_en: r.label_en,
      label_zh: r.label_zh,
      sort_order: String(r.sort_order),
      active: r.active,
    });
  }

  async function save() {
    setBusy(true);
    try {
      if (creating) {
        await apiPost(`/api/v1/reference/${selected}/items`, {
          code: edit.code,
          label_en: edit.label_en,
          label_zh: edit.label_zh,
          sort_order: Number(edit.sort_order) || 0,
          active: edit.active,
        });
        setMsg(t("common.created", "Created"));
      } else if (open) {
        await apiPatch(`/api/v1/reference/items/${open.id}`, {
          code: edit.code,
          label_en: edit.label_en,
          label_zh: edit.label_zh,
          sort_order: Number(edit.sort_order) || 0,
          active: edit.active,
        });
        setMsg(t("common.saved", "Saved"));
      }
      clearLookupCache(selected);
      setOpen(null);
      setCreating(false);
      await loadDatasets();
      await loadItems();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!open) return;
    setBusy(true);
    try {
      await apiDelete(`/api/v1/reference/items/${open.id}`);
      setMsg(t("common.deleted", "Deleted"));
      clearLookupCache(selected);
      setOpen(null);
      await loadDatasets();
      await loadItems();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.ref.title", "Reference data")}</h1>
          <p className="page-sub">
            {t(
              "page.ref.sub",
              "国家、时区、货币、船型、油种等标准选项。可复制系统包到本租户后自定义；业务表单将自动按当前模式取值。",
            )}
          </p>
        </div>
        <Link href="/settings" className="btn btn-ghost">
          {t("nav.settings_hub", "System settings")}
        </Link>
      </div>
      {msg ? <p className="flash">{msg}</p> : null}

      <div className="panel">
        <div className="desk-toolbar" style={{ flexWrap: "wrap" }}>
          <label>
            {t("page.ref.dataset", "Dataset")}
            <select value={selected} onChange={(e) => setSelected(e.target.value)}>
              {datasets.map((d) => (
                <option key={d.code} value={d.code}>
                  {d.name} ({d.mode === "local" ? t("page.ref.local", "Local") : t("page.ref.system", "System")})
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="btn btn-primary" disabled={busy} onClick={clone}>
            {t("page.ref.clone", "Clone system pack")}
          </button>
          <button type="button" className="btn" disabled={busy || current?.mode !== "local"} onClick={reset}>
            {t("page.ref.reset", "Restore system pack")}
          </button>
          <button type="button" className="btn" disabled={busy} onClick={openCreate}>
            {t("page.ref.add", "New item")}
          </button>
        </div>
        {current ? (
          <p className="muted">
            {current.description} · {t("page.ref.mode", "Mode")}: {current.mode} ·{" "}
            {t("page.ref.counts", "System {s} / Local {l}", {
              s: String(current.system_count),
              l: String(current.local_count),
            })}
          </p>
        ) : null}
      </div>

      <div className="panel" style={{ marginTop: "1rem" }}>
        <form
          className="desk-toolbar"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            loadItems().catch(() => undefined);
          }}
        >
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("common.search", "Search")} />
          <button type="submit" className="btn">
            {t("common.search", "Search")}
          </button>
        </form>
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.code", "代码")}</th>
              <th>{t("page.ref.label_zh", "Chinese")}</th>
              <th>{t("page.ref.label_en", "English")}</th>
              <th>{t("common.status", "Status")}</th>
              <th>{t("page.ref.source", "Source")}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((r) => (
              <tr
                key={r.id}
                className={current?.mode === "local" ? "row-openable" : undefined}
                onClick={() => {
                  if (current?.mode === "local") openEdit(r);
                }}
              >
                <td>{r.code}</td>
                <td>{r.label_zh}</td>
                <td>{r.label_en}</td>
                <td>{r.active ? t("common.active", "Active") : t("common.inactive", "Inactive")}</td>
                <td>{r.source}</td>
              </tr>
            ))}
            {!items.length ? (
              <tr>
                <td colSpan={5} className="muted">
                  {current?.mode === "system"
                    ? t("page.ref.system_hint", "Using system pack (read-only). Clone to edit.")
                    : t("common.empty", "No records")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <RecordModal
        open={creating || Boolean(open)}
        title={creating ? t("page.ref.add", "New item") : t("page.ref.edit", "Edit item")}
        onClose={() => {
          setCreating(false);
          setOpen(null);
        }}
        onSave={save}
        onDelete={open ? remove : undefined}
        canDelete={Boolean(open)}
        saving={busy}
      >
        <p className="muted">
          {t("page.ref.edit_hint", "Create/edit switches to local mode (auto-clones if needed).")}
        </p>
        <label>
          {t("common.code", "代码")}
          <input value={edit.code} onChange={(e) => setEdit({ ...edit, code: e.target.value })} required />
        </label>
        <label>
          {t("page.ref.label_zh", "Chinese")}
          <input value={edit.label_zh} onChange={(e) => setEdit({ ...edit, label_zh: e.target.value })} required />
        </label>
        <label>
          {t("page.ref.label_en", "English")}
          <input value={edit.label_en} onChange={(e) => setEdit({ ...edit, label_en: e.target.value })} required />
        </label>
        <label>
          {t("page.ref.sort", "Sort")}
          <input type="number" value={edit.sort_order} onChange={(e) => setEdit({ ...edit, sort_order: e.target.value })} />
        </label>
        <label>
          <input type="checkbox" checked={edit.active} onChange={(e) => setEdit({ ...edit, active: e.target.checked })} />{" "}
          {t("common.active", "Active")}
        </label>
      </RecordModal>
    </AppShell>
  );
}
