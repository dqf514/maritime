"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { LanguageSwitcher, useI18n } from "@/lib/i18n";
import { apiLogin } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

const PRESETS = [
  { labelKey: "login.preset.platform", hintKey: "login.preset.platform_h", label: "Platform operator", hint: "Tenants, plans, branding, identity", tenant: "sys", email: "ops@voyageos.platform", password: "Ops1234!" },
  { labelKey: "login.preset.admin", hintKey: "login.preset.admin_h", label: "Tenant admin", hint: "Security policy & invites", tenant: "demo", email: "admin@demo.voyageos", password: "Demo1234!" },
  { labelKey: "login.preset.mgmt", hintKey: "login.preset.mgmt_h", label: "Executive / director", hint: "Command wall / TCE", tenant: "demo", email: "mgmt@demo.voyageos", password: "Demo1234!" },
  { labelKey: "login.preset.charter", hintKey: "login.preset.charter_h", label: "Chartering lead", hint: "Pipeline wall / CP", tenant: "demo", email: "charterer@demo.voyageos", password: "Demo1234!" },
  { labelKey: "login.preset.ops", hintKey: "login.preset.ops_h", label: "Operations", hint: "Situation room / Twin", tenant: "demo", email: "ops@demo.voyageos", password: "Demo1234!" },
  { labelKey: "login.preset.tech", hintKey: "login.preset.tech_h", label: "Technical / superintendent", hint: "Ship mgmt / PMS", tenant: "demo", email: "tech@demo.voyageos", password: "Demo1234!" },
  { labelKey: "login.preset.fin", hintKey: "login.preset.fin_h", label: "Finance", hint: "Cash wall / AR", tenant: "demo", email: "finance@demo.voyageos", password: "Demo1234!" },
  { labelKey: "login.preset.dem", hintKey: "login.preset.dem_h", label: "Demurrage", hint: "Laytime / claims wall", tenant: "demo", email: "demurrage@demo.voyageos", password: "Demo1234!" },
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

export default function LoginPage() {
  const router = useRouter();
  const { t } = useI18n();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tenant, setTenant] = useState("");
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
      const data = await apiLogin(emailVal, passwordVal, tenantVal);
      localStorage.setItem("voyageos_token", data.access_token);
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
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setError(t("login.error_magic", "Magic link disabled or domain not allowed"));
      return;
    }
    setMagicSent(data.demo_token || "sent");
  }

  function applyPreset(p: (typeof PRESETS)[0]) {
    setTenant(p.tenant);
    setEmail(p.email);
    setPassword(p.password);
  }

  const accent = brand?.primary_color || "#1A9B96";
  const name = brand?.product_name || "VoyageOS";

  return (
    <div className="login-stage login-stage-clean" style={{ ["--portal-accent" as string]: accent }}>
      <div className="login-stage-bg" aria-hidden />
      <header className="login-top">
        <Link href="/" className="login-top-brand">
          <img src={brand?.icon_url || "/branding/mark.svg"} alt="" width={28} height={28} />
          <strong>{name}</strong>
        </Link>
        <div className="login-top-actions">
          <LanguageSwitcher />
        </div>
      </header>

      <div className="login-center">
        <form className="login-card login-card-solo" onSubmit={onSubmit}>
          <div className="login-card-head">
            <h1>{t("login.welcome", "Welcome back")}</h1>
            <p>{t("login.hint_quiet", "Sign in with your organisation credentials.")}</p>
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

          {(methods?.microsoft || methods?.google) && (
            <div className="oauth-row">
              {methods.microsoft ? (
                <button type="button" className="btn oauth-btn ms" onClick={() => startOAuth("microsoft")}>
                  {t("login.microsoft", "Microsoft 365")}
                </button>
              ) : null}
              {methods.google ? (
                <button type="button" className="btn oauth-btn goog" onClick={() => startOAuth("google")}>
                  {t("login.google", "Google")}
                </button>
              ) : null}
            </div>
          )}

          {methods?.password !== false ? (
            <>
              <label htmlFor="email">{t("login.email", "Email")}</label>
              <input
                id="email"
                name="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="username"
              />
              <label htmlFor="password">{t("login.password", "Password")}</label>
              <input
                id="password"
                name="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
              />
              <button className="btn btn-primary" style={{ width: "100%", marginTop: "0.75rem" }} disabled={loading} type="submit">
                {loading ? "…" : t("login.sign_in", "Sign in")}
              </button>
            </>
          ) : (
            <p className="muted">{t("login.password_disabled", "Password login disabled for this tenant — use Microsoft / Google.")}</p>
          )}

          {methods?.magic_link ? (
            <button type="button" className="btn btn-ghost" style={{ width: "100%", marginTop: "0.5rem" }} onClick={() => sendMagic()}>
              {t("login.magic", "Email me a magic link")}
            </button>
          ) : null}
          {magicSent ? (
            <p className="muted">
              {t("login.magic_queued", "Magic link queued. Demo token:")}{" "}
              <Link href={`/login/magic?token=${magicSent}`}>{magicSent.slice(0, 12)}…</Link>
            </p>
          ) : null}

          <p className="login-foot-link">
            <Link href="/">{t("login.back_portal", "← Back")}</Link>
            <span aria-hidden> · </span>
            <Link href="/login/verify-email">{t("login.verify_link", "Verify email")}</Link>
            <span aria-hidden> · </span>
            <Link href="/login/accept-invite">{t("login.invite_link", "Accept invite")}</Link>
          </p>
        </form>

        <details className="login-demo-details">
          <summary>{t("login.demo_toggle", "Demo access (internal)")}</summary>
          <p className="muted">{t("login.demo_sub_quiet", "For evaluation environments only.")}</p>
          <div className="preset-grid preset-grid-compact">
            {PRESETS.map((p) => (
              <button key={p.email + p.labelKey} type="button" className="preset-card" onClick={() => applyPreset(p)}>
                <strong>{t(p.labelKey, p.label)}</strong>
                <small>
                  {p.tenant} / {p.email}
                </small>
              </button>
            ))}
          </div>
        </details>
      </div>
    </div>
  );
}
