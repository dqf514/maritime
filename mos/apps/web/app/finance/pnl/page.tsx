"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type LineKey = "revenue" | "hire" | "demurrage" | "port_costs" | "canal" | "bunker" | "commission" | "emissions" | "other";
const LINE_KEYS: LineKey[] = ["revenue", "hire", "demurrage", "port_costs", "canal", "bunker", "commission", "emissions", "other"];
const REVENUE_KEYS = new Set<LineKey>(["revenue", "hire", "demurrage", "other"]);

const LINE_LABELS: Record<LineKey, string> = {
  revenue: "Freight / Revenue",
  hire: "Hire",
  demurrage: "Demurrage",
  port_costs: "Port Costs",
  canal: "Canal",
  bunker: "Bunker",
  commission: "Commission",
  emissions: "EU ETS / Emissions",
  other: "Other",
};

type ColumnLines = Record<LineKey, number>;
type ColumnTotals = { revenue: number; cost: number; pnl: number; tce?: number | null };
type VoyageRow = {
  voyage_id: string;
  voyage_no: string;
  status: string;
  cargo: string | null;
  columns: Record<"estimate" | "actual" | "posted" | "variance", ColumnLines>;
  totals: Record<"estimate" | "actual" | "posted", ColumnTotals>;
  paid_amount: number;
};
type FleetSummary = {
  voyage_count: number;
  columns: Record<"estimate" | "actual" | "posted" | "variance", ColumnLines>;
  totals: Record<"estimate" | "actual" | "posted", ColumnTotals>;
  paid_amount: number;
};

