"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Msg = {
  id: string;
  subject: string | null;
  from_email: string | null;
  parse_status: string;
  parse_confidence: number | null;
  parse_result: Record<string, unknown>;
};

type Account = { id: string; email: string; provider: string; status: string };

export default function EmailReviewPage() {
  const { t } = useI18n();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [rows, setRows] = useState<Msg[]>([]);
  const [msg, setMsg] = useState("");

  async function load() {
    const [acc, review] = await Promise.all([
      apiGet("/api/v1/email/accounts"),
      apiGet("/api/v1/email/review"),
    ]);
    setAccounts(acc);
    setRows(review);
  }

  useEffect(() => {
    load().catch(() => {
      setAccounts([]);
      setRows([]);
    });
  }, []);

  async function ensureDemoAccount() {
    if (accounts.length) return accounts[0];
    return apiPost("/api/v1/email/accounts", {
      provider: "demo",
      email: "ops@demo.voyageos",
      display_name: "Ops Inbox",
      config: {},
    });
  }

  async function sync() {
    setMsg(t("page.email.syncing", "Syncing demo mailbox…"));
    const acc = await ensureDemoAccount();
    const result = await apiPost(`/api/v1/email/accounts/${acc.id}/sync`);
    await load();
    setMsg(t("page.email.synced", "Synced {n} message(s).", { n: result.synced ?? 1 }));
  }

  async function confirm(id: string) {
    await apiPost(`/api/v1/email/review/${id}/confirm`, {});
    setMsg(t("page.email.confirmed", "Parse result confirmed."));
    await load();
  }

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("page.email.title", "Email Review")}</h1>
      <p style={{ color: "var(--muted)" }}>{t("page.email.sub", "AI-parsed recaps awaiting confirmation.")}</p>
      <button className="btn btn-primary" type="button" onClick={() => sync().catch(() => setMsg(t("page.email.sync_fail", "Sync failed")))}>
        {t("page.email.sync_btn", "Sync demo inbox")}
      </button>
      {msg ? <p>{msg}</p> : null}
      <div className="panel" style={{ marginTop: "1rem" }}>
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.email.subject", "Subject")}</th>
              <th>{t("page.email.from", "From")}</th>
              <th>{t("common.status", "Status")}</th>
              <th>{t("page.email.confidence", "Confidence")}</th>
              <th>{t("page.email.preview", "Parse preview")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.subject || t("page.email.no_subject", "(no subject)")}</td>
                <td>{r.from_email || "—"}</td>
                <td>{r.parse_status}</td>
                <td>{r.parse_confidence != null ? `${(r.parse_confidence * 100).toFixed(0)}%` : "—"}</td>
                <td>
                  <code>{JSON.stringify(r.parse_result)}</code>
                </td>
                <td>
                  {r.parse_status === "review" ? (
                    <button
                      className="btn"
                      type="button"
                      onClick={() => confirm(r.id).catch(() => setMsg(t("page.email.confirm_fail", "Confirm failed")))}
                    >
                      {t("common.confirm", "Confirm")}
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
            {!rows.length ? (
              <tr>
                <td colSpan={6}>{t("page.email.empty", "No messages pending review.")}</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
