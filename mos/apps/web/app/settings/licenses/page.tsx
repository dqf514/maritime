"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiListLicenses } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Lic = { module_code: string; status: string; is_core: boolean };

export default function LicensesPage() {
  const { t } = useI18n();
  const [rows, setRows] = useState<Lic[]>([]);

  useEffect(() => {
    apiListLicenses().then(setRows).catch(() => setRows([]));
  }, []);

  const columns: ColumnDef<Lic>[] = [
    { key: "module_code", title: t("page.licenses.module", "Module"), minWidth: 160, value: (r) => r.module_code },
    { key: "status", title: t("common.status", "Status"), width: 120, value: (r) => r.status },
    {
      key: "is_core",
      title: t("page.licenses.core", "Core"),
      width: 90,
      value: (r) => r.is_core,
      render: (v) => (v ? t("page.licenses.yes", "yes") : t("page.licenses.no", "no")),
    },
  ];

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
      <DataGrid<Lic>
        columns={columns}
        data={rows}
        rowKey={(r) => r.module_code}
        storageKey="settings_licenses_grid"
        emptyText={t("common.no_data", "No data")}
      />
    </AppShell>
  );
}
