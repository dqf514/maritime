"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { Toolbar } from "@/components/Toolbar";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

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
  const toast = useToast();
  const [status, setStatus] = useState<OfficeStatus | null>(null);
  const [jobs, setJobs] = useState<SyncJob[]>([]);
  const [hooks, setHooks] = useState<Webhook[]>([]);
  const [mail, setMail] = useState<Array<Record<string, unknown>>>([]);
  const [drives, setDrives] = useState<Array<Record<string, unknown>>>([]);
  const [teams, setTeams] = useState<Array<Record<string, unknown>>>([]);
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
    load().catch((e) => toast.error(String(e?.message || e)));
  }, []);

  async function connect() {
    const res = await apiGet("/api/v1/office/connect");
    if (res.authorize_url) {
      window.location.href = res.authorize_url;
      return;
    }
    toast.success(t("page.office.connected_stub", "Microsoft 365 connected (demo mode)."));
    await load();
  }

  async function disconnect() {
    await apiPost("/api/v1/office/disconnect");
    toast.success(t("page.office.disconnected", "Office link disconnected."));
    await load();
  }

  async function sync(channel: string) {
    const res = await apiPost("/api/v1/office/sync", { channel, direction: "inbound" });
    toast.success(t("page.office.sync_done", "Sync {channel}: {status}", { channel, status: res.status }));
    await load();
  }

  async function refreshHealth() {
    const h = await apiGet("/api/v1/office/health");
    toast.success(t("page.office.health_ok", "Graph health OK — {user}", { user: String(h.user || h.mode) }));
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
    toast.success(t("page.office.teams_sent", "Teams message queued: {id}", { id: String(res.id || "ok") }));
  }

  async function createHook() {
    const res = await apiPost("/api/v1/office/webhooks", {
      name: hookName,
      target_url: hookUrl,
      events: ["charter.activated", "voyage.started", "invoice.issued", "office.sync.done", "*"],
    });
    toast.success(t("page.office.hook_created", "Webhook created. Secret: {secret}", { secret: res.secret }));
    await load();
  }

  async function testHook(id: string) {
    const res = await apiPost(`/api/v1/office/webhooks/${id}/test`);
    toast.success(t("page.office.hook_test", "Delivery {status}", { status: res.status }));
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

  const jobColumns: ColumnDef<SyncJob>[] = [
    { key: "channel", title: t("page.office.channel", "Channel"), width: 120, value: (r) => r.channel },
    { key: "status", title: t("common.status", "Status"), width: 110, value: (r) => r.status },
    {
      key: "stats",
      title: t("page.office.stats", "Stats"),
      minWidth: 200,
      value: (r) => JSON.stringify(r.stats || r.error || {}),
      render: (v) => <code>{String(v)}</code>,
    },
  ];

  const hookColumns: ColumnDef<Webhook>[] = [
    { key: "name", title: t("common.name", "Name"), minWidth: 140, value: (r) => r.name },
    {
      key: "target_url",
      title: "URL",
      minWidth: 200,
      value: (r) => r.target_url,
      render: (v) => <code>{String(v)}</code>,
    },
    { key: "status", title: t("common.status", "Status"), width: 110, value: (r) => r.status },
    {
      key: "_actions",
      title: "",
      width: 90,
      align: "right",
      render: (_v, h) => (
        <button className="btn" type="button" onClick={() => testHook(h.id).catch((e) => toast.error(String(e)))}>
          {t("common.test", "Test")}
        </button>
      ),
    },
  ];

  type AddonRow = Record<string, unknown>;

  const addonColumns: ColumnDef<AddonRow>[] = [
    {
      key: "name",
      title: t("common.name", "Name"),
      minWidth: 140,
      value: (r) => String(r.name || r.id),
    },
    {
      key: "host",
      title: t("page.office.host", "Host"),
      width: 110,
      value: (r) => String(r.host || "—"),
    },
    { key: "status", title: t("common.status", "Status"), width: 110, value: (r) => String(r.status) },
    {
      key: "manifest",
      title: t("page.office.manifest", "Manifest"),
      minWidth: 180,
      value: (r) => String(r.manifest || ""),
      render: (v) =>
        v ? (
          <a href={String(v)} target="_blank" rel="noreferrer">
            {String(v)}
          </a>
        ) : (
          "—"
        ),
    },
    {
      key: "_actions",
      title: "",
      width: 130,
      align: "right",
      render: (_v, a) => (
        <button
          className="btn"
          type="button"
          onClick={() => markAddon(String(a.id), "installed").catch((e) => toast.error(String(e)))}
        >
          {t("page.office.mark_installed", "Mark installed")}
        </button>
      ),
    },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[
          { label: t("nav.settings_hub", "System settings"), href: "/settings" },
          { label: t("page.office.title", "Office ecosystem") },
        ]}
        title={t("page.office.title", "Office ecosystem")}
        subtitle={t(
          "page.office.sub",
          "Microsoft 365 — Teams, SharePoint, OneDrive, Outlook — shared with MariOS resources."
        )}
      />
      <Toolbar>
        <button className="btn btn-primary" type="button" onClick={() => connect().catch((e) => toast.error(String(e)))}>
          {t("page.office.connect", "Connect Microsoft 365")}
        </button>
        <button className="btn" type="button" onClick={() => refreshHealth().catch((e) => toast.error(String(e)))}>
          {t("page.office.health", "Health check")}
        </button>
        <button className="btn" type="button" onClick={() => disconnect().catch((e) => toast.error(String(e)))}>
          {t("page.office.disconnect", "Disconnect")}
        </button>
        <button type="button" className="btn btn-sm" onClick={() => load().catch(() => undefined)} title={t("common.refresh", "Refresh")}>
          ↻
        </button>
      </Toolbar>


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
            <button key={ch} className="btn" type="button" onClick={() => sync(ch).catch((e) => toast.error(String(e)))}>
              {t("page.office.sync_ch", "Sync {channel}", { channel: ch })}
            </button>
          ))}
        </div>
      </div>

      <div className="workbench-grid" style={{ marginTop: "1rem" }}>
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>{t("page.office.mail", "Mail")}</h3>
          <button className="btn" type="button" onClick={() => loadMail().catch((e) => toast.error(String(e)))}>
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
          <button className="btn" type="button" onClick={() => loadDrives().catch((e) => toast.error(String(e)))}>
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
          <button className="btn" type="button" onClick={() => loadTeams().catch((e) => toast.error(String(e)))}>
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
          <button className="btn btn-primary" type="button" onClick={() => sendTeams().catch((e) => toast.error(String(e)))}>
            {t("page.office.notify", "Post channel message")}
          </button>
        </div>
      </div>

      <div className="panel" style={{ marginTop: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>{t("page.office.jobs", "Sync jobs")}</h3>
        <DataGrid<SyncJob>
          columns={jobColumns}
          data={jobs}
          rowKey={(r) => r.id}
          storageKey="settings_office_jobs_grid"
          emptyText={t("common.no_data", "No data")}
        />
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
          <button className="btn" type="button" onClick={() => createHook().catch((e) => toast.error(String(e)))}>
            {t("common.create", "Create")}
          </button>
        </div>
        <DataGrid<Webhook>
          columns={hookColumns}
          data={hooks}
          rowKey={(r) => r.id}
          storageKey="settings_office_hooks_grid"
          emptyText={t("common.no_data", "No data")}
        />
      </div>

      <div className="panel" style={{ marginTop: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>{t("page.office.addons", "Office / Teams add-ins")}</h3>
        <DataGrid<AddonRow>
          columns={addonColumns}
          data={status?.addons || []}
          rowKey={(r) => String(r.id)}
          storageKey="settings_office_addons_grid"
          emptyText={t("common.no_data", "No data")}
        />
      </div>
    </AppShell>
  );
}
