"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { Num } from "@/components/Num";
import { RevisionsPanel } from "@/components/RevisionsPanel";
import { StateView } from "@/components/StateView";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { apiGet } from "@/lib/api";
import { msgOf } from "@/lib/errors";
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
  const [err, setErr] = useState<string | null>(null);
  const [grossNet, setGrossNet] = useState<"gross" | "net">("gross");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const rows = (await apiGet(`/api/v1/analytics/reports/pnl-4col?voyage_id=${voyageId}`)) as VoyageData[];
      setData(rows[0] ?? null);
    } catch (ex: any) {
      // P1-31：只有 404 才是「未找到」；500/403 等一律显示加载失败 + 重试
      setData(null);
      if (ex?.status === 404) setErr(null);
      else setErr(msgOf(ex));
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

  type PnlDetailRow = {
    id: string;
    label: string;
    kind: "line" | "subtotal" | "total" | "tce" | "commission";
    est: number | null;
    act: number | null;
    posted: number | null;
    vari: number | null;
    pct: number | null;
    paren?: boolean;
    indent?: boolean;
    boldLabel?: boolean;
  };

  const detailRows = useMemo<PnlDetailRow[]>(() => {
    if (!data) return [];
    const estTotals = data.totals.estimate;
    const actTotals = data.totals.actual;
    const postTotals = data.totals.posted;
    const pnlVariance = actTotals.pnl - estTotals.pnl;
    const pnlVariancePct = variancePct(actTotals.pnl, estTotals.pnl);

    if (grossNet === "gross") {
      const rows: PnlDetailRow[] = LINE_KEYS.map((k) => {
        const est = data.columns.estimate[k];
        const act = data.columns.actual[k];
        const posted = data.columns.posted[k];
        const vari = data.columns.variance[k];
        return {
          id: `line-${k}`,
          label: LINE_LABELS[k],
          kind: "line",
          est,
          act,
          posted,
          vari,
          pct: variancePct(act, est),
        };
      });
      rows.push(
        {
          id: "total-revenue",
          label: t("page.pnl.total_revenue", "Total Revenue"),
          kind: "subtotal",
          est: estTotals.revenue,
          act: actTotals.revenue,
          posted: postTotals.revenue,
          vari: actTotals.revenue - estTotals.revenue,
          pct: null,
        },
        {
          id: "total-cost",
          label: t("page.pnl.total_cost", "Total Cost"),
          kind: "subtotal",
          est: estTotals.cost,
          act: actTotals.cost,
          posted: postTotals.cost,
          vari: actTotals.cost - estTotals.cost,
          pct: null,
        },
        {
          id: "net-pnl",
          label: t("page.pnl.net_pnl", "NET P&L"),
          kind: "total",
          est: estTotals.pnl,
          act: actTotals.pnl,
          posted: postTotals.pnl,
          vari: pnlVariance,
          pct: pnlVariancePct,
        },
      );
      if (estTotals.tce != null) {
        rows.push({
          id: "tce",
          label: "TCE",
          kind: "tce",
          est: estTotals.tce,
          act: null,
          posted: null,
          vari: null,
          pct: null,
        });
      }
      return rows;
    }

    return [
      {
        id: "gross-revenue",
        label: t("page.pnl.gross_revenue", "Gross Revenue"),
        kind: "line",
        boldLabel: true,
        est: data.columns.estimate.revenue + data.columns.estimate.hire + data.columns.estimate.demurrage,
        act: data.columns.actual.revenue + data.columns.actual.hire + data.columns.actual.demurrage,
        posted: data.columns.posted.revenue + data.columns.posted.hire + data.columns.posted.demurrage,
        vari: null,
        pct: null,
      },
      {
        id: "commission",
        label: `- ${LINE_LABELS.commission}`,
        kind: "commission",
        est: data.columns.estimate.commission,
        act: data.columns.actual.commission,
        posted: data.columns.posted.commission,
        vari: null,
        pct: null,
        paren: true,
        indent: true,
      },
      {
        id: "net-revenue",
        label: t("page.pnl.net_revenue", "Net Revenue"),
        kind: "subtotal",
        est: estTotals.revenue - data.columns.estimate.commission,
        act: actTotals.revenue - data.columns.actual.commission,
        posted: postTotals.revenue - data.columns.posted.commission,
        vari: null,
        pct: null,
      },
      {
        id: "total-cost",
        label: t("page.pnl.total_cost", "Total Cost"),
        kind: "line",
        boldLabel: true,
        est: estTotals.cost,
        act: actTotals.cost,
        posted: postTotals.cost,
        vari: null,
        pct: null,
      },
      {
        id: "net-pnl",
        label: t("page.pnl.net_pnl", "NET P&L"),
        kind: "total",
        est: estTotals.pnl,
        act: actTotals.pnl,
        posted: postTotals.pnl,
        vari: pnlVariance,
        pct: pnlVariancePct,
      },
    ];
  }, [data, grossNet, t]);

  const detailCols = useMemo<ColumnDef<PnlDetailRow>[]>(
    () => [
      {
        key: "label",
        title: t("page.pnl.line_item", "Line Item"),
        minWidth: 180,
        value: (r) => r.label,
        render: (_v, r) => (
          <span style={r.indent ? { paddingLeft: "1.5rem" } : undefined}>
            {r.id.startsWith("line-") ? (
              <span className="pnl-expand">{expanded.has(r.id.slice(5)) ? "▾" : "▸"}</span>
            ) : null}
            {r.kind === "line" && !r.boldLabel ? r.label : <strong>{r.label}</strong>}
          </span>
        ),
      },
      {
        key: "est",
        title: t("page.pnl.estimate", "Estimate"),
        align: "right",
        value: (r) => r.est,
        render: (v, r) => numCell(v as number | null, { bold: numBold(r), paren: r.paren }),
      },
      {
        key: "act",
        title: t("page.pnl.actual", "Actual"),
        align: "right",
        value: (r) => r.act,
        render: (v, r) =>
          numCell(v as number | null, {
            bold: numBold(r),
            paren: r.paren,
            cls: r.kind === "total" && v != null ? ((v as number) >= 0 ? "pnl-fav" : "pnl-adv") : undefined,
          }),
      },
      {
        key: "posted",
        title: t("page.pnl.posted", "Posted"),
        align: "right",
        value: (r) => r.posted,
        render: (v, r) => numCell(v as number | null, { bold: numBold(r), paren: r.paren }),
      },
      {
        key: "vari",
        title: t("page.pnl.variance", "Variance"),
        align: "right",
        value: (r) => r.vari,
        render: (v, r) =>
          numCell(v as number | null, {
            bold: numBold(r),
            cls: v != null && r.est != null ? varianceClass(v as number, r.est) : undefined,
          }),
      },
      {
        key: "pct",
        title: t("page.pnl.var_pct", "Var %"),
        align: "right",
        value: (r) => r.pct,
        render: (v, r) => {
          const pct = v as number | null;
          if (pct == null) return "—";
          const cls = Math.abs(pct) > 10 ? ((r.vari ?? 0) >= 0 ? "pnl-fav" : "pnl-adv") : "";
          const body = r.kind !== "line" ? <strong>{`${pct.toFixed(1)}%`}</strong> : `${pct.toFixed(1)}%`;
          return <span className={cls || undefined}>{body}</span>;
        },
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, expanded],
  );

  function numCell(v: number | null, opts: { bold?: boolean; paren?: boolean; cls?: string }) {
    if (v == null) return "—";
    const core = opts.paren ? (
      <>
        (<Num v={v} digits={2} />)
      </>
    ) : (
      <Num v={v} digits={2} />
    );
    const body = opts.bold ? <strong>{core}</strong> : core;
    return opts.cls ? <span className={opts.cls}>{body}</span> : body;
  }

  const numBold = (r: PnlDetailRow) => r.kind === "subtotal" || r.kind === "total" || r.kind === "tce";

  if (loading) {
    return (
      <AppShell>
        <PageHeader
          breadcrumb={[
            { label: t("nav.finance", "Finance"), href: "/finance?tab=pnl" },
            { label: t("page.pnl.title", "Profit & Loss"), href: "/finance/pnl" },
            { label: `#${voyageId}` },
          ]}
          title={t("common.loading", "Loading…")}
        />
        <div className="panel"><div className="skeleton-table" /></div>
      </AppShell>
    );
  }

  if (err) {
    return (
      <AppShell>
        <PageHeader
          breadcrumb={[
            { label: t("nav.finance", "Finance"), href: "/finance?tab=pnl" },
            { label: t("page.pnl.title", "Profit & Loss"), href: "/finance/pnl" },
            { label: `#${voyageId}` },
          ]}
          title={t("page.pnl.load_failed", "Failed to load voyage P&L")}
        />
        <div className="panel">
          <StateView loading={false} error={err} empty={false} onRetry={() => void load()}>
            <span />
          </StateView>
        </div>
      </AppShell>
    );
  }

  if (!data) {
    return (
      <AppShell>
        <PageHeader
          breadcrumb={[
            { label: t("nav.finance", "Finance"), href: "/finance?tab=pnl" },
            { label: t("page.pnl.title", "Profit & Loss"), href: "/finance/pnl" },
            { label: `#${voyageId}` },
          ]}
          title={t("common.not_found", "Not found")}
        />
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
    <AppShell>
      <PageHeader
        breadcrumb={[
          { label: t("nav.finance", "Finance"), href: "/finance?tab=pnl" },
          { label: t("page.pnl.title", "Profit & Loss"), href: "/finance/pnl" },
          { label: data.voyage_no ? `#${data.voyage_no}` : `#${voyageId}` },
        ]}
        title={`${t("page.pnl.voyage_title", "Voyage P&L")} — ${data.voyage_no}`}
        subtitle={`${data.status} ${data.cargo ? `· ${data.cargo}` : ""}`}
        actions={
          <>
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
          </>
        }
      />
      <div className="panel">

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

        <DataGrid<PnlDetailRow>
          columns={detailCols}
          data={detailRows}
          rowKey={(r) => r.id}
          onRowClick={(r) => {
            if (r.id.startsWith("line-")) toggleLine(r.id.slice(5));
          }}
          storageKey="finance_pnl_voyage_grid"
          showFooter={false}
          emptyText={t("common.empty", "No records")}
        />
      </div>
      {voyageId ? <RevisionsPanel entityType="voyage" entityId={voyageId} /> : null}
    </AppShell>
  );
}
