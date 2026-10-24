"use client";

// 计划报表调度台 — Report schedule console：按频率向收件人邮件发送报表。
// 列表 / 新建 / 编辑 / 立即运行 / 启用停用 / 删除（确认弹窗）。

import { RefreshButton } from "@/components/RefreshButton";
import { msgOf } from "@/lib/errors";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { Toolbar } from "@/components/Toolbar";
import { StatusBadge } from "@/components/StatusBadge";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StateView } from "@/components/StateView";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { parseUtc } from "@/lib/datetime";
import { useToast } from "@/components/ToastProvider";

type Schedule = {
  id: string;
  report_id: string;
  report_name: string | null;
  schedule_type: string;
  cron_expression: string | null;
  recipients: string[] | null;
  output_format: string;
  is_active: boolean;
  last_run_at: string | null;
  last_status: string | null;
  next_run_at: string | null;
};

type ReportOption = {
  id: string;
  report_name: string;
  report_type: string;
};

const SCHEDULE_TYPES = ["on_demand", "daily", "weekly", "monthly"] as const;
const OUTPUT_FORMATS = ["excel", "csv", "pdf"] as const;

const EMPTY_FORM = {
  report_id: "",
  schedule_type: "daily",
  cron_expression: "",
  recipients: "",
  output_format: "excel",
  is_active: true,
};

function fmtTs(value: string | null): string {
  if (!value) return "—";
  const d = parseUtc(value);
  return d ? d.toISOString().slice(0, 16).replace("T", " ") : value;
}

