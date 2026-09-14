"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
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
    load().catch(() => setMsg(t("page.billing.admin_required", "需要租户管理员")));
  }, [t]);

  async function invokeAi() {
    const res = await apiPost("/api/v1/billing/ai/invoke-demo");
    setMsg(
      t("page.billing.ai_metered", "AI 计量: -{tokens} tokens，余额 {balance}", {
        tokens: res.tokens_charged,
        balance: res.balance,
      }),
    );
    await load();
  }

  const plan = (sub?.plan || null) as Record<string, unknown> | null;

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("page.billing.title", "订阅与用量")}</h1>
      <p className="page-sub">
        {t(
          "page.billing.sub_readonly",
          "查看当前套餐与用量。订阅与充值由平台管理员开通；线上支付开通后再支持自助下单。",
        )}
      </p>
      {msg ? <p>{msg}</p> : null}

      <div className="panel" style={{ borderLeft: "3px solid var(--accent, #1A9B96)" }}>
        <p style={{ margin: 0 }}>
          {t(
            "page.billing.platform_managed",
            "自助订阅/购买暂未开放。如需变更套餐或充值 AI 用量，请联系平台管理员（sys）。",
          )}{" "}
          <Link href="/help">{t("nav.help", "帮助中心")}</Link>
        </p>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.billing.current", "当前订阅")}</h3>
        {plan ? (
          <p>
            <b>{String(plan.name)}</b> ({String(plan.code)}) · {t("common.status", "状态")} {String(sub?.status)} ·{" "}
            {t("page.billing.renews", "到期")} {String(sub?.current_period_end || "—")}
          </p>
        ) : (
          <p>{t("page.billing.no_sub", "暂无有效订阅")}</p>
        )}
        <button className="btn" type="button" onClick={() => invokeAi().catch((e) => setMsg(String(e)))}>
          {t("page.billing.invoke_ai", "试调用计量 AI（演示）")}
        </button>
      </div>

      <div className="workbench-grid" style={{ marginTop: "1rem" }}>
        {wallet.map((w) => (
          <div key={w.meter_code} className="wb-tile">
            <h3>{w.meter_code}</h3>
            <div className="metric">{w.balance.toLocaleString()}</div>
            <p>{t("page.billing.wallet_balance", "钱包余额")}</p>
          </div>
        ))}
        {!wallet.length ? (
          <div className="wb-tile">
            <h3>—</h3>
            <div className="metric">0</div>
            <p>{t("page.billing.wallet_empty", "尚无用量余额")}</p>
          </div>
        ) : null}
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.billing.plans", "套餐目录（只读）")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.billing.plan", "套餐")}</th>
              <th>{t("page.billing.price", "价格")}</th>
              <th>{t("page.billing.seats", "席位")}</th>
              <th>{t("common.status", "状态")}</th>
            </tr>
          </thead>
          <tbody>
            {plans.map((p) => {
              const current = plan && String(plan.code) === String(p.code) && String(sub?.status) === "active";
              return (
                <tr key={String(p.code)}>
                  <td>
                    <b>{String(p.name)}</b>
                    <div style={{ color: "var(--muted)", fontSize: "0.85rem" }}>{String(p.description || "")}</div>
                  </td>
                  <td>
                    {String(p.price_amount)} {String(p.currency)} / {String(p.billing_period)}
                  </td>
                  <td>{p.seat_limit == null ? t("page.billing.unlimited", "不限") : String(p.seat_limit)}</td>
                  <td>
                    {current ? (
                      <span className="badge">{t("page.billing.current_badge", "当前套餐")}</span>
                    ) : (
                      <span className="muted">{t("page.billing.contact_platform", "联系平台开通")}</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.billing.packs", "用量包目录（只读）")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.billing.pack", "用量包")}</th>
              <th>{t("page.billing.meter", "计量项")}</th>
              <th>{t("page.billing.qty", "数量")}</th>
              <th>{t("page.billing.price", "价格")}</th>
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
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.billing.ledger", "用量流水")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.billing.meter", "计量项")}</th>
              <th>{t("page.billing.dir", "方向")}</th>
              <th>{t("page.billing.qty", "数量")}</th>
              <th>{t("common.notes", "备注")}</th>
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
            {!usage.length ? (
              <tr>
                <td colSpan={4} className="muted">
                  {t("common.none", "无")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
