"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { PageHeader } from "@/components/PageHeader";
import { PageGuide } from "@/components/PageGuide";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type Item = {
  id: string;
  entity_type: string;
  entity_id: string;
  definition: string | null;
  step: { name?: string; role_code?: string } | null;
};

export default function WorkflowInboxPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [rows, setRows] = useState<Item[]>([]);
  const rowCtx = useContextMenu<Item>();

  async function load() {
    setRows(await apiGet("/api/v1/workflows/inbox"));
  }

  useEffect(() => {
    load().catch(() => setRows([]));
  }, []);

  async function decide(id: string, decision: string) {
    await apiPost(`/api/v1/workflows/${id}/decide`, { decision });
    toast.success(t("page.inbox.decided", "{decision} recorded", { decision }));
    await load();
  }

  function copyEntityId(r: Item) {
    void navigator.clipboard.writeText(r.entity_id);
    toast.success(t("ctx.copied_id", "ID copied"));
  }

  const menuItems = (r: Item): ContextMenuItem[] => [
    {
      key: "approve",
      label: t("common.approve", "Approve"),
      onClick: () => decide(r.id, "approve").catch(() => toast.error(t("common.failed", "Failed"))),
    },
    {
      key: "reject",
      label: t("common.reject", "Reject"),
      danger: true,
      onClick: () => decide(r.id, "reject").catch(() => toast.error(t("common.failed", "Failed"))),
    },
    { key: "d1", label: "", divider: true },
    { key: "copy", label: t("ctx.copy_entity_id", "Copy entity id"), onClick: () => copyEntityId(r) },
  ];

  const columns: ColumnDef<Item>[] = [
    { key: "definition", title: t("page.inbox.process", "Process"), minWidth: 180, value: (r) => r.definition || "" },
    {
      key: "entity",
      title: t("page.inbox.entity", "Entity"),
      width: 180,
      value: (r) => `${r.entity_type} · ${r.entity_id.slice(0, 8)}`,
    },
    {
      key: "step",
      title: t("page.inbox.step", "Step"),
      minWidth: 160,
      value: (r) => (r.step?.name ? `${r.step.name} (${r.step.role_code || ""})` : ""),
      render: (_v, r) => (
        <span>
          {r.step?.name}
          {r.step?.role_code ? ` (${r.step.role_code})` : ""}
        </span>
      ),
    },
    {
      key: "_actions",
      title: "",
      width: 170,
      align: "right",
      render: (_v, r) => (
        <span
          style={{ display: "flex", gap: "0.35rem", justifyContent: "flex-end" }}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            className="btn btn-primary"
            type="button"
            onClick={() => decide(r.id, "approve").catch(() => toast.error(t("common.failed", "Failed")))}
          >
            {t("common.approve", "Approve")}
          </button>
          <button
            className="btn"
            type="button"
            onClick={() => decide(r.id, "reject").catch(() => toast.error(t("common.failed", "Failed")))}
          >
            {t("common.reject", "Reject")}
          </button>
        </span>
      ),
    },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.inbox", "Approval inbox") }]}
        title={t("page.inbox.title", "Approval inbox")}
        subtitle={t("page.inbox.sub", "Pending business approvals for your role.")}
        actions={<PageGuide pageKey="workflows_inbox" />}
      />
      <div className="panel">
        <DataGrid<Item>
          columns={columns}
          data={rows}
          rowKey={(r) => r.id}
          onRowContextMenu={(r, _i, e) => rowCtx.open(r)(e)}
          storageKey="workflows_inbox_grid"
          showFooter={false}
          emptyText={t("page.inbox.empty", "No pending approvals.")}
        />
        <ContextMenu controller={rowCtx} items={menuItems} />
      </div>
    </AppShell>
  );
}
