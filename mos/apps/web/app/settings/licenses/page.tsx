"use client";

import { useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { StateView } from "@/components/StateView";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiListLicenses } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";

type Lic = { module_code: string; status: string; is_core: boolean };

export default function LicensesPage() {
  const { t } = useI18n();
  const [rows, setRows] = useState<Lic[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const list = await apiListLicenses();
      setRows(Array.isArray(list) ? list : []);
    } catch (ex) {
      setErr(msgOf(ex));
      setRows([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const columns = useMemo<ColumnDef<Lic>[]>(() => [
    { key: "module_code", title: t("page.licenses.module", "Module"), minWidth: 160, value: (r) => r.module_code },
    {
      key: "status",
      title: t("common.status", "Status"),
      width: 120,
      value: (r) => r.status,
      render: (v) => <span className={`badge badge-${v === "active" ? "ok" : "warn"}`}>{t(`status.${v}`, String(v))}</span>,
    },
    {
      key: "is_core",
      title: t("page.licenses.core", "Core"),
      width: 90,
      value: (r) => r.is_core,
      render: (v) => (v ? t("common.yes", "Yes") : t("common.no", "No")),
    },
  ], [t]);

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[
          { label: t("nav.settings_hub", "System settings"), href: "/settings" },
          { label: t("page.licenses.title", "Module licenses") },
        ]}
        title={t("page.licenses.title", "Module licenses")}
        subtitle={t("page.licenses.sub", "Active module entitlements for this tenant.")}
      />
      <StateView
        loading={loading}
        error={err ?? undefined}
        empty={!rows.length}
        onRetry={() => load()}
        emptyText={t("common.no_data", "No data")}
      >
        <DataGrid<Lic>
          columns={columns}
          data={rows}
          rowKey={(r) => r.module_code}
          storageKey="settings_licenses_grid"
          emptyText={t("common.no_data", "No data")}
        />
      </StateView>
    </AppShell>
  );
}
