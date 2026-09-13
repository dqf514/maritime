"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiDelete, apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Item = {
  id: string;
  entity_type: string;
  entity_id: string;
  title: string;
  deleted_at: string | null;
};

const TYPE_KEYS: Record<string, string> = {
  vessel: "recycle.type.vessel",
  port: "recycle.type.port",
  counterparty: "recycle.type.counterparty",
  user: "recycle.type.user",
  api_key: "recycle.type.api_key",
  org_unit: "recycle.type.org_unit",
  connector: "recycle.type.connector",
  estimate: "recycle.type.estimate",
  charter: "recycle.type.charter",
  voyage: "recycle.type.voyage",
  invoice: "recycle.type.invoice",
  claim: "recycle.type.claim",
  laytime: "recycle.type.laytime",
};

export default function RecycleBinPage() {
  const { t } = useI18n();
  const [rows, setRows] = useState<Item[]>([]);
  const [msg, setMsg] = useState("");

  async function load() {
    setRows(await apiGet("/api/v1/recycle-bin"));
  }

  useEffect(() => {
    load().catch(() => setMsg(t("page.recycle.load_fail", "Unable to load recycle bin (sign-in required)")));
  }, [t]);

  async function restore(id: string) {
    await apiPost(`/api/v1/recycle-bin/${id}/restore`);
    setMsg(t("page.recycle.restored", "Restored"));
    await load();
  }

  async function purge(id: string) {
    if (!window.confirm(t("page.recycle.purge_confirm", "Permanently purge this recycle entry? This cannot be undone."))) return;
    await apiDelete(`/api/v1/recycle-bin/${id}`);
    setMsg(t("page.recycle.purged", "Permanently purged"));
    await load();
  }

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.recycle.title", "Recycle bin")}</h1>
          <p className="page-sub">
            {t(
              "page.recycle.sub",
              "软删除的数据会出现在此。可恢复到业务列表，或由管理员永久清除回收记录。",
            )}
          </p>
        </div>
      </div>
      {msg ? <p>{msg}</p> : null}
      <div className="panel">
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.recycle.type", "Type")}</th>
              <th>{t("common.title", "标题")}</th>
              <th>{t("page.recycle.deleted_at", "Deleted at")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{t(TYPE_KEYS[r.entity_type] || "", r.entity_type)}</td>
                <td>{r.title}</td>
                <td>{r.deleted_at ? new Date(r.deleted_at).toLocaleString() : "—"}</td>
                <td style={{ display: "flex", gap: "0.4rem" }}>
                  <button className="btn btn-primary" type="button" onClick={() => restore(r.id).catch(() => setMsg(t("common.failed", "Failed")))}>
                    {t("page.recycle.restore", "Restore")}
                  </button>
                  <button className="btn btn-danger" type="button" onClick={() => purge(r.id).catch(() => setMsg(t("common.failed", "Failed")))}>
                    {t("page.recycle.purge", "Purge")}
                  </button>
                </td>
              </tr>
            ))}
            {!rows.length ? (
              <tr>
                <td colSpan={4} className="muted">
                  {t("page.recycle.empty", "回收站为空")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
