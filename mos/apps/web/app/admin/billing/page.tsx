"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { Toolbar } from "@/components/Toolbar";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type PlanRow = Record<string, unknown>;
type PackRow = Record<string, unknown>;
type UsageRow = Record<string, unknown>;

export default function BillingPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [sub, setSub] = useState<Record<string, unknown> | null>(null);
  const [plans, setPlans] = useState<PlanRow[]>([]);
  const [packs, setPacks] = useState<PackRow[]>([]);
  const [wallet, setWallet] = useState<Array<{ meter_code: string; balance: number }>>([]);
  const [usage, setUsage] = useState<UsageRow[]>([]);

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
    load().catch(() => toast.error(t("page.billing.admin_required", "需要租户管理员")));
  }, [t]);

  async function invokeAi() {
    const res = await apiPost("/api/v1/billing/ai/invoke-demo");
    toast.success(
      t("page.billing.ai_metered", "AI 计量: -{tokens} tokens，余额 {balance}", {
        tokens: res.tokens_charged,
        balance: res.balance,
      }),
    );
    await load();
  }

  const plan = (sub?.plan || null) as Record<string, unknown> | null;

  const planColumns: ColumnDef<PlanRow>[] = [
    {
      key: "name",
      title: t("page.billing.plan", "套餐"),
      minWidth: 200,
      value: (r) => String(r.name || ""),
      render: (v, r) => (
        <span>
          <b>{String(v)}</b>
          <div className="muted">{String(r.description || "")}</div>
        </span>
      ),
    },
    {
      key: "price",
      title: t("page.billing.price", "价格"),
      width: 180,
      value: (r) => `${String(r.price_amount)} ${String(r.currency)}`,
      render: (_v, r) => (
        <span>
          {String(r.price_amount)} {String(r.currency)} / {String(r.billing_period)}
        </span>
      ),
    },
    {
      key: "seat_limit",
      title: t("page.billing.seats", "席位"),
      width: 90,
      value: (r) => (r.seat_limit == null ? null : Number(r.seat_limit)),
      render: (_v, r) => <span>{r.seat_limit == null ? t("page.billing.unlimited", "不限") : String(r.seat_limit)}</span>,
    },
    {
      key: "status",
      title: t("common.status", "状态"),
      width: 130,
      value: (r) => String(r.code || ""),
      render: (_v, r) => {
        const current = plan && String(plan.code) === String(r.code) && String(sub?.status) === "active";
        return current ? (
          <span className="badge">{t("page.billing.current_badge", "当前套餐")}</span>
        ) : (
          <span className="muted">{t("page.billing.contact_platform", "联系平台开通")}</span>
        );
      },
    },
  ];

  const packColumns: ColumnDef<PackRow>[] = [
    { key: "name", title: t("page.billing.pack", "用量包"), minWidth: 160, value: (r) => String(r.name || "") },
    { key: "meter_code", title: t("page.billing.meter", "计量项"), width: 130, value: (r) => String(r.meter_code || "") },
    { key: "quantity", title: t("page.billing.qty", "数量"), width: 90, align: "right", value: (r) => String(r.quantity ?? "") },
    {
      key: "price",
      title: t("page.billing.price", "价格"),
      width: 120,
      value: (r) => `${String(r.price_amount)} ${String(r.currency)}`,
      render: (_v, r) => (
        <span>
          {String(r.price_amount)} {String(r.currency)}
        </span>
      ),
    },
  ];

  const usageColumns: ColumnDef<UsageRow>[] = [
    { key: "meter_code", title: t("page.billing.meter", "计量项"), width: 130, value: (r) => String(r.meter_code || "") },
    { key: "direction", title: t("page.billing.dir", "方向"), width: 90, value: (r) => String(r.direction || "") },
    { key: "quantity", title: t("page.billing.qty", "数量"), width: 90, align: "right", value: (r) => String(r.quantity ?? "") },
    { key: "note", title: t("common.notes", "备注"), minWidth: 180, value: (r) => String(r.note || "") },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.admin", "Administration") }]}
        title={t("page.billing.title", "订阅与用量")}
        subtitle={t(
          "page.billing.sub_readonly",
          "查看当前套餐与用量。订阅与充值由平台管理员开通；线上支付开通后再支持自助下单。",
        )}
      />
      <Toolbar>
        <button type="button" className="btn btn-sm" onClick={() => load().catch(() => undefined)} title={t("common.refresh", "Refresh")}>
          ↻
        </button>
      </Toolbar>

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
        <button className="btn" type="button" onClick={() => invokeAi().catch((e) => toast.error(String(e)))}>
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
        <DataGrid<PlanRow>
          columns={planColumns}
          data={plans}
          rowKey={(r) => String(r.code)}
          storageKey="admin_billing_plans_grid"
          emptyText={t("common.none", "无")}
          showFooter={false}
        />
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.billing.packs", "用量包目录（只读）")}</h3>
        <DataGrid<PackRow>
          columns={packColumns}
          data={packs}
          rowKey={(r) => String(r.code)}
          storageKey="admin_billing_packs_grid"
          emptyText={t("common.none", "无")}
          showFooter={false}
        />
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.billing.ledger", "用量流水")}</h3>
        <DataGrid<UsageRow>
          columns={usageColumns}
          data={usage.slice(0, 20)}
          rowKey={(r, i) => String(r.id ?? r.meter_code ?? i) + `_${i}`}
          storageKey="admin_billing_usage_grid"
          emptyText={t("common.none", "无")}
          showFooter={false}
        />
      </div>
    </AppShell>
  );
}
