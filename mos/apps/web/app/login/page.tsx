"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { LanguageSwitcher, useI18n } from "@/lib/i18n";
import { apiLogin } from "@/lib/api";

import { API_BASE } from "@/lib/api";

const PRESETS = [
  { labelKey: "login.preset.platform", hintKey: "login.preset.platform_h", label: "Platform operator", hint: "Tenants, plans, branding, identity", tenant: "sys", email: "ops@voyageos.platform" },
  { labelKey: "login.preset.admin", hintKey: "login.preset.admin_h", label: "Tenant admin", hint: "Security policy & invites", tenant: "demo", email: "admin@demo.voyageos" },
  { labelKey: "login.preset.mgmt", hintKey: "login.preset.mgmt_h", label: "Executive / director", hint: "Command wall / TCE", tenant: "demo", email: "mgmt@demo.voyageos" },
  { labelKey: "login.preset.charter", hintKey: "login.preset.charter_h", label: "Chartering lead", hint: "Pipeline wall / CP", tenant: "demo", email: "charterer@demo.voyageos" },
  { labelKey: "login.preset.ops", hintKey: "login.preset.ops_h", label: "Operations", hint: "Situation room / Twin", tenant: "demo", email: "ops@demo.voyageos" },
  { labelKey: "login.preset.tech", hintKey: "login.preset.tech_h", label: "Technical / superintendent", hint: "Ship mgmt / PMS", tenant: "demo", email: "tech@demo.voyageos" },
  { labelKey: "login.preset.fin", hintKey: "login.preset.fin_h", label: "Finance", hint: "Cash wall / AR", tenant: "demo", email: "finance@demo.voyageos" },
  { labelKey: "login.preset.dem", hintKey: "login.preset.dem_h", label: "Demurrage", hint: "Laytime / claims wall", tenant: "demo", email: "demurrage@demo.voyageos" },
];

type Branding = {
  product_name: string;
  tagline: string;
  logo_url: string;
  icon_url: string;
  primary_color: string;
};

type AuthMethods = {
  password: boolean;
  microsoft: boolean;
  google: boolean;
  magic_link: boolean;
  require_email_verify: boolean;
  invite_only: boolean;
  provider_modes: { microsoft: string; google: string };
};

function MsIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 21 21" aria-hidden>
      <rect x="1" y="1" width="9" height="9" fill="#f25022" />
      <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
      <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
      <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
    </svg>
  );
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden>
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.3 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.1 8 3l5.7-5.7C34.2 6.1 29.4 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.5-.4-3.5z" />
      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 16.1 19 13 24 13c3.1 0 5.8 1.1 8 3l5.7-5.7C34.2 6.1 29.4 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.1 35.3 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-1.1 3.1-3.5 5.5-6.5 6.6l.1.1 6.2 5.2C36.9 41.1 44 36 44 24c0-1.3-.1-2.5-.4-3.5z" />
    </svg>
  );
}

