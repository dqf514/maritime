"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Item = {
  id: string;
  entity_type: string;
  entity_id: string;
  definition: string | null;
  step: { name?: string; role_code?: string } | null;
};

export default function WorkflowInboxPage() {
  const { t } = useI18n();
  const [rows, setRows] = useState<Item[]>([]);
  const [msg, setMsg] = useState("");

  async function load() {
    setRows(await apiGet("/api/v1/workflows/inbox"));
  }

  useEffect(() => {
    load().catch(() => setRows([]));
  }, []);

  async function decide(id: string, decision: string) {
    await apiPost(`/api/v1/workflows/${id}/decide`, { decision });
    setMsg(t("page.inbox.decided", "{decision} recorded", { decision }));
    await load();
  }

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("page.inbox.title", "Approval inbox")}</h1>
      <p className="page-sub">{t("page.inbox.sub", "Pending business approvals for your role.")}</p>
      {msg ? <p>{msg}</p> : null}
      <div className="panel">
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.inbox.process", "Process")}</th>
              <th>{t("page.inbox.entity", "Entity")}</th>
              <th>{t("page.inbox.step", "Step")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.definition}</td>
                <td>
                  {r.entity_type} · {r.entity_id.slice(0, 8)}
                </td>
                <td>
                  {r.step?.name} ({r.step?.role_code})
                </td>
                <td style={{ display: "flex", gap: "0.35rem" }}>
                  <button
                    className="btn btn-primary"
                    type="button"
                    onClick={() => decide(r.id, "approve").catch(() => setMsg(t("common.failed", "Failed")))}
                  >
                    {t("common.approve", "Approve")}
                  </button>
                  <button className="btn" type="button" onClick={() => decide(r.id, "reject").catch(() => setMsg(t("common.failed", "Failed")))}>
                    {t("common.reject", "Reject")}
                  </button>
                </td>
              </tr>
            ))}
            {!rows.length ? (
              <tr>
                <td colSpan={4}>{t("page.inbox.empty", "No pending approvals.")}</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
