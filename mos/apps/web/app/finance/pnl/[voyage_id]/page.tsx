"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type LineKey = "revenue" | "hire" | "demurrage" | "port_costs" | "canal" | "bunker" | "commission" | "emissions" | "other";
const LINE_KEYS: LineKey[] = ["revenue", "hire", "demurrage", "port_costs", "canal", "bunker", "commission", "emissions", "other"];
const REVENUE_KEYS = new Set<string>(["revenue", "hire", "demurrage", "other"]);

const LINE_LABELS: Record<LineKey, string> = {
  revenue: "Freight / Revenue",
  hire: "Hire",
  demurrage: "Demurrage",
  port_costs: "Port Costs",
  canal: "Canal Dues",
  bunker: "Bunker Cost",
  commission: "Commission",
  emissions: "EU ETS / Emissions",
  other: "Other",
};

const COST_KEYS: LineKey[] = ["port_costs", "canal", "bunker", "commission", "emissions", "other"];

type ColumnLines = Record<LineKey, number>;
type ColumnTotals = { revenue: number; cost: number; pnl: number; tce?: number | null };
type VoyageData = {
  voyage_id: string;
  voyage_no: string;
  status: string;
  cargo: string | null;
  columns: Record<"estimate" | "actual" | "posted" | "variance", ColumnLines>;
  totals: Record<"estimate" | "actual" | "posted", ColumnTotals>;
  paid_amount: number;
};

