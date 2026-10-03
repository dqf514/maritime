"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { OmniSearch } from "@/components/OmniSearch";
import { NavIcon, sectionIconId } from "@/components/NavIcon";
import { NavPopup } from "@/components/NavPopup";
import { NotificationBell } from "@/components/NotificationBell";
import { ThemeToggle } from "@/components/ThemeToggle";
import { DensityToggle } from "@/components/DensityToggle";
import { Breadcrumb, type BreadcrumbItem } from "@/components/Breadcrumb";
import { clearLookupCache } from "@/components/LookupSelect";
import { apiGet, apiLogout, apiMe, readStorage, removeStorage, TOKEN_STORAGE_KEY, type Me } from "@/lib/api";
import { LanguageSwitcher, useI18n } from "@/lib/i18n";

export type NavSection = {
  section: string;
  label: string;
  collapsed_default?: boolean;
  items: { id: string; label: string; href: string }[];
};
export type ShellBootstrap = {
  roles: string[];
  profile_tier: string;
  is_platform: boolean;
  tenant?: { id: string; code: string; name: string };
  company?: {
    display_name?: string | null;
    logo_url?: string | null;
    brand_primary?: string | null;
    brand_secondary?: string | null;
  };
  navigation: NavSection[];
  workspaces: { id: string; label: string }[];
  active_workspace: string;
  home_widgets: { id: string; title: string; href: string; hint: string; icon?: string }[];
  quick_actions: { label: string; href: string }[];
  allowed_paths?: string[];
};

const NAV_COLLAPSE_KEY = "marios_nav_collapsed";
const SEC_COLLAPSE_KEY = "marios_nav_sections";

function pathAllowed(path: string, prefixes: string[] | undefined): boolean {
  if (!prefixes?.length) return true;
  const p = (path || "/").split("?")[0];
  if (
    p.startsWith("/login") ||
    p.startsWith("/help") ||
    p.startsWith("/manual") ||
    p.startsWith("/account") ||
    p.startsWith("/home") ||
    p.startsWith("/dashboards")
  ) {
    return true;
  }
  return prefixes.some((href) => {
    if (!href) return false;
    return p === href || p.startsWith(`${href}/`);
  });
}

function initials(name: string | null | undefined, email: string): string {
  const src = (name || email || "?").trim();
  if (!src) return "?";
  const parts = src.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return src.slice(0, 2).toUpperCase();
}

