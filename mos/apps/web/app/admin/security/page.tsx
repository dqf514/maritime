"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { RefreshButton } from "@/components/RefreshButton";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { RowActions } from "@/components/RowActions";
import { API_BASE as API, apiDelete, apiGet, apiPatch, apiPost, apiPut } from "@/lib/api";
import { msgOf, handled } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { formatInTz, parseUtc } from "@/lib/datetime";
import { StateView } from "@/components/StateView";
import { useToast } from "@/components/ToastProvider";

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

type SsoRow = { provider: string; mode: string; status: string };

type InviteRow = {
  id: string;
  email: string;
  expires_at: string;
  created_at: string | null;
  full_name: string;
  role_codes: string[];
};

export default function TenantSecurityPage() {
  const { t, locale } = useI18n();
  const toast = useToast();
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [domains, setDomains] = useState("");
  const [msHint, setMsHint] = useState("");
  const [googleHd, setGoogleHd] = useState("");
  const [ssoNotes, setSsoNotes] = useState("");
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteSaving, setInviteSaving] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteName, setInviteName] = useState("");
  const [invites, setInvites] = useState<InviteRow[]>([]);
  const [logs, setLogs] = useState<any[]>([]);
  const [demoToken, setDemoToken] = useState("");
  // 邀请列表加载失败必须走错误态，不能静默显示「无」（P1-4）
  const [invitesLoading, setInvitesLoading] = useState(true);
  const [invitesErr, setInvitesErr] = useState("");

  const load = useCallback(async () => {
    const p = await apiGet("/api/v1/admin/security/policy");
    setPolicy(p);
    setDomains((p.allowed_domains || []).join(", "));
    setMsHint(p.microsoft_tenant_hint || "");
    setGoogleHd(p.google_hosted_domain || "");
    setSsoNotes(p.sso_notes || "");
    setInvitesLoading(true);
    setInvitesErr("");
    try {
      setInvites(
        ((await apiGet("/api/v1/admin/security/invites")) as any[]).map((i) => ({
          id: String(i.id),
          email: String(i.email || ""),
          expires_at: String(i.expires_at || ""),
          created_at: i.created_at ?? null,
          full_name: String(i.payload?.full_name || ""),
          role_codes: Array.isArray(i.payload?.role_codes) ? i.payload.role_codes : [],
        })),
      );
    } catch (e) {
      setInvites([]);
      setInvitesErr(msgOf(e, t("common.failed", "Failed")));
    } finally {
      setInvitesLoading(false);
    }
    setLogs(await apiGet("/api/v1/admin/security/mail-logs"));
  }, [t]);

  useEffect(() => {
    load().catch(() => toast.error(t("page.security.admin_required", "需要租户管理员")));
  }, [t]);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!policy) return;
    await apiPut("/api/v1/admin/security/policy", {
      ...policy,
      allowed_domains: domains
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      microsoft_tenant_hint: msHint.trim() || null,
      google_hosted_domain: googleHd.trim() || null,
      sso_notes: ssoNotes.trim() || null,
    });
    toast.success(t("page.security.updated", "登录与安全策略已更新"));
    await load();
  }

  async function invite() {
    setInviteSaving(true);
    try {
      const data = await apiPost("/api/v1/admin/security/invites", {
        email: inviteEmail,
        full_name: inviteName,
        role_codes: ["viewer"],
      });
      setDemoToken(data.demo_token || "");
      toast.success(t("page.security.invite_sent", "已向 {email} 发送邀请（控制台邮件通道）", { email: inviteEmail }));
      setInviteEmail("");
      setInviteName("");
      setInviteOpen(false);
      await load();
    } catch {
      toast.error(t("page.security.invite_fail", "邀请失败"));
    } finally {
      setInviteSaving(false);
    }
  }

  function openInvite() {
    setInviteOpen(true);
  }

  // 行内编辑邀请：值未变化不发请求，避免 blur→reload 打断输入
  async function onInviteCellSave(rowId: string, colKey: string, value: unknown, row: InviteRow) {
    let payload: Record<string, unknown>;
    if (colKey === "expires_at") {
      const prevT = row.expires_at ? parseUtc(row.expires_at)?.getTime() ?? null : null;
      const nextIso = value ? parseUtc(String(value))?.toISOString() ?? null : null;
      const nextT = nextIso ? new Date(nextIso).getTime() : null;
      if (prevT === nextT) return;
      payload = { expires_at: nextIso };
    } else if (colKey === "full_name") {
      const next = value == null ? "" : String(value);
      if ((row.full_name || "") === next) return;
      payload = { full_name: next };
    } else {
      return;
    }
    try {
      await apiPatch(`/api/v1/admin/security/invites/${rowId}`, payload);
      toast.success(t("common.saved", "Saved"));
      await load();
    } catch (ex: any) {
      const msg =
        ex?.code === "INVITE_ACCEPTED"
          ? t("page.security.invite_already_accepted", "This invite was already accepted")
          : ex?.message || t("common.failed", "Failed");
      toast.error(msg);
      await load();
    }
  }

  const deleteInvite = useCallback(
    async (row: InviteRow) => {
      try {
        await apiDelete(`/api/v1/admin/security/invites/${row.id}`);
        toast.success(t("common.deleted", "Deleted"));
        await load();
      } catch (ex: any) {
        toast.error(ex?.message || t("common.failed", "Failed"));
      }
    },
    [t, toast, load],
  );

  const inviteColumns = useMemo<ColumnDef<InviteRow>[]>(
    () => [
      {
        key: "email",
        title: t("common.email", "Email"),
        minWidth: 180,
        value: (r) => r.email,
      },
      {
        key: "full_name",
        title: t("page.users.full_name", "Name"),
        minWidth: 130,
        value: (r) => r.full_name || "",
        render: (v) => (v ? String(v) : "—"),
        editor: { type: "text" },
      },
      {
        key: "expires_at",
        title: t("page.security.expires", "Expires"),
        width: 170,
        value: (r) => r.expires_at || "",
        render: (v) => (v ? formatInTz(v as string | null, null, undefined, locale) : "—"),
        editor: { type: "datetime" },
      },
      {
        key: "_actions",
        title: "",
        width: 30,
        align: "center",
        render: (_v, r) => <RowActions onDelete={() => deleteInvite(r)} label={r.email} />,
      },
    ],
    [t, locale, deleteInvite],
  );

  const ssoColumns = useMemo<ColumnDef<SsoRow>[]>(() => [
    { key: "provider", title: t("common.provider", "提供商"), width: 200, value: (r) => r.provider },
    {
      key: "mode",
      title: t("common.mode", "模式"),
      width: 110,
      value: (r) => r.mode,
      render: (v) => <code>{String(v)}</code>,
    },
    { key: "status", title: t("common.status", "状态"), minWidth: 220, value: (r) => r.status },
  ], [t]);

  useListHotkeys(openInvite);

  if (!policy) {
    return (
      <AppShell>
        <p>{t("common.loading", "加载中…")}</p>
      </AppShell>
    );
  }

  const rt = policy.runtime || {};
  const msMode = rt.microsoft?.mode || "unknown";
  const googMode = rt.google?.mode || "unknown";

  function ssoStatus(mode: string, stubText: string): string {
    return mode === "live"
      ? t("page.security.sso_live", "已配置应用密钥，走真实 OAuth")
      : mode === "stub"
        ? stubText
        : t("page.security.sso_off", "已禁用");
  }

  const ssoRows: SsoRow[] = [
    {
      provider: "Microsoft 365 / Entra",
      mode: msMode,
      status: ssoStatus(
        msMode,
        t("page.security.sso_stub", "未配置密钥，演示 stub（平台可设 OAUTH_ALLOW_STUB=false 关闭）"),
      ),
    },
    {
      provider: "Google",
      mode: googMode,
      status: ssoStatus(googMode, t("page.security.sso_stub", "未配置密钥，演示 stub")),
    },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.admin", "Administration") }]}
        title={t("page.security.title", "登录与安全")}
        subtitle={t(
          "page.security.sub",
          "选择平台已批准的登录方式，强制邮箱验证 / 仅邀请，并限制企业邮箱域名。SSO 密钥由平台运维配置。",
        )}
      />
      <Toolbar>
        <button type="button" className="btn btn-primary" onClick={openInvite}>
          {t("page.security.invite_title", "邀请用户")}
        </button>
        <RefreshButton label={t("common.refresh", "Refresh")} className="btn btn-sm" onClick={() => load().catch(handled)} />
      </Toolbar>
      {demoToken ? (
        <p className="muted">
          {t("page.security.demo_token", "演示邀请令牌:")} <code>{demoToken}</code> —{" "}
          <a href={`/login/accept-invite?token=${demoToken}`}>/login/accept-invite</a>
        </p>
      ) : null}

      <div className="panel">
        <h2>{t("page.security.sso_status", "SSO 运行状态")}</h2>
        <DataGrid<SsoRow>
          columns={ssoColumns}
          data={ssoRows}
          rowKey={(r) => r.provider}
          storageKey="admin_security_sso_grid"
          emptyText={t("common.none", "无")}
          showFooter={false}
        />
        <p className="muted" style={{ fontSize: "0.85rem", marginBottom: 0 }}>
          {t("page.security.redirect_hint", "回调地址需在 IdP 登记:")}{" "}
          <code>{(rt.api_public_base || API).replace(/\/$/, "")}/api/v1/auth/oauth/microsoft/callback</code>
          {" · "}
          <code>{(rt.api_public_base || API).replace(/\/$/, "")}/api/v1/auth/oauth/google/callback</code>
        </p>
      </div>

      <form className="panel" onSubmit={(e) => save(e).catch(() => toast.error(t("page.security.save_fail", "保存失败")))}>
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

      <div className="ship-layout">
        <div className="panel">
          <h2>{t("page.security.pending", "待处理邀请")}</h2>
          <StateView
            loading={invitesLoading}
            error={invitesErr || undefined}
            empty={!invitesErr && !invites.length}
            emptyText={t("common.none", "无")}
            onRetry={() => void load()}
          >
            <DataGrid<InviteRow>
              columns={inviteColumns}
              data={invites}
              rowKey={(r) => r.id}
              storageKey="admin_security_invites_grid"
              emptyText={t("common.none", "无")}
              showFooter={false}
              editable
              onCellSave={onInviteCellSave}
            />
          </StateView>
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
            {/* 截断必须对用户可见（P1-28） */}
            {logs.length > 8 ? (
              <li className="muted">
                {t("page.security.mail_log_more", "Showing the 8 most recent of {n} entries.", { n: logs.length })}
              </li>
            ) : null}
          </ul>
        </div>
      </div>

      <RecordModal
        open={inviteOpen}
        title={t("page.security.invite_title", "邀请用户")}
        onClose={() => setInviteOpen(false)}
        onSave={() => invite()}
        canDelete={false}
        saving={inviteSaving}
      >
        <label>
          {t("page.users.full_name", "姓名")}
          <input value={inviteName} onChange={(e) => setInviteName(e.target.value)} />
        </label>
        <label>
          {t("common.email", "邮箱")}
          <input type="email" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} required />
        </label>
        <p className="muted">{t("page.security.invite_hint", "优先用邀请代替临时密码。接受邀请会标记邮箱已验证。")}</p>
      </RecordModal>
    </AppShell>
  );
}
