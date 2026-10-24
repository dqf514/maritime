"use client";

import { msgOf } from "@/lib/errors";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { SavedViews } from "@/components/SavedViews";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { clearLookupCache } from "@/components/LookupSelect";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StateView } from "@/components/StateView";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";
import { useToast } from "@/components/ToastProvider";

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

function ReferenceAdminPage() {
  const { t, locale } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const { query, setQuery } = useListQuery();
  const selected = query.ds || "countries";
  const q = query.q ?? "";
  const loc = locale?.startsWith("zh") ? "zh-CN" : "en";
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [items, setItems] = useState<Item[]>([]);
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
  // 数据集（下拉/参考数据）失败 → 局部提示；条目列表失败 → 列表级 error
  const [datasetsErr, setDatasetsErr] = useState<string | null>(null);
  const [itemsErr, setItemsErr] = useState<string | null>(null);
  const [itemsLoading, setItemsLoading] = useState(false);
  const [pending, setPending] = useState<{ message: string; danger?: boolean; action: () => void } | null>(null);

  const loadDatasets = useCallback(async () => {
    setDatasetsErr(null);
    try {
      const rows = await apiGet(`/api/v1/reference/datasets?locale=${loc}`);
      setDatasets(Array.isArray(rows) ? rows : []);
      if (rows.length && !rows.find((d: Dataset) => d.code === selected)) {
        setQuery({ ds: rows[0].code }, { resetPage: true });
      }
    } catch (ex) {
      setDatasetsErr(msgOf(ex));
      setDatasets([]);
    }
  }, [loc, selected, setQuery]);

  const loadItems = useCallback(async () => {
    if (!selected) return;
    setItemsLoading(true);
    setItemsErr(null);
    try {
      const qs = new URLSearchParams({ locale: loc });
      if (q.trim()) qs.set("q", q.trim());
      const rows = await apiGet(`/api/v1/reference/${encodeURIComponent(selected)}/admin/items?${qs}`);
      setItems(Array.isArray(rows) ? rows : []);
    } catch (ex) {
      setItemsErr(msgOf(ex));
      setItems([]);
    } finally {
      setItemsLoading(false);
    }
  }, [selected, loc, q]);

  useEffect(() => {
    loadDatasets();
  }, [loadDatasets]);

  useEffect(() => {
    loadItems();
  }, [loadItems]);

  const current = datasets.find((d) => d.code === selected);

  async function clone() {
    setBusy(true);
    try {
      const res = await apiPost(`/api/v1/reference/${selected}/clone`);
      toast.success(t("page.ref.cloned", "Cloned to local: {n} items", { n: String(res.cloned) }));
      clearLookupCache(selected);
      await loadDatasets();
      await loadItems();
    } catch (e) {
      toast.error(t("page.ref.clone_fail", "Failed to clone system pack: {err}", { err: msgOf(e) }));
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    setBusy(true);
    try {
      await apiPost(`/api/v1/reference/${selected}/reset`);
      toast.success(t("page.ref.reset_ok", "Restored system pack"));
      clearLookupCache(selected);
      await loadDatasets();
      await loadItems();
    } catch (e) {
      toast.error(t("page.ref.reset_fail", "Failed to restore system pack: {err}", { err: msgOf(e) }));
    } finally {
      setBusy(false);
    }
  }

  /** 恢复系统包会删除本地副本 → ConfirmDialog 二次确认（指名数据集） */
  function askReset() {
    setPending({
      message: t(
        "page.ref.confirm_reset",
        "删除数据集 {ds} 的本地副本并切回系统包？本地新增/修改的条目将丢失。",
        { ds: current?.name || selected },
      ),
      danger: true,
      action: () => {
        reset().catch((ex) => toast.error(t("page.ref.reset_fail", "Failed to restore system pack: {err}", { err: msgOf(ex) })));
      },
    });
  }

  function openCreate() {
    setCreating(true);
    setOpen(null);
    setEdit({ code: "", label_en: "", label_zh: "", sort_order: "0", active: true });
  }

  useListHotkeys(openCreate);

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
    // 数值校验：sort_order 非法输入 → 中止提交（不静默变 0；0 本身合法）
    const sortOrderRaw = String(edit.sort_order ?? "").trim();
    const sortOrder = sortOrderRaw === "" ? 0 : Number(sortOrderRaw);
    if (!Number.isFinite(sortOrder)) {
      toast.error(t("page.ref.invalid_sort_order", "Sort order must be a number."));
      return;
    }
    setBusy(true);
    try {
      if (creating) {
        await apiPost(`/api/v1/reference/${selected}/items`, {
          code: edit.code,
          label_en: edit.label_en,
          label_zh: edit.label_zh,
          sort_order: sortOrder,
          active: edit.active,
        });
        toast.success(t("common.created", "Created"));
      } else if (open) {
        await apiPatch(`/api/v1/reference/items/${open.id}`, {
          code: edit.code,
          label_en: edit.label_en,
          label_zh: edit.label_zh,
          sort_order: sortOrder,
          active: edit.active,
        });
        toast.success(t("common.saved", "Saved"));
      }
      clearLookupCache(selected);
      setOpen(null);
      setCreating(false);
      await loadDatasets();
      await loadItems();
    } catch (e) {
      toast.error(t("page.ref.save_fail", "Failed to save item: {err}", { err: msgOf(e) }));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!open) return;
    setBusy(true);
    try {
      await apiDelete(`/api/v1/reference/items/${open.id}`);
      toast.success(t("common.deleted", "Deleted"));
      clearLookupCache(selected);
      setOpen(null);
      await loadDatasets();
      await loadItems();
    } catch (e) {
      toast.error(t("page.ref.delete_fail", "Failed to delete item: {err}", { err: msgOf(e) }));
    } finally {
      setBusy(false);
    }
  }

  const itemColumns = useMemo<ColumnDef<Item>[]>(() => [
    {
      key: "code",
      title: t("common.code", "Code"),
      width: 140,
      value: (r) => r.code,
      render: (v, r) =>
        current?.mode === "local" ? (
          <button type="button" className="linklike" onClick={() => openEdit(r)}>
            {String(v)}
          </button>
        ) : (
          String(v)
        ),
    },
    { key: "label_zh", title: t("page.ref.label_zh", "Chinese"), minWidth: 140, value: (r) => r.label_zh },
    { key: "label_en", title: t("page.ref.label_en", "English"), minWidth: 140, value: (r) => r.label_en },
    {
      key: "active",
      title: t("common.status", "Status"),
      width: 100,
      value: (r) => r.active,
      render: (v) => (v ? t("common.active", "Active") : t("common.inactive", "Inactive")),
    },
    { key: "source", title: t("page.ref.source", "Source"), width: 100, value: (r) => r.source },
  ], [current?.mode, t]);

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[
          { label: t("nav.settings_hub", "System settings"), href: "/settings" },
          { label: t("page.ref.title", "Reference data") },
        ]}
        title={t("page.ref.title", "Reference data")}
        subtitle={t(
          "page.ref.sub",
          "Countries, time zones, currencies, vessel types and other standard options. Clone the system pack to customize locally; business forms pick up values by the current mode.",
        )}
        actions={
          <>
            <SavedViews
              storageKey="settings_reference"
              onApply={(qs) => router.replace(`/settings/reference${qs}`)}
            />
            <Link href="/settings" className="btn btn-ghost">
              {t("nav.settings_hub", "System settings")}
            </Link>
          </>
        }
      />

      <Toolbar
        filterCount={(q ? 1 : 0) + (selected !== "countries" ? 1 : 0)}
        onClearFilters={() => setQuery({ q: null, ds: null }, { resetPage: true })}
        right={
          <input
            className="input input-sm"
            style={{ width: 200 }}
            value={q}
            onChange={(e) => setQuery({ q: e.target.value || null }, { resetPage: true })}
            placeholder={t("common.search", "Search")}
          />
        }
      >
        <label style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
          <span className="muted">{t("page.ref.dataset", "Dataset")}</span>
          <select
            className="input input-sm"
            value={selected}
            onChange={(e) => setQuery({ ds: e.target.value || null }, { resetPage: true })}
          >
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
        <button type="button" className="btn" disabled={busy || current?.mode !== "local"} onClick={askReset}>
          {t("page.ref.reset", "Restore system pack")}
        </button>
        <button type="button" className="btn" disabled={busy} onClick={openCreate}>
          {t("page.ref.add", "New item")}
        </button>
      </Toolbar>
      {current ? (
        <p className="muted">
          {current.description} · {t("page.ref.mode", "Mode")}: {current.mode} ·{" "}
          {t("page.ref.counts", "System {s} / Local {l}", {
            s: String(current.system_count),
            l: String(current.local_count),
          })}
        </p>
      ) : null}

      {datasetsErr ? <p className="text-danger">{datasetsErr}</p> : null}
      <div className="panel" style={{ marginTop: "1rem" }}>
        <StateView
          loading={itemsLoading}
          error={itemsErr ?? undefined}
          empty={!items.length}
          onRetry={() => loadItems()}
          emptyText={
            current?.mode === "system"
              ? t("page.ref.system_hint", "Using system pack (read-only). Clone to edit.")
              : t("common.empty", "No records")
          }
        >
          <DataGrid<Item>
            columns={itemColumns}
            data={items}
            rowKey={(r) => r.id}
            storageKey="settings_reference_items_grid"
            onRowDoubleClick={(r) => {
              if (current?.mode === "local") openEdit(r);
            }}
            emptyText={
              current?.mode === "system"
                ? t("page.ref.system_hint", "Using system pack (read-only). Clone to edit.")
                : t("common.empty", "No records")
            }
          />
        </StateView>
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

// Next 16: useSearchParams（useListQuery）须位于 Suspense 边界内
export default function Page() {
  return (
    <Suspense fallback={null}>
      <ReferenceAdminPage />
    </Suspense>
  );
}