export function AppShell({
  children,
  breadcrumbs,
  title,
  subtitle,
  rightPanel,
  rightPanelTitle,
}: {
  children: React.ReactNode;
  breadcrumbs?: BreadcrumbItem[];
  title?: string;
  subtitle?: string;
  rightPanel?: React.ReactNode;
  rightPanelTitle?: string;
}) {
  const [me, setMe] = useState<Me | null>(null);
  const [shell, setShell] = useState<ShellBootstrap | null>(null);
  const [iconUrl, setIconUrl] = useState("/branding/mark.svg");
  const [productName, setProductName] = useState("MariOS");
  const [navCollapsed, setNavCollapsed] = useState(false);
  const [rightPanelOpen, setRightPanelOpen] = useState(true);
  const [secOpen, setSecOpen] = useState<Record<string, boolean>>({});
  const [navHint, setNavHint] = useState<{ text: string; x: number; y: number } | null>(null);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const pathname = usePathname();
  const { t, reload } = useI18n();

  const revealNavHint = useCallback(
    (el: HTMLElement, text: string) => {
      if (!navCollapsed) return;
      const r = el.getBoundingClientRect();
      setNavHint({ text, x: r.right + 10, y: r.top + r.height / 2 });
    },
    [navCollapsed],
  );
  const hideNavHint = useCallback(() => setNavHint(null), []);

  const load = useCallback(async () => {
    // Session lives in an HttpOnly cookie (sent via credentials:"include");
    // the legacy localStorage token is only a fallback header credential.
    // Probe /me directly — a 401 lands in the catch below and redirects to /login.
    const [m, s, b] = await Promise.all([
      apiMe(),
      apiGet("/api/v1/shell/bootstrap"),
      apiGet("/api/v1/public/branding").catch(() => null),
    ]);
    setMe(m);
    setShell(s);
    if (b?.icon_url) setIconUrl(b.icon_url);
    if (b?.product_name) setProductName(b.product_name);
    if (s?.company?.logo_url) setIconUrl(s.company.logo_url);
    if (s?.company?.display_name) setProductName(s.company.display_name);
    if (s?.company?.brand_primary && typeof document !== "undefined") {
      document.documentElement.style.setProperty("--brand", s.company.brand_primary);
      document.documentElement.style.setProperty("--accent", s.company.brand_primary);
    }
    await reload();

    const storedSecs = readStorage(SEC_COLLAPSE_KEY);
    const parsed: Record<string, boolean> = storedSecs ? JSON.parse(storedSecs) : {};
    const next: Record<string, boolean> = {};
    for (const sec of s.navigation as NavSection[]) {
      if (typeof parsed[sec.section] === "boolean") next[sec.section] = parsed[sec.section];
      else next[sec.section] = !sec.collapsed_default;
    }
    setSecOpen(next);
  }, [router, reload]);

  useEffect(() => {
    setNavCollapsed(readStorage(NAV_COLLAPSE_KEY) === "1");
  }, []);

  useEffect(() => {
    load().catch(() => {
      removeStorage(TOKEN_STORAGE_KEY);
      router.replace("/login");
    });
  }, [load, router]);

  useEffect(() => {
    if (!shell?.allowed_paths?.length) return;
    if (!pathAllowed(pathname, shell.allowed_paths)) {
      router.replace("/home");
    }
  }, [pathname, shell, router]);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!userMenuRef.current?.contains(e.target as Node)) setUserMenuOpen(false);
    }
    if (userMenuOpen) document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [userMenuOpen]);

  useEffect(() => {
    setMobileNavOpen(false);
  }, [pathname]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMobileNavOpen(false);
    }
    if (!mobileNavOpen) return;
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [mobileNavOpen]);

  function closeMobileNav() {
    setMobileNavOpen(false);
  }

  function toggleNavCollapsed() {
    setNavCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem(NAV_COLLAPSE_KEY, next ? "1" : "0");
      if (next === false) setNavHint(null);
      return next;
    });
  }

  function toggleSection(id: string) {
    setSecOpen((prev) => {
      const next = { ...prev, [id]: !prev[id] };
      localStorage.setItem(SEC_COLLAPSE_KEY, JSON.stringify(next));
      return next;
    });
  }

  async function signOut() {
    // Clear the server-side HttpOnly cookie first, then local state.
    await apiLogout();
    removeStorage(TOKEN_STORAGE_KEY); // legacy token cleanup
    clearLookupCache();
    router.replace("/login");
  }

  if (!me || !shell) {
    return (
      <div className="login-page">
        <p>{t("common.loading", "加载中…")}</p>
      </div>
    );
  }

  const roleLabel = shell.roles.join(" · ");
  const isActive = (href: string) => pathname === href || (href !== "/" && pathname.startsWith(href));
  const collapseLabel = navCollapsed
    ? t("shell.expand_nav", "展开导航")
    : t("shell.collapse_nav", "收起导航");

  return (
    <div
      className={`app-shell ${navCollapsed ? "nav-collapsed" : ""} ${mobileNavOpen ? "mobile-nav-open" : ""} ${rightPanel && !rightPanelOpen ? "right-panel-hidden" : ""}`}
    >
      <header className="topbar">
        <button
          type="button"
          className="nav-hamburger"
          aria-label={mobileNavOpen ? t("shell.close_nav", "关闭导航") : t("shell.open_nav", "打开导航")}
          aria-expanded={mobileNavOpen}
          aria-controls="app-sidenav"
          onClick={() => setMobileNavOpen((o) => !o)}
        >
          <span className="nav-hamburger-box" aria-hidden>
            <span />
            <span />
            <span />
          </span>
        </button>
        <Link href="/home" className="brand brand-link" onClick={closeMobileNav}>
          <img src={iconUrl} alt="" width={28} height={28} />
          <span className="brand-text">
            {productName}
            <span>{shell.is_platform ? t("shell.platform", "平台") : me.tenant.name}</span>
          </span>
        </Link>
        <div className="topbar-search">
          <OmniSearch />
        </div>
        <div className="topbar-right">
          {/* Refresh (F5) */}
          <button
            type="button"
            className="icon-btn"
            title={t("shell.refresh", "刷新 (F5)")}
            aria-label={t("shell.refresh", "刷新")}
            onClick={() => window.location.reload()}
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <path d="M13.6 2.4A7 7 0 0 0 2.5 6.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              <path d="M2.4 13.6A7 7 0 0 0 13.5 9.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              <path d="M13.5 2.5v3.5h-3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M2.5 13.5v-3.5h3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </button>
          {/* Fullscreen (F11) */}
          <button
            type="button"
            className="icon-btn"
            title={t("shell.fullscreen", "全屏 (F11)")}
            aria-label={t("shell.fullscreen", "全屏")}
            onClick={() => {
              if (document.fullscreenElement) {
                document.exitFullscreen();
              } else {
                document.documentElement.requestFullscreen();
              }
            }}
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <path d="M2 6V2h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M14 6V2h-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M2 10v4h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M14 10v4h-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </button>
          <NotificationBell />
          <DensityToggle />
          <div className="user-menu" ref={userMenuRef}>
            <button
              type="button"
              className="user-avatar-btn"
              aria-expanded={userMenuOpen}
              aria-haspopup="menu"
              title={me.user.full_name || me.user.email}
              onClick={() => setUserMenuOpen((o) => !o)}
            >
              <span className="user-avatar" aria-hidden>
                {initials(me.user.full_name, me.user.email)}
              </span>
            </button>
            {userMenuOpen ? (
              <div className="user-menu-pop" role="menu">
                <div className="user-menu-head">
                  <strong>{me.user.full_name || me.user.email}</strong>
                  <small>{me.user.email}</small>
                  <small className="user-menu-roles">{roleLabel}</small>
                </div>
                <Link
                  href="/account/security"
                  role="menuitem"
                  onClick={() => setUserMenuOpen(false)}
                >
                  {t("nav.account_sec", "账户安全")}
                </Link>
                <Link href="/help" role="menuitem" onClick={() => setUserMenuOpen(false)}>
                  {t("help.centre", "帮助中心")}
                </Link>
                <div className="user-menu-sep" />
                <div className="user-menu-setting">
                  <span>{t("shell.theme", "主题")}</span>
                  <ThemeToggle />
                </div>
                <div className="user-menu-setting">
                  <span>{t("shell.language", "语言")}</span>
                  <LanguageSwitcher />
                </div>
                <div className="user-menu-sep" />
                <button type="button" role="menuitem" className="user-menu-danger" onClick={signOut}>
                  {t("shell.sign_out", "退出登录")}
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </header>
      <div className="body">
        <div
          className="nav-backdrop"
          hidden={!mobileNavOpen}
          onClick={closeMobileNav}
          aria-hidden={!mobileNavOpen}
        />
        <nav id="app-sidenav" className="sidenav" aria-label={t("shell.main_nav", "主导航")}>
          <div className="sidenav-mobile-head">
            <strong>{t("shell.main_nav", "主导航")}</strong>
            <button type="button" className="nav-drawer-close" onClick={closeMobileNav} aria-label={t("shell.close_nav", "关闭导航")}>
              ×
            </button>
          </div>
          <div className="sidenav-inner">
            <NavPopup
              sections={shell.navigation}
              navCollapsed={navCollapsed}
              pathname={pathname}
              onNavigate={closeMobileNav}
            />
          </div>
          <div className="sidenav-foot">
            <Link
              href="/help"
              className={pathname.startsWith("/help") ? "active" : ""}
              title={navCollapsed ? undefined : t("help.centre", "帮助中心")}
              aria-label={t("help.centre", "帮助中心")}
              onClick={closeMobileNav}
              onMouseEnter={(e) => revealNavHint(e.currentTarget, t("help.centre", "帮助中心"))}
              onMouseLeave={hideNavHint}
              onFocus={(e) => revealNavHint(e.currentTarget, t("help.centre", "帮助中心"))}
              onBlur={hideNavHint}
            >
              <span className="nav-icon-wrap" aria-hidden>
                <NavIcon id="help" />
              </span>
              <span className="nav-item-text">{t("help.centre", "帮助中心")}</span>
            </Link>
            <button
              type="button"
              className="nav-collapse-btn"
              aria-label={collapseLabel}
              title={navCollapsed ? undefined : collapseLabel}
              onClick={toggleNavCollapsed}
              onMouseEnter={(e) => revealNavHint(e.currentTarget, collapseLabel)}
              onMouseLeave={hideNavHint}
              onFocus={(e) => revealNavHint(e.currentTarget, collapseLabel)}
              onBlur={hideNavHint}
            >
              <span className="nav-icon-wrap" aria-hidden>
                {navCollapsed ? "»" : "«"}
              </span>
              <span className="nav-item-text">{collapseLabel}</span>
            </button>
          </div>
        </nav>
        {navHint ? (
          <div className="nav-float-hint" style={{ left: navHint.x, top: navHint.y }} role="tooltip">
            {navHint.text}
          </div>
        ) : null}
        <div className="main-col">
          <main className="content">
            {breadcrumbs?.length ? <Breadcrumb items={breadcrumbs} /> : null}
            {title ? (
              <div className="page-header">
                <div>
                  <h1 style={{ margin: 0 }}>{title}</h1>
                  {subtitle ? <p className="page-sub">{subtitle}</p> : null}
                </div>
              </div>
            ) : null}
            {children}
          </main>
          <footer className="statusbar">
            <span>
              {t("shell.tenant_tier", "租户 {code} · 档位 {tier}", {
                code: me.tenant.code,
                tier: me.tenant.profile_tier,
              })}
            </span>
            <span className="muted">{roleLabel}</span>
            <span className="statusbar-search-hint">{t("shell.omni_search", "搜索 (Ctrl+K)")}</span>
            <span className="ok-dot">{t("common.online", "在线")}</span>
          </footer>
        </div>
        {/* Right contextual panel — AI / properties / details */}
        {rightPanel ? (
          <aside className={`right-panel ${rightPanelOpen ? "visible" : "hidden"}`}>
            <div className="panel-header">
              <span>{rightPanelTitle || t("shell.details", "详情")}</span>
              <button
                type="button"
                className="icon-btn"
                style={{ width: 18, height: 18 }}
                onClick={() => setRightPanelOpen(false)}
                aria-label={t("shell.close_panel", "收起面板")}
              >
                ×
              </button>
            </div>
            <div className="panel-body" style={{ flex: 1, overflow: "auto" }}>
              {rightPanel}
            </div>
          </aside>
        ) : null}
        {/* Right panel toggle (floating) */}
        {rightPanel && !rightPanelOpen ? (
          <button
            type="button"
            className="right-panel-toggle icon-btn"
            onClick={() => setRightPanelOpen(true)}
            title={t("shell.open_panel", "展开面板")}
            style={{
              position: "fixed",
              right: 0,
              top: "50%",
              transform: "translateY(-50%)",
              zIndex: 40,
              width: 18,
              height: 48,
              borderRadius: "4px 0 0 4px",
              border: "1px solid var(--chrome-border)",
              borderRight: "none",
              background: "var(--chrome-bg)",
              color: "var(--muted)",
              fontSize: 12,
            }}
          >
            ‹
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function useShellBootstrap() {
  const [shell, setShell] = useState<ShellBootstrap | null>(null);
  const [error, setError] = useState(false);
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setError(false);
    apiGet("/api/v1/shell/bootstrap")
      .then((s) => {
        if (!cancelled) setShell(s);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [nonce]);
  return { shell, error, retry: () => setNonce((n) => n + 1) };
}
