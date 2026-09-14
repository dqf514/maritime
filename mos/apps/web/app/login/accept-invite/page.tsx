"use client";

import { FormEvent, Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useI18n } from "@/lib/i18n";

import { API_BASE as API } from "@/lib/api";

function AcceptInvitePage() {
  const sp = useSearchParams();
  const router = useRouter();
  const { t } = useI18n();
  const [token, setToken] = useState(sp.get("token") || "");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    const res = await fetch(`${API}/api/v1/auth/invites/accept`, {
      method: "POST",
      credentials: "include", // required so the Set-Cookie session is stored
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, password, full_name: fullName || null }),
    });
    await res.json().catch(() => ({}));
    if (!res.ok) {
      setError(t("login.invite_invalid", "Invalid or expired invite"));
      return;
    }
    // Cookie session planted by the server — just navigate.
    router.replace("/home");
  }

  return (
    <div className="login-stage">
      <div className="login-stage-bg" aria-hidden />
      <form className="login-card" style={{ maxWidth: 440, margin: "4rem auto", position: "relative", zIndex: 1 }} onSubmit={submit}>
        <h1 style={{ marginTop: 0 }}>{t("login.invite_title", "Accept invite")}</h1>
        <p className="muted">{t("login.invite_help", "Set your password — email is marked verified on accept.")}</p>
        {error ? <div className="error">{error}</div> : null}
        <label>
          {t("login.invite_token", "Invite token")}
          <input value={token} onChange={(e) => setToken(e.target.value)} required />
        </label>
        <label>
          {t("login.invite_name", "Full name")}
          <input value={fullName} onChange={(e) => setFullName(e.target.value)} />
        </label>
        <label>
          {t("login.invite_password", "Password")}
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} required />
        </label>
        <button className="btn btn-primary" type="submit" style={{ width: "100%" }}>
          {t("login.invite_activate", "Activate account")}
        </button>
        <p className="login-foot-link">
          <Link href="/login">{t("login.invite_signin", "← Sign in")}</Link>
        </p>
      </form>
    </div>
  );
}

export default function AcceptInvitePageWrapper() {
  return (
    <Suspense>
      <AcceptInvitePage />
    </Suspense>
  );
}