export default function LoginPage() {
  const router = useRouter();
  const { t } = useI18n();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tenant, setTenant] = useState("demo");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [brand, setBrand] = useState<Branding | null>(null);
  const [methods, setMethods] = useState<AuthMethods | null>(null);
  const [magicSent, setMagicSent] = useState("");

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/public/branding`)
      .then((r) => r.json())
      .then(setBrand)
      .catch(() =>
        setBrand({
          product_name: "VoyageOS",
          tagline: "Maritime commercial operating system",
          logo_url: "/branding/logo.svg",
          icon_url: "/branding/mark.svg",
          primary_color: "#1A9B96",
        }),
      );
  }, []);

  useEffect(() => {
    const code = tenant.trim() || "demo";
    fetch(`${API_BASE}/api/v1/auth/methods?tenant_code=${encodeURIComponent(code)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setMethods)
      .catch(() => setMethods(null));
  }, [tenant]);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError("");
    const fd = new FormData(e.currentTarget);
    const tenantVal = String(fd.get("tenant") || tenant).trim();
    const emailVal = String(fd.get("email") || email).trim();
    const passwordVal = String(fd.get("password") || password);
    setTenant(tenantVal);
    setEmail(emailVal);
    setPassword(passwordVal);
    try {
      // Session cookie is planted by the server (HttpOnly) — no localStorage.
      await apiLogin(emailVal, passwordVal, tenantVal);
      router.replace(tenantVal === "sys" ? "/platform" : "/home");
    } catch (err: any) {
      const detail = err?.detail || err?.message;
      if (String(detail).includes("EMAIL_NOT_VERIFIED") || err?.code === "EMAIL_NOT_VERIFIED") {
        setError(t("login.error_unverified", "Email not verified. Check your inbox or ask tenant admin to resend."));
      } else if (String(err?.message || "").includes("Failed to fetch") || err?.name === "TypeError") {
        setError(t("login.error_network", "Cannot reach API — check that the backend is running."));
      } else {
        setError(
          typeof detail === "object" && detail?.message
            ? String(detail.message)
            : t("login.error_generic", "Sign-in failed. Check tenant / credentials (or verification / method policy)."),
        );
      }
    } finally {
      setLoading(false);
    }
  }

  async function startOAuth(provider: "microsoft" | "google") {
    setError("");
    const res = await fetch(`${API_BASE}/api/v1/auth/oauth/${provider}/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant_code: tenant || "demo", provider, intent: "login" }),
    });
    if (!res.ok) {
      setError(t("login.error_oauth", "{provider} sign-in unavailable for this tenant", { provider }));
      return;
    }
    const data = await res.json();
    if (data.authorize_url) window.location.href = data.authorize_url;
    else setError(t("login.error_oauth_cfg", "OAuth not configured"));
  }

  async function sendMagic() {
    setError("");
    const res = await fetch(`${API_BASE}/api/v1/auth/magic-link/request`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, tenant_code: tenant || "demo" }),
    });
    if (!res.ok) {
      setError(t("login.error_magic", "Magic link disabled or domain not allowed"));
      return;
    }
    setMagicSent("sent");
  }

  function applyPreset(p: (typeof PRESETS)[0]) {
    setTenant(p.tenant);
    setEmail(p.email);
  }

  const accent = brand?.primary_color || "#1A9B96";
  const name = brand?.product_name || "VoyageOS";
  const showSso = Boolean(methods?.microsoft || methods?.google);
  const showPassword = methods?.password !== false;

  return (
    <div className="login-stage login-stage-clean" style={{ ["--portal-accent" as string]: accent }}>
      <div className="login-stage-bg" aria-hidden />
      <header className="login-top">
        <Link href="/" className="login-top-brand">
          <img src={brand?.icon_url || "/branding/mark.svg"} alt="" width={24} height={24} />
          <strong>{name}</strong>
        </Link>
        <LanguageSwitcher />
      </header>

      <main className="login-center">
        <form className="login-card login-card-solo" onSubmit={onSubmit}>
          <div className="login-card-head">
            <h1>{t("login.welcome", "Welcome back")}</h1>
            <p>{t("login.hint_quiet", "Sign in to your organisation workspace.")}</p>
          </div>

          {error ? <div className="error">{error}</div> : null}

          <label htmlFor="tenant">{t("login.tenant", "Tenant code")}</label>
          <input
            id="tenant"
            name="tenant"
            value={tenant}
            onChange={(e) => setTenant(e.target.value)}
            autoComplete="organization"
            placeholder={t("login.tenant_ph", "Your company code")}
          />

          {showSso ? (
            <div className="oauth-stack">
              {methods?.microsoft ? (
                <button type="button" className="btn oauth-btn oauth-btn-full ms" onClick={() => startOAuth("microsoft")}>
                  <MsIcon />
                  <span>{t("login.microsoft_full", "Continue with Microsoft")}</span>
                </button>
              ) : null}
              {methods?.google ? (
                <button type="button" className="btn oauth-btn oauth-btn-full goog" onClick={() => startOAuth("google")}>
                  <GoogleIcon />
                  <span>{t("login.google_full", "Continue with Google")}</span>
                </button>
              ) : null}
            </div>
          ) : null}

          {showSso && showPassword ? (
            <div className="login-divider" role="separator">
              <span>{t("login.or_email", "or continue with email")}</span>
            </div>
          ) : null}

          {showPassword ? (
            <>
              <label htmlFor="email">{t("login.email", "Email")}</label>
              <input
                id="email"
                name="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="username"
                required
              />
              <label htmlFor="password">{t("login.password", "Password")}</label>
              <input
                id="password"
                name="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
              <button className="btn btn-primary login-submit" disabled={loading} type="submit">
                {loading ? "…" : t("login.sign_in", "Sign in")}
              </button>
            </>
          ) : (
            <p className="muted">{t("login.password_disabled", "Password login disabled — use Microsoft / Google.")}</p>
          )}

          <div className="login-alt-row">
            {methods?.magic_link ? (
              <button type="button" className="login-text-btn" onClick={() => sendMagic()}>
                {t("login.magic", "Email me a magic link")}
              </button>
            ) : null}
            <Link href="/login/verify-email">{t("login.verify_link", "Verify email")}</Link>
            <Link href="/login/accept-invite">{t("login.invite_link", "Accept invite")}</Link>
          </div>
          {magicSent ? (
            <p className="muted login-magic-note">
              {t("login.magic_queued", "Magic link sent — check your inbox to complete sign-in.")}
            </p>
          ) : null}
        </form>

        <details className="login-demo-details">
          <summary>{t("login.demo_toggle", "Demo access")}</summary>
          <div className="preset-grid preset-grid-compact">
            {PRESETS.map((p) => (
              <button key={p.email + p.labelKey} type="button" className="preset-card" onClick={() => applyPreset(p)}>
                <strong>{t(p.labelKey, p.label)}</strong>
                <small>{p.email}</small>
              </button>
            ))}
          </div>
        </details>
      </main>
    </div>
  );
}
