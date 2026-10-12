"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { Toolbar } from "@/components/Toolbar";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiCreateBackup, apiListBackups } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type Backup = {
  id: string;
  status: string;
  trigger: string;
  storage_path?: string;
  created_at: string;
};

export default function BackupPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [rows, setRows] = useState<Backup[]>([]);

  async function refresh() {
    const data = await apiListBackups();
    setRows(data);
  }

  useEffect(() => {
    refresh().catch(() => toast.error(t("page.backup.load_fail", "Unable to load backups")));
  }, [t]);

  async function backup() {
    toast.success(t("page.backup.creating", "Creating backup…"));
    try {
      await apiCreateBackup();
      await refresh();
      toast.success(t("page.backup.done", "Backup completed (Wave 0 placeholder snapshot)."));
    } catch {
      toast.error(t("page.backup.failed", "Backup failed"));
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
    { key: "trigger", title: t("page.backup.trigger", "Trigger"), width: 110, value: (r) => r.trigger },
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
        subtitle={t("page.backup.sub", "One-click tenant backup and restore drills.")}
      />
      <Toolbar>
        <button className="btn btn-primary" type="button" onClick={backup}>
          {t("page.backup.now", "Backup now")}
        </button>
        <button type="button" className="btn btn-sm" onClick={() => refresh().catch(() => undefined)} title={t("common.refresh", "Refresh")}>
          ↻
        </button>
      </Toolbar>
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