function fmt(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function variancePct(actual: number, estimate: number): number | null {
  if (estimate === 0) return null;
  return ((actual - estimate) / Math.abs(estimate)) * 100;
}

function varianceClass(val: number, base: number): string {
  if (base === 0) return val > 0 ? "pnl-fav" : val < 0 ? "pnl-adv" : "";
  const pct = Math.abs(val / Math.abs(base));
  if (pct > 0.1) {
    return val >= 0 ? "pnl-fav" : "pnl-adv";
  }
  return "";
}

export default function VoyagePnlDetailPage() {
  const { t } = useI18n();
  const params = useParams();
  const voyageId = params.voyage_id as string;

  const [data, setData] = useState<VoyageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [grossNet, setGrossNet] = useState<"gross" | "net">("gross");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = (await apiGet(`/api/v1/analytics/reports/pnl-4col?voyage_id=${voyageId}`)) as VoyageData[];
      setData(rows[0] ?? null);
    } finally {
      setLoading(false);
    }
  }, [voyageId]);

  useEffect(() => { load(); }, [load]);

  function toggleLine(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }

  const netLines = useMemo(() => {
    if (!data) return null;
    const result: Record<string, Record<"estimate" | "actual" | "posted" | "variance", number>> = {};
    for (const k of LINE_KEYS) {
      result[k] = {
        estimate: data.columns.estimate[k],
        actual: data.columns.actual[k],
        posted: data.columns.posted[k],
        variance: data.columns.variance[k],
      };
    }
    return result;
  }, [data]);

  if (loading) {
    return (
      <AppShell breadcrumbs={[{ label: "Finance", href: "/finance" }, { label: "P&L", href: "/finance/pnl" }, { label: "Loading…" }]}>
        <div className="panel"><div className="skeleton-table" /></div>
      </AppShell>
    );
  }

  if (!data) {
    return (
      <AppShell breadcrumbs={[{ label: "Finance", href: "/finance" }, { label: "P&L", href: "/finance/pnl" }, { label: "Not Found" }]}>
        <div className="panel">
          <p className="muted">{t("common.not_found", "Voyage not found")}</p>
          <Link href="/finance/pnl" className="btn btn-ghost">{t("common.back", "Back")}</Link>
        </div>
      </AppShell>
    );
  }

  const estTotals = data.totals.estimate;
  const actTotals = data.totals.actual;
  const postTotals = data.totals.posted;
  const pnlVariance = actTotals.pnl - estTotals.pnl;
  const pnlVariancePct = variancePct(actTotals.pnl, estTotals.pnl);

  return (
    <AppShell
      breadcrumbs={[
        { label: "Finance", href: "/finance" },
        { label: "P&L", href: "/finance/pnl" },
        { label: data.voyage_no },
      ]}
    >
      <div className="panel">
        <div className="desk-toolbar" style={{ marginBottom: "0.75rem" }}>
          <div>
            <h1 style={{ margin: 0, fontSize: "1.25rem" }}>
              {t("page.pnl.voyage_title", "Voyage P&L")} — {data.voyage_no}
            </h1>
            <div className="muted" style={{ fontSize: "0.85rem", marginTop: "0.25rem" }}>
              {data.status} {data.cargo ? `· ${data.cargo}` : ""}
            </div>
          </div>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <div className="btn-group">
              <button
                className={`btn btn-sm${grossNet === "gross" ? " btn-primary" : ""}`}
                type="button"
                onClick={() => setGrossNet("gross")}
              >
                Gross
              </button>
              <button
                className={`btn btn-sm${grossNet === "net" ? " btn-primary" : ""}`}
                type="button"
                onClick={() => setGrossNet("net")}
              >
                Net
              </button>
            </div>
            <button className="btn btn-sm btn-ghost" type="button" onClick={load}>
              {t("common.refresh", "Refresh")}
            </button>
          </div>
        </div>

        <div className="pnl-kpi-row">
          <div className="pnl-kpi">
            <span className="pnl-kpi-label">Est. P&L</span>
            <span className="pnl-kpi-value">{fmt(estTotals.pnl)}</span>
            {estTotals.tce != null ? <span className="pnl-kpi-sub">TCE: {fmt(estTotals.tce)}</span> : null}
          </div>
          <div className="pnl-kpi">
            <span className="pnl-kpi-label">Actual P&L</span>
            <span className={`pnl-kpi-value ${actTotals.pnl >= 0 ? "pnl-fav" : "pnl-adv"}`}>{fmt(actTotals.pnl)}</span>
          </div>
          <div className="pnl-kpi">
            <span className="pnl-kpi-label">Posted P&L</span>
            <span className="pnl-kpi-value">{fmt(postTotals.pnl)}</span>
          </div>
          <div className="pnl-kpi">
            <span className="pnl-kpi-label">Variance</span>
            <span className={`pnl-kpi-value ${varianceClass(pnlVariance, estTotals.pnl)}`}>
              {fmt(pnlVariance)}
              {pnlVariancePct != null ? ` (${pnlVariancePct.toFixed(1)}%)` : ""}
            </span>
          </div>
          <div className="pnl-kpi">
            <span className="pnl-kpi-label">Paid</span>
            <span className="pnl-kpi-value">{fmt(data.paid_amount)}</span>
          </div>
        </div>

        <div className="table-scroll">
          <table className="table pnl-detail-table">
            <thead>
              <tr>
                <th style={{ minWidth: 180 }}>{t("page.pnl.line_item", "Line Item")}</th>
                <th className="pnl-num pnl-col-estimate">{t("page.pnl.estimate", "Estimate")}</th>
                <th className="pnl-num pnl-col-actual">{t("page.pnl.actual", "Actual")}</th>
                <th className="pnl-num pnl-col-posted">{t("page.pnl.posted", "Posted")}</th>
                <th className="pnl-num pnl-col-variance">{t("page.pnl.variance", "Variance")}</th>
                <th className="pnl-num">{t("page.pnl.var_pct", "Var %")}</th>
              </tr>
            </thead>
            <tbody>
              {grossNet === "gross" ? (
                <>
                  {LINE_KEYS.map((k) => {
                    const est = data.columns.estimate[k];
                    const act = data.columns.actual[k];
                    const posted = data.columns.posted[k];
                    const vari = data.columns.variance[k];
                    const pct = variancePct(act, est);
                    const isExpanded = expanded.has(k);
                    return (
                      <Fragment key={k}>
                        <tr
                          className={`pnl-line-row ${varianceClass(vari, est)}`}
                          style={{ cursor: "pointer" }}
                          onClick={() => toggleLine(k)}
                        >
                          <td>
                            <span className="pnl-expand">{isExpanded ? "▾" : "▸"}</span>
                            {LINE_LABELS[k]}
                          </td>
                          <td className="pnl-num">{fmt(est)}</td>
                          <td className="pnl-num">{fmt(act)}</td>
                          <td className="pnl-num">{fmt(posted)}</td>
                          <td className={`pnl-num ${varianceClass(vari, est)}`}>{fmt(vari)}</td>
                          <td className={`pnl-num ${pct != null && Math.abs(pct) > 10 ? (vari >= 0 ? "pnl-fav" : "pnl-adv") : ""}`}>
                            {pct != null ? `${pct.toFixed(1)}%` : "—"}
                          </td>
                        </tr>
                      </Fragment>
                    );
                  })}
                  <tr className="pnl-subtotal-row">
                    <td><strong>{t("page.pnl.total_revenue", "Total Revenue")}</strong></td>
                    <td className="pnl-num"><strong>{fmt(estTotals.revenue)}</strong></td>
                    <td className="pnl-num"><strong>{fmt(actTotals.revenue)}</strong></td>
                    <td className="pnl-num"><strong>{fmt(postTotals.revenue)}</strong></td>
                    <td className={`pnl-num ${varianceClass(actTotals.revenue - estTotals.revenue, estTotals.revenue)}`}>
                      <strong>{fmt(actTotals.revenue - estTotals.revenue)}</strong>
                    </td>
                    <td className="pnl-num">—</td>
                  </tr>
                  <tr className="pnl-subtotal-row">
                    <td><strong>{t("page.pnl.total_cost", "Total Cost")}</strong></td>
                    <td className="pnl-num"><strong>{fmt(estTotals.cost)}</strong></td>
                    <td className="pnl-num"><strong>{fmt(actTotals.cost)}</strong></td>
                    <td className="pnl-num"><strong>{fmt(postTotals.cost)}</strong></td>
                    <td className={`pnl-num ${varianceClass(actTotals.cost - estTotals.cost, estTotals.cost)}`}>
                      <strong>{fmt(actTotals.cost - estTotals.cost)}</strong>
                    </td>
                    <td className="pnl-num">—</td>
                  </tr>
                  <tr className="pnl-total-row">
                    <td><strong>{t("page.pnl.net_pnl", "NET P&L")}</strong></td>
                    <td className="pnl-num"><strong>{fmt(estTotals.pnl)}</strong></td>
                    <td className={`pnl-num ${actTotals.pnl >= 0 ? "pnl-fav" : "pnl-adv"}`}><strong>{fmt(actTotals.pnl)}</strong></td>
                    <td className="pnl-num"><strong>{fmt(postTotals.pnl)}</strong></td>
                    <td className={`pnl-num ${varianceClass(pnlVariance, estTotals.pnl)}`}><strong>{fmt(pnlVariance)}</strong></td>
                    <td className={`pnl-num ${pnlVariancePct != null && Math.abs(pnlVariancePct) > 10 ? (pnlVariance >= 0 ? "pnl-fav" : "pnl-adv") : ""}`}>
                      <strong>{pnlVariancePct != null ? `${pnlVariancePct.toFixed(1)}%` : "—"}</strong>
                    </td>
                  </tr>
                  {estTotals.tce != null ? (
                    <tr className="pnl-subtotal-row">
                      <td><strong>TCE</strong></td>
                      <td className="pnl-num"><strong>{fmt(estTotals.tce)}</strong></td>
                      <td className="pnl-num" colSpan={4}>—</td>
                    </tr>
                  ) : null}
                </>
              ) : (
                <>
                  <tr className="pnl-line-row">
                    <td><strong>{t("page.pnl.gross_revenue", "Gross Revenue")}</strong></td>
                    <td className="pnl-num">{fmt(data.columns.estimate.revenue + data.columns.estimate.hire + data.columns.estimate.demurrage)}</td>
                    <td className="pnl-num">{fmt(data.columns.actual.revenue + data.columns.actual.hire + data.columns.actual.demurrage)}</td>
                    <td className="pnl-num">{fmt(data.columns.posted.revenue + data.columns.posted.hire + data.columns.posted.demurrage)}</td>
                    <td className="pnl-num">—</td>
                    <td className="pnl-num">—</td>
                  </tr>
                  <tr className="pnl-line-row">
                    <td style={{ paddingLeft: "1.5rem" }}>- {LINE_LABELS.commission}</td>
                    <td className="pnl-num">({fmt(data.columns.estimate.commission)})</td>
                    <td className="pnl-num">({fmt(data.columns.actual.commission)})</td>
                    <td className="pnl-num">({fmt(data.columns.posted.commission)})</td>
                    <td className="pnl-num">—</td>
                    <td className="pnl-num">—</td>
                  </tr>
                  <tr className="pnl-subtotal-row">
                    <td><strong>{t("page.pnl.net_revenue", "Net Revenue")}</strong></td>
                    <td className="pnl-num"><strong>{fmt(estTotals.revenue - data.columns.estimate.commission)}</strong></td>
                    <td className="pnl-num"><strong>{fmt(actTotals.revenue - data.columns.actual.commission)}</strong></td>
                    <td className="pnl-num"><strong>{fmt(postTotals.revenue - data.columns.posted.commission)}</strong></td>
                    <td className="pnl-num">—</td>
                    <td className="pnl-num">—</td>
                  </tr>
                  <tr className="pnl-line-row">
                    <td><strong>{t("page.pnl.total_cost", "Total Cost")}</strong></td>
                    <td className="pnl-num">{fmt(estTotals.cost)}</td>
                    <td className="pnl-num">{fmt(actTotals.cost)}</td>
                    <td className="pnl-num">{fmt(postTotals.cost)}</td>
                    <td className="pnl-num">—</td>
                    <td className="pnl-num">—</td>
                  </tr>
                  <tr className="pnl-total-row">
                    <td><strong>{t("page.pnl.net_pnl", "NET P&L")}</strong></td>
                    <td className="pnl-num"><strong>{fmt(estTotals.pnl)}</strong></td>
                    <td className={`pnl-num ${actTotals.pnl >= 0 ? "pnl-fav" : "pnl-adv"}`}><strong>{fmt(actTotals.pnl)}</strong></td>
                    <td className="pnl-num"><strong>{fmt(postTotals.pnl)}</strong></td>
                    <td className={`pnl-num ${varianceClass(pnlVariance, estTotals.pnl)}`}><strong>{fmt(pnlVariance)}</strong></td>
                    <td className={`pnl-num ${pnlVariancePct != null && Math.abs(pnlVariancePct) > 10 ? (pnlVariance >= 0 ? "pnl-fav" : "pnl-adv") : ""}`}>
                      <strong>{pnlVariancePct != null ? `${pnlVariancePct.toFixed(1)}%` : "—"}</strong>
                    </td>
                  </tr>
                </>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </AppShell>
  );
}
