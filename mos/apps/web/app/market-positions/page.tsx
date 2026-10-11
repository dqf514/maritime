"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { StateView } from "@/components/StateView";
import { apiGet } from "@/lib/api";
import { fmt } from "@/lib/fmt";
import { useI18n } from "@/lib/i18n";

type MarketPosition = {
  id: string;
  route: string;
  commodity: string;
  period: string;
  long_qty: number;
  short_qty: number;
  net_qty: number;
  avg_price: number;
  market_price: number;
  unrealized_pnl: number;
  var_95: number;
};

function num(v: unknown): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function unwrapList(data: unknown): Record<string, unknown>[] {
  if (Array.isArray(data)) return data as Record<string, unknown>[];
  if (data && typeof data === "object") {
    const o = data as { items?: unknown; rows?: unknown; results?: unknown };
    const arr = o.items ?? o.rows ?? o.results;
    if (Array.isArray(arr)) return arr as Record<string, unknown>[];
  }
  return [];
}

function MarketPositionsWorkspace() {
  const { t } = useI18n();
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState("");
  const [rows, setRows] = useState<MarketPosition[]>([]);
  const [filterCommodity, setFilterCommodity] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setLoadErr("");
    try {
      const data = await apiGet("/api/v1/market-positions");
      setRows(
        unwrapList(data).map((r) => ({
          id: String(r.id ?? `${r.route}-${r.period}`),
          route: String(r.route ?? ""),
          commodity: String(r.commodity ?? ""),
          period: String(r.period ?? ""),
          long_qty: num(r.long_qty),
          short_qty: num(r.short_qty),
          net_qty: num(r.net_qty),
          avg_price: num(r.avg_price),
          market_price: num(r.market_price),
          unrealized_pnl: num(r.unrealized_pnl),
          var_95: num(r.var_95),
        })),
      );
    } catch (ex) {
      setLoadErr(String(ex));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const commodities = useMemo(() => {
    const s = new Set(rows.map((r) => r.commodity).filter(Boolean));
    return Array.from(s).sort();
  }, [rows]);

  const filtered = useMemo(
    () => (filterCommodity ? rows.filter((r) => r.commodity === filterCommodity) : rows),
    [rows, filterCommodity],
  );

  const totals = useMemo(() => {
    let longTotal = 0, shortTotal = 0, netTotal = 0, pnlTotal = 0;
    for (const r of filtered) {
      longTotal += r.long_qty;
      shortTotal += r.short_qty;
      netTotal += r.net_qty;
      pnlTotal += r.unrealized_pnl;
    }
    return { longTotal, shortTotal, netTotal, pnlTotal };
  }, [filtered]);

  const cols = useMemo<ColumnDef<MarketPosition>[]>(
    () => [
      { key: "route", title: t("page.market_pos.route", "Route"), width: 120, sortable: true, sticky: true },
      { key: "commodity", title: t("page.market_pos.commodity", "Commodity"), width: 100, sortable: true },
      { key: "period", title: t("page.market_pos.period", "Period"), width: 120, sortable: true },
      {
        key: "long_qty", title: t("page.market_pos.long", "Long"), width: 100, align: "right", agg: "sum",
        value: (r) => r.long_qty, render: (v) => fmt(num(v)),
      },
      {
        key: "short_qty", title: t("page.market_pos.short", "Short"), width: 100, align: "right", agg: "sum",
        value: (r) => r.short_qty, render: (v) => fmt(num(v)),
      },
      {
        key: "net_qty", title: t("page.market_pos.net", "Net"), width: 100, align: "right", agg: "sum",
        value: (r) => r.net_qty,
        render: (v) => {
          const n = num(v);
          return <span className={n >= 0 ? "pnl-pos" : "pnl-neg"}>{fmt(n)}</span>;
        },
      },
      {
        key: "avg_price", title: t("page.market_pos.avg_price", "Avg price"), width: 100, align: "right", agg: "avg",
        value: (r) => r.avg_price, render: (v) => fmt(num(v)),
      },
      {
        key: "market_price", title: t("page.market_pos.mkt_price", "Mkt price"), width: 100, align: "right", agg: "avg",
        value: (r) => r.market_price, render: (v) => fmt(num(v)),
      },
      {
        key: "unrealized_pnl", title: t("page.market_pos.unrealized", "Unrealized P&L"), width: 130, align: "right", agg: "sum",
        value: (r) => r.unrealized_pnl,
        render: (v) => {
          const n = num(v);
          return <span className={n >= 0 ? "pnl-pos" : "pnl-neg"}>{fmt(n)}</span>;
        },
      },
      {
        key: "var_95", title: t("page.market_pos.var", "VaR 95%"), width: 100, align: "right",
        value: (r) => r.var_95, render: (v) => fmt(num(v)),
      },
    ],
    [t],
  );

  return (
    <AppShell>
      <PageHeader
        title={t("page.market_pos.title", "Market Positions")}
        subtitle={t("page.market_pos.sub", "Consolidated view of paper and physical positions across all books.")}
        actions={
          <button type="button" className="btn btn-sm" onClick={load}>
            {t("common.refresh", "Refresh")}
          </button>
        }
      />

      <div className="mtm-tiles" style={{ marginBottom: "var(--gap-md)" }}>
        <div className="mtm-tile">
          <span>{t("page.market_pos.total_long", "Total long")}</span>
          <strong>{fmt(totals.longTotal)}</strong>
        </div>
        <div className="mtm-tile">
          <span>{t("page.market_pos.total_short", "Total short")}</span>
          <strong>{fmt(totals.shortTotal)}</strong>
        </div>
        <div className={`mtm-tile ${totals.netTotal >= 0 ? "pos" : "neg"}`}>
          <span>{t("page.market_pos.total_net", "Net position")}</span>
          <strong>{fmt(totals.netTotal)}</strong>
        </div>
        <div className={`mtm-tile ${totals.pnlTotal >= 0 ? "pos" : "neg"}`}>
          <span>{t("page.market_pos.total_pnl", "Unrealized P&L")}</span>
          <strong>{fmt(totals.pnlTotal)}</strong>
        </div>
      </div>

      <div className="trading-toolbar">
        <span className="field-inline">
          {t("page.market_pos.filter_commodity", "Commodity")}
          <select value={filterCommodity} onChange={(e) => setFilterCommodity(e.target.value)}>
            <option value="">{t("common.all", "All")}</option>
            {commodities.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </span>
        <div className="spacer" />
        <span className="hint">{t("page.market_pos.count", "{n} positions", { n: filtered.length })}</span>
      </div>

      <StateView loading={loading} error={loadErr} empty={!loading && !loadErr && filtered.length === 0} onRetry={load}>
        <div className="trading-grid-wrap">
          <DataGrid<MarketPosition>
            columns={cols}
            data={filtered}
            rowKey={(r) => r.id}
            storageKey="market_positions"
            emptyText={t("common.empty", "No records")}
          />
        </div>
      </StateView>
    </AppShell>
  );
}

export default function MarketPositionsPage() {
  return (
    <Suspense fallback={null}>
      <MarketPositionsWorkspace />
    </Suspense>
  );
}
