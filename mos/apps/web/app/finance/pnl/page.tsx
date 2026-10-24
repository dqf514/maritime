"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { Num } from "@/components/Num";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { apiGet } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { StateView } from "@/components/StateView";

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

  // P0-16/17：走 lib/csv（自带 BOM + 公式注入防护），不再自造 Blob。
  const body: (string | number)[][] = rows.map((r) => {
    const cells: (string | number)[] = [r.voyage_no, r.status, r.cargo ?? ""];
    for (const col of ["estimate", "actual", "posted"] as const) {
      for (const k of LINE_KEYS) cells.push(r.columns[col][k] ?? 0);
      const t = r.totals[col as "estimate" | "actual" | "posted"];
      cells.push(t.revenue, t.cost, t.pnl);
    }
    for (const k of LINE_KEYS) cells.push(r.columns.variance[k] ?? 0);
    return cells;
  });
  downloadCsv(`pnl_fleet_${new Date().toISOString().slice(0, 10)}`, cols, body);
}

export default function PnlOverviewPage() {
  const { t } = useI18n();
  const [voyages, setVoyages] = useState<VoyageRow[]>([]);
  const [fleet, setFleet] = useState<FleetSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<string>("voyage_no");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const [v, f] = await Promise.all([
        apiGet("/api/v1/analytics/reports/pnl-4col") as Promise<VoyageRow[]>,
        apiGet("/api/v1/analytics/reports/pnl-fleet") as Promise<FleetSummary>,
      ]);
      setVoyages(v);
      setFleet(f);
    } catch (ex) {
      // P1-4：主列表取数失败必须走错误态，不能静默变空表
      setErr(msgOf(ex));
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
      } else if (sortKey === "variance_fav") {
        av = (a.totals.actual?.pnl ?? 0) - (a.totals.estimate?.pnl ?? 0);
        bv = (b.totals.actual?.pnl ?? 0) - (b.totals.estimate?.pnl ?? 0);
      } else if (sortKey === "variance_line") {
        av = (a.columns.variance?.revenue ?? 0) + (a.columns.variance?.hire ?? 0) + (a.columns.variance?.demurrage ?? 0);
        bv = (b.columns.variance?.revenue ?? 0) + (b.columns.variance?.hire ?? 0) + (b.columns.variance?.demurrage ?? 0);
      } else {
        av = 0; bv = 0;
      }
      if (typeof av === "string") return sortDir === "asc" ? av.localeCompare(bv as string) : (bv as string).localeCompare(av);
      return sortDir === "asc" ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
    return arr;
  }, [voyages, sortKey, sortDir]);

  const FLEET_ID = "__fleet_total__";

  type GridRow = VoyageRow | (FleetSummary & { voyage_id: string; voyage_no: string; status: string });

  const gridRows = useMemo<GridRow[]>(() => {
    const rows: GridRow[] = [...sorted];
    if (fleet) {
      rows.push({ ...fleet, voyage_id: FLEET_ID, voyage_no: "FLEET TOTAL", status: "" });
    }
    return rows;
  }, [sorted, fleet]);

  const isFleet = (r: GridRow) => r.voyage_id === FLEET_ID;

  const fleetNum = (v: number, fleetRow: boolean) =>
    fleetRow ? (
      <strong>
        <Num v={v} digits={2} />
      </strong>
    ) : (
      <Num v={v} digits={2} />
    );

  const cols = useMemo<ColumnDef<GridRow>[]>(
    () => [
      {
        key: "voyage_no",
        title: t("page.voyages.no", "Voyage"),
        width: 130,
        sticky: true,
        sortable: true,
        value: (r) => r.voyage_no,
        render: (v, r) =>
          isFleet(r) ? (
            <strong>{String(v)}</strong>
          ) : (
            <Link href={`/finance/pnl/${r.voyage_id}`}>{String(v)}</Link>
          ),
      },
      {
        key: "status",
        title: t("common.status", "Status"),
        width: 100,
        sortable: true,
        value: (r) => r.status,
        // 不写 render：让 DataGrid status.* 自动翻译（走查：raw planned/completed）
        render: (v, r) => (isFleet(r) ? "" : v ? t(`status.${v}`, String(v).replace(/_/g, " ")) : ""),
      },
      {
        key: "totals.estimate.revenue",
        title: t("page.pnl.est_rev_short", "Est. Rev"),
        align: "right",
        sortable: true,
        value: (r) => r.totals.estimate.revenue,
        render: (v, r) => fleetNum(v as number, isFleet(r)),
      },
      {
        key: "totals.estimate.cost",
        title: t("page.pnl.est_cost_short", "Est. Cost"),
        align: "right",
        sortable: true,
        value: (r) => r.totals.estimate.cost,
        render: (v, r) => fleetNum(v as number, isFleet(r)),
      },
      {
        key: "totals.estimate.pnl",
        title: t("page.pnl.est_pnl_short", "Est. P&L"),
        align: "right",
        sortable: true,
        value: (r) => r.totals.estimate.pnl,
        render: (v, r) => fleetNum(v as number, isFleet(r)),
      },
      {
        key: "totals.actual.revenue",
        title: t("page.pnl.act_rev_short", "Act. Rev"),
        align: "right",
        sortable: true,
        value: (r) => r.totals.actual.revenue,
        render: (v, r) => fleetNum(v as number, isFleet(r)),
      },
      {
        key: "totals.actual.cost",
        title: t("page.pnl.act_cost_short", "Act. Cost"),
        align: "right",
        sortable: true,
        value: (r) => r.totals.actual.cost,
        render: (v, r) => fleetNum(v as number, isFleet(r)),
      },
      {
        key: "totals.actual.pnl",
        title: t("page.pnl.act_pnl_short", "Act. P&L"),
        align: "right",
        sortable: true,
        value: (r) => r.totals.actual.pnl,
        render: (v, r) => fleetNum(v as number, isFleet(r)),
      },
      {
        key: "totals.posted.revenue",
        title: t("page.pnl.post_rev_short", "Post. Rev"),
        align: "right",
        sortable: true,
        value: (r) => r.totals.posted.revenue,
        render: (v, r) => fleetNum(v as number, isFleet(r)),
      },
      {
        key: "totals.posted.cost",
        title: t("page.pnl.post_cost_short", "Post. Cost"),
        align: "right",
        sortable: true,
        value: (r) => r.totals.posted.cost,
        render: (v, r) => fleetNum(v as number, isFleet(r)),
      },
      {
        key: "totals.posted.pnl",
        title: t("page.pnl.post_pnl_short", "Post. P&L"),
        align: "right",
        sortable: true,
        value: (r) => r.totals.posted.pnl,
        render: (v, r) => fleetNum(v as number, isFleet(r)),
      },
      {
        key: "variance_fav",
        title: t("page.pnl.fav_adv", "Fav/(Adv)"),
        align: "right",
        sortable: true,
        value: (r) => r.totals.actual.pnl - r.totals.estimate.pnl,
        render: (_v, r) => {
          const estPnl = r.totals.estimate.pnl;
          const varPnl = r.totals.actual.pnl - estPnl;
          if (isFleet(r)) return <strong><Num v={varPnl} digits={2} /></strong>;
          return <span className={varianceClass(varPnl, estPnl)}><Num v={varPnl} digits={2} /></span>;
        },
      },
      {
        key: "variance_pct",
        title: t("page.pnl.var_pct", "%"),
        align: "right",
        value: (r) => {
          if (isFleet(r)) return null;
          const estPnl = r.totals.estimate.pnl;
          return estPnl !== 0 ? ((r.totals.actual.pnl - estPnl) / Math.abs(estPnl)) * 100 : null;
        },
        render: (_v, r) => {
          if (isFleet(r)) return "—";
          const estPnl = r.totals.estimate.pnl;
          const varPnl = r.totals.actual.pnl - estPnl;
          const varPct = estPnl !== 0 ? (varPnl / Math.abs(estPnl)) * 100 : null;
          if (varPct == null) return "—";
          const cls = Math.abs(varPct) > 10 ? (varPnl >= 0 ? "pnl-fav" : "pnl-adv") : "";
          return <span className={cls}>{`${varPct.toFixed(1)}%`}</span>;
        },
      },
      {
        key: "variance_line",
        title: t("page.pnl.var_pnl_short", "Var. P&L"),
        align: "right",
        sortable: true,
        value: (r) => {
          if (isFleet(r)) return null;
          return (r.columns.variance?.revenue ?? 0) + (r.columns.variance?.hire ?? 0) + (r.columns.variance?.demurrage ?? 0);
        },
        render: (_v, r) => {
          if (isFleet(r)) return "—";
          return (
            <Num
              v={(r.columns.variance?.revenue ?? 0) + (r.columns.variance?.hire ?? 0) + (r.columns.variance?.demurrage ?? 0)}
              digits={2}
            />
          );
        },
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t],
  );

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[
          { label: t("nav.finance", "Finance"), href: "/finance?tab=pnl" },
          { label: t("page.pnl.title", "Profit & Loss") },
        ]}
        title={t("page.pnl.title", "Profit & Loss — 4-Column Comparison")}
        actions={
          <>
            <button className="btn btn-sm btn-ghost" type="button" onClick={load}>
              {t("common.refresh", "Refresh")}
            </button>
            <button className="btn btn-sm" type="button" onClick={() => exportCsv(sorted)}>
              {t("common.export_csv", "Export CSV")}
            </button>
          </>
        }
      />
      <div className="panel">

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

        <StateView
          loading={loading}
          error={err ?? undefined}
          empty={!loading && !err && !gridRows.length}
          emptyText={t("common.empty", "No records")}
          onRetry={() => void load()}
        >
          <DataGrid<GridRow>
            columns={cols}
            data={gridRows}
            rowKey={(r) => r.voyage_id}
            onSortChange={(key, dir) => {
              setSortKey(key);
              setSortDir(dir === "desc" ? "desc" : "asc");
            }}
            storageKey="finance_pnl_list_grid"
            showFooter={false}
            emptyText={t("common.empty", "No records")}
          />
        </StateView>
      </div>
    </AppShell>
  );
}
