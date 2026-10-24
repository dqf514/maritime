"use client";

import { RefreshButton } from "@/components/RefreshButton";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { Toolbar } from "@/components/Toolbar";
import { StateView } from "@/components/StateView";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { apiDelete, apiGet, apiPost } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

export default function AccountSecurityPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [sec, setSec] = useState<any>(null);
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [demoToken, setDemoToken] = useState("");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  /** 待确认解绑的身份提供方 */
  const [pendingUnlink, setPendingUnlink] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      setSec(await apiGet("/api/v1/me/security"));
    } catch (ex) {
      // 取数失败 ≠ 一直「加载中」
      setErr(msgOf(ex, t("page.account.signin_required", "Sign in required")));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function requestVerify() {
    try {
      const data = await apiPost("/api/v1/auth/email/verify/request", {});
      setDemoToken(data.demo_token || "");
      toast.success(t("page.account.verify_queued", "Verification email queued (console channel)."));
    } catch (ex) {
      toast.error(msgOf(ex, t("common.failed", "Failed")));
    }
  }

  async function confirmVerify(e: FormEvent) {
    e.preventDefault();
    try {
      await apiPost("/api/v1/auth/email/verify/confirm", { token: demoToken });
      toast.success(t("page.account.email_verified", "Email verified."));
      await load();
    } catch (ex) {
      toast.error(msgOf(ex, t("page.account.confirm_fail", "Confirm failed")));
    }
  }

  async function changePassword(e: FormEvent) {
    e.preventDefault();
    try {
      await apiPost("/api/v1/me/security/password", { current_password: cur || null, new_password: next });
      toast.success(t("page.account.pw_updated", "Password updated."));
      setCur("");
      setNext("");
      await load();
    } catch (ex) {
      toast.error(msgOf(ex, t("page.account.pw_fail", "Password change failed")));
    }
  }

  async function unlink(provider: string) {
    try {
      await apiDelete(`/api/v1/me/identities/${provider}`);
      toast.success(t("page.account.unlinked", "Unlinked {provider}", { provider }));
      await load();
    } catch (ex) {
      toast.error(msgOf(ex, t("page.account.unlink_fail", "Unlink failed")));
    }
  }

  if (loading) {
    return (
      <AppShell>
        <StateView loading error="" empty={false} emptyText="" onRetry={() => void load()}>
          <span />
        </StateView>
      </AppShell>
    );
  }

  if (err || !sec) {
    return (
      <AppShell>
        <StateView
          loading={false}
          error={err || t("page.account.signin_required", "Sign in required")}
          empty={false}
          emptyText=""
          onRetry={() => void load()}
        >
          <span />
        </StateView>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.account_sec", "My security") }]}
        title={t("page.account.title", "My account security")}
        subtitle={t("page.account.sub", "Verify email, manage password, and linked Microsoft / Google identities.")}
      />
      <Toolbar>
        <RefreshButton label={t("common.refresh", "Refresh")} className="btn btn-sm" onClick={() => void load()} />
      </Toolbar>

      <div className="panel">
        <h2>{t("page.account.email", "Email")}</h2>
        <p>
          {sec.email}{" "}
          {sec.email_verified ? (
            <span className="pill valid">{t("page.account.verified", "verified")}</span>
          ) : (
            <span className="pill expiring">{t("page.account.unverified", "unverified")}</span>
          )}
        </p>
        {!sec.email_verified ? (
          <div className="quick-row">
            <button type="button" className="btn btn-primary" onClick={() => void requestVerify()}>
              {t("page.account.send_verify", "Send verification email")}
            </button>
            {demoToken ? (
              <form onSubmit={(e) => void confirmVerify(e)} className="acct-inline-form">
                <input value={demoToken} onChange={(e) => setDemoToken(e.target.value)} />
                <button className="btn btn-ghost" type="submit">
                  {t("page.account.confirm_token", "Confirm token")}
                </button>
              </form>
            ) : null}
          </div>
        ) : null}
      </div>

      <form className="panel" onSubmit={(e) => void changePassword(e)}>
        <h2>{t("page.account.password", "Password")}</h2>
        {sec.has_password ? (
          <label>
            {t("page.account.current_pw", "Current password")}
            <input type="password" value={cur} onChange={(e) => setCur(e.target.value)} />
          </label>
        ) : (
          <p className="muted">{t("page.account.no_pw", "No password yet (SSO-only). Set one to unlock account recovery.")}</p>
        )}
        <label>
          {t("page.account.new_pw", "New password")}
          <input type="password" value={next} onChange={(e) => setNext(e.target.value)} minLength={8} required />
        </label>
        <button className="btn btn-primary" type="submit">
          {t("page.account.update_pw", "Update password")}
        </button>
      </form>

      <div className="panel">
        <h2>{t("page.account.linked", "Linked identities")}</h2>
        <ul className="compact-list">
          {(sec.identities || []).map((i: any) => (
            <li key={i.provider}>
              <strong>{i.provider}</strong> · {i.email || "—"}
              <button
                type="button"
                className="btn btn-ghost acct-unlink-btn"
                onClick={() => setPendingUnlink(i.provider)}
              >
                {t("page.account.unlink", "Unlink")}
              </button>
            </li>
          ))}
          {!(sec.identities || []).length ? (
            <li className="muted">{t("page.account.no_linked", "No Microsoft / Google account linked yet. Use login OAuth buttons.")}</li>
          ) : null}
        </ul>
      </div>

      <ConfirmDialog
        open={pendingUnlink !== null}
        title={t("page.account.unlink_title", "Unlink identity")}
        message={t("page.account.unlink_confirm", "Unlink the {provider} identity from your account? You will sign in with your password instead.", { provider: pendingUnlink ?? "" })}
        confirmLabel={t("page.account.unlink", "Unlink")}
        danger
        onConfirm={() => {
          const provider = pendingUnlink;
          setPendingUnlink(null);
          if (provider) void unlink(provider);
        }}
        onCancel={() => setPendingUnlink(null)}
      />
    </AppShell>
  );
}
