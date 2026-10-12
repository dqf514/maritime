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
import { useListQuery } from "@/lib/useListQuery";
import { useToast } from "@/components/ToastProvider";

type Item = {
  id: string;
  entity_type: string;
  entity_id: string;
  title: string;
  deleted_at: string | null;
};

const TYPE_KEYS: Record<string, string> = {
  vessel: "recycle.type.vessel",
  port: "recycle.type.port",
  counterparty: "recycle.type.counterparty",
  user: "recycle.type.user",
  api_key: "recycle.type.api_key",
  org_unit: "recycle.type.org_unit",
  connector: "recycle.type.connector",
  estimate: "recycle.type.estimate",
  charter: "recycle.type.charter",
  voyage: "recycle.type.voyage",
  invoice: "recycle.type.invoice",
  claim: "recycle.type.claim",
  laytime: "recycle.type.laytime",
};

function RecycleBinPage() {
  const { t } = useI18n();
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
      render: (v) => t(TYPE_KEYS[String(v)] || "", String(v)),
    },
    { key: "title", title: t("common.title", "Title"), minWidth: 180, value: (r) => r.title },
    {
      key: "deleted_at",
      title: t("page.recycle.deleted_at", "Deleted at"),
      width: 180,
      value: (r) => r.deleted_at || "",
      render: (v) => (v ? new Date(String(v)).toLocaleString() : "—"),
    },
    {
      key: "_actions",
      title: "",
      width: 200,
      align: "right",
      render: (_v, r) => (
        <span style={{ display: "flex", gap: "0.4rem" }}>
          <button className="btn btn-primary" type="button" onClick={() => restore(r.id).catch(() => toast.error(t("common.failed", "Failed")))}>
            {t("page.recycle.restore", "Restore")}
          </button>
          <button className="btn btn-danger" type="button" onClick={() => purge(r.id).catch(() => toast.error(t("common.failed", "Failed")))}>
            {t("page.recycle.purge", "Purge")}
          </button>
        </span>
      ),
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
                {t(TYPE_KEYS[ty] || "", ty)}
              </option>
            ))}
          </select>
        }
      >
        <button type="button" className="btn btn-sm" onClick={() => load().catch(() => undefined)} title={t("common.refresh", "Refresh")}>
          ↻
        </button>
        <span className="muted" style={{ fontSize: "var(--font-label)" }}>
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
