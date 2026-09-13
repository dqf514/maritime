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

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

const PROMOS = [
  {
    titleKey: "portal.promo.clarity.title",
    bodyKey: "portal.promo.clarity.body",
    title: "One place for the commercial voyage",
    body: "Bring chartering, operations and settlement into a single daily workspace — less switching, clearer accountability.",
  },
  {
    titleKey: "portal.promo.trust.title",
    bodyKey: "portal.promo.trust.body",
    title: "Built for maritime teams",
    body: "Designed around how shipping desks actually work: roles, approvals, local time, and the language of the trade.",
  },
  {
    titleKey: "portal.promo.connect.title",
    bodyKey: "portal.promo.connect.body",
    title: "Connected to how you collaborate",
    body: "Fit into your organisation’s identity and Microsoft 365 ways of working, without forcing a new collaboration stack.",
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
            "A calm, connected workspace for owners, charterers, operators and ship managers — from fixture to settlement.",
        }),
      );
  }, []);

  const name = brand?.product_name || "VoyageOS";
  const accent = brand?.primary_color || "#1A9B96";

  return (
    <div className="portal portal-marketing" style={{ ["--portal-accent" as string]: accent }}>
      <header className="portal-nav portal-nav-slim">
        <div className="portal-brand">
          <img src={brand?.icon_url || "/branding/mark.svg"} alt="" width={32} height={32} />
          <strong>{name}</strong>
        </div>
        <div className="portal-nav-actions">
          <LanguageSwitcher />
          <Link href="/login" className="btn btn-primary portal-cta">
            {t("portal.sign_in", "Sign in")}
          </Link>
        </div>
      </header>

      <section className="portal-hero portal-hero-single">
        <div className="portal-hero-copy">
          <p className="portal-brand-mark">{name}</p>
          <h1>{t("portal.hero_title", "The operating system for commercial shipping")}</h1>
          <p className="portal-lead">
            {t(
              "portal.hero_sub",
              "A calm, connected workspace for owners, charterers, operators and ship managers — from fixture to settlement.",
            )}
          </p>
          <div className="portal-actions">
            <Link href="/login" className="btn btn-primary">
              {t("portal.sign_in", "Sign in")}
            </Link>
            <a className="btn btn-ghost portal-ghost" href="mailto:sales@voyageos.example">
              {t("portal.cta_contact", "Talk to us")}
            </a>
          </div>
        </div>
        <div className="portal-hero-visual portal-hero-atmosphere" aria-hidden>
          <img src={brand?.logo_url || "/branding/logo.svg"} alt="" className="portal-logo-xl" />
        </div>
      </section>

      <section className="portal-promo" aria-labelledby="portal-why">
        <h2 id="portal-why">{t("portal.why_title", "Why teams choose VoyageOS")}</h2>
        <p className="portal-promo-sub">
          {t(
            "portal.why_sub",
            "Not a catalogue of screens — a clearer way to run the commercial voyage together.",
          )}
        </p>
        <ul className="portal-promo-list">
          {PROMOS.map((item) => (
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
        <Link href="/login">{t("portal.cta_signin", "Sign in →")}</Link>
      </footer>
    </div>
  );
}
