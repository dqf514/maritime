"use client";

import { msgOf } from "@/lib/errors";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { RowActions } from "@/components/RowActions";
import { SavedViews } from "@/components/SavedViews";
import { StateView } from "@/components/StateView";
import { StatusBadge } from "@/components/StatusBadge";
import { StatusLegend } from "@/components/StatusLegend";
import { Toolbar } from "@/components/Toolbar";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { useI18n } from "@/lib/i18n";
import { formatInTz } from "@/lib/datetime";
import { useListQuery } from "@/lib/useListQuery";
import { useToast } from "@/components/ToastProvider";

type ShipReport = {
  id: string;
  report_ref: string;
  form_type: string;
  vessel_name: string | null;
  submitted_at: string;
  status: string;
  submitted_by: string | null;
  review_notes: string | null;
};

type ShipForm = {
  id: string;
  form_type: string;
  form_name: string;
  is_active: boolean;
  auto_import: boolean;
};

function MariLinkPageInner() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const { query, setQuery } = useListQuery();
  const filter = typeof query.form_type === "string" ? query.form_type : "";
  const [reports, setReports] = useState<ShipReport[]>([]);
  const [forms, setForms] = useState<ShipForm[]>([]);
  const [open, setOpen] = useState<ShipReport | null>(null);
  const [reviewNotes, setReviewNotes] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState("");
  // 参考数据取数失败的可见提示（P1-4）
  const [refWarn, setRefWarn] = useState("");
  // 驳回报文不可撤销 —— 二次确认并指名报文（P1-8）。
  const [rejectPending, setRejectPending] = useState<(() => void) | null>(null);
  const [rejectLabel, setRejectLabel] = useState("");
  const rowCtx = useContextMenu<ShipReport>();

  function exportRows(selected: ShipReport[]) {
    downloadCsv(
      "marilink-reports",
      ["id", "report_ref", "form_type", "vessel_name", "submitted_at", "status", "submitted_by"],
      selected.map((r) => [r.id, r.report_ref, r.form_type, r.vessel_name ?? "", r.submitted_at, r.status, r.submitted_by ?? ""]),
    );
  }

  function rowMenuItems(target: ShipReport): ContextMenuItem[] {
    return [
      {
        key: "open",
        label: t("common.open", "Open"),
        onClick: () => {
          if (target.status === "submitted") setOpen(target);
        },
      },
      { key: "copy", label: t("common.copy_id", "Copy id"), onClick: () => void navigator.clipboard?.writeText(target.id) },
      { key: "export", label: t("page.finance.export_selected", "Export selected"), onClick: () => exportRows([target]) },
      ...(target.status === "submitted"
        ? [{ key: "review", label: t("common.review", "Review"), onClick: () => setOpen(target) } as ContextMenuItem]
        : []),
    ];
  }

  const load = useCallback(async () => {
    const params = filter ? `?form_type=${filter}` : "";
    setLoading(true);
    setLoadErr("");
    try {
      const [r, f] = await Promise.all([
        apiGet(`/api/v1/marilink/reports${params}`),
        apiGet("/api/v1/marilink/forms").catch(() => {
          setRefWarn(t("page.marilink.forms_fail", "Could not load the form templates."));
          return [];
        }),
      ]);
      setReports(Array.isArray(r) ? r : []);
      setForms(Array.isArray(f) ? f : []);
    } catch (e) {
      // 主列表失败必须走错误态，不能静默变成「没有报文」（P1-4）。
      setReports([]);
      setLoadErr(msgOf(e, t("common.failed", "Failed")));
    } finally {
      setLoading(false);
    }
  }, [filter, t]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  async function seedPresets() {
    await apiPost("/api/v1/marilink/forms/seed-presets", {});
    toast.success(t("page.marilink.presets_seeded", "Form presets seeded"));
    await load();
  }

  async function approveReport() {
    if (!open) return;
    await apiPost(`/api/v1/marilink/reports/${open.id}/review`, {
      action: "approve",
      notes: reviewNotes,
    });
    toast.success(t("page.marilink.approved", "Report approved and imported"));
    setOpen(null);
    setReviewNotes("");
    await load();
  }

  async function rejectReport() {
    if (!open) return;
    await apiPost(`/api/v1/marilink/reports/${open.id}/review`, {
      action: "reject",
      notes: reviewNotes,
    });
    toast.success(t("page.marilink.rejected", "Report rejected"));
    setOpen(null);
    setReviewNotes("");
    await load();
  }

  /** 驳回报文不可撤销 —— 二次确认并指名报文（P1-8）。 */
  function askRejectReport() {
    if (!open) return;
    const ref = open.report_ref;
    setRejectPending(() => () =>
      rejectReport().catch((e) => toast.error(msgOf(e, t("common.failed", "Failed")))),
    );
    setRejectLabel(ref);
  }

  async function onReportCellSave(rowId: string, colKey: string, value: unknown, row: ShipReport) {
    const src = row as unknown as Record<string, unknown>;
    if ((src[colKey] ?? "") === (value ?? "")) return;
    try {
      await apiPatch(`/api/v1/marilink/reports/${rowId}`, { [colKey]: value === "" ? null : value });
      toast.success(t("common.saved", "Saved"));
      await load();
    } catch (ex: any) {
      toast.error(msgOf(ex));
    }
  }

  const deleteReport = useCallback(
    async (reportId: string) => {
      try {
        await apiDelete(`/api/v1/marilink/reports/${reportId}`);
        toast.success(t("common.recycled", "Moved to recycle bin"));
        await load();
      } catch (ex: any) {
        toast.error(msgOf(ex));
      }
    },
    [t, toast, load],
  );

  async function onFormCellSave(rowId: string, colKey: string, value: unknown, row: ShipForm) {
    let payload: Record<string, unknown>;
    if (colKey === "is_active" || colKey === "auto_import") {
      const next = Boolean(value);
      if (row[colKey] === next) return;
      payload = { [colKey]: next };
    } else {
      const src = row as unknown as Record<string, unknown>;
      if ((src[colKey] ?? "") === (value ?? "")) return;
      payload = { [colKey]: value === "" ? null : value };
    }
    try {
      await apiPatch(`/api/v1/marilink/forms/${rowId}`, payload);
      toast.success(t("common.saved", "Saved"));
      await load();
    } catch (ex: any) {
      toast.error(msgOf(ex));
    }
  }

  const deleteForm = useCallback(
    async (formId: string) => {
      try {
        await apiDelete(`/api/v1/marilink/forms/${formId}`);
        toast.success(t("common.deleted", "Deleted"));
        await load();
      } catch (ex: any) {
        toast.error(msgOf(ex));
      }
    },
    [t, toast, load],
  );

  const columns = useMemo<ColumnDef<ShipReport>[]>(
    () => [
      {
        key: "report_ref",
        title: t("page.marilink.ref", "Reference"),
        width: 150,
        value: (r) => r.report_ref,
        render: (_v, r) => <code>{r.report_ref}</code>,
      },
      {
        key: "form_type",
        title: t("page.marilink.type", "Type"),
        width: 130,
        value: (r) => r.form_type,
        editor: {
          type: "select",
          options: [
            { value: "noon_report", label: t("page.marilink.noon_report", "Noon Report") },
            { value: "bunker_report", label: t("page.marilink.bunker_report", "Bunker Report") },
            { value: "incident", label: t("page.marilink.incident", "Incident") },
          ],
        },
      },
      {
        key: "vessel_name",
        title: t("page.marilink.vessel", "Vessel"),
        minWidth: 140,
        value: (r) => r.vessel_name || "",
        render: (_v, r) => r.vessel_name || "—",
      },
      {
        key: "submitted_at",
        title: t("page.marilink.submitted", "Submitted"),
        width: 170,
        value: (r) => r.submitted_at,
        render: (_v, r) => formatInTz(r.submitted_at),
      },
      {
        key: "status",
        title: t("page.marilink.status", "Status"),
        width: 110,
        value: (r) => r.status,
        render: (_v, r) => <StatusBadge status={r.status} />,
      },
      {
        key: "review_notes",
        title: t("page.marilink.notes", "Review Notes"),
        minWidth: 140,
        value: (r) => r.review_notes || "",
        editor: { type: "text" },
      },
      {
        key: "actions",
        title: t("common.actions", "Actions"),
        width: 110,
        value: (r) => r.status,
        render: (_v, r) =>
          r.status === "submitted" ? (
            <button className="btn btn-secondary btn-sm" onClick={() => setOpen(r)}>
              {t("common.review", "Review")}
            </button>
          ) : (
            ""
          ),
      },
      {
        key: "_actions",
        title: "",
        width: 70,
        align: "right",
        render: (_v, r) => {
          const locked = r.status === "approved" || r.status === "rejected";
          return (
            <RowActions
              label={r.report_ref}
              canEdit={!locked}
              canDelete={!locked}
              onDelete={() => deleteReport(r.id)}
            />
          );
        },
      },
    ],
    [t, deleteReport],
  );

  const formColumns = useMemo<ColumnDef<ShipForm>[]>(
    () => [
      {
        key: "form_name",
        title: t("common.name", "Name"),
        minWidth: 180,
        value: (f) => f.form_name,
        editor: { type: "text" },
      },
      {
        key: "form_type",
        title: t("page.marilink.type", "Type"),
        width: 150,
        value: (f) => f.form_type,
        editor: {
          type: "select",
          options: [
            { value: "noon_report", label: t("page.marilink.noon_report", "Noon Report") },
            { value: "bunker_report", label: t("page.marilink.bunker_report", "Bunker Report") },
            { value: "incident", label: t("page.marilink.incident", "Incident") },
          ],
        },
      },
      {
        key: "is_active",
        title: t("common.status", "Status"),
        width: 110,
        value: (f) => f.is_active,
        editor: { type: "checkbox" },
        render: (v) => (v ? t("page.marilink.form_active", "Active") : t("page.marilink.form_inactive", "Inactive")),
      },
      {
        key: "auto_import",
        title: t("page.marilink.auto_import", "Auto import"),
        width: 110,
        value: (f) => f.auto_import,
        editor: { type: "checkbox" },
        render: (v) => (v ? t("common.yes", "Yes") : t("common.no", "No")),
      },
      {
        key: "_actions",
        title: "",
        width: 70,
        align: "right",
        render: (_v, f) => <RowActions label={f.form_name} onDelete={() => deleteForm(f.id)} />,
      },
    ],
    [t, deleteForm],
  );


  return (
    <AppShell>
      <PageHeader
        breadcrumb={[
          { label: t("nav.operations", "Operations"), href: "/operations/voyages" },
          { label: t("page.marilink.title", "MariLink Ship Reports") },
        ]}
        title={t("page.marilink.title", "MariLink Ship Reports")}
        actions={
          <SavedViews storageKey="marilink_list" onApply={(q) => router.replace(`/operations/marilink${q}`)} />
        }
      />

      <Toolbar
        filterCount={filter ? 1 : 0}
        onClearFilters={() => setQuery({ form_type: null })}
        right={<span className="hint">{t("page.marilink.count", "{n} reports", { n: reports.length })}</span>}
      >
        <button onClick={seedPresets} className="btn btn-secondary btn-sm">
          {t("page.marilink.seed_forms", "Seed Form Presets")}
        </button>
        <select
          className="input input-sm"
          value={filter}
          onChange={(e) => setQuery({ form_type: e.target.value || null })}
          aria-label={t("page.marilink.type", "Type")}
        >
          <option value="">{t("page.marilink.all_types", "All Types")}</option>
          <option value="noon_report">{t("page.marilink.noon_report", "Noon Report")}</option>
          <option value="bunker_report">{t("page.marilink.bunker_report", "Bunker Report")}</option>
          <option value="incident">{t("page.marilink.incident", "Incident")}</option>
        </select>
      </Toolbar>

      <StatusLegend statuses={["submitted", "review", "approved", "rejected"]} />
      {refWarn ? <p className="flash-err">{refWarn}</p> : null}
      <div className="card" style={{ overflow: "auto" }}>
        <StateView
          loading={loading}
          error={loadErr || undefined}
          empty={!loadErr && !reports.length}
          emptyText={t("page.marilink.no_reports", "No ship reports yet")}
          onRetry={() => void load()}
        >
          <div style={{ width: "100%" }}>
            <DataGrid<ShipReport>
              columns={columns}
              data={reports}
              rowKey={(r) => r.id}
              editable
              onCellSave={onReportCellSave}
              onRowContextMenu={(r, _i, e) => rowCtx.open(r)(e)}
              storageKey="marilink_reports_grid"
              showFooter={false}
              emptyText={t("page.marilink.no_reports", "No ship reports yet")}
            />
          </div>
        </StateView>
      </div>

      <div style={{ marginTop: 24 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>
          {t("page.marilink.active_forms", "Active Form Form Templates")}
        </h2>
        <div className="card" style={{ overflow: "auto" }}>
          <DataGrid<ShipForm>
            columns={formColumns}
            data={forms}
            rowKey={(f) => f.id}
            editable
            onCellSave={onFormCellSave}
            storageKey="marilink_forms_grid"
            showFooter={false}
            emptyText={t("common.no_data", "No data")}
          />
        </div>
      </div>

      {open && (
        <RecordModal
          title={`${t("common.review", "Review")} ${open.report_ref}`}
          open={!!open}
          onClose={() => { setOpen(null); setReviewNotes(""); }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div>
              <label style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                {t("page.marilink.notes", "Review Notes")}
              </label>
              <textarea
                value={reviewNotes}
                onChange={(e) => setReviewNotes(e.target.value)}
                rows={3}
                style={{ width: "100%", padding: 8, borderRadius: 6, border: "1px solid var(--border)" }}
              />
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn btn-primary" onClick={approveReport}>
                {t("common.approve", "Approve & Import")}
              </button>
              <button className="btn btn-danger" onClick={askRejectReport}>
                {t("common.reject", "Reject")}
              </button>
            </div>
          </div>
        </RecordModal>
      )}

      <ContextMenu controller={rowCtx} items={rowMenuItems} />

      {/* 驳回报文不可撤销 —— 二次确认并指名报文（P1-8） */}
      <ConfirmDialog
        open={Boolean(rejectPending)}
        title={t("common.reject", "Reject")}
        message={t(
          "page.marilink.reject_confirm",
          'Reject report "{ref}"? The report is rejected and cannot be undone.',
          { ref: rejectLabel },
        )}
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

export default function MariLinkPage() {
  return (
    <Suspense fallback={null}>
      <MariLinkPageInner />
    </Suspense>
  );
}
