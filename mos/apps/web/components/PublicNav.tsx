"use client";

import Link from "next/link";
import { LanguageSwitcher, useI18n } from "@/lib/i18n";
import { assetUrl } from "@/lib/api";

type PublicNavProps = {
  brand?: { product_name?: string; icon_url?: string } | null;
  current?: "home" | "intro" | "manual";
  compact?: boolean;
};

// 公开面导航链接集——落地页 / 介绍页 / 手册 / 登录必须完全一致
const LINKS = [
  { id: "home" as const, href: "/", key: "portal.nav_home", fallback: { en: "Home", zh: "首页" } },
  { id: "intro" as const, href: "/intro.html", key: "portal.nav_intro", fallback: { en: "Product tour", zh: "产品介绍" } },
  { id: "manual" as const, href: "/manual/", key: "portal.nav_manual", fallback: { en: "User manual", zh: "操作手册" } },
];

export function PublicNav({ brand, current, compact }: PublicNavProps) {
  const { t } = useI18n();
  const name = brand?.product_name || "MariOS";
  const markSize = compact ? 24 : 28;

  return (
    <header className={compact ? "public-nav public-nav-compact" : "public-nav"}>
      <Link href="/" className="public-nav-brand">
        <img src={assetUrl(brand?.icon_url) || "/branding/mark.svg"} alt="" width={markSize} height={markSize} />
        <strong>{name}</strong>
      </Link>
      <nav className="public-nav-links">
        {LINKS.map((l) => (
          <Link
            key={l.id}
            href={l.href}
            className={current === l.id ? "active" : undefined}
            aria-current={current === l.id ? "page" : undefined}
          >
            {t(l.key, l.fallback)}
          </Link>
        ))}
      </nav>
      <div className="public-nav-actions">
        <LanguageSwitcher />
        <Link href="/login" className="btn btn-primary public-nav-cta">
          {t("portal.sign_in", "Sign in")}
        </Link>
      </div>
    </header>
  );
}
