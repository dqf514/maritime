"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { OmniSearch } from "@/components/OmniSearch";
import { NavIcon, sectionIconId } from "@/components/NavIcon";
import { apiGet, apiMe, type Me } from "@/lib/api";
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
  navigation: NavSection[];
  workspaces: { id: string; label: string }[];
  active_workspace: string;
  home_widgets: { id: string; title: string; href: string; hint: string }[];
  quick_actions: { label: string; href: string }[];
  allowed_paths?: string[];
};

const NAV_COLLAPSE_KEY = "voyageos_nav_collapsed";
const SEC_COLLAPSE_KEY = "voyageos_nav_sections";

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

export function AppShell({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [shell, setShell] = useState<ShellBootstrap | null>(null);
  const [iconUrl, setIconUrl] = useState("/branding/mark.svg");
  const [productName, setProductName] = useState("VoyageOS");
  const [navCollapsed, setNavCollapsed] = useState(false);
  const [secOpen, setSecOpen] = useState<Record<string, boolean>>({});
  const [navHint, setNavHint] = useState<{ text: string; x: number; y: number } | null>(null);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
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
    const token = localStorage.getItem("voyageos_token");
    if (!token) {
      router.replace("/login");
      return;
    }
    const [m, s, b] = await Promise.all([
      apiMe(),
      apiGet("/api/v1/shell/bootstrap"),
      apiGet("/api/v1/public/branding").catch(() => null),
    ]);
    setMe(m);
    setShell(s);
    if (b?.icon_url) setIconUrl(b.icon_url);
    if (b?.product_name) setProductName(b.product_name);
    await reload();

    const storedSecs = localStorage.getItem(SEC_COLLAPSE_KEY);
    const parsed: Record<string, boolean> = storedSecs ? JSON.parse(storedSecs) : {};
    const next: Record<string, boolean> = {};
    for (const sec of s.navigation as NavSection[]) {
      if (typeof parsed[sec.section] === "boolean") next[sec.section] = parsed[sec.section];
      else next[sec.section] = !sec.collapsed_default;
    }
    setSecOpen(next);
  }, [router, reload]);

  useEffect(() => {
    setNavCollapsed(localStorage.getItem(NAV_COLLAPSE_KEY) === "1");
  }, []);

  useEffect(() => {
    load().catch(() => {
      localStorage.removeItem("voyageos_token");
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

  function signOut() {
    localStorage.removeItem("voyageos_token");
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
    <div className={`app-shell ${navCollapsed ? "nav-collapsed" : ""}`}>
      <header className="topbar">
        <Link href="/home" className="brand brand-link">
          <img src={iconUrl} alt="" width={28} height={28} />
          <span className="brand-text">
            {productName}
            <span>{shell.is_platform ? t("shell.platform", "平台") : me.tenant.name}</span>
          </span>
        </Link>
        <OmniSearch />
        <div className="topbar-right">
          <LanguageSwitcher />
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
                <button type="button" role="menuitem" className="user-menu-danger" onClick={signOut}>
                  {t("shell.sign_out", "退出登录")}
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </header>
      <div className="body">
        <nav className="sidenav" aria-label={t("shell.main_nav", "主导航")}>
          <div className="sidenav-inner">
            {shell.navigation.map((sec) => {
              const open = navCollapsed ? true : secOpen[sec.section] !== false;
              const secLabel = t(`section.${sec.section}`, sec.label);
              return (
                <div key={sec.section} className={`nav-section ${open ? "open" : "closed"}`}>
                  <button
                    type="button"
                    className="nav-section-label"
                    onClick={() => !navCollapsed && toggleSection(sec.section)}
                    aria-expanded={open}
                    aria-label={secLabel}
                    title={navCollapsed ? undefined : secLabel}
                    onMouseEnter={(e) => revealNavHint(e.currentTarget, secLabel)}
                    onMouseLeave={hideNavHint}
                    onFocus={(e) => revealNavHint(e.currentTarget, secLabel)}
                    onBlur={hideNavHint}
                  >
                    <span className="nav-section-icon" aria-hidden>
                      <NavIcon id={sectionIconId(sec.section)} />
                    </span>
                    <span className="nav-section-text">{secLabel}</span>
                    <em className="nav-section-caret" aria-hidden>
                      {open ? "−" : "+"}
                    </em>
                  </button>
                  {open ? (
                    <div className="nav-section-items">
                      {sec.items.map((item) => {
                        const label = t(`nav.${item.id}`, item.label);
                        return (
                          <Link
                            key={item.href}
                            href={item.href}
                            className={isActive(item.href) ? "active" : ""}
                            title={navCollapsed ? undefined : label}
                            aria-label={label}
                            onMouseEnter={(e) => revealNavHint(e.currentTarget, label)}
                            onMouseLeave={hideNavHint}
                            onFocus={(e) => revealNavHint(e.currentTarget, label)}
                            onBlur={hideNavHint}
                          >
                            <span className="nav-icon-wrap" aria-hidden>
                              <NavIcon id={item.id} />
                            </span>
                            <span className="nav-item-text">{label}</span>
                          </Link>
                        );
                      })}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
          <div className="sidenav-foot">
            <Link
              href="/help"
              className={pathname.startsWith("/help") ? "active" : ""}
              title={navCollapsed ? undefined : t("help.centre", "帮助中心")}
              aria-label={t("help.centre", "帮助中心")}
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
          <main className="content">{children}</main>
          <footer className="statusbar">
            <span>
              {t("shell.tenant_tier", "租户 {code} · 档位 {tier}", {
                code: me.tenant.code,
                tier: me.tenant.profile_tier,
              })}
            </span>
            <span className="muted">{roleLabel}</span>
            <span>{t("shell.omni_search", "搜索 (Ctrl+K)")}</span>
            <span className="ok-dot">{t("common.online", "在线")}</span>
          </footer>
        </div>
      </div>
    </div>
  );
}

export function useShellBootstrap() {
  const [shell, setShell] = useState<ShellBootstrap | null>(null);
  useEffect(() => {
    apiGet("/api/v1/shell/bootstrap").then(setShell).catch(() => setShell(null));
  }, []);
  return shell;
}
