"use client";

import { RefreshButton } from "@/components/RefreshButton";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { StateView } from "@/components/StateView";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { RowActions } from "@/components/RowActions";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type Tenant = { id: string; code: string; name: string };
type Plan = {
  id: string;
  code: string;
  name: string;
  price_amount: number;
  billing_period: string;
  currency: string;
  seat_limit: number | null;
  included_quotas?: Record<string, unknown>;
};
type Pack = {
  id: string;
  code: string;
  name: string;
  meter_code: string;
  quantity: number;
  price_amount: number;
  currency: string;
};
type AiRow = {
  id: string;
  code: string;
  name: string;
  provider_type: string;
  model_default: string | null;
  meter_code: string;
  tokens_per_call_est: number;
  status: string;
};
type SubRow = {
  id: string;
  tenant_id: string;
  tenant_code: string | null;
  tenant_name: string | null;
  status: string;
  current_period_end: string | null;
  plan: { code: string; name: string } | null;
};

/** 金额千分位 + 币种（套餐目录以 USD 计价）；无法解析时原样返回 */
function money(v: unknown): string {
  const n = typeof v === "number" ? v : Number(v);
  if (v == null || v === "") return "—";
  if (!Number.isFinite(n)) return String(v);
  return `${n.toLocaleString("en-US", { maximumFractionDigits: 2 })} USD`;
}

/** 500000 → "500k"、5000000 → "5M"（配额紧凑显示；其余原样） */
function compactNum(v: unknown): string {
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return String(v ?? "");
  if (Math.abs(n) >= 1_000_000_000) return `${trim(n / 1_000_000_000)}B`;
  if (Math.abs(n) >= 1_000_000) return `${trim(n / 1_000_000)}M`;
  if (Math.abs(n) >= 1_000) return `${trim(n / 1_000)}k`;
  return String(n);
  function trim(x: number): string {
    return String(Math.round(x * 10) / 10);
  }
}

function PlatformSaasPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [overview, setOverview] = useState<Record<string, unknown> | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [packs, setPacks] = useState<Pack[]>([]);
  const [meters, setMeters] = useState<Array<Record<string, unknown>>>([]);
  const [ai, setAi] = useState<AiRow[]>([]);
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
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [pending, setPending] = useState<{ message: string; danger?: boolean; action: () => void } | null>(null);
  /** 订阅列表客户端分页（后端一次返回全量；总数始终可见，不静默截断） */
  const [subPage, setSubPage] = useState(1);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
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
    } catch (ex) {
      setErr(msgOf(ex, t("page.saas.admin_required", "Platform admin required")));
    } finally {
      setLoading(false);
    }
  }, [tenantId, planCode, packCode, t]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [t]);

  function openAssign() {
    setModal("assign");
  }

  function openCredit() {
    setModal("credit");
  }

  useListHotkeys(openAssign);

  // ── 订阅列表客户端分页：总数常显，不做静默 slice ──
  const SUB_PAGE_SIZE = 40;
  const subPages = Math.max(1, Math.ceil(subs.length / SUB_PAGE_SIZE));
  const subPageSafe = Math.min(Math.max(1, subPage), subPages);
  const subRows = subs.slice((subPageSafe - 1) * SUB_PAGE_SIZE, subPageSafe * SUB_PAGE_SIZE);

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
      toast.error(msgOf(err, t("common.failed", "Failed")));
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
      toast.error(msgOf(err, t("common.failed", "Failed")));
    } finally {
      setBusy(false);
    }
  }

  async function cancelSub() {
    if (!tenantId) return;
    setBusy(true);
    try {
      const res = await apiPost(`/api/v1/platform/saas/tenants/${tenantId}/cancel-subscription`, {});
      toast.success(t("page.saas.cancelled", "Cancelled {n} subscription(s) for {tenant}", { n: res.cancelled, tenant: res.tenant_code }));
      await load();
    } catch (ex) {
      toast.error(msgOf(ex, t("common.failed", "Failed")));
    } finally {
      setBusy(false);
    }
  }

  /** 取消订阅属不可逆操作 → ConfirmDialog 二次确认，指名租户 */
  function askCancelSub() {
    if (!tenantId) return;
    const tn = tenants.find((x) => x.id === tenantId);
    const name = tn ? `${tn.code} · ${tn.name}` : tenantId;
    setPending({
      message: t(
        "page.saas.cancel_confirm",
        "取消租户「{tenant}」的生效订阅？该操作不可撤销。",
        { tenant: name },
      ),
      danger: true,
      action: () => {
        cancelSub().catch((ex) => toast.error(msgOf(ex, t("common.failed", "Failed"))));
      },
    });
  }

  // ── 行内编辑：值未变化不发请求，避免 blur→reload 打断输入 ──
  function dirtyEq(prev: unknown, next: unknown): boolean {
    if (typeof prev === "number" || typeof next === "number") {
      const a = prev === null || prev === "" || prev === undefined ? null : Number(prev);
      const b = next === null || next === "" || next === undefined ? null : Number(next);
      return a === b || (a !== null && b !== null && isNaN(a) && isNaN(b));
    }
    return (prev ?? "") === (next ?? "");
  }

  async function patchCell(
    path: string,
    colKey: string,
    value: unknown,
    row: Record<string, unknown>,
    numericKeys: string[] = [],
  ) {
    if (dirtyEq(row[colKey], value)) return;
    const isNum = numericKeys.includes(colKey);
    const next = isNum
      ? value === null || value === ""
        ? null
        : Number(value)
      : value === ""
        ? null
        : value;
    if (isNum && next !== null && isNaN(next as number)) return;
    try {
      await apiPatch(path, { [colKey]: next });
      toast.success(t("common.saved", "Saved"));
      await load();
    } catch (ex: any) {
      toast.error(msgOf(ex, t("common.failed", "Failed")));
    }
  }

  async function onPlanCellSave(rowId: string, colKey: string, value: unknown, row: Plan) {
    await patchCell(`/api/v1/platform/saas/plans/${rowId}`, colKey, value, row as unknown as Record<string, unknown>, [
      "price_amount",
      "seat_limit",
    ]);
  }

  const deletePlan = useCallback(async (row: Plan) => {
    try {
      await apiDelete(`/api/v1/platform/saas/plans/${row.id}`);
      toast.success(t("common.deleted", "Deleted"));
      await load();
    } catch (ex: any) {
      toast.error(msgOf(ex, t("common.failed", "Failed")));
    }
  }, [load, t, toast]);

  async function onPackCellSave(rowId: string, colKey: string, value: unknown, row: Pack) {
    await patchCell(`/api/v1/platform/saas/packs/${rowId}`, colKey, value, row as unknown as Record<string, unknown>, [
      "quantity",
      "price_amount",
    ]);
  }

  const deletePackRow = useCallback(async (row: Pack) => {
    try {
      await apiDelete(`/api/v1/platform/saas/packs/${row.id}`);
      toast.success(t("common.deleted", "Deleted"));
      await load();
    } catch (ex: any) {
      toast.error(msgOf(ex, t("common.failed", "Failed")));
    }
  }, [load, t, toast]);

  async function onAiCellSave(rowId: string, colKey: string, value: unknown, row: AiRow) {
    await patchCell(`/api/v1/platform/saas/ai-endpoints/${rowId}`, colKey, value, row as unknown as Record<string, unknown>, [
      "tokens_per_call_est",
    ]);
  }

  const deleteAi = useCallback(async (row: AiRow) => {
    try {
      await apiDelete(`/api/v1/platform/saas/ai-endpoints/${row.id}`);
      toast.success(t("common.deleted", "Deleted"));
      await load();
    } catch (ex: any) {
      toast.error(msgOf(ex, t("common.failed", "Failed")));
    }
  }, [load, t, toast]);

  const subColumns = useMemo<ColumnDef<SubRow>[]>(() => [
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
    {
      key: "status",
      title: t("common.status", "Status"),
      width: 110,
      value: (r) => r.status,
      render: (v) => <span className={`badge badge-${v === "active" ? "ok" : "warn"}`}>{t(`status.${v}`, String(v))}</span>,
    },
    {
      key: "current_period_end",
      title: t("page.billing.renews", "Renews"),
      width: 130,
      value: (r) => r.current_period_end || "—",
    },
  ], [t]);

  const planColumns = useMemo<ColumnDef<Plan>[]>(() => [
    { key: "code", title: t("common.code", "Code"), width: 120, value: (r) => r.code },
    {
      key: "name",
      title: t("common.name", "Name"),
      minWidth: 140,
      value: (r) => r.name,
      editor: { type: "text" },
    },
    {
      key: "billing_period",
      title: t("page.saas.billing_period", "Billing period"),
      width: 120,
      value: (r) => r.billing_period,
      render: (v) => (v ? t(`page.saas.period_${v}`, String(v)) : ""),
      editor: {
        type: "select",
        options: ["monthly", "quarterly", "annual", "one_time"].map((p) => ({
          value: p,
          label: t(`page.saas.period_${p}`, p),
        })),
      },
    },
    {
      key: "price_amount",
      title: t("page.saas.price", "Price"),
      width: 110,
      align: "right",
      value: (r) => r.price_amount,
      editor: { type: "number", step: 0.01 },
    },
    {
      key: "currency",
      title: t("page.saas.currency", "Currency"),
      width: 90,
      value: (r) => r.currency,
      editor: { type: "text" },
    },
    {
      key: "seat_limit",
      title: t("page.saas.seat_limit", "Seat limit"),
      width: 100,
      align: "right",
      value: (r) => r.seat_limit ?? "",
      render: (v) => (v === "" || v == null ? "—" : String(v)),
      editor: { type: "number" },
    },
    {
      key: "included_quotas",
      title: t("page.saas.quotas", "Quotas"),
      minWidth: 160,
      value: (r) => r.included_quotas || {},
      // 配额 JSON → 紧凑可读形式（ai.tokens 500k · api.calls 50k）
      render: (v) => {
        const q = (v || {}) as Record<string, unknown>;
        const entries = Object.entries(q);
        if (!entries.length) return <span className="muted">—</span>;
        const parts = entries.map(([k, val]) => `${k} ${compactNum(val)}`);
        return <span>{parts.join(" · ")}</span>;
      },
    },
    {
      key: "_actions",
      title: "",
      width: 30,
      align: "center",
      render: (_v, r) => <RowActions onDelete={() => deletePlan(r)} label={r.name || r.code} />,
    },
  ], [t, deletePlan]);

  const packColumns = useMemo<ColumnDef<Pack>[]>(() => [
    { key: "code", title: t("common.code", "Code"), width: 120, value: (r) => r.code },
    {
      key: "name",
      title: t("common.name", "Name"),
      minWidth: 140,
      value: (r) => r.name,
      editor: { type: "text" },
    },
    {
      key: "meter_code",
      title: t("page.saas.meter", "Meter"),
      width: 120,
      value: (r) => r.meter_code,
      editor: { type: "text" },
    },
    {
      key: "quantity",
      title: t("page.saas.quantity", "Quantity"),
      width: 110,
      align: "right",
      value: (r) => r.quantity,
      editor: { type: "number", step: 1 },
    },
    {
      key: "price_amount",
      title: t("page.saas.price", "Price"),
      width: 110,
      align: "right",
      value: (r) => r.price_amount,
      editor: { type: "number", step: 0.01 },
    },
    {
      key: "currency",
      title: t("page.saas.currency", "Currency"),
      width: 90,
      value: (r) => r.currency,
      editor: { type: "text" },
    },
    {
      key: "_actions",
      title: "",
      width: 30,
      align: "center",
      render: (_v, r) => <RowActions onDelete={() => deletePackRow(r)} label={r.name || r.code} />,
    },
  ], [t, deletePackRow]);

  type MeterRow = Record<string, unknown>;

  const meterColumns = useMemo<ColumnDef<MeterRow>[]>(() => [
    { key: "code", title: t("common.code", "Code"), width: 130, value: (r) => String(r.code) },
    { key: "name", title: t("common.name", "Name"), minWidth: 150, value: (r) => String(r.name) },
    {
      key: "overage_price",
      title: t("page.saas.overage", "Overage price"),
      width: 140,
      value: (r) => `${String(r.overage_price)} ${String(r.currency)}`,
    },
  ], [t]);

  const aiColumns = useMemo<ColumnDef<AiRow>[]>(() => [
    { key: "code", title: t("common.code", "Code"), width: 130, value: (r) => r.code },
    {
      key: "name",
      title: t("common.name", "Name"),
      minWidth: 140,
      value: (r) => r.name,
      editor: { type: "text" },
    },
    {
      key: "model_default",
      title: t("page.saas.model", "Model"),
      width: 150,
      value: (r) => r.model_default || "",
      editor: { type: "text" },
    },
    {
      key: "meter_code",
      title: t("page.saas.meter", "Meter"),
      width: 130,
      value: (r) => r.meter_code,
      editor: { type: "text" },
    },
    {
      key: "tokens_per_call_est",
      title: t("page.saas.tokens", "Est. tokens/call"),
      width: 140,
      align: "right",
      value: (r) => r.tokens_per_call_est,
      editor: { type: "number", step: 1 },
    },
    {
      key: "_actions",
      title: "",
      width: 30,
      align: "center",
      render: (_v, r) => <RowActions onDelete={() => deleteAi(r)} label={r.name || r.code} />,
    },
  ], [t, deleteAi]);

  type ProviderRow = Record<string, unknown>;

  const providerColumns = useMemo<ColumnDef<ProviderRow>[]>(() => [
    { key: "code", title: t("common.code", "Code"), width: 130, value: (r) => String(r.code) },
    { key: "name", title: t("common.name", "Name"), minWidth: 150, value: (r) => String(r.name) },
    {
      key: "status",
      title: t("common.status", "Status"),
      width: 110,
      value: (r) => String(r.status),
      render: (v) => <span className={`badge badge-${v === "active" ? "ok" : "warn"}`}>{t(`status.${v}`, String(v))}</span>,
    },
  ], [t]);

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
        <button type="button" className="btn btn-ghost" disabled={busy || !tenantId} onClick={() => askCancelSub()}>
          {t("page.saas.cancel_sub", "Cancel subscription")}
        </button>
        <RefreshButton label={t("common.refresh", "Refresh")} className="btn btn-sm" onClick={() => load()} />
      </Toolbar>

      <div className="workbench-grid">
        <div className="wb-tile">
          <h3>{t("page.saas.active_subs", "Active subscriptions")}</h3>
          <div className="metric">{String(overview?.active_subscriptions ?? "—")}</div>
        </div>
        <div className="wb-tile">
          <h3>{t("page.saas.mrr", "MRR estimate")}</h3>
          <div className="metric">{money(overview?.mrr_estimate)}</div>
        </div>
        <div className="wb-tile">
          <h3>{t("page.saas.paid_vol", "Paid volume")}</h3>
          <div className="metric">{money(overview?.paid_volume)}</div>
        </div>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.saas.subs_list", "Tenant subscriptions")}</h3>
        <StateView
          loading={loading}
          error={err ?? undefined}
          empty={!subs.length}
          onRetry={() => load()}
          emptyText={t("common.none", "None")}
        >
          <DataGrid<SubRow>
            columns={subColumns}
            data={subRows}
            rowKey={(r) => r.id}
            storageKey="platform_saas_subs_grid"
            emptyText={t("common.none", "None")}
          />
          <div className="dt-pager">
            <span className="muted">{t("common.count_total", "共 {n} 条", { n: subs.length })}</span>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              disabled={subPageSafe <= 1}
              aria-label={t("common.page_prev", "上一页")}
              onClick={() => setSubPage((p) => Math.max(1, p - 1))}
            >
              ←
            </button>
            <span className="muted">
              {subPageSafe} / {subPages}
            </span>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              disabled={subPageSafe >= subPages}
              aria-label={t("common.page_next", "下一页")}
              onClick={() => setSubPage((p) => Math.min(subPages, p + 1))}
            >
              →
            </button>
          </div>
        </StateView>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.saas.plans", "Commercial plan catalog")}</h3>
        <StateView loading={loading} error={err ?? undefined} empty={!plans.length} onRetry={() => load()} emptyText={t("common.none", "None")}>
          <DataGrid<Plan>
            columns={planColumns}
            data={plans}
            rowKey={(r) => r.id}
            storageKey="platform_saas_plans_grid"
            emptyText={t("common.none", "None")}
            editable
            onCellSave={onPlanCellSave}
          />
        </StateView>
      </div>

      <div className="panel">
        <div className="panel-header">{t("page.saas.packs", "Usage packs")}</div>
        <StateView loading={loading} error={err ?? undefined} empty={!packs.length} onRetry={() => load()} emptyText={t("common.none", "None")}>
          <DataGrid<Pack>
            columns={packColumns}
            data={packs}
            rowKey={(r) => r.id}
            storageKey="platform_saas_packs_grid"
            emptyText={t("common.none", "None")}
            editable
            onCellSave={onPackCellSave}
          />
        </StateView>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.saas.meters", "Meters")}</h3>
        <StateView loading={loading} error={err ?? undefined} empty={!meters.length} onRetry={() => load()} emptyText={t("common.none", "None")}>
          <DataGrid<MeterRow>
            columns={meterColumns}
            data={meters}
            rowKey={(r) => String(r.code)}
            storageKey="platform_saas_meters_grid"
            emptyText={t("common.none", "None")}
          />
        </StateView>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.saas.ai_endpoints", "Platform AI endpoints")}</h3>
        <StateView loading={loading} error={err ?? undefined} empty={!ai.length} onRetry={() => load()} emptyText={t("common.none", "None")}>
          <DataGrid<AiRow>
            columns={aiColumns}
            data={ai}
            rowKey={(r) => r.id}
            storageKey="platform_saas_ai_endpoints_grid"
            emptyText={t("common.none", "None")}
            editable
            onCellSave={onAiCellSave}
          />
        </StateView>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.saas.payments", "Payment providers")}</h3>
        <p className="muted" style={{ marginTop: 0 }}>
          {t("page.saas.payments_hint", "All providers are unwired; connect checkout & webhooks once online payments go live.")}
        </p>
        <StateView loading={loading} error={err ?? undefined} empty={!providers.length} onRetry={() => load()} emptyText={t("common.none", "None")}>
          <DataGrid<ProviderRow>
            columns={providerColumns}
            data={providers}
            rowKey={(r) => String(r.code)}
            storageKey="platform_saas_payments_grid"
            emptyText={t("common.none", "None")}
          />
        </StateView>
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

      <ConfirmDialog
        open={Boolean(pending)}
        title={t("common.confirm", "Confirm")}
        message={pending?.message || ""}
        danger={pending?.danger}
        onConfirm={() => {
          const fn = pending?.action;
          setPending(null);
          fn?.();
        }}
        onCancel={() => setPending(null)}
      />
    </AppShell>
  );
}

export default function Page() {
  return <PlatformSaasPage />;
}
