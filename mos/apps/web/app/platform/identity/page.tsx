"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiPut } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Identity = {
  microsoft_enabled: boolean;
  google_enabled: boolean;
  email_password_enabled: boolean;
  magic_link_enabled: boolean;
  email_channel: string;
  email_from: string;
  email_from_name: string;
  default_require_email_verify: boolean;
  default_invite_only: boolean;
  default_allowed_domains: string[];
  notes: string | null;
  runtime: any;
  secret_guidance?: Record<string, string>;
};

export default function PlatformIdentityPage() {
  const { t } = useI18n();
  const [form, setForm] = useState<Identity | null>(null);
  const [domains, setDomains] = useState("");
  const [logs, setLogs] = useState<any[]>([]);
  const [msg, setMsg] = useState("");

  async function load() {
    const data = await apiGet("/api/v1/platform/identity");
    setForm(data);
    setDomains((data.default_allowed_domains || []).join(", "));
    setLogs(await apiGet("/api/v1/platform/identity/mail-logs"));
  }

  useEffect(() => {
    load().catch(() => setMsg(t("page.identity.admin_required", "Platform admin required")));
  }, [t]);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    await apiPut("/api/v1/platform/identity", {
      ...form,
      default_allowed_domains: domains
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    });
    setMsg(t("page.identity.saved", "Platform identity settings saved. Client secrets stay in server env only."));
    await load();
  }

  if (!form) {
    return (
      <AppShell>
        <p>{msg || t("common.loading", "Loading…")}</p>
      </AppShell>
    );
  }

  const rt = form.runtime || {};

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("page.identity.title", "Identity & verification (Platform)")}</h1>
      <p className="page-sub">
        {t("page.identity.sub", "Platform owns global OAuth apps, email delivery channel, and default policy templates.")}
      </p>
      {msg ? <p className="flash">{msg}</p> : null}

      <div className="card verdict" style={{ marginBottom: "1rem", padding: "0.85rem 1rem", borderLeft: "4px solid var(--accent)", background: "#f3fbfa" }}>
        <strong>{t("page.identity.email_box", "邮件通道与发件人")}</strong>
        <p className="muted" style={{ margin: "0.35rem 0 0" }}>
          {t(
            "page.identity.email_box_d",
            "在下方「邮件通道」选择 console / SMTP / SendGrid / Graph，并设置 From 地址与显示名后保存。SMTP 密码等密钥仅放在服务器环境变量，不会出现在浏览器。",
          )}
        </p>
      </div>

      <div className="kpi-row">
        <div className="kpi-card">
          <span>Microsoft</span>
          <strong>{rt.microsoft?.mode || "—"}</strong>
        </div>
        <div className="kpi-card">
          <span>Google</span>
          <strong>{rt.google?.mode || "—"}</strong>
        </div>
        <div className="kpi-card">
          <span>{t("page.identity.email_ch", "Email channel")}</span>
          <strong>{form.email_channel}</strong>
        </div>
        <div className="kpi-card">
          <span>{t("page.identity.stub_oauth", "Stub OAuth")}</span>
          <strong>{rt.oauth_allow_stub ? "ON" : "OFF"}</strong>
        </div>
      </div>

      <form className="panel" onSubmit={(e) => save(e).catch(() => setMsg(t("common.failed", "Failed")))}>
        <h2>{t("page.identity.methods", "Global methods")}</h2>
        <div className="check-grid">
          {(
            [
              ["microsoft_enabled", t("page.identity.ms", "Microsoft 365 / Entra ID")],
              ["google_enabled", t("page.identity.google", "Google Workspace / Google")],
              ["email_password_enabled", t("page.identity.email_pw", "Email + password")],
              ["magic_link_enabled", t("page.identity.magic", "Email magic link")],
            ] as const
          ).map(([key, label]) => (
            <label key={key} className="check-row">
              <input
                type="checkbox"
                checked={Boolean((form as any)[key])}
                onChange={(e) => setForm({ ...form, [key]: e.target.checked })}
              />
              {label}
            </label>
          ))}
        </div>

        <h2>{t("page.identity.email_ch", "Email channel")}</h2>
        <div className="form-grid">
          <label>
            {t("page.identity.channel", "Channel")}
            <select
              value={form.email_channel}
              onChange={(e) => setForm({ ...form, email_channel: e.target.value })}
            >
              <option value="console">{t("page.identity.ch_console", "Console (demo / log)")}</option>
              <option value="smtp">{t("page.identity.ch_smtp", "SMTP")}</option>
              <option value="sendgrid">{t("page.identity.ch_sendgrid", "SendGrid")}</option>
              <option value="graph">{t("page.identity.ch_graph", "Microsoft Graph mail")}</option>
            </select>
          </label>
          <label>
            {t("page.identity.from_addr", "From address")}
            <input value={form.email_from} onChange={(e) => setForm({ ...form, email_from: e.target.value })} />
          </label>
          <label>
            {t("page.identity.from_name", "From name")}
            <input
              value={form.email_from_name}
              onChange={(e) => setForm({ ...form, email_from_name: e.target.value })}
            />
          </label>
        </div>

        <h2>{t("page.identity.defaults", "Default policy for new tenants")}</h2>
        <div className="check-grid">
          <label className="check-row">
            <input
              type="checkbox"
              checked={form.default_require_email_verify}
              onChange={(e) => setForm({ ...form, default_require_email_verify: e.target.checked })}
            />
            {t("page.identity.require_verify", "Require email verification")}
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={form.default_invite_only}
              onChange={(e) => setForm({ ...form, default_invite_only: e.target.checked })}
            />
            {t("page.identity.invite_only", "Invite-only by default")}
          </label>
        </div>
        <label>
          {t("page.identity.domains", "Default allowed domains (comma-separated, empty = any)")}
          <input value={domains} onChange={(e) => setDomains(e.target.value)} placeholder="acme.com, acme.sg" />
        </label>

        <h2>{t("page.identity.secrets", "Secret guidance (env only)")}</h2>
        <ul className="compact-list">
          {Object.entries(form.secret_guidance || {}).map(([k, v]) => (
            <li key={k}>
              <strong>{k}</strong>: {v}
            </li>
          ))}
        </ul>

        <button className="btn btn-primary" type="submit" style={{ marginTop: "1rem" }}>
          {t("page.identity.save", "Save platform identity")}
        </button>
      </form>

      <div className="panel">
        <h2>{t("page.identity.mail_logs", "Recent verification / invite emails")}</h2>
        <ul className="compact-list">
          {logs.map((l) => (
            <li key={l.id}>
              [{l.purpose}] {l.to_email} — {l.subject}
              <div className="muted">{l.created_at}</div>
            </li>
          ))}
          {!logs.length ? <li className="muted">{t("page.identity.no_mail", "No outbound mail yet.")}</li> : null}
        </ul>
      </div>
    </AppShell>
  );
}
