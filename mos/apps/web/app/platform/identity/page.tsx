"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { StateView } from "@/components/StateView";
import { apiGet, apiPost, apiPut } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type Identity = {
  microsoft_enabled: boolean;
  google_enabled: boolean;
  email_password_enabled: boolean;
  magic_link_enabled: boolean;
  email_channel: string;
  email_from: string;
  email_from_name: string;
  smtp_host: string | null;
  smtp_port: number | null;
  smtp_security: string;
  smtp_username: string | null;
  smtp_password_set: boolean;
  default_require_email_verify: boolean;
  default_invite_only: boolean;
  default_allowed_domains: string[];
  notes: string | null;
  runtime: any;
  secret_guidance?: Record<string, { en: string; zh: string } | string>;
};

export default function PlatformIdentityPage() {
  const { t, locale } = useI18n();
  const toast = useToast();
  const [form, setForm] = useState<Identity | null>(null);
  const [domains, setDomains] = useState("");
  const [logs, setLogs] = useState<any[]>([]);
  const [smtpPw, setSmtpPw] = useState(""); // "" = keep current
  const [smtpPwClear, setSmtpPwClear] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testTo, setTestTo] = useState("");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [logsErr, setLogsErr] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setErr(null);
    setLogsErr(null);
    try {
      const data = await apiGet("/api/v1/platform/identity");
      setForm(data);
      setDomains((data.default_allowed_domains || []).join(", "));
    } catch (ex) {
      setErr(msgOf(ex, t("page.identity.admin_required", "Platform admin required")));
      setLoading(false);
      return;
    }
    try {
      setLogs(await apiGet("/api/v1/platform/identity/mail-logs"));
    } catch (ex) {
      setLogsErr(msgOf(ex));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    const { runtime, secret_guidance, smtp_password_set, ...rest } = form;
    void runtime;
    void secret_guidance;
    void smtp_password_set;
    const body: Record<string, unknown> = {
      ...rest,
      default_allowed_domains: domains
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    };
    if (smtpPwClear) body.smtp_password = "";
    else if (smtpPw) body.smtp_password = smtpPw;
    await apiPut("/api/v1/platform/identity", body);
    toast.success(t("page.identity.saved", "Platform identity settings saved. The SMTP password is encrypted at rest and never sent to the browser."));
    setSmtpPw("");
    setSmtpPwClear(false);
    await load();
  }

  async function sendTest() {
    setTesting(true);
    try {
      const res = await apiPost("/api/v1/platform/identity/smtp-test", testTo ? { to_email: testTo } : {});
      if (res.ok) toast.success(t("page.identity.smtp_test_ok", "Test mail delivered to the SMTP relay."));
      else
        toast.error(
          t("page.identity.smtp_test_fail", "SMTP test failed: {msg}", { msg: res.message || "" }),
        );
    } catch (err) {
      toast.error(msgOf(err, t("common.failed", "Failed")));
    } finally {
      setTesting(false);
    }
  }

  if (loading || (!form && !err)) {
    return (
      <AppShell>
        <p>{t("common.loading", "Loading…")}</p>
      </AppShell>
    );
  }

  if (err || !form) {
    return (
      <AppShell>
        <PageHeader
          title={t("page.identity.title", "Identity & verification (Platform)")}
          subtitle={t("page.identity.sub", "Platform owns global OAuth apps, email delivery channel, and default policy templates.")}
          breadcrumb={[{ label: t("page.platform.title", "Platform"), href: "/platform" }, { label: t("page.identity.title", "Identity & verification (Platform)") }]}
        />
        <StateView loading={false} error={err ?? undefined} empty={false} onRetry={() => load()}>
          <span />
        </StateView>
      </AppShell>
    );
  }

  const rt = form.runtime || {};
  const smtpConfigured = Boolean(form.smtp_host);

  return (
    <AppShell>
      <PageHeader
        title={t("page.identity.title", "Identity & verification (Platform)")}
        subtitle={t("page.identity.sub", "Platform owns global OAuth apps, email delivery channel, and default policy templates.")}
        breadcrumb={[{ label: t("page.platform.title", "Platform"), href: "/platform" }, { label: t("page.identity.title", "Identity & verification (Platform)") }]}
      />

      <div className="card verdict" style={{ marginBottom: "1rem", padding: "0.85rem 1rem", borderLeft: "4px solid var(--accent)", background: "#f3fbfa" }}>
        <strong>{t("page.identity.email_box", "Email channel and sender")}</strong>
        <p className="muted" style={{ margin: "0.35rem 0 0" }}>
          {t(
            "page.identity.email_box_d",
            "Choose console / SMTP / SendGrid / Graph under \"Email channel\", set the From address and display name, then save. SMTP host / port / security / credentials are configured on this page; the password is encrypted at rest and never reaches the browser.",
          )}
        </p>
      </div>

      <div className="kpi-row">
        <div className="kpi-card">
          <span>Microsoft</span>
          <strong>
            {rt.microsoft?.mode ? t(`page.identity.mode_${rt.microsoft.mode}`, rt.microsoft.mode) : "—"}
          </strong>
        </div>
        <div className="kpi-card">
          <span>Google</span>
          <strong>{rt.google?.mode ? t(`page.identity.mode_${rt.google.mode}`, rt.google.mode) : "—"}</strong>
        </div>
        <div className="kpi-card">
          <span>{t("page.identity.email_ch", "Email channel")}</span>
          <strong>{t(`page.identity.ch_${form.email_channel}`, form.email_channel)}</strong>
        </div>
        <div className="kpi-card">
          <span>{t("page.identity.stub_oauth", "Stub OAuth")}</span>
          <strong>{rt.oauth_allow_stub ? t("page.identity.on", "ON") : t("page.identity.off", "OFF")}</strong>
        </div>
      </div>

      <form className="panel" onSubmit={(e) => save(e).catch(() => toast.error(t("common.failed", "Failed")))}>
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

        <h2>{t("page.identity.smtp_section", "SMTP delivery")}</h2>
        <p className="muted" style={{ margin: "0 0 0.5rem" }}>
          {t("page.identity.smtp_d", "Used when the email channel is SMTP. The password is stored encrypted; leave the field blank to keep the saved password.")}
        </p>
        <div className="form-grid">
          <label>
            {t("page.identity.smtp_host", "SMTP host")}
            <input
              value={form.smtp_host || ""}
              onChange={(e) => setForm({ ...form, smtp_host: e.target.value })}
              placeholder="smtp.example.com"
            />
          </label>
          <label>
            {t("page.identity.smtp_port", "Port")}
            <input
              type="number"
              min={1}
              max={65535}
              value={form.smtp_port ?? ""}
              onChange={(e) => setForm({ ...form, smtp_port: e.target.value ? Number(e.target.value) : null })}
              placeholder={form.smtp_security === "ssl" ? "465" : "587"}
            />
          </label>
          <label>
            {t("page.identity.smtp_security", "Security")}
            <select
              value={form.smtp_security || "starttls"}
              onChange={(e) => setForm({ ...form, smtp_security: e.target.value })}
            >
              <option value="starttls">{t("page.identity.smtp_sec_starttls", "STARTTLS (587)")}</option>
              <option value="ssl">{t("page.identity.smtp_sec_ssl", "SSL / TLS (465)")}</option>
              <option value="none">{t("page.identity.smtp_sec_none", "None (plain)")}</option>
            </select>
          </label>
          <label>
            {t("page.identity.smtp_username", "Username (optional)")}
            <input
              value={form.smtp_username || ""}
              onChange={(e) => setForm({ ...form, smtp_username: e.target.value })}
              autoComplete="off"
            />
          </label>
          <label>
            {t("page.identity.smtp_password", "Password")}
            {form.smtp_password_set && !smtpPwClear ? (
              <div style={{ display: "flex", gap: "0.4rem" }}>
                <input
                  type="password"
                  value={smtpPw}
                  onChange={(e) => setSmtpPw(e.target.value)}
                  placeholder={t("platform.officecfg.secret_keep", "Leave blank to keep the current secret")}
                  autoComplete="new-password"
                  style={{ flex: 1 }}
                />
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => setSmtpPwClear(true)}
                  title={t("platform.officecfg.clear_secret", "Clear secret")}
                >
                  {t("platform.officecfg.clear_secret", "Clear secret")}
                </button>
              </div>
            ) : (
              <div style={{ display: "flex", gap: "0.4rem" }}>
                <input
                  type="password"
                  value={smtpPwClear ? "" : smtpPw}
                  onChange={(e) => {
                    setSmtpPw(e.target.value);
                    if (smtpPwClear) setSmtpPwClear(false);
                  }}
                  placeholder={
                    smtpPwClear
                      ? t("page.identity.smtp_pw_cleared", "Will be cleared on save")
                      : t("page.identity.smtp_pw_placeholder", "SMTP password")
                  }
                  autoComplete="new-password"
                  disabled={smtpPwClear}
                  style={{ flex: 1 }}
                />
                {smtpPwClear ? (
                  <button type="button" className="btn btn-sm" onClick={() => setSmtpPwClear(false)}>
                    {t("common.cancel", "Cancel")}
                  </button>
                ) : null}
              </div>
            )}
            {form.smtp_password_set && !smtpPwClear ? (
              <span className="badge badge-ok" style={{ marginTop: "0.25rem", alignSelf: "flex-start" }}>
                {t("page.identity.smtp_pw_saved", "Password saved (encrypted)")}
              </span>
            ) : null}
          </label>
        </div>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-end", marginTop: "0.5rem", flexWrap: "wrap" }}>
          <label style={{ flex: "0 1 260px" }}>
            {t("page.identity.smtp_test_to", "Test recipient (default: your account)")}
            <input value={testTo} onChange={(e) => setTestTo(e.target.value)} placeholder="you@example.com" />
          </label>
          <button
            type="button"
            className="btn"
            disabled={testing || !smtpConfigured}
            onClick={sendTest}
            title={smtpConfigured ? undefined : t("page.identity.smtp_test_need_save", "Save an SMTP host first, then test.")}
          >
            {testing ? t("page.identity.testing", "Sending…") : t("page.identity.smtp_test", "Send test mail")}
          </button>
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
              <strong>{k}</strong>:{" "}
              {typeof v === "string" ? v : locale?.startsWith("zh") ? v.zh : v.en}
            </li>
          ))}
        </ul>

        <button className="btn btn-primary" type="submit" style={{ marginTop: "1rem" }}>
          {t("page.identity.save", "Save platform identity")}
        </button>
      </form>

      <div className="panel">
        <h2>{t("page.identity.mail_logs", "Recent verification / invite emails")}</h2>
        {logsErr ? <p className="text-danger">{logsErr}</p> : null}
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
