"use client";

import { FormEvent, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useI18n } from "@/lib/i18n";

const API = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export default function AcceptInvitePage() {
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
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, password, full_name: fullName || null }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setError(t("login.invite_invalid", "Invalid or expired invite"));
      return;
    }
    localStorage.setItem("voyageos_token", data.access_token);
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
