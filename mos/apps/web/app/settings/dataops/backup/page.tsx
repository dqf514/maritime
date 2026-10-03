"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
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
    refresh().catch(() => toast.success(t("page.backup.load_fail", "Unable to load backups")));
  }, [t]);

  async function backup() {
    toast.success(t("page.backup.creating", "Creating backup…"));
    try {
      await apiCreateBackup();
      await refresh();
      toast.success(t("page.backup.done", "Backup completed (Wave 0 placeholder snapshot)."));
    } catch {
      toast.success(t("page.backup.failed", "Backup failed"));
    }
  }

  return (
    <AppShell>
      <PageHeader
        title={t("page.backup.title", "Backup")}
        subtitle={t("page.backup.sub", "One-click tenant backup and restore drills.")}
        actions={
          <button className="btn btn-primary" type="button" onClick={backup}>
            {t("page.backup.now", "Backup now")}
          </button>
        }
      />
      <div className="panel">
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.backup.when", "When")}</th>
              <th>{t("common.status", "Status")}</th>
              <th>{t("page.backup.trigger", "Trigger")}</th>
              <th>{t("page.backup.path", "Path")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{new Date(r.created_at).toLocaleString()}</td>
                <td>{r.status}</td>
                <td>{r.trigger}</td>
                <td>{r.storage_path}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
