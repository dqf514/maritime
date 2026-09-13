"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const API = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

type Policy = {
  password_enabled: boolean;
  microsoft_enabled: boolean;
  google_enabled: boolean;
  magic_link_enabled: boolean;
  require_email_verify: boolean;
  invite_only: boolean;
  allowed_domains: string[];
  session_hours: number;
  platform_gates?: Record<string, boolean>;
  runtime?: any;
};

export default function TenantSecurityPage() {
  const { t } = useI18n();
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [domains, setDomains] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteName, setInviteName] = useState("");
  const [invites, setInvites] = useState<any[]>([]);
  const [logs, setLogs] = useState<any[]>([]);
  const [msg, setMsg] = useState("");
  const [demoToken, setDemoToken] = useState("");

  async function load() {
    const p = await apiGet("/api/v1/admin/security/policy");
    setPolicy(p);
    setDomains((p.allowed_domains || []).join(", "));
    setInvites(await apiGet("/api/v1/admin/security/invites"));
    setLogs(await apiGet("/api/v1/admin/security/mail-logs"));
  }

  useEffect(() => {
    load().catch(() => setMsg(t("page.security.admin_required", "Tenant admin required")));
  }, [t]);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!policy) return;
    const res = await fetch(`${API}/api/v1/admin/security/policy`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${localStorage.getItem("voyageos_token")}`,
      },
      body: JSON.stringify({
        ...policy,
        allowed_domains: domains
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      }),
    });
    if (!res.ok) throw new Error("fail");
    setMsg(t("page.security.updated", "Tenant login & verification policy updated."));
    await load();
  }

  async function invite(e: FormEvent) {
    e.preventDefault();
    const data = await apiPost("/api/v1/admin/security/invites", {
      email: inviteEmail,
      full_name: inviteName,
      role_codes: ["viewer"],
    });
    setDemoToken(data.demo_token || "");
    setMsg(t("page.security.invite_sent", "Invite sent to {email} (console mail channel).", { email: inviteEmail }));
    setInviteEmail("");
    setInviteName("");
    await load();
  }

  if (!policy) {
    return (
      <AppShell>
        <p>{msg || t("common.loading", "Loading…")}</p>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("page.security.title", "Login & security (Tenant)")}</h1>
      <p className="page-sub">
        {t(
          "page.security.sub",
          "Choose which platform-approved methods to offer, enforce email verification / invite-only, and restrict corporate domains.",
        )}
      </p>
      {msg ? <p className="flash">{msg}</p> : null}
      {demoToken ? (
        <p className="muted">
          {t("page.security.demo_token", "Demo invite token:")} <code>{demoToken}</code> —{" "}
          <a href={`/login/accept-invite?token=${demoToken}`}>/login/accept-invite</a>
        </p>
      ) : null}

      <form className="panel" onSubmit={(e) => save(e).catch(() => setMsg(t("page.security.save_fail", "Save failed")))}>
        <h2>{t("page.security.methods", "Sign-in methods")}</h2>
        <div className="check-grid">
          {(
            [
              ["password_enabled", t("page.security.method_password", "Email + password"), "password"],
              ["microsoft_enabled", t("page.security.method_ms", "Microsoft 365"), "microsoft"],
              ["google_enabled", t("page.security.method_google", "Google"), "google"],
              ["magic_link_enabled", t("page.security.method_magic", "Magic link (email)"), "magic_link"],
            ] as const
          ).map(([key, label, gate]) => (
            <label key={key} className="check-row">
              <input
                type="checkbox"
                checked={Boolean((policy as any)[key])}
                disabled={policy.platform_gates && policy.platform_gates[gate] === false}
                onChange={(e) => setPolicy({ ...policy, [key]: e.target.checked })}
              />
              {label}
              {policy.platform_gates && policy.platform_gates[gate] === false ? (
                <span className="muted"> {t("page.security.disabled_plat", "(disabled by platform)")}</span>
              ) : null}
            </label>
          ))}
        </div>
        <div className="check-grid">
          <label className="check-row">
            <input
              type="checkbox"
              checked={policy.require_email_verify}
              onChange={(e) => setPolicy({ ...policy, require_email_verify: e.target.checked })}
            />
            {t("page.security.require_verify", "Require email verification before password login")}
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={policy.invite_only}
              onChange={(e) => setPolicy({ ...policy, invite_only: e.target.checked })}
            />
            {t("page.security.invite_only", "Invite-only (block self-signup via OAuth)")}
          </label>
        </div>
        <label>
          {t("page.security.domains", "Allowed email domains")}
          <input value={domains} onChange={(e) => setDomains(e.target.value)} placeholder="company.com, company.sg" />
        </label>
        <button className="btn btn-primary" type="submit" style={{ marginTop: "0.75rem" }}>
          {t("page.security.save_policy", "Save policy")}
        </button>
      </form>

      <form className="panel" onSubmit={(e) => invite(e).catch(() => setMsg(t("page.security.invite_fail", "Invite failed")))}>
        <h2>{t("page.security.invite_title", "Invite user (email verification path)")}</h2>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
          <label>
            {t("page.users.full_name", "Full name")}
            <input value={inviteName} onChange={(e) => setInviteName(e.target.value)} />
          </label>
          <label>
            {t("common.email", "Email")}
            <input type="email" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} required />
          </label>
          <button className="btn btn-primary" type="submit">
            {t("page.security.send_invite", "Send invite")}
          </button>
        </div>
        <p className="muted">{t("page.security.invite_hint", "Prefer invites over temp passwords. Accepting invite marks email verified.")}</p>
      </form>

      <div className="ship-layout">
        <div className="panel">
          <h2>{t("page.security.pending", "Pending invites")}</h2>
          <ul className="compact-list">
            {invites.map((i, idx) => (
              <li key={idx}>
                {i.email} · {t("page.security.expires", "expires")} {i.expires_at}
              </li>
            ))}
            {!invites.length ? <li className="muted">{t("common.none", "None")}</li> : null}
          </ul>
        </div>
        <div className="panel">
          <h2>{t("page.security.mail_log", "Tenant mail log")}</h2>
          <ul className="compact-list">
            {logs.slice(0, 8).map((l) => (
              <li key={l.id}>
                [{l.purpose}] {l.to_email}
              </li>
            ))}
            {!logs.length ? <li className="muted">{t("common.none", "None")}</li> : null}
          </ul>
        </div>
      </div>
    </AppShell>
  );
}
