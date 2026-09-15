"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiDelete, apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function AccountSecurityPage() {
  const { t } = useI18n();
  const [sec, setSec] = useState<any>(null);
  const [msg, setMsg] = useState("");
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [demoToken, setDemoToken] = useState("");

  async function load() {
    setSec(await apiGet("/api/v1/me/security"));
  }

  useEffect(() => {
    load().catch(() => setMsg(t("page.account.signin_required", "Sign in required")));
  }, [t]);

  async function requestVerify() {
    const data = await apiPost("/api/v1/auth/email/verify/request", {});
    setDemoToken(data.demo_token || "");
    setMsg(t("page.account.verify_queued", "Verification email queued (console channel)."));
  }

  async function confirmVerify(e: FormEvent) {
    e.preventDefault();
    await apiPost("/api/v1/auth/email/verify/confirm", { token: demoToken });
    setMsg(t("page.account.email_verified", "Email verified."));
    await load();
  }

  async function changePassword(e: FormEvent) {
    e.preventDefault();
    await apiPost("/api/v1/me/security/password", { current_password: cur || null, new_password: next });
    setMsg(t("page.account.pw_updated", "Password updated."));
    setCur("");
    setNext("");
    await load();
  }

  async function unlink(provider: string) {
    await apiDelete(`/api/v1/me/identities/${provider}`);
    setMsg(t("page.account.unlinked", "Unlinked {provider}", { provider }));
    await load();
  }

  if (!sec) {
    return (
      <AppShell>
        <p>{msg || t("common.loading", "Loading…")}</p>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("page.account.title", "My account security")}</h1>
      <p className="page-sub">{t("page.account.sub", "Verify email, manage password, and linked Microsoft / Google identities.")}</p>
      {msg ? <p className="flash">{msg}</p> : null}

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
            <button type="button" className="btn btn-primary" onClick={() => requestVerify().catch(() => setMsg(t("common.failed", "Failed")))}>
              {t("page.account.send_verify", "Send verification email")}
            </button>
            {demoToken ? (
              <form onSubmit={(e) => confirmVerify(e).catch(() => setMsg(t("page.account.confirm_fail", "Confirm failed")))} style={{ display: "flex", gap: "0.5rem" }}>
                <input value={demoToken} onChange={(e) => setDemoToken(e.target.value)} />
                <button className="btn btn-ghost" type="submit">
                  {t("page.account.confirm_token", "Confirm token")}
                </button>
              </form>
            ) : null}
          </div>
        ) : null}
      </div>

      <form className="panel" onSubmit={(e) => changePassword(e).catch(() => setMsg(t("page.account.pw_fail", "Password change failed")))}>
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
                className="btn btn-ghost"
                style={{ marginLeft: "0.75rem" }}
                onClick={() => unlink(i.provider).catch(() => setMsg(t("page.account.unlink_fail", "Unlink failed")))}
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
    </AppShell>
  );
}
