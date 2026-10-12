"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { Num } from "@/components/Num";
import { PageHeader } from "@/components/PageHeader";
import { StatusLegend } from "@/components/StatusLegend";
import { Toolbar } from "@/components/Toolbar";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { apiGet, apiPost } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

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
  const toast = useToast();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [rows, setRows] = useState<Msg[]>([]);
  const rowCtx = useContextMenu<Msg>();

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
      email: "ops@demo.marios",
      display_name: "Ops Inbox",
      config: {},
    });
  }

  async function sync() {
    toast.success(t("page.email.syncing", "Syncing demo mailbox…"));
    const acc = await ensureDemoAccount();
    const result = await apiPost(`/api/v1/email/accounts/${acc.id}/sync`);
    await load();
    toast.success(t("page.email.synced", "Synced {n} message(s).", { n: result.synced ?? 1 }));
  }

  async function confirm(id: string) {
    await apiPost(`/api/v1/email/review/${id}/confirm`, {});
    toast.success(t("page.email.confirmed", "Parse result confirmed."));
    await load();
  }

  function copyMsgId(m: Msg) {
    void navigator.clipboard.writeText(m.id);
    toast.success(t("ctx.copied_id", "ID copied"));
  }

  function exportMsgs(list: Msg[]) {
    downloadCsv(
      "email_review",
      ["id", "subject", "from_email", "parse_status", "parse_confidence"],
      list.map((m) => [m.id, m.subject ?? "", m.from_email ?? "", m.parse_status, m.parse_confidence ?? ""]),
      { emptyGuard: t("export.empty_confirm", "No rows to export. Export anyway?") },
    );
  }

  const menuItems = (m: Msg): ContextMenuItem[] => [
    ...(m.parse_status === "review"
      ? [
          {
            key: "confirm",
            label: t("common.confirm", "Confirm"),
            onClick: () => confirm(m.id).catch(() => toast.error(t("page.email.confirm_fail", "Confirm failed"))),
          },
        ]
      : []),
    { key: "copy", label: t("ctx.copy_id", "Copy id"), onClick: () => copyMsgId(m) },
    { key: "export", label: t("ctx.export_selected", "Export selected"), onClick: () => exportMsgs([m]) },
  ];

  const columns: ColumnDef<Msg>[] = [
    {
      key: "subject",
      title: t("page.email.subject", "Subject"),
      minWidth: 180,
      value: (r) => r.subject || "",
      render: (_v, r) => r.subject || t("page.email.no_subject", "(no subject)"),
    },
    {
      key: "from_email",
      title: t("page.email.from", "From"),
      width: 160,
      value: (r) => r.from_email || "",
      render: (_v, r) => r.from_email || "—",
    },
    { key: "parse_status", title: t("common.status", "Status"), width: 110, value: (r) => r.parse_status },
    {
      key: "parse_confidence",
      title: t("page.email.confidence", "Confidence"),
      width: 110,
      align: "right",
      value: (r) => r.parse_confidence ?? null,
      render: (_v, r) => (r.parse_confidence != null ? <><Num v={r.parse_confidence * 100} digits={0} />%</> : "—"),
    },
    {
      key: "parse_preview",
      title: t("page.email.preview", "Parse preview"),
      minWidth: 220,
      value: (r) => JSON.stringify(r.parse_result),
      render: (v) => <code>{String(v)}</code>,
    },
    {
      key: "actions",
      title: "",
      width: 110,
      render: (_v, r) =>
        r.parse_status === "review" ? (
          <button
            className="btn"
            type="button"
            onClick={() => confirm(r.id).catch(() => toast.error(t("page.email.confirm_fail", "Confirm failed")))}
          >
            {t("common.confirm", "Confirm")}
          </button>
        ) : null,
    },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.email", "Email Review") }]}
        title={t("page.email.title", "Email Review")}
        subtitle={t("page.email.sub", "AI-parsed recaps awaiting confirmation.")}
      />
      <Toolbar right={<span className="hint">{t("page.email.count", "{n} messages", { n: rows.length })}</span>}>
        <button className="btn btn-primary" type="button" onClick={() => sync().catch(() => toast.error(t("page.email.sync_fail", "Sync failed")))}>
          {t("page.email.sync_btn", "Sync demo inbox")}
        </button>
      </Toolbar>
      <StatusLegend statuses={["pending", "review", "parsed", "failed"]} />
      <div className="panel">
        <DataGrid<Msg>
          columns={columns}
          data={rows}
          rowKey={(r) => r.id}
          onRowContextMenu={(r, _i, e) => rowCtx.open(r)(e)}
          storageKey="email_review_grid"
          emptyText={t("page.email.empty", "No messages pending review.")}
        />
        <ContextMenu controller={rowCtx} items={menuItems} />
      </div>
    </AppShell>
  );
}
