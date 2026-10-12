"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

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

function PlatformSaasPage() {
  const { t } = useI18n();
  const toast = useToast();
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
  const [busy, setBusy] = useState(false);
  const [modal, setModal] = useState<"assign" | "credit" | null>(null);

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
    load().catch(() => toast.error(t("page.saas.admin_required", "Platform admin required")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [t]);

  function openAssign() {
    setModal("assign");
  }

  function openCredit() {
    setModal("credit");
  }

  useListHotkeys(openAssign);

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
      toast.success(t("page.saas.assigned", "Plan {plan} assigned to {tenant}", { tenant: res.tenant_code, plan: res.plan_code }));
      setNote("");
      setModal(null);
      await load();
    } catch (err: any) {
      toast.error(String(err?.detail?.message || err?.message || t("common.failed", "Failed")));
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
      toast.success(
        t("page.saas.credited", "Credited {pack} ({qty}) to {tenant}", {
          tenant: res.tenant_code,
          pack: res.pack_code,
          qty: res.quantity,
        }),
      );
      setNote("");
      setModal(null);
      await load();
    } catch (err: any) {
      toast.error(String(err?.detail?.message || err?.message || t("common.failed", "Failed")));
    } finally {
      setBusy(false);
    }
  }

  async function cancelSub() {
    if (!tenantId) return;
    if (!confirm(t("page.saas.cancel_confirm", "Cancel the active subscription for this tenant?"))) return;
    setBusy(true);
    try {
      const res = await apiPost(`/api/v1/platform/saas/tenants/${tenantId}/cancel-subscription`, {});
      toast.success(t("page.saas.cancelled", "Cancelled {n} subscription(s) for {tenant}", { n: res.cancelled, tenant: res.tenant_code }));
      await load();
    } catch {
      toast.error(t("common.failed", "Failed"));
    } finally {
      setBusy(false);
    }
  }

  const subColumns: ColumnDef<SubRow>[] = [
    {
      key: "tenant",
      title: t("page.saas.tenant", "Tenant"),
      minWidth: 180,
      value: (r) => `${r.tenant_code || ""} · ${r.tenant_name || ""}`,
    },
    {
      key: "plan",
      title: t("page.saas.plan", "Plan"),
      minWidth: 160,
      value: (r) => (r.plan ? `${r.plan.name} (${r.plan.code})` : "—"),
    },
    { key: "status", title: t("common.status", "Status"), width: 110, value: (r) => r.status },
    {
      key: "current_period_end",
      title: t("page.billing.renews", "Renews"),
      width: 130,
      value: (r) => r.current_period_end || "—",
    },
  ];

  const planColumns: ColumnDef<Plan>[] = [
    { key: "code", title: t("common.code", "Code"), width: 120, value: (r) => r.code },
    { key: "name", title: t("common.name", "Name"), minWidth: 140, value: (r) => r.name },
    {
      key: "price",
      title: t("page.saas.price", "Price"),
      width: 130,
      value: (r) => `${r.price_amount} / ${r.billing_period}`,
    },
    {
      key: "included_quotas",
      title: t("page.saas.quotas", "Quotas"),
      minWidth: 160,
      value: (r) => JSON.stringify((r as { included_quotas?: Record<string, unknown> }).included_quotas || {}),
      render: (v) => <code>{String(v)}</code>,
    },
  ];

  type MeterRow = Record<string, unknown>;

  const meterColumns: ColumnDef<MeterRow>[] = [
    { key: "code", title: t("common.code", "Code"), width: 130, value: (r) => String(r.code) },
    { key: "name", title: t("common.name", "Name"), minWidth: 150, value: (r) => String(r.name) },
    {
      key: "overage_price",
      title: t("page.saas.overage", "Overage price"),
      width: 140,
      value: (r) => `${String(r.overage_price)} ${String(r.currency)}`,
    },
  ];

  type AiRow = Record<string, unknown>;

  const aiColumns: ColumnDef<AiRow>[] = [
    { key: "code", title: t("common.code", "Code"), width: 130, value: (r) => String(r.code) },
    { key: "model_default", title: t("page.saas.model", "Model"), width: 150, value: (r) => String(r.model_default) },
    { key: "meter_code", title: t("page.saas.meter", "Meter"), width: 130, value: (r) => String(r.meter_code) },
    {
      key: "tokens_per_call_est",
      title: t("page.saas.tokens", "Est. tokens/call"),
      width: 140,
      align: "right",
      value: (r) => String(r.tokens_per_call_est),
    },
  ];

  type ProviderRow = Record<string, unknown>;

  const providerColumns: ColumnDef<ProviderRow>[] = [
    { key: "code", title: t("common.code", "Code"), width: 130, value: (r) => String(r.code) },
    { key: "name", title: t("common.name", "Name"), minWidth: 150, value: (r) => String(r.name) },
    { key: "status", title: t("common.status", "Status"), width: 110, value: (r) => String(r.status) },
  ];

  return (
    <AppShell>
      <PageHeader
        title={t("page.saas.title", "Plans, AI gateway & payments")}
        subtitle={t(
          "page.saas.sub_manage",
          "Until online checkout is live, platform admins assign plans and credit usage packs for tenants.",
        )}
        breadcrumb={[{ label: t("page.platform.title", "Platform"), href: "/platform" }, { label: t("page.saas.title", "Plans, AI gateway & payments") }]}
        actions={
          <Link href="/platform/tenants" className="btn btn-ghost">
            {t("page.saas.tenants_link", "Tenants →")}
          </Link>
        }
      />

      <Toolbar>
        <button type="button" className="btn btn-primary" onClick={openAssign}>
          {t("page.saas.assign_plan", "Assign plan")}
        </button>
        <button type="button" className="btn" onClick={openCredit}>
          {t("page.saas.credit_pack", "Credit pack")}
        </button>
        <button type="button" className="btn btn-ghost" disabled={busy || !tenantId} onClick={() => cancelSub()}>
          {t("page.saas.cancel_sub", "Cancel subscription")}
        </button>
        <button type="button" className="btn btn-sm" onClick={() => load().catch(() => undefined)} title={t("common.refresh", "Refresh")}>
          ↻
        </button>
      </Toolbar>

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
        <h3 style={{ marginTop: 0 }}>{t("page.saas.subs_list", "Tenant subscriptions")}</h3>
        <DataGrid<SubRow>
          columns={subColumns}
          data={subs.slice(0, 40)}
          rowKey={(r) => r.id}
          storageKey="platform_saas_subs_grid"
          emptyText={t("common.none", "None")}
        />
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.saas.plans", "Commercial plan catalog")}</h3>
        <DataGrid<Plan>
          columns={planColumns}
          data={plans}
          rowKey={(r) => r.code}
          storageKey="platform_saas_plans_grid"
          emptyText={t("common.none", "None")}
        />
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.saas.meters", "Meters")}</h3>
        <DataGrid<MeterRow>
          columns={meterColumns}
          data={meters}
          rowKey={(r) => String(r.code)}
          storageKey="platform_saas_meters_grid"
          emptyText={t("common.none", "None")}
        />
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.saas.ai_endpoints", "Platform AI endpoints")}</h3>
        <DataGrid<AiRow>
          columns={aiColumns}
          data={ai}
          rowKey={(r) => String(r.code)}
          storageKey="platform_saas_ai_endpoints_grid"
          emptyText={t("common.none", "None")}
        />
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.saas.payments", "Payment providers")}</h3>
        <p className="muted" style={{ marginTop: 0 }}>
          {t("page.saas.payments_hint", "All providers are unwired; connect checkout & webhooks once online payments go live.")}
        </p>
        <DataGrid<ProviderRow>
          columns={providerColumns}
          data={providers}
          rowKey={(r) => String(r.code)}
          storageKey="platform_saas_payments_grid"
          emptyText={t("common.none", "None")}
        />
      </div>

      <RecordModal
        open={modal === "assign"}
        title={t("page.saas.assign_plan", "Assign plan")}
        onClose={() => setModal(null)}
        onSave={assignPlan}
        saving={busy}
        canDelete={false}
      >
        <div className="form-grid">
          <label>
            {t("page.saas.tenant", "Tenant")}
            <select value={tenantId} onChange={(e) => setTenantId(e.target.value)} required>
              {tenants.map((ten) => (
                <option key={ten.id} value={ten.id}>
                  {ten.code} · {ten.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("page.saas.plan", "Plan")}
            <select value={planCode} onChange={(e) => setPlanCode(e.target.value)} required>
              {plans.map((p) => (
                <option key={p.code} value={p.code}>
                  {p.name} ({p.code}) · {p.price_amount}/{p.billing_period}
                </option>
              ))}
            </select>
          </label>
          <label className="check-row">
            <input type="checkbox" checked={grantQuotas} onChange={(e) => setGrantQuotas(e.target.checked)} />
            {t("page.saas.grant_quotas", "Also grant plan-included quotas")}
          </label>
          <label>
            {t("common.notes", "Note")}
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("page.saas.note_ph", "Offline contract / ticket no.")} />
          </label>
        </div>
      </RecordModal>

      <RecordModal
        open={modal === "credit"}
        title={t("page.saas.credit_pack", "Credit pack")}
        onClose={() => setModal(null)}
        onSave={creditPack}
        saving={busy}
        canDelete={false}
      >
        <div className="form-grid">
          <label>
            {t("page.saas.tenant", "Tenant")}
            <select value={tenantId} onChange={(e) => setTenantId(e.target.value)} required>
              {tenants.map((ten) => (
                <option key={ten.id} value={ten.id}>
                  {ten.code} · {ten.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("page.saas.pack", "Usage pack")}
            <select value={packCode} onChange={(e) => setPackCode(e.target.value)} required>
              {packs.map((p) => (
                <option key={p.code} value={p.code}>
                  {p.name} · {p.meter_code} × {p.quantity}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("common.notes", "Note")}
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("page.saas.note_ph", "Offline contract / ticket no.")} />
          </label>
        </div>
      </RecordModal>
    </AppShell>
  );
}

export default function Page() {
  return <PlatformSaasPage />;
}
