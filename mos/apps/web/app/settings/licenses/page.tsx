"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { apiListLicenses } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Lic = { module_code: string; status: string; is_core: boolean };

export default function LicensesPage() {
  const { t } = useI18n();
  const [rows, setRows] = useState<Lic[]>([]);

  useEffect(() => {
    apiListLicenses().then(setRows).catch(() => setRows([]));
  }, []);

  return (
    <AppShell>
      <PageHeader
        title={t("page.licenses.title", "Module licenses")}
        subtitle={t("page.licenses.sub", "Active module entitlements for this tenant.")}
      />
      <div className="panel">
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.licenses.module", "Module")}</th>
              <th>{t("common.status", "Status")}</th>
              <th>{t("page.licenses.core", "Core")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.module_code}>
                <td>{r.module_code}</td>
                <td>{r.status}</td>
                <td>{r.is_core ? t("page.licenses.yes", "yes") : t("page.licenses.no", "no")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
