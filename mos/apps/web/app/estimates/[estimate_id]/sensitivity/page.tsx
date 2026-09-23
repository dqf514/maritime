"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

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
        apiGet<any>(`/estimates/${estimateId}/sensitivity?pct=${pct}`),
        apiGet<any>(`/estimates/${estimateId}/bep`),
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
    return Math.max(...sensitivity.tornado.map((p) => p.max_impact));
  }, [sensitivity]);

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
          <div className="alert alert-warning">Failed to load sensitivity analysis</div>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="container">
        <div className="page-header">
          <h1>Sensitivity Analysis</h1>
          <div className="btn-group">
            <label>Perturbation: ±{pct}%</label>
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
        </div>

        <div className="kpi-row">
          <div className="kpi">
            <div className="kpi-label">Base P&L</div>
            <div className="kpi-value">{fmt(sensitivity.base_pnl)}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Revenue</div>
            <div className="kpi-value">{fmt(sensitivity.base_revenue)}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Cost</div>
            <div className="kpi-value">{fmt(sensitivity.base_cost)}</div>
          </div>
        </div>

        <section className="card">
          <h2>Tornado Chart</h2>
          <div className="tornado-chart">
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
        </section>

        <section className="card">
          <h2>Parameter Impact (±{pct}%)</h2>
          <table className="table">
            <thead>
              <tr>
                <th>Parameter</th>
                <th className="text-right">P&L if +{pct}%</th>
                <th className="text-right">Impact</th>
                <th className="text-right">P&L if -{pct}%</th>
                <th className="text-right">Impact</th>
                <th className="text-right">Max Impact</th>
              </tr>
            </thead>
            <tbody>
              {sensitivity.perturbations.map((p) => (
                <tr key={p.parameter}>
                  <td>{p.label}</td>
                  <td className="text-right">{fmt(p.pnl_up)}</td>
                  <td className={`text-right ${p.impact_up >= 0 ? "text-success" : "text-danger"}`}>
                    {fmt(p.impact_up)}
                  </td>
                  <td className="text-right">{fmt(p.pnl_down)}</td>
                  <td className={`text-right ${p.impact_down >= 0 ? "text-success" : "text-danger"}`}>
                    {fmt(p.impact_down)}
                  </td>
                  <td className="text-right font-bold">{fmt(p.max_impact)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="card">
          <h2>Break-Even Point (BEP)</h2>
          <div className="kpi-row">
            <div className="kpi">
              <div className="kpi-label">BEP Freight Rate</div>
              <div className="kpi-value">
                {bep.bep_freight_rate ? `$${fmtNum(bep.bep_freight_rate)}/MT` : "N/A"}
              </div>
              <div className="kpi-sub">
                Current: ${fmtNum(bep.current_freight_rate)}/MT
              </div>
            </div>
            <div className="kpi">
              <div className="kpi-label">BEP Cargo Qty</div>
              <div className="kpi-value">
                {bep.bep_cargo_qty ? `${fmtNum(bep.bep_cargo_qty, 1)} MT` : "N/A"}
              </div>
              <div className="kpi-sub">
                Current: {fmtNum(bep.current_cargo_qty, 1)} MT
              </div>
            </div>
            <div className="kpi">
              <div className="kpi-label">Margin of Safety</div>
              <div className="kpi-value">
                {bep.current_freight_rate > 0 && bep.bep_freight_rate
                  ? `${fmtNum(((bep.current_freight_rate - bep.bep_freight_rate) / bep.current_freight_rate) * 100, 1)}%`
                  : "N/A"}
              </div>
              <div className="kpi-sub">Freight rate buffer</div>
            </div>
          </div>
        </section>
      </div>
    </AppShell>
  );
}
