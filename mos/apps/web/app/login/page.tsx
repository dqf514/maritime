"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useI18n } from "@/lib/i18n";
import { apiLogin } from "@/lib/api";
import { PublicNav } from "@/components/PublicNav";

import { API_BASE } from "@/lib/api";

const PRESETS = [
  { labelKey: "login.preset.platform", hintKey: "login.preset.platform_h", label: "Platform operator", hint: "Tenants, plans, branding, identity", tenant: "sys", email: "ops@marios.platform", password: "Ops1234!" },
  { labelKey: "login.preset.admin", hintKey: "login.preset.admin_h", label: "Tenant admin", hint: "Security policy & invites", tenant: "demo", email: "admin@demo.marios", password: "Demo1234!" },
  { labelKey: "login.preset.mgmt", hintKey: "login.preset.mgmt_h", label: "Executive / director", hint: "Command wall / TCE", tenant: "demo", email: "mgmt@demo.marios", password: "Demo1234!" },
  { labelKey: "login.preset.charter", hintKey: "login.preset.charter_h", label: "Chartering lead", hint: "Pipeline wall / CP", tenant: "demo", email: "charterer@demo.marios", password: "Demo1234!" },
  { labelKey: "login.preset.ops", hintKey: "login.preset.ops_h", label: "Operations", hint: "Situation room / Twin", tenant: "demo", email: "ops@demo.marios", password: "Demo1234!" },
  { labelKey: "login.preset.tech", hintKey: "login.preset.tech_h", label: "Technical / superintendent", hint: "Ship mgmt / PMS", tenant: "demo", email: "tech@demo.marios", password: "Demo1234!" },
  { labelKey: "login.preset.fin", hintKey: "login.preset.fin_h", label: "Finance", hint: "Cash wall / AR", tenant: "demo", email: "finance@demo.marios", password: "Demo1234!" },
  { labelKey: "login.preset.dem", hintKey: "login.preset.dem_h", label: "Demurrage", hint: "Laytime / claims wall", tenant: "demo", email: "demurrage@demo.marios", password: "Demo1234!" },
];

type Branding = {
  product_name: string;
  tagline: string;
  logo_url: string;
  icon_url: string;
  primary_color: string;
};

/** 最近使用的登录身份（租户+邮箱，绝不存密码）——回填登录页，免得每次 demo+空邮箱 */
type RecentIdentity = { tenant: string; email: string; at: number };
const RECENT_KEY = "marios_recent_logins";
const RECENT_MAX = 5;

function readRecents(): RecentIdentity[] {
  try {
    const arr = JSON.parse(window.localStorage.getItem(RECENT_KEY) || "[]");
    if (!Array.isArray(arr)) return [];
    return arr.filter(
      (r): r is RecentIdentity =>
        Boolean(r) && typeof r.tenant === "string" && typeof r.email === "string" && Boolean(r.email),
    );
  } catch {
    return []; // 损坏/隐私模式 — 当作没有记录
  }
}

function rememberIdentity(tenantVal: string, emailVal: string) {
  if (!emailVal) return;
  try {
    const prev = readRecents().filter((r) => !(r.tenant === tenantVal && r.email === emailVal));
    prev.unshift({ tenant: tenantVal, email: emailVal, at: Date.now() });
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(prev.slice(0, RECENT_MAX)));
  } catch {
    // 存储不可用 — 静默降级为不回填
  }
}

type AuthMethods = {
  password: boolean;
  microsoft: boolean;
  google: boolean;
  magic_link: boolean;
  require_email_verify: boolean;
  invite_only: boolean;
  allowed_domains: string[];
  provider_modes: { microsoft: string; google: string };
};

/**
 * 「已激活」的 SSO 提供商（登录页只展示这些）：除 policy/platform 开关外，
 * 还要求运行时 mode=live —— 凭据没配到位（stub/disabled）的提供商点了也登不进去，
 * 只会误导用户。旧后端不带 provider_modes 时按布尔兜底（保持原行为）。
 */
