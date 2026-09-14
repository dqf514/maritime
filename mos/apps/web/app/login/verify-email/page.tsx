"use client";

import { FormEvent, Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { useI18n } from "@/lib/i18n";

import { API_BASE as API } from "@/lib/api";

function VerifyEmailPage() {
  const sp = useSearchParams();
  const { t } = useI18n();
  const [token, setToken] = useState(sp.get("token") || "");
  const [email, setEmail] = useState("");
  const [tenant, setTenant] = useState("demo");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  async function request(e: FormEvent) {
    e.preventDefault();
    const res = await fetch(`${API}/api/v1/auth/email/verify/request`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, tenant_code: tenant }),
    });
    const data = await res.json().catch(() => ({}));
    if (data.demo_token) setToken(data.demo_token);
    setMsg(t("login.verify_sent", "If the account exists, a verification email was sent (console channel in demo)."));
  }

  async function confirm(e: FormEvent) {
    e.preventDefault();
    const res = await fetch(`${API}/api/v1/auth/email/verify/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    if (!res.ok) {
      setError(t("login.verify_bad", "Invalid or expired token"));
      return;
    }
    setMsg(t("login.verify_ok", "Email verified — you can sign in."));
    setError("");
  }

  return (
    <div className="login-stage">
      <div className="login-stage-bg" aria-hidden />
      <div className="login-card" style={{ maxWidth: 460, margin: "4rem auto", position: "relative", zIndex: 1 }}>
        <h1 style={{ marginTop: 0 }}>{t("login.verify_title", "Verify email")}</h1>
        {msg ? <p className="flash">{msg}</p> : null}
        {error ? <div className="error">{error}</div> : null}
        <form onSubmit={request}>
          <label>
            {t("login.tenant", "Tenant code")}
            <input value={tenant} onChange={(e) => setTenant(e.target.value)} />
          </label>
          <label>
            {t("login.email", "Email")}
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
          <button className="btn btn-ghost" type="submit">
            {t("login.verify_request", "Request verification")}
          </button>
        </form>
        <hr style={{ borderColor: "rgba(255,255,255,0.1)", margin: "1rem 0" }} />
        <form onSubmit={confirm}>
          <label>
            {t("login.verify_token", "Verification token")}
            <input value={token} onChange={(e) => setToken(e.target.value)} required />
          </label>
          <button className="btn btn-primary" type="submit" style={{ width: "100%" }}>
            {t("login.verify_confirm", "Confirm")}
          </button>
        </form>
        <p className="login-foot-link">
          <Link href="/login">{t("login.invite_signin", "← Sign in")}</Link>
        </p>
      </div>
    </div>
  );
}

export default function VerifyEmailPageWrapper() {
  return (
    <Suspense>
      <VerifyEmailPage />
    </Suspense>
  );
}
