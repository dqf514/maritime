"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function PlatformSaasPage() {
  const { t } = useI18n();
  const [overview, setOverview] = useState<Record<string, unknown> | null>(null);
  const [plans, setPlans] = useState<Array<Record<string, unknown>>>([]);
  const [meters, setMeters] = useState<Array<Record<string, unknown>>>([]);
  const [ai, setAi] = useState<Array<Record<string, unknown>>>([]);
  const [providers, setProviders] = useState<Array<Record<string, unknown>>>([]);

  useEffect(() => {
    Promise.all([
      apiGet("/api/v1/platform/saas/overview"),
      apiGet("/api/v1/platform/saas/plans"),
      apiGet("/api/v1/platform/saas/meters"),
      apiGet("/api/v1/platform/saas/ai-endpoints"),
      apiGet("/api/v1/platform/saas/payments/providers"),
    ])
      .then(([o, p, m, a, pay]) => {
        setOverview(o);
        setPlans(p);
        setMeters(m);
        setAi(a);
        setProviders(pay);
      })
      .catch(() => undefined);
  }, []);

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.saas.title", "Plans, AI gateway & payments")}</h1>
          <p className="page-sub">{t("page.saas.sub", "Commercial catalog for the SaaS control plane.")}</p>
        </div>
        <Link href="/platform/tenants" className="btn btn-ghost">
          {t("page.saas.tenants_link", "Tenants →")}
        </Link>
      </div>

      <div className="workbench-grid">
        <div className="wb-tile">
          <h3>{t("page.saas.active_subs", "Active subscriptions")}</h3>
          <div className="metric">{String(overview?.active_subscriptions ?? "—")}</div>
        </div>
        <div className="wb-tile">
          <h3>{t("page.saas.mrr", "MRR estimate")}</h3>
          <div className="metric">{String(overview?.mrr_estimate ?? "—")}</div>
        </div>
        <div className="wb-tile">
          <h3>{t("page.saas.paid_vol", "Paid volume")}</h3>
          <div className="metric">{String(overview?.paid_volume ?? "—")}</div>
        </div>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.saas.plans", "Commercial plans")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.code", "Code")}</th>
              <th>{t("common.name", "Name")}</th>
              <th>{t("page.saas.price", "Price")}</th>
              <th>{t("page.saas.quotas", "Quotas")}</th>
            </tr>
          </thead>
          <tbody>
            {plans.map((p) => (
              <tr key={String(p.code)}>
                <td>{String(p.code)}</td>
                <td>{String(p.name)}</td>
                <td>
                  {String(p.price_amount)} / {String(p.billing_period)}
                </td>
                <td>
                  <code>{JSON.stringify(p.included_quotas)}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.saas.meters", "Usage meters")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.code", "Code")}</th>
              <th>{t("common.name", "Name")}</th>
              <th>{t("page.saas.overage", "Overage")}</th>
            </tr>
          </thead>
          <tbody>
            {meters.map((m) => (
              <tr key={String(m.code)}>
                <td>{String(m.code)}</td>
                <td>{String(m.name)}</td>
                <td>
                  {String(m.overage_price)} {String(m.currency)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.saas.ai_endpoints", "Platform AI endpoints")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.code", "Code")}</th>
              <th>{t("page.saas.model", "Model")}</th>
              <th>{t("page.saas.meter", "Meter")}</th>
              <th>{t("page.saas.tokens", "Est tokens/call")}</th>
            </tr>
          </thead>
          <tbody>
            {ai.map((a) => (
              <tr key={String(a.code)}>
                <td>{String(a.code)}</td>
                <td>{String(a.model_default)}</td>
                <td>{String(a.meter_code)}</td>
                <td>{String(a.tokens_per_call_est)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.saas.payments", "Payment providers")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.code", "Code")}</th>
              <th>{t("common.name", "Name")}</th>
              <th>{t("common.status", "Status")}</th>
            </tr>
          </thead>
          <tbody>
            {providers.map((p) => (
              <tr key={String(p.code)}>
                <td>{String(p.code)}</td>
                <td>{String(p.name)}</td>
                <td>{String(p.status)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