export default function ReportSchedulerPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [rows, setRows] = useState<Schedule[]>([]);
  const [reports, setReports] = useState<ReportOption[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(false);
  /** 主列表加载失败 —— 与「没有调度」区分 */
  const [err, setErr] = useState<string | null>(null);
  /** 报表下拉（参考数据）加载失败 —— 局部提示 */
  const [reportsErr, setReportsErr] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Schedule | null>(null);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [confirmDel, setConfirmDel] = useState<string | null>(null);
  /** 待确认的「立即运行」—— 会真实跑批 */
  const [confirmRun, setConfirmRun] = useState<Schedule | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet("/api/v1/reports/schedules/list");
      setRows(Array.isArray(data) ? data : []);
      setErr(null);
    } catch (ex) {
      setRows([]);
      setErr(msgOf(ex));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadReports = useCallback(async () => {
    try {
      const data = await apiGet("/api/v1/reports");
      setReports(Array.isArray(data) ? data : []);
      setReportsErr(null);
    } catch (ex) {
      setReports([]);
      setReportsErr(msgOf(ex));
    }
  }, []);

  useEffect(() => {
    load();
    loadReports();
  }, [load, loadReports]);

  const filtered = useMemo(() => {
    if (!statusFilter) return rows;
    if (statusFilter === "active") return rows.filter((r) => r.is_active);
    if (statusFilter === "paused") return rows.filter((r) => !r.is_active);
    return rows.filter((r) => (r.last_status || "never") === statusFilter);
  }, [rows, statusFilter]);

  function openCreate() {
    setForm({ ...EMPTY_FORM, report_id: reports[0]?.id ?? "" });
    setEditing(null);
    setCreating(true);
  }

  const openEdit = useCallback((row: Schedule) => {
    setForm({
      report_id: row.report_id,
      schedule_type: row.schedule_type,
      cron_expression: row.cron_expression || "",
      recipients: (row.recipients || []).join(", "),
      output_format: row.output_format,
      is_active: !!row.is_active,
    });
    setEditing(row);
    setCreating(false);
  }, []);

  async function save(e?: FormEvent) {
    e?.preventDefault();
    if (!form.report_id) {
      toast.error(t("sched.need_report", "Select a report first"));
      return;
    }
    const recipients = form.recipients
      .split(/[,\s;]+/)
      .map((x) => x.trim())
      .filter(Boolean);
    setSaving(true);
    try {
      const body = {
        schedule_type: form.schedule_type,
        cron_expression: form.cron_expression.trim() || null,
        recipients,
        output_format: form.output_format,
        is_active: form.is_active,
      };
      if (editing) {
        await apiPatch(`/api/v1/reports/schedules/${editing.id}`, body);
      } else {
        await apiPost("/api/v1/reports/schedules", { report_id: form.report_id, ...body });
      }
      toast.success(t("sched.saved", "Schedule saved"));
      setCreating(false);
      setEditing(null);
      await load();
    } catch (err) {
      toast.error(t("sched.save_fail", "Failed to save schedule: {err}", { err: msgOf(err) }));
    } finally {
      setSaving(false);
    }
  }

  const toggleActive = useCallback(
    async (row: Schedule) => {
      try {
        await apiPatch(`/api/v1/reports/schedules/${row.id}`, { is_active: !row.is_active });
        setRows((prev) => prev.map((r) => (r.id === row.id ? { ...r, is_active: !row.is_active } : r)));
      } catch (err) {
        toast.error(t("sched.toggle_fail", "Failed to update schedule: {err}", { err: msgOf(err) }));
      }
    },
    [t, toast],
  );

  async function runNow(row: Schedule) {
    setBusyId(row.id);
    try {
      const res = await apiPost(`/api/v1/reports/schedules/${row.id}/run`);
      if (res?.ok) {
        toast.success(t("sched.run_ok", "Schedule executed"));
      } else {
        toast.error(t("sched.run_fail", "Run failed: {err}", { err: res?.error || t("sched.run_unknown", "unknown error") }));
      }
      await load();
    } catch (err) {
      toast.error(t("sched.run_fail", "Run failed: {err}", { err: msgOf(err) }));
    } finally {
      setBusyId(null);
    }
  }

  /** 「立即运行」会真实跑批并发信 —— 先确认。 */
  const requestRun = useCallback((row: Schedule) => {
    setConfirmRun(row);
  }, []);

  async function remove(id: string) {
    try {
      await apiDelete(`/api/v1/reports/schedules/${id}`);
      toast.success(t("sched.deleted", "Schedule deleted"));
      setRows((prev) => prev.filter((r) => r.id !== id));
    } catch (err) {
      toast.error(t("sched.delete_fail", "Failed to delete schedule: {err}", { err: msgOf(err) }));
    }
  }

  const reportNameOf = useCallback(
    (row: Schedule) => row.report_name || reports.find((r) => r.id === row.report_id)?.report_name || row.report_id.slice(0, 8),
    [reports],
  );

  const columns = useMemo<ColumnDef<Schedule>[]>(
    () => [
      {
        key: "report_name",
        title: t("sched.col_report", "Report"),
        width: 220,
        sticky: true,
        value: (r) => reportNameOf(r),
        render: (v, r) => (
          <button type="button" className="linklike" onClick={() => openEdit(r)}>
            {String(v)}
          </button>
        ),
      },
      {
        key: "schedule_type",
        title: t("sched.col_frequency", "Frequency"),
        width: 130,
        value: (r) => r.schedule_type,
        render: (v, r) => (
          <span>
            {t(`sched.freq_${String(v)}`, String(v))}
            {r.cron_expression ? <span className="muted"> · {r.cron_expression}</span> : null}
          </span>
        ),
      },
      {
        key: "next_run_at",
        title: t("sched.col_next_run", "Next run"),
        width: 150,
        value: (r) => r.next_run_at || "",
        render: (v) => <span className="muted">{fmtTs(String(v || "") || null)}</span>,
      },
      {
        key: "last_run_at",
        title: t("sched.col_last_run", "Last run"),
        width: 150,
        value: (r) => r.last_run_at || "",
        render: (v) => <span className="muted">{fmtTs(String(v || "") || null)}</span>,
      },
      {
        key: "last_status",
        title: t("sched.col_last_status", "Last status"),
        width: 120,
        value: (r) => r.last_status || "never",
        render: (v) => {
          const s = String(v || "never");
          if (s === "never") {
            return <StatusBadge status="never" tone="muted" label={t("sched.status_never", "Never run")} />;
          }
          return <StatusBadge status={s} />;
        },
      },
      {
        key: "is_active",
        title: t("sched.col_enabled", "Enabled"),
        width: 100,
        value: (r) => r.is_active,
        render: (_v, r) => (
          <button
            type="button"
            className="linklike"
            onClick={() => toggleActive(r)}
            title={t("sched.toggle_hint", "Click to enable / pause")}
            aria-label={t("sched.toggle_active", "Enable or pause schedule")}
          >
            <StatusBadge
              status={r.is_active ? "active" : "inactive"}
              tone={r.is_active ? "ok" : "muted"}
              label={r.is_active ? t("sched.on", "ON") : t("sched.off", "OFF")}
            />
          </button>
        ),
      },
      {
        key: "_actions",
        title: t("sched.col_actions", "Actions"),
        width: 200,
        align: "right",
        render: (_v, r) => (
          <span style={{ display: "inline-flex", gap: 6, justifyContent: "flex-end" }}>
            <button type="button" className="btn btn-sm" onClick={() => openEdit(r)}>
              {t("common.edit", "Edit")}
            </button>
            <button
              type="button"
              className="btn btn-sm"
              disabled={busyId === r.id}
              onClick={() => requestRun(r)}
              title={t("sched.run_hint", "Execute this schedule once")}
            >
              {busyId === r.id ? t("sched.running", "Running…") : t("sched.run_now", "Run now")}
            </button>
            <button
              type="button"
              className="btn btn-sm btn-danger"
              onClick={() => setConfirmDel(r.id)}
              title={t("sched.delete_hint", "Delete schedule")}
            >
              {t("common.delete", "Delete")}
            </button>
          </span>
        ),
      },
    ],
    [t, reportNameOf, openEdit, toggleActive, requestRun, busyId],
  );

  const formFields = (
    <>
      <label className="field">
        <span>{t("sched.field_report", "Report")}</span>
        <select
          className="input"
          value={form.report_id}
          disabled={!!editing}
          onChange={(e) => setForm((f) => ({ ...f, report_id: e.target.value }))}
        >
          {reports.length === 0 ? (
            <option value="">{t("sched.no_reports", "No reports available")}</option>
          ) : null}
          {reports.map((r) => (
            <option key={r.id} value={r.id}>
              {r.report_name}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>{t("sched.field_frequency", "Frequency")}</span>
        <select
          className="input"
          value={form.schedule_type}
          onChange={(e) => setForm((f) => ({ ...f, schedule_type: e.target.value }))}
        >
          {SCHEDULE_TYPES.map((x) => (
            <option key={x} value={x}>
              {t(`sched.freq_${x}`, x)}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>{t("sched.field_cron", "Cron (optional)")}</span>
        <input
          className="input"
          value={form.cron_expression}
          onChange={(e) => setForm((f) => ({ ...f, cron_expression: e.target.value }))}
          placeholder={t("sched.cron_placeholder", "0 8 * * *")}
        />
      </label>
      <label className="field">
        <span>{t("sched.field_format", "Output format")}</span>
        <select
          className="input"
          value={form.output_format}
          onChange={(e) => setForm((f) => ({ ...f, output_format: e.target.value }))}
        >
          {OUTPUT_FORMATS.map((x) => (
            <option key={x} value={x}>
              {t(`sched.fmt_${x}`, x)}
            </option>
          ))}
        </select>
      </label>
      <label className="field" style={{ gridColumn: "1 / -1" }}>
        <span>{t("sched.field_recipients", "Recipients")}</span>
        <input
          className="input"
          value={form.recipients}
          onChange={(e) => setForm((f) => ({ ...f, recipients: e.target.value }))}
          placeholder="ops@example.com, cfo@example.com"
        />
      </label>
      <label className="field" style={{ gridColumn: "1 / -1" }}>
        <span>{t("sched.field_active", "Enabled")}</span>
        <input
          type="checkbox"
          checked={form.is_active}
          onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))}
          style={{ width: "auto", height: "auto" }}
        />
      </label>
      <p className="muted" style={{ gridColumn: "1 / -1", fontSize: "var(--font-label)" }}>
        {t(
          "sched.timezone_note",
          "Times are stored in UTC. Cron is 5-field (minute hour day month weekday) and overrides the interval frequency when set.",
        )}
      </p>
    </>
  );

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.analytics", "Analytics"), href: "/analytics" }, { label: t("sched.report.title", "Scheduled reports") }]}
        title={t("sched.report.title", "Scheduled reports")}
        subtitle={t("sched.report.sub", "Recurring report generation and email delivery")}
      />
      <Toolbar
        filterCount={statusFilter ? 1 : 0}
        onClearFilters={() => setStatusFilter("")}
        right={
          <select
            className="input input-sm"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            aria-label={t("sched.filter_status", "Status")}
          >
            <option value="">{t("sched.all_statuses", "All statuses")}</option>
            <option value="active">{t("sched.status_active", "Active")}</option>
            <option value="paused">{t("sched.status_paused", "Paused")}</option>
            <option value="success">{t("sched.status_success", "Success")}</option>
            <option value="failed">{t("sched.status_failed", "Failed")}</option>
            <option value="never">{t("sched.status_never", "Never run")}</option>
          </select>
        }
      >
        <button type="button" className="btn btn-primary btn-sm" onClick={openCreate}>
          {t("sched.new", "New schedule")}
        </button>
        <RefreshButton label={t("common.refresh", "Refresh")} className="btn btn-sm" onClick={() => load()} />
        <span className="muted" style={{ fontSize: "var(--font-label)" }}>
          {filtered.length} / {rows.length}
        </span>
      </Toolbar>

      {reportsErr ? (
        <p className="state-view-error" role="alert">
          {t("sched.reports_fail", "Report list could not be loaded: {err}", { err: reportsErr })}
        </p>
      ) : null}

      <StateView
        loading={loading}
        error={err ?? undefined}
        empty={!loading && !err && filtered.length === 0}
        emptyText={t("sched.empty", "No scheduled reports yet")}
        onRetry={() => void load()}
      >
        <DataGrid<Schedule>
          columns={columns}
          data={filtered}
          rowKey={(r) => r.id}
          storageKey="analytics_scheduler"
          onRowDoubleClick={(r) => openEdit(r)}
          emptyText={t("sched.empty", "No scheduled reports yet")}
        />
      </StateView>

      <RecordModal
        open={creating || !!editing}
        title={editing ? t("sched.edit_title", "Edit schedule") : t("sched.new_title", "New schedule")}
        onClose={() => {
          setCreating(false);
          setEditing(null);
        }}
        onSave={save}
        onDelete={editing ? () => remove(editing.id) : undefined}
        canDelete={!!editing}
        saving={saving}
        size="md"
      >
        <div className="form-grid">{formFields}</div>
      </RecordModal>

      <ConfirmDialog
        open={confirmDel !== null}
        title={t("sched.confirm_title", "Delete schedule")}
        message={t(
          "sched.confirm_message",
          "Delete this schedule? Delivery stops immediately and cannot be undone.",
        )}
        confirmLabel={t("common.delete", "Delete")}
        danger
        onConfirm={() => {
          if (confirmDel) remove(confirmDel);
          setConfirmDel(null);
        }}
        onCancel={() => setConfirmDel(null)}
      />

      {/* 立即运行 —— 会真实跑批并向收件人发信，先确认 */}
      <ConfirmDialog
        open={confirmRun !== null}
        title={t("sched.confirm_run_title", "Run schedule now")}
        message={t(
          "sched.confirm_run_message",
          'Run "{name}" now? The report will be generated and emailed to the recipients immediately.',
          { name: confirmRun ? reportNameOf(confirmRun) : "" },
        )}
        confirmLabel={t("sched.run_now", "Run now")}
        danger
        onConfirm={() => {
          const row = confirmRun;
          setConfirmRun(null);
          if (row) void runNow(row);
        }}
        onCancel={() => setConfirmRun(null)}
      />
    </AppShell>
  );
}
