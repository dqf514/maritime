"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type OfficeStatus = {
  graph_mode: string;
  config_source?: string;
  status: string;
  connected: boolean;
  mail_enabled: boolean;
  files_enabled: boolean;
  teams_enabled: boolean;
  sharepoint_enabled: boolean;
  consent_url?: string | null;
  last_health?: Record<string, unknown>;
  defaults?: Record<string, unknown>;
  addons?: Array<Record<string, unknown>>;
  catalog?: Array<Record<string, unknown>>;
};

type SyncJob = {
  id: string;
  channel: string;
  status: string;
  stats?: Record<string, unknown>;
  error?: string | null;
};

type Webhook = {
  id: string;
  name: string;
  target_url: string;
  events: string[];
  status: string;
  last_delivery?: Record<string, unknown>;
};

export default function OfficeEcosystemPage() {
  const { t } = useI18n();
  const [status, setStatus] = useState<OfficeStatus | null>(null);
  const [jobs, setJobs] = useState<SyncJob[]>([]);
  const [hooks, setHooks] = useState<Webhook[]>([]);
  const [mail, setMail] = useState<Array<Record<string, unknown>>>([]);
  const [drives, setDrives] = useState<Array<Record<string, unknown>>>([]);
  const [teams, setTeams] = useState<Array<Record<string, unknown>>>([]);
  const [msg, setMsg] = useState("");
  const [hookName, setHookName] = useState("Power Automate");
  const [hookUrl, setHookUrl] = useState("stub://power-automate");
  const [notifyText, setNotifyText] = useState("MariOS alert: voyage DEMO-001 ETA updated.");

  async function load() {
    const [st, j, wh] = await Promise.all([
      apiGet("/api/v1/office/status"),
      apiGet("/api/v1/office/sync/jobs"),
      apiGet("/api/v1/office/webhooks"),
    ]);
    setStatus(st);
    setJobs(Array.isArray(j) ? j : []);
    setHooks(Array.isArray(wh) ? wh : []);
  }

  useEffect(() => {
    load().catch((e) => setMsg(String(e?.message || e)));
  }, []);

  async function connect() {
    const res = await apiGet("/api/v1/office/connect");
    if (res.authorize_url) {
      window.location.href = res.authorize_url;
      return;
    }
    setMsg(t("page.office.connected_stub", "Microsoft 365 connected (demo mode)."));
    await load();
  }

  async function disconnect() {
    await apiPost("/api/v1/office/disconnect");
    setMsg(t("page.office.disconnected", "Office link disconnected."));
    await load();
  }

  async function sync(channel: string) {
    const res = await apiPost("/api/v1/office/sync", { channel, direction: "inbound" });
    setMsg(t("page.office.sync_done", "Sync {channel}: {status}", { channel, status: res.status }));
    await load();
  }

  async function refreshHealth() {
    const h = await apiGet("/api/v1/office/health");
    setMsg(t("page.office.health_ok", "Graph health OK — {user}", { user: String(h.user || h.mode) }));
    await load();
  }

  async function loadMail() {
    const res = await apiGet("/api/v1/office/mail?top=10");
    setMail(res.items || []);
  }

  async function loadDrives() {
    const res = await apiGet("/api/v1/office/drives");
    setDrives(res.items || []);
  }

  async function loadTeams() {
    const res = await apiGet("/api/v1/office/teams");
    setTeams(res.items || []);
  }

  async function sendTeams() {
    const res = await apiPost("/api/v1/office/teams/notify", { text: notifyText });
    setMsg(t("page.office.teams_sent", "Teams message queued: {id}", { id: String(res.id || "ok") }));
  }

  async function createHook() {
    const res = await apiPost("/api/v1/office/webhooks", {
      name: hookName,
      target_url: hookUrl,
      events: ["charter.activated", "voyage.started", "invoice.issued", "office.sync.done", "*"],
    });
    setMsg(t("page.office.hook_created", "Webhook created. Secret: {secret}", { secret: res.secret }));
    await load();
  }

  async function testHook(id: string) {
    const res = await apiPost(`/api/v1/office/webhooks/${id}/test`);
    setMsg(t("page.office.hook_test", "Delivery {status}", { status: res.status }));
    await load();
  }

  async function markAddon(id: string, st: string) {
    await apiPost(`/api/v1/office/addons/${id}`, { status: st });
    await load();
  }

  function configSourceBadge(src?: string) {
    const map: Record<string, [string, string]> = {
      tenant: ["badge badge-pass", t("settings.office.src_tenant", "本租户专属应用")],
      global: ["badge badge-info", t("settings.office.src_global", "平台全局应用")],
      stub: ["badge badge-warn", t("settings.office.src_stub", "演示模式")],
      disabled: ["badge", t("settings.office.src_disabled", "未配置")],
    };
    const [cls, label] = map[src || ""] || ["badge", src || "—"];
    return <span className={cls}>{label}</span>;
  }

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.office.title", "Office ecosystem")}</h1>
          <p className="page-sub">
            {t(
              "page.office.sub",
              "Microsoft 365 — Teams, SharePoint, OneDrive, Outlook — shared with MariOS resources."
            )}
          </p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <button className="btn btn-primary" type="button" onClick={() => connect().catch((e) => setMsg(String(e)))}>
            {t("page.office.connect", "Connect Microsoft 365")}
          </button>
          <button className="btn" type="button" onClick={() => refreshHealth().catch((e) => setMsg(String(e)))}>
            {t("page.office.health", "Health check")}
          </button>
          <button className="btn" type="button" onClick={() => disconnect().catch((e) => setMsg(String(e)))}>
            {t("page.office.disconnect", "Disconnect")}
          </button>
        </div>
      </div>

      {msg ? <p className="flash">{msg}</p> : null}

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.office.link", "Tenant link")}</h3>
        <p>
          {t("common.status", "Status")}: <strong>{status?.status || "—"}</strong> ·{" "}
          {t("page.office.mode", "Mode")}: <code>{status?.graph_mode || "—"}</code> ·{" "}
          {status?.connected ? t("page.office.is_connected", "Connected") : t("page.office.not_connected", "Not connected")}
        </p>
        <p>
          {t("settings.office.config_source", "配置来源")}: {configSourceBadge(status?.config_source)}
        </p>
        {status?.config_source === "stub" ? (
          <p className="muted">
            {t("settings.office.demo_hint", "当前为演示数据，请联系平台管理员配置 Microsoft 365 应用。")}
          </p>
        ) : null}
        <p style={{ color: "var(--muted)", fontSize: "0.9rem" }}>
          <code>{JSON.stringify(status?.last_health || {})}</code>
        </p>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          {(["mail", "onedrive", "sharepoint", "teams"] as const).map((ch) => (
            <button key={ch} className="btn" type="button" onClick={() => sync(ch).catch((e) => setMsg(String(e)))}>
              {t("page.office.sync_ch", "Sync {channel}", { channel: ch })}
            </button>
          ))}
        </div>
      </div>

      <div className="workbench-grid" style={{ marginTop: "1rem" }}>
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>{t("page.office.mail", "Mail")}</h3>
          <button className="btn" type="button" onClick={() => loadMail().catch((e) => setMsg(String(e)))}>
            {t("page.office.load_mail", "Load inbox sample")}
          </button>
          <ul>
            {mail.map((m) => (
              <li key={String(m.id)}>
                <strong>{String(m.subject)}</strong>
                <div style={{ color: "var(--muted)", fontSize: "0.85rem" }}>{String((m as any).bodyPreview || "")}</div>
              </li>
            ))}
          </ul>
        </div>
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>{t("page.office.files", "OneDrive / SharePoint")}</h3>
          <button className="btn" type="button" onClick={() => loadDrives().catch((e) => setMsg(String(e)))}>
            {t("page.office.load_drives", "List drives")}
          </button>
          <ul>
            {drives.map((d) => (
              <li key={String(d.id)}>
                {String(d.name)} <span style={{ color: "var(--muted)" }}>({String(d.driveType)})</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>{t("page.office.teams", "Teams")}</h3>
          <button className="btn" type="button" onClick={() => loadTeams().catch((e) => setMsg(String(e)))}>
            {t("page.office.load_teams", "List teams")}
          </button>
          <ul>
            {teams.map((tm) => (
              <li key={String(tm.id)}>{String(tm.displayName)}</li>
            ))}
          </ul>
          <textarea
            value={notifyText}
            onChange={(e) => setNotifyText(e.target.value)}
            rows={3}
            style={{ width: "100%", marginTop: "0.5rem" }}
          />
          <button className="btn btn-primary" type="button" onClick={() => sendTeams().catch((e) => setMsg(String(e)))}>
            {t("page.office.notify", "Post channel message")}
          </button>
        </div>
      </div>

      <div className="panel" style={{ marginTop: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>{t("page.office.jobs", "Sync jobs")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.office.channel", "Channel")}</th>
              <th>{t("common.status", "Status")}</th>
              <th>{t("page.office.stats", "Stats")}</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id}>
                <td>{j.channel}</td>
                <td>{j.status}</td>
                <td>
                  <code>{JSON.stringify(j.stats || j.error || {})}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel" style={{ marginTop: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>{t("page.office.webhooks", "Outbound webhooks")}</h3>
        <p style={{ color: "var(--muted)" }}>
          {t("page.office.webhooks_sub", "Power Automate / Teams Workflows / partner systems.")}
        </p>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
          <input value={hookName} onChange={(e) => setHookName(e.target.value)} placeholder="Name" />
          <input
            value={hookUrl}
            onChange={(e) => setHookUrl(e.target.value)}
            placeholder="https://..."
            style={{ minWidth: "280px" }}
          />
          <button className="btn" type="button" onClick={() => createHook().catch((e) => setMsg(String(e)))}>
            {t("common.create", "Create")}
          </button>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.name", "Name")}</th>
              <th>URL</th>
              <th>{t("common.status", "Status")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {hooks.map((h) => (
              <tr key={h.id}>
                <td>{h.name}</td>
                <td>
                  <code>{h.target_url}</code>
                </td>
                <td>{h.status}</td>
                <td>
                  <button className="btn" type="button" onClick={() => testHook(h.id).catch((e) => setMsg(String(e)))}>
                    {t("common.test", "Test")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel" style={{ marginTop: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>{t("page.office.addons", "Office / Teams add-ins")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.name", "Name")}</th>
              <th>{t("page.office.host", "Host")}</th>
              <th>{t("common.status", "Status")}</th>
              <th>{t("page.office.manifest", "Manifest")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {(status?.addons || []).map((a) => (
              <tr key={String(a.id)}>
                <td>{String(a.name || a.id)}</td>
                <td>{String(a.host || "—")}</td>
                <td>{String(a.status)}</td>
                <td>
                  {a.manifest ? (
                    <a href={String(a.manifest)} target="_blank" rel="noreferrer">
                      {String(a.manifest)}
                    </a>
                  ) : (
                    "—"
                  )}
                </td>
                <td>
                  <button className="btn" type="button" onClick={() => markAddon(String(a.id), "installed").catch((e) => setMsg(String(e)))}>
                    {t("page.office.mark_installed", "Mark installed")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
