"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { Toolbar } from "@/components/Toolbar";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiCreateBackup, apiGet, apiListBackups, apiPut } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type Backup = {
  id: string;
  status: string;
  trigger: string;
  storage_path?: string;
  created_at: string;
};

type Schedule = {
  enabled: boolean;
  frequency: string;
  hour_utc: number;
  weekday: number;
  keep_last: number;
  last_run_at: string | null;
  next_run_at: string | null;
};

const DEFAULT_SCHEDULE: Schedule = {
  enabled: false,
  frequency: "daily",
  hour_utc: 2,
  weekday: 0,
  keep_last: 14,
  last_run_at: null,
  next_run_at: null,
};

export default function BackupPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [rows, setRows] = useState<Backup[]>([]);
  const [sched, setSched] = useState<Schedule>(DEFAULT_SCHEDULE);
  const [schedBusy, setSchedBusy] = useState(false);

  async function refresh() {
    const data = await apiListBackups();
    setRows(data);
  }

  useEffect(() => {
    refresh().catch(() => toast.error(t("page.backup.load_fail", "Unable to load backups")));
    apiGet("/api/v1/settings/dataops/backup-schedule")
      .then((s: Schedule) => setSched({ ...DEFAULT_SCHEDULE, ...s }))
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function backup() {
    toast.success(t("page.backup.creating", "Creating backup…"));
    try {
      await apiCreateBackup();
      await refresh();
      toast.success(t("page.backup.done", "Backup completed (full tenant data snapshot)."));
    } catch {
      toast.error(t("page.backup.failed", "Backup failed"));
    }
  }

  async function saveSchedule() {
    setSchedBusy(true);
    try {
      const saved: Schedule = await apiPut("/api/v1/settings/dataops/backup-schedule", {
        enabled: sched.enabled,
        frequency: sched.frequency,
        hour_utc: sched.hour_utc,
        weekday: sched.weekday,
        keep_last: sched.keep_last,
      });
      setSched({ ...DEFAULT_SCHEDULE, ...saved });
      toast.success(t("page.backup.sched_saved", "Auto-backup schedule saved."));
    } catch {
      toast.error(t("page.backup.sched_failed", "Failed to save schedule"));
    } finally {
      setSchedBusy(false);
    }
  }

  const columns: ColumnDef<Backup>[] = [
    {
      key: "created_at",
      title: t("page.backup.when", "When"),
      width: 180,
      value: (r) => r.created_at,
      render: (v) => new Date(String(v)).toLocaleString(),
    },
    { key: "status", title: t("common.status", "Status"), width: 110, value: (r) => r.status },
    {
      key: "trigger",
      title: t("page.backup.trigger", "Trigger"),
      width: 130,
      value: (r) => r.trigger,
      render: (v) =>
        v === "auto"
          ? t("page.backup.trigger_auto", "auto (scheduled)")
          : v === "platform_purge"
            ? t("page.backup.trigger_purge", "pre-purge")
            : String(v),
    },
    {
      key: "storage_path",
      title: t("page.backup.path", "Path"),
      minWidth: 200,
      value: (r) => r.storage_path || "",
    },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[
          { label: t("nav.settings_hub", "System settings"), href: "/settings" },
          { label: t("page.backup.title", "Backup") },
        ]}
        title={t("page.backup.title", "Backup")}
        subtitle={t("page.backup.sub", "One-click full tenant backup + scheduled auto-backup.")}
      />
      <Toolbar>
        <button className="btn btn-primary" type="button" onClick={backup}>
          {t("page.backup.now", "Backup now")}
        </button>
        <button type="button" className="btn btn-sm" onClick={() => refresh().catch(() => undefined)} title={t("common.refresh", "Refresh")}>
          ↻
        </button>
      </Toolbar>

      <div className="panel">
        <div className="panel-header">{t("page.backup.sched_title", "Auto-backup schedule 自动备份计划")}</div>
        <div className="panel-body">
          <div
            className="form-grid"
            style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))", gap: "0.75rem" }}
          >
            <label style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
              <input
                type="checkbox"
                checked={sched.enabled}
                onChange={(e) => setSched({ ...sched, enabled: e.target.checked })}
              />
              {t("page.backup.sched_enabled", "启用自动备份")}
            </label>
            <label>
              {t("page.backup.sched_freq", "频率")}
              <select value={sched.frequency} onChange={(e) => setSched({ ...sched, frequency: e.target.value })}>
                <option value="daily">{t("page.backup.freq_daily", "每天 (Daily)")}</option>
                <option value="weekly">{t("page.backup.freq_weekly", "每周 (Weekly)")}</option>
              </select>
            </label>
            {sched.frequency === "weekly" ? (
              <label>
                {t("page.backup.sched_weekday", "星期（UTC）")}
                <select value={sched.weekday} onChange={(e) => setSched({ ...sched, weekday: Number(e.target.value) })}>
                  {[0, 1, 2, 3, 4, 5, 6].map((d) => (
                    <option key={d} value={d}>
                      {["周一", "周二", "周三", "周四", "周五", "周六", "周日"][d]}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <label>
              {t("page.backup.sched_hour", "时间（UTC 小时）")}
              <input
                type="number"
                min={0}
                max={23}
                value={sched.hour_utc}
                onChange={(e) => setSched({ ...sched, hour_utc: Number(e.target.value) })}
              />
            </label>
            <label>
              {t("page.backup.sched_keep", "保留份数")}
              <input
                type="number"
                min={1}
                max={365}
                value={sched.keep_last}
                onChange={(e) => setSched({ ...sched, keep_last: Number(e.target.value) })}
              />
            </label>
          </div>
          <p className="muted" style={{ marginTop: "0.5rem" }}>
            {t("page.backup.sched_next", "上次运行")}:{" "}
            {sched.last_run_at ? new Date(sched.last_run_at).toLocaleString() : t("common.never", "从未")} ·{" "}
            {t("page.backup.sched_next_run", "下次运行")}:{" "}
            {sched.next_run_at ? new Date(sched.next_run_at).toLocaleString() : t("common.none", "—")}
          </p>
          <button className="btn btn-primary" type="button" disabled={schedBusy} onClick={saveSchedule}>
            {t("page.backup.sched_save", "保存计划")}
          </button>
        </div>
      </div>

      <DataGrid<Backup>
        columns={columns}
        data={rows}
        rowKey={(r) => r.id}
        storageKey="settings_dataops_backup_grid"
        emptyText={t("common.no_data", "No data")}
      />
    </AppShell>
  );
}