function fmt(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function varianceClass(val: number, estimate: number): string {
  if (estimate === 0) return val > 0 ? "pnl-fav" : val < 0 ? "pnl-adv" : "";
  const pct = val / Math.abs(estimate);
  if (Math.abs(pct) > 0.1) {
    const favorable = val > 0;
    return favorable ? "pnl-fav" : "pnl-adv";
  }
  return "";
}

function exportCsv(rows: VoyageRow[]) {
  const cols = ["Voyage", "Status", "Cargo"];
  for (const col of ["estimate", "actual", "posted"]) {
    for (const k of LINE_KEYS) cols.push(`${col}_${k}`);
    cols.push(`${col}_revenue_total`, `${col}_cost_total`, `${col}_pnl_total`);
  }
  for (const k of LINE_KEYS) cols.push(`variance_${k}`);

  const lines = [cols.join(",")];
  for (const r of rows) {
    const cells: (string | number)[] = [r.voyage_no, r.status, r.cargo ?? ""];
    for (const col of ["estimate", "actual", "posted"]) {
      for (const k of LINE_KEYS) cells.push(r.columns[col][k] ?? 0);
      const t = r.totals[col as "estimate" | "actual" | "posted"];
      cells.push(t.revenue, t.cost, t.pnl);
    }
    for (const k of LINE_KEYS) cells.push(r.columns.variance[k] ?? 0);
    lines.push(cells.map((c) => (typeof c === "number" ? c.toFixed(2) : `"${c}"`)).join(","));
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `pnl_fleet_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function PnlOverviewPage() {
  const { t } = useI18n();
  const [voyages, setVoyages] = useState<VoyageRow[]>([]);
  const [fleet, setFleet] = useState<FleetSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<string>("voyage_no");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [v, f] = await Promise.all([
        apiGet("/api/v1/analytics/reports/pnl-4col") as Promise<VoyageRow[]>,
        apiGet("/api/v1/analytics/reports/pnl-fleet") as Promise<FleetSummary>,
      ]);
      setVoyages(v);
      setFleet(f);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const sorted = useMemo(() => {
    const arr = [...voyages];
    arr.sort((a, b) => {
      let av: number | string, bv: number | string;
      if (sortKey.startsWith("totals.")) {
        const parts = sortKey.split(".");
        const col = parts[1] as "estimate" | "actual" | "posted";
        const field = parts[2] as keyof ColumnTotals;
        av = a.totals[col]?.[field] ?? 0;
        bv = b.totals[col]?.[field] ?? 0;
      } else if (sortKey === "voyage_no") {
        av = a.voyage_no; bv = b.voyage_no;
      } else if (sortKey === "status") {
        av = a.status; bv = b.status;
      } else {
        av = 0; bv = 0;
      }
      if (typeof av === "string") return sortDir === "asc" ? av.localeCompare(bv as string) : (bv as string).localeCompare(av);
      return sortDir === "asc" ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
    return arr;
  }, [voyages, sortKey, sortDir]);

  function toggleSort(key: string) {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(key); setSortDir("asc"); }
  }

  const sortIcon = (key: string) => (sortKey === key ? (sortDir === "asc" ? " ▲" : " ▼") : "");

  return (
    <AppShell breadcrumbs={[{ label: "Finance", href: "/finance" }, { label: "P&L" }]}>
      <div className="panel">
        <div className="desk-toolbar" style={{ marginBottom: "0.75rem" }}>
          <h1 style={{ margin: 0, fontSize: "1.25rem" }}>
            {t("page.pnl.title", "Profit & Loss — 4-Column Comparison")}
          </h1>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <button className="btn btn-sm btn-ghost" type="button" onClick={load}>
              {t("common.refresh", "Refresh")}
            </button>
            <button className="btn btn-sm" type="button" onClick={() => exportCsv(sorted)}>
              {t("common.export_csv", "Export CSV")}
            </button>
          </div>
        </div>

        {fleet ? (
          <div className="pnl-fleet-summary">
            <div className="pnl-summary-card">
              <span className="pnl-summary-label">{t("page.pnl.voyages", "Voyages")}</span>
              <span className="pnl-summary-value">{fleet.voyage_count}</span>
            </div>
            {(["estimate", "actual", "posted"] as const).map((col) => (
              <div key={col} className="pnl-summary-card">
                <span className="pnl-summary-label" style={{ textTransform: "capitalize" }}>{col}</span>
                <div className="pnl-summary-row">
                  <span>Rev</span><span>{fmt(fleet.totals[col].revenue)}</span>
                </div>
                <div className="pnl-summary-row">
                  <span>Cost</span><span>{fmt(fleet.totals[col].cost)}</span>
                </div>
                <div className="pnl-summary-row">
                  <span>P&L</span>
                  <span className={fleet.totals[col].pnl >= 0 ? "pnl-fav" : "pnl-adv"}>
                    {fmt(fleet.totals[col].pnl)}
                  </span>
                </div>
                {col === "estimate" && fleet.totals.estimate.tce != null ? (
                  <div className="pnl-summary-row">
                    <span>TCE</span><span>{fmt(fleet.totals.estimate.tce)}</span>
                  </div>
                ) : null}
              </div>
            ))}
            <div className="pnl-summary-card">
              <span className="pnl-summary-label">{t("page.pnl.paid", "Paid")}</span>
              <span className="pnl-summary-value">{fmt(fleet.paid_amount)}</span>
            </div>
          </div>
        ) : null}

        {loading ? (
          <div className="skeleton-table" />
        ) : (
          <div className="table-scroll">
            <table className="table pnl-table">
              <thead>
                <tr>
                  <th rowSpan={2} className="pnl-sticky-col" onClick={() => toggleSort("voyage_no")}>
                    {t("page.voyages.no", "Voyage")}{sortIcon("voyage_no")}
                  </th>
                  <th rowSpan={2} onClick={() => toggleSort("status")}>
                    {t("common.status", "Status")}{sortIcon("status")}
                  </th>
                  <th colSpan={3} className="pnl-col-header pnl-col-estimate">Estimate</th>
                  <th colSpan={3} className="pnl-col-header pnl-col-actual">Actual</th>
                  <th colSpan={3} className="pnl-col-header pnl-col-posted">Posted</th>
                  <th colSpan={3} className="pnl-col-header pnl-col-variance">Variance</th>
                </tr>
                <tr>
                  {(["estimate", "actual", "posted"] as const).map((col) => (
                    <Fragment key={col}>
                      <th className="pnl-num" onClick={() => toggleSort(`totals.${col}.revenue`)}>
                        Rev{sortIcon(`totals.${col}.revenue`)}
                      </th>
                      <th className="pnl-num" onClick={() => toggleSort(`totals.${col}.cost`)}>
                        Cost{sortIcon(`totals.${col}.cost`)}
                      </th>
                      <th className="pnl-num" onClick={() => toggleSort(`totals.${col}.pnl`)}>
                        P&L{sortIcon(`totals.${col}.pnl`)}
                      </th>
                    </Fragment>
                  ))}
                  <th className="pnl-num">Fav/(Adv)</th>
                  <th className="pnl-num">%</th>
                  <th className="pnl-num">P&L</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((r) => {
                  const estPnl = r.totals.estimate.pnl;
                  const actPnl = r.totals.actual.pnl;
                  const varPnl = actPnl - estPnl;
                  const varPct = estPnl !== 0 ? (varPnl / Math.abs(estPnl)) * 100 : null;
                  return (
                    <tr key={r.voyage_id}>
                      <td className="pnl-sticky-col">
                        <Link href={`/finance/pnl/${r.voyage_id}`}>{r.voyage_no}</Link>
                      </td>
                      <td>{r.status}</td>
                      <td className="pnl-num pnl-col-estimate">{fmt(r.totals.estimate.revenue)}</td>
                      <td className="pnl-num pnl-col-estimate">{fmt(r.totals.estimate.cost)}</td>
                      <td className="pnl-num pnl-col-estimate">{fmt(r.totals.estimate.pnl)}</td>
                      <td className="pnl-num pnl-col-actual">{fmt(r.totals.actual.revenue)}</td>
                      <td className="pnl-num pnl-col-actual">{fmt(r.totals.actual.cost)}</td>
                      <td className="pnl-num pnl-col-actual">{fmt(r.totals.actual.pnl)}</td>
                      <td className="pnl-num pnl-col-posted">{fmt(r.totals.posted.revenue)}</td>
                      <td className="pnl-num pnl-col-posted">{fmt(r.totals.posted.cost)}</td>
                      <td className="pnl-num pnl-col-posted">{fmt(r.totals.posted.pnl)}</td>
                      <td className={`pnl-num ${varianceClass(varPnl, estPnl)}`}>{fmt(varPnl)}</td>
                      <td className={`pnl-num ${varPct != null && Math.abs(varPct) > 10 ? (varPnl >= 0 ? "pnl-fav" : "pnl-adv") : ""}`}>
                        {varPct != null ? `${varPct.toFixed(1)}%` : "—"}
                      </td>
                      <td className={`pnl-num pnl-col-variance`}>{fmt(r.columns.variance.revenue + r.columns.variance.hire + r.columns.variance.demurrage)}</td>
                    </tr>
                  );
                })}
                {!sorted.length ? (
                  <tr><td colSpan={14} className="muted">{t("common.empty", "No records")}</td></tr>
                ) : null}
              </tbody>
              {fleet ? (
                <tfoot>
                  <tr className="pnl-total-row">
                    <td className="pnl-sticky-col"><strong>FLEET TOTAL</strong></td>
                    <td></td>
                    <td className="pnl-num">{fmt(fleet.totals.estimate.revenue)}</td>
                    <td className="pnl-num">{fmt(fleet.totals.estimate.cost)}</td>
                    <td className="pnl-num">{fmt(fleet.totals.estimate.pnl)}</td>
                    <td className="pnl-num">{fmt(fleet.totals.actual.revenue)}</td>
                    <td className="pnl-num">{fmt(fleet.totals.actual.cost)}</td>
                    <td className="pnl-num">{fmt(fleet.totals.actual.pnl)}</td>
                    <td className="pnl-num">{fmt(fleet.totals.posted.revenue)}</td>
                    <td className="pnl-num">{fmt(fleet.totals.posted.cost)}</td>
                    <td className="pnl-num">{fmt(fleet.totals.posted.pnl)}</td>
                    <td className="pnl-num">{fmt(fleet.totals.actual.pnl - fleet.totals.estimate.pnl)}</td>
                    <td className="pnl-num">—</td>
                    <td className="pnl-num">—</td>
                  </tr>
                </tfoot>
              ) : null}
            </table>
          </div>
        )}
      </div>
    </AppShell>
  );
}
