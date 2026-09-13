"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function WorkflowsAdminPage() {
  const { t } = useI18n();
  const [rows, setRows] = useState<Array<Record<string, unknown>>>([]);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    apiGet("/api/v1/admin/workflows")
      .then(setRows)
      .catch(() => setMsg(t("page.wf.admin_required", "Tenant admin required")));
  }, [t]);

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("page.wf.title", "Enterprise workflows")}</h1>
      <p className="page-sub">{t("page.wf.sub", "Approval process definitions.")}</p>
      {msg ? <p>{msg}</p> : null}
      <div className="panel">
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.code", "Code")}</th>
              <th>{t("common.name", "Name")}</th>
              <th>{t("page.wf.entity", "Entity")}</th>
              <th>{t("page.wf.steps", "Steps")}</th>
              <th>{t("page.wf.enabled", "Enabled")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={String(r.id)}>
                <td>{String(r.code)}</td>
                <td>{String(r.name)}</td>
                <td>{String(r.entity_type)}</td>
                <td>
                  <code>{JSON.stringify((r.steps as { steps?: unknown })?.steps || r.steps)}</code>
                </td>
                <td>{String(r.enabled)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
