"use client";

import { FormEvent, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useI18n } from "@/lib/i18n";

const API = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export default function OAuthStubPage() {
  const sp = useSearchParams();
  const router = useRouter();
  const { t } = useI18n();
  const state = sp.get("state") || "";
  const provider = sp.get("provider") || "microsoft";
  const [email, setEmail] = useState("admin@demo.voyageos");
  const [name, setName] = useState("SSO Demo User");
  const [error, setError] = useState("");

  const title = useMemo(
    () =>
      provider === "google"
        ? t("login.oauth_stub_title_goog", "Google (stub)")
        : t("login.oauth_stub_title_ms", "Microsoft 365 (stub)"),
    [provider, t],
  );

  async function complete(e: FormEvent) {
    e.preventDefault();
    setError("");
    const res = await fetch(`${API}/api/v1/auth/oauth/stub/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state, email, full_name: name, subject: `stub:${provider}:${email}` }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setError(data?.detail?.message || data?.detail || t("login.oauth_stub_fail", "Stub OAuth failed"));
      return;
    }
    localStorage.setItem("voyageos_token", data.access_token);
    router.replace("/home");
  }

  return (
    <div className="login-stage">
      <div className="login-stage-bg" aria-hidden />
      <form className="login-card" style={{ maxWidth: 440, margin: "4rem auto", position: "relative", zIndex: 1 }} onSubmit={complete}>
        <h1 style={{ marginTop: 0 }}>{title}</h1>
        <p className="muted">
          {t(
            "login.oauth_stub_help",
            "Platform OAuth app secrets are not configured — this stub simulates IdP consent for demos.",
          )}{" "}
          {t("login.oauth_stub_env", "Set MICROSOFT_* / GOOGLE_* env for live mode.")}
        </p>
        {error ? <div className="error">{String(error)}</div> : null}
        <label>
          {t("login.oauth_stub_email", "Email to assert")}
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>
          {t("login.oauth_stub_name", "Display name")}
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <button className="btn btn-primary" type="submit" style={{ width: "100%" }}>
          {t("login.oauth_stub_continue", "Continue as verified identity")}
        </button>
        <p className="login-foot-link">
          <Link href="/login">{t("login.oauth_stub_back", "← Back")}</Link>
        </p>
      </form>
    </div>
  );
}
