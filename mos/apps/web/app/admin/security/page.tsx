"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

import { API_BASE as API } from "@/lib/api";

type Policy = {
  password_enabled: boolean;
  microsoft_enabled: boolean;
  google_enabled: boolean;
  magic_link_enabled: boolean;
  require_email_verify: boolean;
  invite_only: boolean;
  allowed_domains: string[];
  session_hours: number;
  microsoft_tenant_hint?: string | null;
  google_hosted_domain?: string | null;
  sso_notes?: string | null;
  platform_gates?: Record<string, boolean>;
  runtime?: {
    microsoft?: { mode?: string; configured?: boolean; client_id_set?: boolean; tenant?: string };
    google?: { mode?: string; configured?: boolean; client_id_set?: boolean };
    oauth_allow_stub?: boolean;
    api_public_base?: string;
    web_public_base?: string;
  };
};

export default function TenantSecurityPage() {
  const { t } = useI18n();
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [domains, setDomains] = useState("");
  const [msHint, setMsHint] = useState("");
  const [googleHd, setGoogleHd] = useState("");
  const [ssoNotes, setSsoNotes] = useState("");
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
    setMsHint(p.microsoft_tenant_hint || "");
    setGoogleHd(p.google_hosted_domain || "");
    setSsoNotes(p.sso_notes || "");
    setInvites(await apiGet("/api/v1/admin/security/invites"));
    setLogs(await apiGet("/api/v1/admin/security/mail-logs"));
  }

  useEffect(() => {
    load().catch(() => setMsg(t("page.security.admin_required", "需要租户管理员")));
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
        microsoft_tenant_hint: msHint.trim() || null,
        google_hosted_domain: googleHd.trim() || null,
        sso_notes: ssoNotes.trim() || null,
      }),
    });
    if (!res.ok) throw new Error("fail");
    setMsg(t("page.security.updated", "登录与安全策略已更新"));
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
    setMsg(t("page.security.invite_sent", "已向 {email} 发送邀请（控制台邮件通道）", { email: inviteEmail }));
    setInviteEmail("");
    setInviteName("");
    await load();
  }

  if (!policy) {
    return (
      <AppShell>
        <p>{msg || t("common.loading", "加载中…")}</p>
      </AppShell>
    );
  }

  const rt = policy.runtime || {};
  const msMode = rt.microsoft?.mode || "unknown";
  const googMode = rt.google?.mode || "unknown";

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("page.security.title", "登录与安全")}</h1>
      <p className="page-sub">
        {t(
          "page.security.sub",
          "选择平台已批准的登录方式，强制邮箱验证 / 仅邀请，并限制企业邮箱域名。SSO 密钥由平台运维配置。",
        )}
      </p>
      {msg ? <p className="flash">{msg}</p> : null}
      {demoToken ? (
        <p className="muted">
          {t("page.security.demo_token", "演示邀请令牌:")} <code>{demoToken}</code> —{" "}
          <a href={`/login/accept-invite?token=${demoToken}`}>/login/accept-invite</a>
        </p>
      ) : null}

      <div className="panel">
        <h2>{t("page.security.sso_status", "SSO 运行状态")}</h2>
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.provider", "提供商")}</th>
              <th>{t("common.mode", "模式")}</th>
              <th>{t("common.status", "状态")}</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Microsoft 365 / Entra</td>
              <td>
                <code>{msMode}</code>
              </td>
              <td>
                {msMode === "live"
                  ? t("page.security.sso_live", "已配置应用密钥，走真实 OAuth")
                  : msMode === "stub"
                    ? t("page.security.sso_stub", "未配置密钥，演示 stub（平台可设 OAUTH_ALLOW_STUB=false 关闭）")
                    : t("page.security.sso_off", "已禁用")}
              </td>
            </tr>
            <tr>
              <td>Google</td>
              <td>
                <code>{googMode}</code>
              </td>
              <td>
                {googMode === "live"
                  ? t("page.security.sso_live", "已配置应用密钥，走真实 OAuth")
                  : googMode === "stub"
                    ? t("page.security.sso_stub", "未配置密钥，演示 stub")
                    : t("page.security.sso_off", "已禁用")}
              </td>
            </tr>
          </tbody>
        </table>
        <p className="muted" style={{ fontSize: "0.85rem", marginBottom: 0 }}>
          {t("page.security.redirect_hint", "回调地址需在 IdP 登记:")}{" "}
          <code>{(rt.api_public_base || API).replace(/\/$/, "")}/api/v1/auth/oauth/microsoft/callback</code>
          {" · "}
          <code>{(rt.api_public_base || API).replace(/\/$/, "")}/api/v1/auth/oauth/google/callback</code>
        </p>
      </div>

      <form className="panel" onSubmit={(e) => save(e).catch(() => setMsg(t("page.security.save_fail", "保存失败")))}>
        <h2>{t("page.security.methods", "登录方式")}</h2>
        <div className="check-grid">
          {(
            [
              ["password_enabled", t("page.security.method_password", "邮箱 + 密码"), "password"],
              ["microsoft_enabled", t("page.security.method_ms", "Microsoft 365"), "microsoft"],
              ["google_enabled", t("page.security.method_google", "Google"), "google"],
              ["magic_link_enabled", t("page.security.method_magic", "魔术链接（邮件）"), "magic_link"],
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
                <span className="muted"> {t("page.security.disabled_plat", "（平台已关闭）")}</span>
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
            {t("page.security.require_verify", "密码登录前要求邮箱验证")}
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={policy.invite_only}
              onChange={(e) => setPolicy({ ...policy, invite_only: e.target.checked })}
            />
            {t("page.security.invite_only", "仅邀请（阻止 OAuth 自助注册）")}
          </label>
        </div>
        <label>
          {t("page.security.domains", "允许的邮箱域名")}
          <input value={domains} onChange={(e) => setDomains(e.target.value)} placeholder="company.com, company.sg" />
        </label>
        <h2 style={{ marginTop: "1.25rem" }}>{t("page.security.sso_tenant", "企业 SSO 限定")}</h2>
        <div className="kv-grid">
          <label>
            {t("page.security.ms_tenant", "Microsoft Entra 租户 ID")}
            <input
              value={msHint}
              onChange={(e) => setMsHint(e.target.value)}
              placeholder="common | organizations | {guid}"
            />
          </label>
          <label>
            {t("page.security.google_hd", "Google Workspace 域名 (hd)")}
            <input value={googleHd} onChange={(e) => setGoogleHd(e.target.value)} placeholder="company.com" />
          </label>
        </div>
        <label>
          {t("page.security.sso_notes", "SSO 运维备注")}
          <textarea value={ssoNotes} onChange={(e) => setSsoNotes(e.target.value)} rows={2} />
        </label>
        <button className="btn btn-primary" type="submit" style={{ marginTop: "0.75rem" }}>
          {t("page.security.save_policy", "保存策略")}
        </button>
      </form>

      <form className="panel" onSubmit={(e) => invite(e).catch(() => setMsg(t("page.security.invite_fail", "邀请失败")))}>
        <h2>{t("page.security.invite_title", "邀请用户")}</h2>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
          <label>
            {t("page.users.full_name", "姓名")}
            <input value={inviteName} onChange={(e) => setInviteName(e.target.value)} />
          </label>
          <label>
            {t("common.email", "邮箱")}
            <input type="email" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} required />
          </label>
          <button className="btn btn-primary" type="submit">
            {t("page.security.send_invite", "发送邀请")}
          </button>
        </div>
        <p className="muted">{t("page.security.invite_hint", "优先用邀请代替临时密码。接受邀请会标记邮箱已验证。")}</p>
      </form>

      <div className="ship-layout">
        <div className="panel">
          <h2>{t("page.security.pending", "待处理邀请")}</h2>
          <ul className="compact-list">
            {invites.map((i, idx) => (
              <li key={idx}>
                {i.email} · {t("page.security.expires", "过期")} {i.expires_at}
              </li>
            ))}
            {!invites.length ? <li className="muted">{t("common.none", "无")}</li> : null}
          </ul>
        </div>
        <div className="panel">
          <h2>{t("page.security.mail_log", "租户邮件日志")}</h2>
          <ul className="compact-list">
            {logs.slice(0, 8).map((l) => (
              <li key={l.id}>
                [{l.purpose}] {l.to_email}
              </li>
            ))}
            {!logs.length ? <li className="muted">{t("common.none", "无")}</li> : null}
          </ul>
        </div>
      </div>
    </AppShell>
  );
}