function liveProviders(m: AuthMethods | null): ("microsoft" | "google")[] {
  if (!m) return [];
  const modes = (m.provider_modes || {}) as Partial<AuthMethods["provider_modes"]>;
  const ok = (p: "microsoft" | "google") => Boolean(m[p]) && (modes[p] ? modes[p] === "live" : true);
  return (["microsoft", "google"] as const).filter(ok);
}

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
  // Step 1: tenant + email → methods resolved → step 2: password form or direct SSO jump.
  const [step, setStep] = useState<"identity" | "credentials">("identity");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tenant, setTenant] = useState("demo");
  const [recents, setRecents] = useState<RecentIdentity[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [brand, setBrand] = useState<Branding | null>(null);
  const [methods, setMethods] = useState<AuthMethods | null>(null);
  const [magicSent, setMagicSent] = useState("");
  /** 绑定 SSO 时密码默认收起 —— 点「改用密码登录」才展开（SSO 是主路径，密码是备选） */
  const [pwOpen, setPwOpen] = useState(false);
  // 登录失败后清空密码框并把焦点移回 —— 明文残留会被误读为「已提交成功」，
  // 也有肩窥/录屏泄露风险（P1-21）。
  const passwordRef = useRef<HTMLInputElement>(null);

  // —— 方法可用性（handlers 里也要用，声明在 handlers 之前）——
  /** 已激活的 SSO 提供商：只展示真实凭据到位的（见 liveProviders） */
  const ssoProviders = useMemo(() => liveProviders(methods), [methods]);
  const showSso = ssoProviders.length > 0;
  const showPassword = methods?.password !== false;
  const showMagic = Boolean(methods?.magic_link);
  // 绑定 SSO 且密码仍开放：SSO 按钮是主操作（回车即 SSO），密码收起为「改用密码登录」备选
  const collapsePassword = showSso && showPassword;
  const passwordVisible = showPassword && (!collapsePassword || pwOpen);

  // 打开登录页即回填最近一次使用的租户+邮箱（无记录则保持 demo+空）
  useEffect(() => {
    const r = readRecents();
    setRecents(r);
    if (r.length) {
      setTenant(r[0].tenant);
      setEmail(r[0].email);
    }
  }, []);

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/public/branding`)
      .then((r) => r.json())
      .then(setBrand)
      .catch(() =>
        setBrand({
          product_name: "MariOS",
          tagline: "Maritime commercial operating system",
          logo_url: "/branding/logo.svg",
          icon_url: "/branding/mark.svg",
          primary_color: "#1A9B96",
        }),
      );
  }, []);

  // Surface OAuth callback failures (?oauth_error=… from the backend redirect).
  useEffect(() => {
    const code = new URLSearchParams(window.location.search).get("oauth_error");
    if (!code) return;
    const map: Record<string, string> = {
      access_denied: t("login.oauth_err_access_denied", "Sign-in was cancelled at the identity provider."),
      invalid_state: t("login.oauth_err_state", "Sign-in session expired — please try again."),
      expired_state: t("login.oauth_err_state", "Sign-in session expired — please try again."),
      domain_not_allowed: t("login.error_domain", "This email domain is not allowed by the tenant."),
      invite_only: t("login.oauth_err_invite_only", "This tenant is invite-only — ask an admin for an invitation."),
      email_not_verified: t("login.error_unverified", "Email not verified. Check your inbox or ask tenant admin to resend."),
      token_exchange_failed: t("login.oauth_err_token", "Identity provider rejected the sign-in — check the tenant SSO configuration."),
      oauth_not_configured: t("login.oauth_err_not_configured", "SSO is not configured for this tenant."),
      identity_missing_email: t("login.oauth_err_no_email", "Identity provider did not return an email address."),
      missing_id_token: t("login.oauth_err_token", "Identity provider rejected the sign-in — check the tenant SSO configuration."),
      invalid_id_token: t("login.oauth_err_token", "Identity provider rejected the sign-in — check the tenant SSO configuration."),
      token_endpoint_unreachable: t("login.error_network", "Cannot reach API — check that the backend is running."),
    };
    setError(map[code] || t("login.oauth_err_generic", "SSO sign-in failed.", { code }));
    window.history.replaceState(null, "", window.location.pathname);
  }, [t]);

  async function onContinue(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const tenantVal = String(fd.get("tenant") || tenant).trim() || "demo";
    const emailVal = String(fd.get("email") || email).trim();
    setTenant(tenantVal);
    setEmail(emailVal);
    setLoading(true);
    setError("");
    try {
      const r = await fetch(`${API_BASE}/api/v1/auth/methods?tenant_code=${encodeURIComponent(tenantVal)}`);
      if (r.status === 404) {
        setError(t("login.error_tenant", "Tenant not found — check the company code."));
        return;
      }
      if (!r.ok) {
        setError(t("login.error_generic", "Sign-in failed. Check tenant / credentials (or verification / method policy)."));
        return;
      }
      const m: AuthMethods = await r.json();
      setMethods(m);
      // Early domain gate — same rule the backend enforces.
      const dom = emailVal.includes("@") ? emailVal.split("@").pop()!.toLowerCase() : "";
      if ((m.allowed_domains || []).length && dom && !(m.allowed_domains || []).some((d) => d.toLowerCase() === dom)) {
        setError(t("login.error_domain", "This email domain is not allowed by the tenant."));
        return;
      }
      if (m.password) {
        setStep("credentials");
        return;
      }
      // No password — route straight to the tenant's SSO / magic link.
      // 只跳「已激活」的提供商：stub/disabled 的点进去也登不上。
      const live = liveProviders(m);
      if (live.length) {
        await startOAuth(live[0], tenantVal, emailVal);
        return;
      }
      if (m.magic_link) {
        setStep("credentials");
        await sendMagic(tenantVal, emailVal);
        return;
      }
      setError(t("login.error_no_method", "No sign-in method is enabled for this tenant."));
    } catch {
      setError(t("login.error_network", "Cannot reach API — check that the backend is running."));
    } finally {
      setLoading(false);
    }
  }

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    // 密码收起时，表单提交（回车 / 主按钮）= 走绑定的 SSO —— 「继续」即 SSO，少一次选错
    if (collapsePassword && !pwOpen && ssoProviders.length) {
      await startOAuth(ssoProviders[0]);
      return;
    }
    setLoading(true);
    setError("");
    const fd = new FormData(e.currentTarget);
    const passwordVal = String(fd.get("password") || password);
    setPassword(passwordVal);
    try {
      // Session cookie is planted by the server (HttpOnly) — no localStorage.
      await apiLogin(email, passwordVal, tenant);
      rememberIdentity(tenant, email);
      router.replace(tenant === "sys" ? "/platform" : "/home");
    } catch (err: any) {
      // 失败即清空密码 + 焦点回密码框（成功路径不变，仍直接跳转）。
      setPassword("");
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
      // 焦点回密码框：用户改完密码可直接再次回车提交。
      window.requestAnimationFrame(() => passwordRef.current?.focus());
    } finally {
      setLoading(false);
    }
  }

  async function startOAuth(provider: "microsoft" | "google", tenantVal?: string, emailVal?: string) {
    setError("");
    const code = tenantVal ?? tenant;
    const mail = emailVal ?? email;
    const res = await fetch(`${API_BASE}/api/v1/auth/oauth/${provider}/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant_code: code || "demo", provider, intent: "login", email: mail || null }),
    });
    if (!res.ok) {
      setError(t("login.error_oauth", "{provider} sign-in unavailable for this tenant", { provider }));
      return;
    }
    const data = await res.json();
    if (data.authorize_url) {
      rememberIdentity(code, mail); // 身份意图已确认 — 回来时回填
      window.location.href = data.authorize_url;
    } else setError(t("login.error_oauth_cfg", "OAuth not configured"));
  }

  async function sendMagic(tenantVal?: string, emailVal?: string) {
    setError("");
    const res = await fetch(`${API_BASE}/api/v1/auth/magic-link/request`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: emailVal ?? email, tenant_code: (tenantVal ?? tenant) || "demo" }),
    });
    if (!res.ok) {
      setError(t("login.error_magic", "Magic link disabled or domain not allowed"));
      return;
    }
    rememberIdentity((tenantVal ?? tenant) || "demo", emailVal ?? email);
    setMagicSent("sent");
  }

  function applyPreset(p: (typeof PRESETS)[0]) {
    setTenant(p.tenant);
    setEmail(p.email);
    setPassword(p.password);
    setMethods(null); // presets bypass methods resolution — show the plain password form
    setPwOpen(false);
    setError("");
    setStep("credentials");
  }

  const accent = brand?.primary_color || "#1A9B96";
  const name = brand?.product_name || "MariOS";

  return (
    <div className="login-stage login-stage-clean" style={{ ["--portal-accent" as string]: accent }}>
      <div className="login-stage-bg" aria-hidden />
      <PublicNav brand={brand} compact />

      <main className="login-split">
        <aside className="login-brand-pane">
          <div className="login-brand-inner">
            <p className="login-brand-mark">{name}</p>
            <p className="login-brand-tagline">
              {t("login.brand_tagline", "把 Excel、邮件和计算器，变成一个为航运生意而生的系统")}
            </p>
            <a className="login-brand-intro" href="/intro.html">
              {t("portal.cta_intro", "了解详情")} →
            </a>
          </div>
          <svg className="login-brand-waves" viewBox="0 0 480 220" fill="none" aria-hidden>
            <path d="M-20 150 Q60 132 120 150 T260 150 T400 150 T540 150" stroke="#2ea8ff" strokeWidth="2" opacity=".45" />
            <path d="M-20 178 Q60 160 120 178 T260 178 T400 178 T540 178" stroke="#45d5f2" strokeWidth="1.6" opacity=".3" />
            <path d="M-20 206 Q60 190 120 206 T260 206 T400 206 T540 206" stroke="#e9bd5c" strokeWidth="1.4" opacity=".22" />
          </svg>
        </aside>

        <div className="login-form-pane">
          {step === "identity" ? (
          <form className="login-card login-card-solo" onSubmit={onContinue}>
          <div className="login-card-head">
            <h1>{t("login.welcome", "Welcome back")}</h1>
            <p>{t("login.hint_identity", "Tenant code + corporate identity")}</p>
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
            autoFocus
          />

          <label htmlFor="email">{t("login.email", "Email")}</label>
          <input
            id="email"
            name="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
            placeholder={t("login.email_ph", "you@company.com")}
            required
          />

          {recents.length ? (
            <div className="login-recent">
              <span className="login-recent-label">{t("login.recent", "Recent sign-ins")}</span>
              {recents.map((r) => (
                <button
                  key={`${r.tenant}/${r.email}`}
                  type="button"
                  className="login-recent-chip"
                  onClick={() => {
                    setTenant(r.tenant);
                    setEmail(r.email);
                  }}
                >
                  <span className="login-recent-email">{r.email}</span>
                  <span className="login-recent-tenant">{r.tenant}</span>
                </button>
              ))}
            </div>
          ) : null}

          <button className="btn btn-primary login-submit" disabled={loading} type="submit">
            {loading ? "…" : t("login.continue", "Continue")}
          </button>

          <div className="login-alt-row">
            <Link href="/login/verify-email">{t("login.verify_link", "Verify email")}</Link>
            <Link href="/login/accept-invite">{t("login.invite_link", "Accept invite")}</Link>
          </div>
          </form>
          ) : (
          <form className="login-card login-card-solo" onSubmit={onSubmit}>
          <div className="login-card-head">
            <h1>{t("login.welcome", "Welcome back")}</h1>
            <p className="muted">
              {tenant} · {email}{" "}
              <button type="button" className="login-text-btn" onClick={() => { setStep("identity"); setError(""); setMagicSent(""); setPwOpen(false); }}>
                {t("login.not_you", "Not you?")}
              </button>
            </p>
          </div>

          {error ? <div className="error">{error}</div> : null}

          {showSso ? (
            <div className="oauth-stack">
              {ssoProviders.map((p, i) => {
                // 密码收起时，首个提供商按钮就是表单主提交 —— 回车/点击 = SSO，「继续」不再让人二选一
                const heroIsSubmit = collapsePassword && !pwOpen && i === 0;
                return (
                  <button
                    key={p}
                    type={heroIsSubmit ? "submit" : "button"}
                    className={`btn oauth-btn oauth-btn-full ${p === "microsoft" ? "ms" : "goog"}${collapsePassword ? " oauth-btn-hero" : ""}`}
                    onClick={heroIsSubmit ? undefined : () => startOAuth(p)}
                    autoFocus={collapsePassword && !pwOpen && i === 0}
                  >
                    {p === "microsoft" ? <MsIcon /> : <GoogleIcon />}
                    <span>
                      {p === "microsoft"
                        ? t("login.microsoft_full", "Continue with Microsoft")
                        : t("login.google_full", "Continue with Google")}
                    </span>
                  </button>
                );
              })}
              {collapsePassword && !pwOpen ? (
                <p className="login-sso-hint">
                  {ssoProviders.length === 1
                    ? t("login.sso_hero_hint", "This tenant uses {provider} sign-on — you'll continue there.", {
                        provider: ssoProviders[0] === "microsoft" ? "Microsoft" : "Google",
                      })
                    : t("login.sso_hint_multi", "This tenant uses single sign-on — pick your work account above.")}
                </p>
              ) : null}
            </div>
          ) : null}

          {showPassword && collapsePassword && !pwOpen ? (
            <div className="login-divider" role="separator">
              <button
                type="button"
                className="login-text-btn"
                onClick={() => {
                  setPwOpen(true);
                  window.requestAnimationFrame(() => passwordRef.current?.focus());
                }}
              >
                {t("login.use_password", "Use password instead")}
              </button>
            </div>
          ) : null}

          {passwordVisible ? (
            <>
              {collapsePassword ? (
                <div className="login-divider" role="separator">
                  <span>{t("login.or_email", "or continue with email")}</span>
                </div>
              ) : null}
              <label htmlFor="password">{t("login.password", "Password")}</label>
              <input
                id="password"
                name="password"
                type="password"
                ref={passwordRef}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                autoFocus
                required
              />
              <button className="btn btn-primary login-submit" disabled={loading} type="submit">
                {loading ? "…" : t("login.sign_in", "Sign in")}
              </button>
            </>
          ) : null}

          {!showPassword && !showSso ? (
            <p className="muted">{t("login.password_disabled", "Password login disabled — use Microsoft / Google.")}</p>
          ) : null}

          <div className="login-alt-row">
            {showMagic ? (
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
          )}

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
        </div>
      </main>
    </div>
  );
}
