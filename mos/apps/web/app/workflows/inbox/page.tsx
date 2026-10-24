"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { PageHeader } from "@/components/PageHeader";
import { PageGuide } from "@/components/PageGuide";
import { StateView } from "@/components/StateView";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiGet, apiPost } from "@/lib/api";
import { msgOf } from "@/lib/errors";
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // 否决业务审批不可撤销 —— 二次确认并指名单据（P1-8）。
  const [rejectPending, setRejectPending] = useState<(() => void) | null>(null);
  const [rejectLabel, setRejectLabel] = useState("");
  const rowCtx = useContextMenu<Item>();

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await apiGet("/api/v1/workflows/inbox");
      setRows(Array.isArray(data) ? data : []);
    } catch (e) {
      // 主列表失败必须走错误态，不能静默变成「没有待办」（P1-4）。
      setRows([]);
      setError(msgOf(e, t("common.failed", "Failed")));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    load();
  }, [load]);

  const label = useCallback((r: Item) => r.definition || `${r.entity_type} ${r.entity_id.slice(0, 8)}`, []);

  const decide = useCallback(
    async (id: string, decision: string) => {
      await apiPost(`/api/v1/workflows/${id}/decide`, { decision });
      toast.success(t("page.inbox.decided", "{decision} recorded", { decision }));
      await load();
    },
    [t, toast, load],
  );

  const askReject = useCallback(
    (r: Item) => {
      setRejectLabel(label(r));
      setRejectPending(() => () =>
        decide(r.id, "reject").catch((e) => toast.error(msgOf(e, t("common.failed", "Failed")))),
      );
    },
    [decide, label, t, toast],
  );

  function copyEntityId(r: Item) {
    void navigator.clipboard.writeText(r.entity_id);
    toast.success(t("ctx.copied_id", "ID copied"));
  }

  const menuItems = (r: Item): ContextMenuItem[] => [
    {
      key: "approve",
      label: t("common.approve", "Approve"),
      onClick: () => decide(r.id, "approve").catch((e) => toast.error(msgOf(e, t("common.failed", "Failed")))),
    },
    {
      key: "reject",
      label: t("common.reject", "Reject"),
      danger: true,
      onClick: () => askReject(r),
    },
    { key: "d1", label: "", divider: true },
    { key: "copy", label: t("ctx.copy_entity_id", "Copy entity id"), onClick: () => copyEntityId(r) },
  ];

  const columns = useMemo<ColumnDef<Item>[]>(
    () => [
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
              onClick={() => decide(r.id, "approve").catch((e) => toast.error(msgOf(e, t("common.failed", "Failed"))))}
            >
              {t("common.approve", "Approve")}
            </button>
            <button
              className="btn"
              type="button"
              onClick={() => askReject(r)}
            >
              {t("common.reject", "Reject")}
            </button>
          </span>
        ),
      },
    ],
    [t, toast, decide, askReject],
  );

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.inbox", "Approval inbox") }]}
        title={t("page.inbox.title", "Approval inbox")}
        subtitle={t("page.inbox.sub", "Pending business approvals for your role.")}
        actions={<PageGuide pageKey="workflows_inbox" />}
      />
      <div className="panel">
        <StateView
          loading={loading}
          error={error || undefined}
          empty={!rows.length}
          emptyText={t("page.inbox.empty", "No pending approvals.")}
          onRetry={load}
        >
          <DataGrid<Item>
            columns={columns}
            data={rows}
            rowKey={(r) => r.id}
            onRowContextMenu={(r, _i, e) => rowCtx.open(r)(e)}
            storageKey="workflows_inbox_grid"
            showFooter={false}
            emptyText={t("page.inbox.empty", "No pending approvals.")}
          />
        </StateView>
        <ContextMenu controller={rowCtx} items={menuItems} />
      </div>

      <ConfirmDialog
        open={Boolean(rejectPending)}
        title={t("common.reject", "Reject")}
        message={t("page.inbox.reject_confirm", 'Reject "{name}"? The approval is rejected and cannot be undone.', {
          name: rejectLabel,
        })}
        danger
        confirmLabel={t("common.reject", "Reject")}
        onConfirm={() => {
          const fn = rejectPending;
          setRejectPending(null);
          fn?.();
        }}
        onCancel={() => setRejectPending(null)}
      />
    </AppShell>
  );
}
