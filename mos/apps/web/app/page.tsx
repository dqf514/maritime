"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { LanguageSwitcher, useI18n } from "@/lib/i18n";

type Branding = {
  product_name: string;
  tagline: string;
  logo_url: string;
  icon_url: string;
  primary_color: string;
  hero_title: string;
  hero_subtitle: string;
};

import { API_BASE } from "@/lib/api";

const HIGHLIGHTS = [
  {
    titleKey: "portal.hl.dem.title",
    bodyKey: "portal.hl.dem.body",
    title: "滞期费，一分钱不丢",
    body: "从 SOF 证据到索赔账单，全程留痕，应收尽收。",
  },
  {
    titleKey: "portal.hl.est.title",
    bodyKey: "portal.hl.est.body",
    title: "估算 3 分钟变 30 秒",
    body: "航线、货量、油价一填，TCE 立刻出来，模板一键起草。",
  },
  {
    titleKey: "portal.hl.carbon.title",
    bodyKey: "portal.hl.carbon.body",
    title: "碳成本自动算",
    body: "EU ETS / FuelEU 自动计入航次成本与报价，不用另开表。",
  },
  {
    titleKey: "portal.hl.m365.title",
    bodyKey: "portal.hl.m365.body",
    title: "Outlook、Teams 直接用",
    body: "不换工作方式：邮件、会议、公司账号，全部沿用。",
  },
];

export default function PortalPage() {
  const [brand, setBrand] = useState<Branding | null>(null);
  const { t } = useI18n();

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
          hero_title: "The operating system for commercial shipping",
          hero_subtitle:
            "A calm workspace for owners, charterers, operators and ship managers — from fixture to settlement.",
        }),
      );
  }, []);

  const name = brand?.product_name || "VoyageOS";
  const accent = brand?.primary_color || "#1A9B96";

  return (
    <div className="portal portal-marketing" style={{ ["--portal-accent" as string]: accent }}>
      <header className="portal-nav portal-nav-slim">
        <div className="portal-brand">
          <img src={brand?.icon_url || "/branding/mark.svg"} alt="" width={28} height={28} />
          <strong>{name}</strong>
        </div>
        <div className="portal-nav-actions">
          <LanguageSwitcher />
          <Link href="/login" className="btn btn-primary portal-cta">
            {t("portal.sign_in", "Sign in")}
          </Link>
        </div>
      </header>

      <section className="portal-hero portal-hero-bleed">
        <div className="portal-hero-inner">
          <p className="portal-brand-mark">{name}</p>
          <h1>{t("portal.hero_tagline", "把 Excel、邮件和计算器，变成一个为航运生意而生的系统")}</h1>
          <p className="portal-lead">
            {t("portal.hero_sub", "估算、租约、航次、滞期索赔、结算——一次做对，一个系统管好。")}
          </p>
          <div className="portal-actions">
            <a className="btn btn-primary portal-cta-lg" href="/intro.html">
              {t("portal.cta_intro", "了解详情")}
            </a>
            <Link href="/login" className="btn btn-ghost portal-ghost portal-cta-lg-ghost">
              {t("portal.sign_in", "登录")}
            </Link>
          </div>
        </div>
      </section>

      <section className="portal-promo portal-promo-compact" aria-labelledby="portal-why">
        <h2 id="portal-why">{t("portal.why_title", "为航运生意而生")}</h2>
        <ul className="portal-promo-grid portal-promo-grid-4">
          {HIGHLIGHTS.map((item) => (
            <li key={item.titleKey}>
              <strong>{t(item.titleKey, item.title)}</strong>
              <p>{t(item.bodyKey, item.body)}</p>
            </li>
          ))}
        </ul>
      </section>

      <footer className="portal-foot">
        <span>
          © {new Date().getFullYear()} {name}
        </span>
        <a href="/intro.html">{t("portal.cta_intro", "了解详情")}</a>
        <Link href="/login" className="portal-foot-login">
          {t("portal.cta_signin", "登录 →")}
        </Link>
      </footer>
    </div>
  );
}
