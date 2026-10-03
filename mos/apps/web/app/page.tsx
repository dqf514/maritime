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
  { value: "7 环", labelKey: "portal.stat.lifecycle", label: { en: "Voyage lifecycle coverage", zh: "航次全生命周期覆盖" } },
  { value: "10 类", labelKey: "portal.stat.exceptions", label: { en: "Exception types monitored", zh: "异常风险主动监控" } },
  { value: "30 秒", labelKey: "portal.stat.estimate", label: { en: "To complete a voyage estimate", zh: "完成一次航次估算" } },
  { value: "12 种", labelKey: "portal.stat.sof", label: { en: "Port event types recognized", zh: "港口事件自动识别" } },
];

const LIFECYCLE = [
  { zhKey: "portal.flow.estimate", zh: { en: "Estimate", zh: "估算" }, en: "Estimate" },
  { zhKey: "portal.flow.fixture", zh: { en: "Fixture", zh: "租约" }, en: "Fixture" },
  { zhKey: "portal.flow.execution", zh: { en: "Execution", zh: "执行" }, en: "Execution" },
  { zhKey: "portal.flow.demurrage", zh: { en: "Demurrage", zh: "滞期" }, en: "Demurrage" },
  { zhKey: "portal.flow.invoicing", zh: { en: "Invoicing", zh: "开票" }, en: "Invoicing" },
  { zhKey: "portal.flow.settlement", zh: { en: "Settlement", zh: "结算" }, en: "Settlement" },
];

