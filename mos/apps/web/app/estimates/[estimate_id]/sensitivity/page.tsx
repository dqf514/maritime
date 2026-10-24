"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { maxOf } from "@/lib/numbers";

type Perturbation = {
  parameter: string;
  label: string;
  pct_change: number;
  pnl_up: number;
  pnl_down: number;
  impact_up: number;
  impact_down: number;
  max_impact: number;
};

type SensitivityData = {
  estimate_id: string;
  base_pnl: number;
  base_revenue: number;
  base_cost: number;
  perturbation_pct: number;
  perturbations: Perturbation[];
  tornado: Perturbation[];
};

type BEPData = {
  estimate_id: string;
  bep_freight_rate: number | null;
  bep_cargo_qty: number | null;
  has_cost_base?: boolean;
  current_freight_rate: number;
  current_cargo_qty: number;
  base_pnl: number;
  base_revenue: number;
  base_cost: number;
};

function fmt(n: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n);
}

function fmtNum(n: number, decimals = 2): string {
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: decimals,
  }).format(n);
}

export default function SensitivityPage() {
  const params = useParams();
  const estimateId = params?.estimate_id as string;
  const { t } = useI18n();

  const [sensitivity, setSensitivity] = useState<SensitivityData | null>(null);
  const [bep, setBep] = useState<BEPData | null>(null);
  const [pct, setPct] = useState(10);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    if (!estimateId) return;
    setLoading(true);
    try {
      const [sens, bepRes] = await Promise.all([
        apiGet(`/api/v1/estimates/${estimateId}/sensitivity?pct=${pct}`),
        apiGet(`/api/v1/estimates/${estimateId}/bep`),
      ]);
      setSensitivity(sens);
      setBep(bepRes);
    } catch (err) {
      console.error("Failed to load sensitivity data:", err);
    } finally {
      setLoading(false);
    }
  }, [estimateId, pct]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const maxImpact = useMemo(() => {
    if (!sensitivity?.tornado?.length) return 0;
    return maxOf(sensitivity.tornado, (p) => p.max_impact);
  }, [sensitivity]);

  const impactColumns: ColumnDef<Perturbation>[] = useMemo(
    () => [
      {
        key: "parameter",
        title: t("page.sensitivity.parameter", { en: "Parameter", zh: "参数" }),
        minWidth: 140,
        value: (p) => p.label,
      },
      {
        key: "pnl_up",
        title: t("page.sensitivity.pnl_if_up", { en: "P&L if +{pct}%", zh: "若 +{pct}% 的损益" }, { pct }),
        width: 130,
        align: "right",
        value: (p) => p.pnl_up,
        render: (v) => fmt(Number(v)),
      },
      {
        key: "impact_up",
        title: t("page.sensitivity.impact", { en: "Impact", zh: "影响" }),
        width: 110,
        align: "right",
        value: (p) => p.impact_up,
        render: (v, p) => (
          <span className={p.impact_up >= 0 ? "text-success" : "text-danger"}>{fmt(Number(v))}</span>
        ),
      },
      {
        key: "pnl_down",
        title: t("page.sensitivity.pnl_if_down", { en: "P&L if -{pct}%", zh: "若 -{pct}% 的损益" }, { pct }),
        width: 130,
        align: "right",
        value: (p) => p.pnl_down,
        render: (v) => fmt(Number(v)),
      },
      {
        key: "impact_down",
        title: t("page.sensitivity.impact", { en: "Impact", zh: "影响" }),
        width: 110,
        align: "right",
        value: (p) => p.impact_down,
        render: (v, p) => (
          <span className={p.impact_down >= 0 ? "text-success" : "text-danger"}>{fmt(Number(v))}</span>
        ),
      },
      {
        key: "max_impact",
        title: t("page.sensitivity.max_impact", { en: "Max Impact", zh: "最大影响" }),
        width: 120,
        align: "right",
        value: (p) => p.max_impact,
        render: (v) => <span className="font-bold">{fmt(Number(v))}</span>,
      },
    ],
    [pct, t],
  );

  if (loading) {
    return (
      <AppShell>
        <div className="container">
          <div className="skeleton-table">
            <div className="skeleton-row" />
            <div className="skeleton-row" />
            <div className="skeleton-row" />
          </div>
        </div>
      </AppShell>
    );
  }

  if (!sensitivity || !bep) {
    return (
      <AppShell>
        <div className="container">
          <div className="alert alert-warning">
            {t("page.sensitivity.load_fail", { en: "Failed to load sensitivity analysis", zh: "敏感性分析加载失败" })}
          </div>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="container">
        <PageHeader
          title={t("page.sensitivity.title", { en: "Sensitivity Analysis", zh: "敏感性分析" })}
          breadcrumb={[
            { label: t("nav.estimates", "Estimates"), href: "/estimates" },
            { label: `#${estimateId}`, href: `/estimates?id=${estimateId}` },
            { label: t("page.sensitivity.title", { en: "Sensitivity Analysis", zh: "敏感性分析" }) },
          ]}
          actions={
            <div className="btn-group">
              <label>
                {t("page.sensitivity.perturbation", { en: "Perturbation", zh: "扰动幅度" })}: ±{pct}%
              </label>
              <input
                type="range"
                min="5"
                max="30"
                step="5"
                value={pct}
                onChange={(e) => setPct(Number(e.target.value))}
                className="slider"
              />
            </div>
          }
        />

        <div className="kpi-row">
          <div className="kpi">
            <div className="kpi-label">
              {t("page.sensitivity.base_pnl", { en: "Base P&L", zh: "基准损益" })}
            </div>
            <div className="kpi-value">{fmt(sensitivity.base_pnl)}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">{t("page.sensitivity.revenue", { en: "Revenue", zh: "收入" })}</div>
            <div className="kpi-value">{fmt(sensitivity.base_revenue)}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">{t("page.sensitivity.cost", { en: "Cost", zh: "成本" })}</div>
            <div className="kpi-value">{fmt(sensitivity.base_cost)}</div>
          </div>
        </div>

        <section className="card">
          <h2>{t("page.sensitivity.tornado", { en: "Tornado Chart", zh: "龙卷风图" })}</h2>
          {/* 无障碍：图形本身对读屏不可见 —— 补一份可读的文本摘要（aria-label + sr-only 列表） */}
          <div
            className="tornado-chart"
            role="img"
            aria-label={t(
              "page.sensitivity.tornado_aria",
              {
                en: "Tornado chart of parameter sensitivity at {pct}% perturbation. Largest impact: {top} ({value}).",
                zh: "参数敏感性龙卷风图（扰动 {pct}%）。最大影响：{top}（{value}）。",
              },
              {
                pct,
                top: sensitivity.tornado[0]?.label ?? "—",
                value: fmt(sensitivity.tornado[0]?.max_impact ?? 0),
              },
            )}
          >
            {sensitivity.tornado.map((p) => {
              const widthPct = maxImpact > 0 ? (p.max_impact / maxImpact) * 100 : 0;
              const isPositive = p.impact_up > 0;
              return (
                <div key={p.parameter} className="tornado-bar">
                  <div className="tornado-label">{p.label}</div>
                  <div className="tornado-track">
                    <div
                      className={`tornado-fill ${isPositive ? "positive" : "negative"}`}
                      style={{ width: `${widthPct}%` }}
                    />
                  </div>
                  <div className="tornado-value">{fmt(p.max_impact)}</div>
                </div>
              );
            })}
          </div>
          <ul className="sr-only">
            {sensitivity.tornado.map((p) => (
              <li key={`sr-${p.parameter}`}>
                {t(
                  "page.sensitivity.tornado_item",
                  { en: "{param}: {value}", zh: "{param}：{value}" },
                  { param: p.label, value: fmt(p.max_impact) },
                )}
              </li>
            ))}
          </ul>
        </section>

        <section className="card">
          <h2>
            {t(
              "page.sensitivity.param_impact",
              { en: "Parameter Impact (±{pct}%)", zh: "参数影响（±{pct}%）" },
              { pct },
            )}
          </h2>
          <DataGrid<Perturbation>
            columns={impactColumns}
            data={sensitivity.perturbations}
            rowKey={(p) => p.parameter}
            storageKey="estimate_sensitivity_grid"
            emptyText={t("page.sensitivity.no_params", { en: "No parameters", zh: "没有参数" })}
          />
        </section>

        <section className="card">
          <h2>{t("page.sensitivity.bep", { en: "Break-Even Point (BEP)", zh: "盈亏平衡点 (BEP)" })}</h2>
          {bep.has_cost_base === false ? (
            <div className="alert alert-warning">
              {t(
                "page.sensitivity.no_cost_base",
                "No cost inputs were captured for this estimate, so the break-even point cannot be computed. Add bunker / port cost inputs and calculate again.",
              )}
            </div>
          ) : null}
          <div className="kpi-row">
            <div className="kpi">
              <div className="kpi-label">
                {t("page.sensitivity.bep_freight", { en: "BEP Freight Rate", zh: "BEP 运费率" })}
              </div>
              <div className="kpi-value">
                {bep.bep_freight_rate != null ? `$${fmtNum(bep.bep_freight_rate)}/MT` : "N/A"}
              </div>
              <div className="kpi-sub">
                {t(
                  "page.sensitivity.current_rate",
                  { en: "Current: ${v}/MT", zh: "当前：${v}/MT" },
                  { v: fmtNum(bep.current_freight_rate) },
                )}
              </div>
            </div>
            <div className="kpi">
              <div className="kpi-label">
                {t("page.sensitivity.bep_cargo", { en: "BEP Cargo Qty", zh: "BEP 货量" })}
              </div>
              <div className="kpi-value">
                {bep.bep_cargo_qty != null ? `${fmtNum(bep.bep_cargo_qty, 1)} MT` : "N/A"}
              </div>
              <div className="kpi-sub">
                {t(
                  "page.sensitivity.current_qty",
                  { en: "Current: {v} MT", zh: "当前：{v} MT" },
                  { v: fmtNum(bep.current_cargo_qty, 1) },
                )}
              </div>
            </div>
            <div className="kpi">
              <div className="kpi-label">
                {t("page.sensitivity.margin_of_safety", { en: "Margin of Safety", zh: "安全边际" })}
              </div>
              <div className="kpi-value">
                {bep.current_freight_rate > 0 && bep.bep_freight_rate != null
                  ? `${fmtNum(((bep.current_freight_rate - bep.bep_freight_rate) / bep.current_freight_rate) * 100, 1)}%`
                  : "N/A"}
              </div>
              <div className="kpi-sub">
                {t("page.sensitivity.freight_buffer", { en: "Freight rate buffer", zh: "运费率缓冲" })}
              </div>
            </div>
          </div>
        </section>
      </div>
    </AppShell>
  );
}
