"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { SavedViews } from "@/components/SavedViews";
import { Toolbar } from "@/components/Toolbar";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiDelete, apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { formatInTz } from "@/lib/datetime";
import { useListQuery } from "@/lib/useListQuery";
import { useToast } from "@/components/ToastProvider";

type Item = {
  id: string;
  entity_type: string;
  entity_id: string;
  title: string;
  deleted_at: string | null;
  restorable?: boolean;
  source_missing?: boolean;
};

function RecycleBinPage() {
  const { t, locale } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const { query, setQuery } = useListQuery();
  const filterType = query.type ?? "";
  const [rows, setRows] = useState<Item[]>([]);

  async function load() {
    setRows(await apiGet("/api/v1/recycle-bin"));
  }

  useEffect(() => {
    load().catch(() => toast.error(t("page.recycle.load_fail", "Unable to load recycle bin (sign-in required)")));
  }, [t]);

  async function restore(id: string) {
    await apiPost(`/api/v1/recycle-bin/${id}/restore`);
    toast.success(t("page.recycle.restored", "Restored"));
    await load();
  }

  async function purge(id: string) {
    if (!window.confirm(t("page.recycle.purge_confirm", "Permanently purge this recycle entry? This cannot be undone."))) return;
    await apiDelete(`/api/v1/recycle-bin/${id}`);
    toast.success(t("page.recycle.purged", "Permanently purged"));
    await load();
  }

  const typeOptions = Array.from(new Set(rows.map((r) => r.entity_type))).sort();
  const filtered = filterType ? rows.filter((r) => r.entity_type === filterType) : rows;

  const columns: ColumnDef<Item>[] = [
    {
      key: "entity_type",
      title: t("page.recycle.type", "Type"),
      width: 140,
      value: (r) => r.entity_type,
      render: (v) => t(`recycle.type.${String(v)}`, String(v)),
    },
    { key: "title", title: t("common.title", "Title"), minWidth: 180, value: (r) => r.title },
    {
      key: "deleted_at",
      title: t("page.recycle.deleted_at", "Deleted at"),
      width: 180,
      value: (r) => r.deleted_at || "",
      render: (v) => formatInTz(v as string | null, null, undefined, locale),
    },
    {
      key: "state",
      title: t("page.recycle.state", "State"),
      width: 160,
      value: (r) => (r.source_missing ? "source_missing" : r.restorable === false ? "unsupported" : "restorable"),
      render: (v) => {
        const key = String(v);
        if (key === "source_missing") {
          return <span className="muted">{t("page.recycle.source_missing", "Source record no longer exists")}</span>;
        }
        if (key === "unsupported") {
          return <span className="muted">{t("page.recycle.unsupported", "This type cannot be restored")}</span>;
        }
        return <span>{t("page.recycle.restorable", "Restorable")}</span>;
      },
    },
    {
      key: "_actions",
      title: "",
      width: 200,
      align: "right",
      render: (_v, r) => {
        const blocked = r.restorable === false || r.source_missing === true;
        return (
          <span className="row-actions">
            <button
              className="btn btn-primary"
              type="button"
              disabled={blocked}
              title={
                blocked
                  ? r.source_missing
                    ? t("page.recycle.source_missing", "Source record no longer exists")
                    : t("page.recycle.unsupported", "This type cannot be restored")
                  : t("page.recycle.restore", "Restore")
              }
              onClick={() => restore(r.id).catch(() => toast.error(t("common.failed", "Failed")))}
            >
              {t("page.recycle.restore", "Restore")}
            </button>
            <button className="btn btn-danger" type="button" onClick={() => purge(r.id).catch(() => toast.error(t("common.failed", "Failed")))}>
              {t("page.recycle.purge", "Purge")}
            </button>
          </span>
        );
      },
    },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[
          { label: t("nav.settings_hub", "System settings"), href: "/settings" },
          { label: t("page.recycle.title", "Recycle bin") },
        ]}
        title={t("page.recycle.title", "Recycle bin")}
        subtitle={t(
          "page.recycle.sub",
          "Soft-deleted records appear here. Restore to the business list, or purge permanently.",
        )}
        actions={
          <SavedViews
            storageKey="settings_recycle"
            onApply={(qs) => router.replace(`/settings/recycle${qs}`)}
          />
        }
      />
      <Toolbar
        filterCount={filterType ? 1 : 0}
        onClearFilters={() => setQuery({ type: null }, { resetPage: true })}
        right={
          <select
            className="input input-sm"
            value={filterType}
            onChange={(e) => setQuery({ type: e.target.value || null }, { resetPage: true })}
            aria-label={t("page.recycle.type", "Type")}
          >
            <option value="">{t("common.all", "All")}</option>
            {typeOptions.map((ty) => (
              <option key={ty} value={ty}>
                {t(`recycle.type.${ty}`, ty)}
              </option>
            ))}
          </select>
        }
      >
        <button type="button" className="btn btn-sm" onClick={() => load().catch(() => undefined)} title={t("common.refresh", "Refresh")}>
          ↻
        </button>
        <span className="muted">
          {filtered.length} / {rows.length}
        </span>
      </Toolbar>
      <DataGrid<Item>
        columns={columns}
        data={filtered}
        rowKey={(r) => r.id}
        storageKey="settings_recycle_grid"
        emptyText={t("page.recycle.empty", "Recycle bin is empty")}
      />
    </AppShell>
  );
}

// Next 16: useSearchParams（useListQuery）须位于 Suspense 边界内
export default function Page() {
  return (
    <Suspense fallback={null}>
      <RecycleBinPage />
    </Suspense>
  );
}
