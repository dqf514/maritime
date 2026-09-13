"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiCreateBackup, apiListBackups } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Backup = {
  id: string;
  status: string;
  trigger: string;
  storage_path?: string;
  created_at: string;
};

export default function BackupPage() {
  const { t } = useI18n();
  const [rows, setRows] = useState<Backup[]>([]);
  const [msg, setMsg] = useState("");

  async function refresh() {
    const data = await apiListBackups();
    setRows(data);
  }

  useEffect(() => {
    refresh().catch(() => setMsg(t("page.backup.load_fail", "Unable to load backups")));
  }, [t]);

  async function backup() {
    setMsg(t("page.backup.creating", "Creating backup…"));
    try {
      await apiCreateBackup();
      await refresh();
      setMsg(t("page.backup.done", "Backup completed (Wave 0 placeholder snapshot)."));
    } catch {
      setMsg(t("page.backup.failed", "Backup failed"));
    }
  }

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("page.backup.title", "Backup")}</h1>
      <p style={{ color: "var(--muted)" }}>{t("page.backup.sub", "One-click tenant backup and restore drills.")}</p>
      <button className="btn btn-primary" type="button" onClick={backup}>
        {t("page.backup.now", "Backup now")}
      </button>
      {msg ? <p>{msg}</p> : null}
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
