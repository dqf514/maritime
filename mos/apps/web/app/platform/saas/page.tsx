"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Tenant = { id: string; code: string; name: string };
type Plan = { code: string; name: string; price_amount: number; billing_period: string };
type Pack = { code: string; name: string; meter_code: string; quantity: number; price_amount: number };
type SubRow = {
  id: string;
  tenant_id: string;
  tenant_code: string | null;
  tenant_name: string | null;
  status: string;
  current_period_end: string | null;
  plan: { code: string; name: string } | null;
};

export default function PlatformSaasPage() {
  const { t } = useI18n();
  const [overview, setOverview] = useState<Record<string, unknown> | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [packs, setPacks] = useState<Pack[]>([]);
  const [meters, setMeters] = useState<Array<Record<string, unknown>>>([]);
  const [ai, setAi] = useState<Array<Record<string, unknown>>>([]);
  const [providers, setProviders] = useState<Array<Record<string, unknown>>>([]);
  const [subs, setSubs] = useState<SubRow[]>([]);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [tenantId, setTenantId] = useState("");
  const [planCode, setPlanCode] = useState("");
  const [packCode, setPackCode] = useState("");
  const [grantQuotas, setGrantQuotas] = useState(true);
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    const [o, p, pk, m, a, pay, s, ten] = await Promise.all([
      apiGet("/api/v1/platform/saas/overview"),
      apiGet("/api/v1/platform/saas/plans"),
      apiGet("/api/v1/platform/saas/packs"),
      apiGet("/api/v1/platform/saas/meters"),
      apiGet("/api/v1/platform/saas/ai-endpoints"),
      apiGet("/api/v1/platform/saas/payments/providers"),
      apiGet("/api/v1/platform/saas/subscriptions"),
      apiGet("/api/v1/platform/tenants"),
    ]);
    setOverview(o);
    setPlans(p);
    setPacks(pk);
    setMeters(m);
    setAi(a);
    setProviders(pay);
    setSubs(s);
    setTenants(ten);
    if (!tenantId && ten.length) setTenantId(ten.find((x: Tenant) => x.code === "demo")?.id || ten[0].id);
    if (!planCode && p.length) setPlanCode(p[0].code);
    if (!packCode && pk.length) setPackCode(pk[0].code);
  }

  useEffect(() => {
    load().catch(() => setMsg(t("page.saas.admin_required", "需要平台管理员")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [t]);

  async function assignPlan(e: FormEvent) {
    e.preventDefault();
    if (!tenantId || !planCode) return;
    setBusy(true);
    try {
      const res = await apiPost(`/api/v1/platform/saas/tenants/${tenantId}/assign-plan`, {
        plan_code: planCode,
        grant_quotas: grantQuotas,
        note: note || null,
      });
      setMsg(t("page.saas.assigned", "已为 {tenant} 开通套餐 {plan}", { tenant: res.tenant_code, plan: res.plan_code }));
      setNote("");
      await load();
    } catch (err: any) {
      setMsg(String(err?.detail?.message || err?.message || t("common.failed", "失败")));
    } finally {
      setBusy(false);
    }
  }

  async function creditPack(e: FormEvent) {
    e.preventDefault();
    if (!tenantId || !packCode) return;
    setBusy(true);
    try {
      const res = await apiPost(`/api/v1/platform/saas/tenants/${tenantId}/credit-pack`, {
        pack_code: packCode,
        note: note || null,
      });
      setMsg(
        t("page.saas.credited", "已为 {tenant} 充值 {pack}（{qty}）", {
          tenant: res.tenant_code,
          pack: res.pack_code,
          qty: res.quantity,
        }),
      );
      setNote("");
      await load();
    } catch (err: any) {
      setMsg(String(err?.detail?.message || err?.message || t("common.failed", "失败")));
    } finally {
      setBusy(false);
    }
  }

  async function cancelSub() {
    if (!tenantId) return;
    if (!confirm(t("page.saas.cancel_confirm", "确认取消该租户当前有效订阅？"))) return;
    setBusy(true);
    try {
      const res = await apiPost(`/api/v1/platform/saas/tenants/${tenantId}/cancel-subscription`, {});
      setMsg(t("page.saas.cancelled", "已取消 {n} 条订阅（{tenant}）", { n: res.cancelled, tenant: res.tenant_code }));
      await load();
    } catch {
      setMsg(t("common.failed", "失败"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.saas.title", "套餐、AI 网关与支付")}</h1>
          <p className="page-sub">
            {t(
              "page.saas.sub_manage",
              "线上支付未开通前，由平台管理员为租户分配套餐与充值用量包。",
            )}
          </p>
        </div>
        <Link href="/platform/tenants" className="btn btn-ghost">
          {t("page.saas.tenants_link", "租户 →")}
        </Link>
      </div>
      {msg ? <p className="flash">{msg}</p> : null}

      <div className="workbench-grid">
        <div className="wb-tile">
          <h3>{t("page.saas.active_subs", "有效订阅")}</h3>
          <div className="metric">{String(overview?.active_subscriptions ?? "—")}</div>
        </div>
        <div className="wb-tile">
          <h3>{t("page.saas.mrr", "MRR 估算")}</h3>
          <div className="metric">{String(overview?.mrr_estimate ?? "—")}</div>
        </div>
        <div className="wb-tile">
          <h3>{t("page.saas.paid_vol", "已入账金额")}</h3>
          <div className="metric">{String(overview?.paid_volume ?? "—")}</div>
        </div>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.saas.assign_title", "为租户开通 / 充值")}</h3>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end", marginBottom: "0.75rem" }}>
          <label>
            {t("page.saas.tenant", "租户")}
            <select value={tenantId} onChange={(e) => setTenantId(e.target.value)}>
              {tenants.map((ten) => (
                <option key={ten.id} value={ten.id}>
                  {ten.code} · {ten.name}
                </option>
              ))}
            </select>
          </label>
          <label style={{ flex: 1, minWidth: 180 }}>
            {t("common.notes", "备注")}
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("page.saas.note_ph", "线下合同 / 工单号")} />
          </label>
        </div>
        <form
          onSubmit={assignPlan}
          style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end", marginBottom: "0.75rem" }}
        >
          <label>
            {t("page.saas.plan", "套餐")}
            <select value={planCode} onChange={(e) => setPlanCode(e.target.value)}>
              {plans.map((p) => (
                <option key={p.code} value={p.code}>
                  {p.name} ({p.code}) · {p.price_amount}/{p.billing_period}
                </option>
              ))}
            </select>
          </label>
          <label className="check-row">
            <input type="checkbox" checked={grantQuotas} onChange={(e) => setGrantQuotas(e.target.checked)} />
            {t("page.saas.grant_quotas", "同时发放套餐内配额")}
          </label>
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {t("page.saas.assign_plan", "开通套餐")}
          </button>
          <button className="btn btn-ghost" type="button" disabled={busy} onClick={() => cancelSub()}>
            {t("page.saas.cancel_sub", "取消当前订阅")}
          </button>
        </form>
        <form onSubmit={creditPack} style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
          <label>
            {t("page.saas.pack", "用量包")}
            <select value={packCode} onChange={(e) => setPackCode(e.target.value)}>
              {packs.map((p) => (
                <option key={p.code} value={p.code}>
                  {p.name} · {p.meter_code} × {p.quantity}
                </option>
              ))}
            </select>
          </label>
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {t("page.saas.credit_pack", "充值用量包")}
          </button>
        </form>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.saas.subs_list", "租户订阅")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.saas.tenant", "租户")}</th>
              <th>{t("page.saas.plan", "套餐")}</th>
              <th>{t("common.status", "状态")}</th>
              <th>{t("page.billing.renews", "到期")}</th>
            </tr>
          </thead>
          <tbody>
            {subs.slice(0, 40).map((s) => (
              <tr key={s.id}>
                <td>
                  {s.tenant_code} · {s.tenant_name}
                </td>
                <td>{s.plan ? `${s.plan.name} (${s.plan.code})` : "—"}</td>
                <td>{s.status}</td>
                <td>{s.current_period_end || "—"}</td>
              </tr>
            ))}
            {!subs.length ? (
              <tr>
                <td colSpan={4} className="muted">
                  {t("common.none", "无")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.saas.plans", "商业套餐目录")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.code", "编码")}</th>
              <th>{t("common.name", "名称")}</th>
              <th>{t("page.saas.price", "价格")}</th>
              <th>{t("page.saas.quotas", "配额")}</th>
            </tr>
          </thead>
          <tbody>
            {plans.map((p) => (
              <tr key={p.code}>
                <td>{p.code}</td>
                <td>{p.name}</td>
                <td>
                  {p.price_amount} / {p.billing_period}
                </td>
                <td>
                  <code>{JSON.stringify((p as any).included_quotas || {})}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.saas.meters", "计量项")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.code", "编码")}</th>
              <th>{t("common.name", "名称")}</th>
              <th>{t("page.saas.overage", "超限单价")}</th>
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
        <h3 style={{ marginTop: 0 }}>{t("page.saas.ai_endpoints", "平台 AI 端点")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.code", "编码")}</th>
              <th>{t("page.saas.model", "模型")}</th>
              <th>{t("page.saas.meter", "计量")}</th>
              <th>{t("page.saas.tokens", "预估 tokens/次")}</th>
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
        <h3 style={{ marginTop: 0 }}>{t("page.saas.payments", "支付通道")}</h3>
        <p className="muted" style={{ marginTop: 0 }}>
          {t("page.saas.payments_hint", "目前均为未接线状态；开通线上支付后再对接收银台与 webhook。")}
        </p>
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.code", "编码")}</th>
              <th>{t("common.name", "名称")}</th>
              <th>{t("common.status", "状态")}</th>
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