const ZONES = [
  {
    titleKey: "portal.zone.ops.title",
    title: { en: "Commercial Operations", zh: "商业运营" },
    en: "Commercial Operations",
    items: [
      { key: "portal.zone.ops.i1", text: { en: "Voyage estimate & TCE calculation with commission, bunker and carbon costs", zh: "航次估算与 TCE 日收益测算，佣金、油价、碳成本自动算齐" } },
      { key: "portal.zone.ops.i2", text: { en: "Fixture and clause management with full audit trail", zh: "租约与条款全流程管理，变更审批留痕" } },
      { key: "portal.zone.ops.i3", text: { en: "Demurrage, despatch and performance claims — good weather evaluation, about tolerance analysis, one-click SOF statement", zh: "滞期、速遣与航速绩效索赔——好天气评估、about 容差分析，SOF 一键生成计算书" } },
      { key: "portal.zone.ops.i4", text: { en: "Clause-aware NOR delivery validation, invoicing and multi-currency settlement with live P&L", zh: "NOR 递交条件按条款校验，开票、收款与多币种结算，航次盈亏实时可见" } },
    ],
  },
  {
    titleKey: "portal.zone.collab.title",
    title: { en: "Collaboration & AI", zh: "协同智能" },
    en: "Collaboration & AI",
    items: [
      { key: "portal.zone.collab.i1", text: { en: "Role workbench: today's tasks, approvals and role updates in one screen", zh: "角色工作台：今日待办、待审批、岗位动态一屏摆好" } },
      { key: "portal.zone.collab.i2", text: { en: "Task assignment and progress tracking with notification center alerts", zh: "任务分派与进度跟踪，通知中心自动提醒、点击直达业务页面" } },
      { key: "portal.zone.collab.i3", text: { en: "MariAI assistant and smart actions — laytime statements and voyage instructions drafted from live data", zh: "MariAI 智能助手与智能动作——计算书、航次指令按业务数据自动起草" } },
      { key: "portal.zone.collab.i4", text: { en: "Email intelligence and LLM document extraction — fixture recaps, NORs and statements parsed into records", zh: "邮件智能与 LLM 单据抽取——recap、NOR、计算书自动解析入库" } },
    ],
  },
  {
    titleKey: "portal.zone.risk.title",
    title: { en: "Risk & Exceptions", zh: "异常与风控" },
    en: "Risk & Exceptions",
    items: [
      { key: "portal.zone.risk.i1", text: { en: "10 exception types with severity levels", zh: "10 类异常主动扫描，严重 / 提醒分级呈现" } },
      { key: "portal.zone.risk.i2", text: { en: "Claim deadline countdown with auto alerts", zh: "索赔时效倒计时，届满前自动预警" } },
      { key: "portal.zone.risk.i3", text: { en: "Sanctions screening and counterparty credit limit monitoring", zh: "制裁名单筛查与客户信用额度监控，超限即时告警" } },
      { key: "portal.zone.risk.i4", text: { en: "Certificate expiry reminder 30 days ahead", zh: "证书到期提前 30 天提醒责任人" } },
    ],
  },
  {
    titleKey: "portal.zone.analytics.title",
    title: { en: "Analytics & Twin", zh: "分析与数字孪生" },
    en: "Analytics & Twin",
    items: [
      { key: "portal.zone.analytics.i1", text: { en: "Voyage P&L and reporting — revenue, hire, bunker, port and emissions in one view", zh: "航次盈亏与报表——收入、租金、油耗、港口费、排放一屏算清" } },
      { key: "portal.zone.analytics.i2", text: { en: "Market data: freight rates, bunker prices, distance and ETA services", zh: "市场数据：运价、油价、距离与 ETA 服务随取随用" } },
      { key: "portal.zone.analytics.i3", text: { en: "Emissions & CII: carbon calculator, EU ETS, CII rating and carbon cost allocation", zh: "碳排放与 CII：碳成本测算、EU ETS、CII 评级与碳成本分摊" } },
      { key: "portal.zone.analytics.i4", text: { en: "Fleet digital twin with what-if simulation on speed and TCE", zh: "船队数字孪生，航速与 TCE 一键推演" } },
    ],
  },
  {
    titleKey: "portal.zone.gov.title",
    title: { en: "Platform Governance", zh: "平台治理" },
    en: "Platform Governance",
    items: [
      { key: "portal.zone.gov.i1", text: { en: "Role-based permissions with full audit trail", zh: "权限分级与操作留痕，全程可审计" } },
      { key: "portal.zone.gov.i2", text: { en: "PrintDoc PDF export with company header and one-click Excel export for core lists", zh: "PrintDoc 公司抬头专业打印导出，核心清单一键导出 Excel" } },
      { key: "portal.zone.gov.i3", text: { en: "Ctrl+K OmniSearch, saved views and bulk operations — column visibility, bulk CSV export, inline editing", zh: "Ctrl+K 全局搜索、常用视图与批量操作——列显隐、批量导出 CSV、行内编辑" } },
      { key: "portal.zone.gov.i4", text: { en: "Outlook and Teams integration, no workflow change", zh: "Outlook、Teams 直接集成，不换工作方式" } },
    ],
  },
  {
    titleKey: "portal.zone.data.title",
    title: { en: "Data & Integration", zh: "数据与集成" },
    en: "Data & Integration",
    items: [
      { key: "portal.zone.data.i1", text: { en: "Background jobs and webhooks — async processing and external notifications", zh: "后台作业与 Webhook——异步处理，外部系统实时通知" } },
      { key: "portal.zone.data.i2", text: { en: "Data quality SelfCheck — automated data health checks with auto-fix", zh: "数据质量 SelfCheck——自动体检，修复销号" } },
      { key: "portal.zone.data.i3", text: { en: "Port cost benchmarking against historical disbursement costs", zh: "港口使费对标历史 PDA 成本，高低一眼看清" } },
      { key: "portal.zone.data.i4", text: { en: "Clause library: 10 system clause templates, tenant custom clauses and parameter materialization", zh: "条款库：10 条系统条款模板、租户自定义条款，参数物化直通计算引擎" } },
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
          <h1>{t("portal.hero_tagline", { en: "Make every voyage's commercial value visible", zh: "让每一个航次的商业价值，清晰可见" })}</h1>
          <p className="land-lead">
            {t(
              "portal.hero_sub",
              {
                en: "Estimate, fixture, execution, demurrage, invoicing, settlement — a commercial shipping system built for owners, charterers, operators and ship managers.",
                zh: "估算、租约、执行、滞期、开票、结算——为船东、租家、Operator 与船舶管理公司而生的航运商业系统。",
              },
            )}
          </p>
          <div className="land-ctas">
            <Link href="/login" className="btn land-btn land-btn-primary">
              {t("portal.sign_in", "Sign in")}
            </Link>
            <a className="btn land-btn land-btn-ghost" href="/intro.html">
              {t("portal.cta_intro", "Learn more")}
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
          {t("portal.flow_title", { en: "Voyage lifecycle, one continuous thread", zh: "航次全生命周期，一条主线走到底" })}
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
          {t("portal.zones_title", { en: "One system to manage every link of your shipping business", zh: "一套系统，管好航运生意的每一环" })}
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
          <a href="/intro.html">{t("portal.cta_intro", { en: "Learn more", zh: "了解详情" })}</a>
          <Link href="/login">{t("portal.cta_signin", { en: "Sign in →", zh: "登录 →" })}</Link>
        </span>
      </footer>
    </div>
  );
}
