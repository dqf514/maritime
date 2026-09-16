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

const STATS = [
  { value: "7 环", labelKey: "portal.stat.lifecycle", label: "航次全生命周期覆盖" },
  { value: "10 类", labelKey: "portal.stat.exceptions", label: "异常风险主动监控" },
  { value: "30 秒", labelKey: "portal.stat.estimate", label: "完成一次航次估算" },
  { value: "12 种", labelKey: "portal.stat.sof", label: "港口事件自动识别" },
];

const LIFECYCLE = [
  { zhKey: "portal.flow.estimate", zh: "估算", en: "Estimate" },
  { zhKey: "portal.flow.fixture", zh: "租约", en: "Fixture" },
  { zhKey: "portal.flow.execution", zh: "执行", en: "Execution" },
  { zhKey: "portal.flow.demurrage", zh: "滞期", en: "Demurrage" },
  { zhKey: "portal.flow.invoicing", zh: "开票", en: "Invoicing" },
  { zhKey: "portal.flow.settlement", zh: "结算", en: "Settlement" },
];

const ZONES = [
  {
    titleKey: "portal.zone.ops.title",
    title: "商业运营",
    en: "Commercial Operations",
    items: [
      { key: "portal.zone.ops.i1", text: "航次估算与 TCE 日收益测算，佣金、油价、碳成本自动算齐" },
      { key: "portal.zone.ops.i2", text: "租约与条款全流程管理，变更审批留痕" },
      { key: "portal.zone.ops.i3", text: "滞期与速遣索赔，SOF 一键生成计算书" },
      { key: "portal.zone.ops.i4", text: "发票、收款与多币种结算，航次盈亏实时可见" },
    ],
  },
  {
    titleKey: "portal.zone.collab.title",
    title: "协同智能",
    en: "Collaboration",
    items: [
      { key: "portal.zone.collab.i1", text: "角色工作台：今日待办、待审批、岗位动态一屏摆好" },
      { key: "portal.zone.collab.i2", text: "任务分派与进度跟踪，指派自动通知同事" },
      { key: "portal.zone.collab.i3", text: "通知中心未读角标，点击直达业务页面" },
      { key: "portal.zone.collab.i4", text: "新人上手清单与页面操作指引，到岗即上手" },
    ],
  },
  {
    titleKey: "portal.zone.risk.title",
    title: "异常与风控",
    en: "Risk & Exceptions",
    items: [
      { key: "portal.zone.risk.i1", text: "10 类异常主动扫描，严重 / 提醒分级呈现" },
      { key: "portal.zone.risk.i2", text: "索赔时效倒计时，届满前自动预警" },
      { key: "portal.zone.risk.i3", text: "证书到期提前 30 天提醒责任人" },
      { key: "portal.zone.risk.i4", text: "数据质量一键体检，修复自动销号" },
    ],
  },
  {
    titleKey: "portal.zone.gov.title",
    title: "平台治理",
    en: "Platform Governance",
    items: [
      { key: "portal.zone.gov.i1", text: "权限分级与操作留痕，全程可审计" },
      { key: "portal.zone.gov.i2", text: "证书扫描件上传与版本管理，历史可回看" },
      { key: "portal.zone.gov.i3", text: "核心清单一键导出 Excel，衔接既有习惯" },
      { key: "portal.zone.gov.i4", text: "Outlook、Teams 直接集成，不换工作方式" },
    ],
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
          product_name: "MariOS",
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

  const name = brand?.product_name || "MariOS";
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

      <section className="land-hero">
        <div className="land-hero-inner">
          <img className="land-logo" src={brand?.icon_url || "/branding/mark.svg"} alt="" width={64} height={64} />
          <p className="land-eyebrow">
            {t("portal.hero_eyebrow", "The Operating System for Commercial Shipping")}
          </p>
          <h1>{t("portal.hero_tagline", "让每一个航次的商业价值，清晰可见")}</h1>
          <p className="land-lead">
            {t(
              "portal.hero_sub",
              "估算、租约、执行、滞期、开票、结算——为船东、租家、Operator 与船舶管理公司而生的航运商业系统。",
            )}
          </p>
          <div className="land-ctas">
            <Link href="/login" className="btn land-btn land-btn-primary">
              {t("portal.sign_in", "登录")}
            </Link>
            <a className="btn land-btn land-btn-ghost" href="/intro.html">
              {t("portal.cta_intro", "了解详情")}
            </a>
          </div>
        </div>
      </section>

      <section className="land-stats" aria-label="highlights">
        {STATS.map((s) => (
          <div className="land-stat" key={s.labelKey}>
            <b>{s.value}</b>
            <span>{t(s.labelKey, s.label)}</span>
          </div>
        ))}
      </section>

      <section className="land-flow" aria-labelledby="land-flow-h">
        <h2 id="land-flow-h" className="land-h2">
          {t("portal.flow_title", "航次全生命周期，一条主线走到底")}
        </h2>
        <ol className="land-flow-track">
          {LIFECYCLE.map((s, i) => (
            <li className="land-node" key={s.en}>
              <i>{String(i + 1).padStart(2, "0")}</i>
              <strong>{t(s.zhKey, s.zh)}</strong>
              <small>{s.en}</small>
            </li>
          ))}
        </ol>
      </section>

      <section className="land-zones" aria-labelledby="land-zones-h">
        <h2 id="land-zones-h" className="land-h2">
          {t("portal.zones_title", "一套系统，管好航运生意的每一环")}
        </h2>
        <div className="land-zone-grid">
          {ZONES.map((z) => (
            <div className="land-zone" key={z.titleKey}>
              <h3>{t(z.titleKey, z.title)}</h3>
              <p className="land-zone-en">{z.en}</p>
              <ul>
                {z.items.map((item) => (
                  <li key={item.key}>{t(item.key, item.text)}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      <footer className="land-foot">
        <span>
          © {new Date().getFullYear()} {name}
        </span>
        <span className="land-foot-links">
          <a href="/intro.html">{t("portal.cta_intro", "了解详情")}</a>
          <Link href="/login">{t("portal.cta_signin", "登录 →")}</Link>
        </span>
      </footer>
    </div>
  );
}
