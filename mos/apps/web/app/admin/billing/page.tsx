"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function BillingPage() {
  const { t } = useI18n();
  const [sub, setSub] = useState<Record<string, unknown> | null>(null);
  const [plans, setPlans] = useState<Array<Record<string, unknown>>>([]);
  const [packs, setPacks] = useState<Array<Record<string, unknown>>>([]);
  const [wallet, setWallet] = useState<Array<{ meter_code: string; balance: number }>>([]);
  const [usage, setUsage] = useState<Array<Record<string, unknown>>>([]);
  const [msg, setMsg] = useState("");

  async function load() {
    const [s, p, pk, w, u] = await Promise.all([
      apiGet("/api/v1/billing/subscription"),
      apiGet("/api/v1/platform/saas/plans"),
      apiGet("/api/v1/platform/saas/packs"),
      apiGet("/api/v1/billing/wallet"),
      apiGet("/api/v1/billing/usage"),
    ]);
    setSub(s);
    setPlans(p);
    setPacks(pk);
    setWallet(w);
    setUsage(u);
  }

  useEffect(() => {
    load().catch(() => setMsg(t("page.billing.admin_required", "Tenant admin required")));
  }, [t]);

  async function subscribe(plan_code: string) {
    const order = await apiPost("/api/v1/billing/subscribe", { plan_code, provider_code: "manual" });
    await apiPost(`/api/v1/billing/orders/${order.order_id}/confirm-paid`);
    setMsg(t("page.billing.subscribed", "Subscribed to {plan}", { plan: plan_code }));
    await load();
  }

  async function topup(pack_code: string) {
    const order = await apiPost("/api/v1/billing/topup", { pack_code, provider_code: "manual" });
    await apiPost(`/api/v1/billing/orders/${order.order_id}/confirm-paid`);
    setMsg(t("page.billing.topped", "Topped up {pack}", { pack: pack_code }));
    await load();
  }

  async function invokeAi() {
    const res = await apiPost("/api/v1/billing/ai/invoke-demo");
    setMsg(t("page.billing.ai_metered", "AI metered: -{tokens} tokens, balance {balance}", { tokens: res.tokens_charged, balance: res.balance }));
    await load();
  }

  const plan = (sub?.plan || null) as Record<string, unknown> | null;

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("page.billing.title", "Subscription & usage")}</h1>
      <p className="page-sub">{t("page.billing.sub", "Plans, AI packs, wallet and ledger.")}</p>
      {msg ? <p>{msg}</p> : null}

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.billing.current", "Current subscription")}</h3>
        {plan ? (
          <p>
            <b>{String(plan.name)}</b> ({String(plan.code)}) · {t("common.status", "Status")} {String(sub?.status)} ·{" "}
            {t("page.billing.renews", "renews")} {String(sub?.current_period_end || "—")}
          </p>
        ) : (
          <p>{t("page.billing.no_sub", "No active subscription")}</p>
        )}
        <button className="btn" type="button" onClick={() => invokeAi().catch((e) => setMsg(String(e)))}>
          {t("page.billing.invoke_ai", "Invoke metered AI (demo)")}
        </button>
      </div>

      <div className="workbench-grid" style={{ marginTop: "1rem" }}>
        {wallet.map((w) => (
          <div key={w.meter_code} className="wb-tile">
            <h3>{w.meter_code}</h3>
            <div className="metric">{w.balance.toLocaleString()}</div>
            <p>{t("page.billing.wallet_balance", "Wallet balance")}</p>
          </div>
        ))}
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.billing.plans", "Plans")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.billing.plan", "Plan")}</th>
              <th>{t("page.billing.price", "Price")}</th>
              <th>{t("page.billing.seats", "Seats")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {plans.map((p) => (
              <tr key={String(p.code)}>
                <td>
                  <b>{String(p.name)}</b>
                  <div style={{ color: "var(--muted)", fontSize: "0.85rem" }}>{String(p.description || "")}</div>
                </td>
                <td>
                  {String(p.price_amount)} {String(p.currency)} / {String(p.billing_period)}
                </td>
                <td>{p.seat_limit == null ? t("page.billing.unlimited", "Unlimited") : String(p.seat_limit)}</td>
                <td>
                  <button
                    className="btn btn-primary"
                    type="button"
                    onClick={() => subscribe(String(p.code)).catch(() => setMsg(t("page.billing.subscribe_fail", "Subscribe failed")))}
                  >
                    {t("page.billing.subscribe", "Subscribe")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.billing.packs", "Usage top-up packs")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.billing.pack", "Pack")}</th>
              <th>{t("page.billing.meter", "Meter")}</th>
              <th>{t("page.billing.qty", "Qty")}</th>
              <th>{t("page.billing.price", "Price")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {packs.map((p) => (
              <tr key={String(p.code)}>
                <td>{String(p.name)}</td>
                <td>{String(p.meter_code)}</td>
                <td>{String(p.quantity)}</td>
                <td>
                  {String(p.price_amount)} {String(p.currency)}
                </td>
                <td>
                  <button className="btn" type="button" onClick={() => topup(String(p.code)).catch(() => setMsg(t("page.billing.topup_fail", "Top-up failed")))}>
                    {t("page.billing.buy", "Buy")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.billing.ledger", "Usage ledger")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.billing.meter", "Meter")}</th>
              <th>{t("page.billing.dir", "Dir")}</th>
              <th>{t("page.billing.qty", "Qty")}</th>
              <th>{t("common.notes", "Notes")}</th>
            </tr>
          </thead>
          <tbody>
            {usage.slice(0, 20).map((u, i) => (
              <tr key={i}>
                <td>{String(u.meter_code)}</td>
                <td>{String(u.direction)}</td>
                <td>{String(u.quantity)}</td>
                <td>{String(u.note || "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
