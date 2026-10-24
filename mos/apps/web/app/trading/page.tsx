"use client";

// Phase 7 Trading — 交易工作台
// Blotter（成交簿）/ Positions（纸货实货净头寸）/ MtM P&L（逐日盯市）/ Exposure（敞口与限额）。
// 新建成交走 RecordModal；金额表均用 DataGrid 聚合 footer。

import { msgOf } from "@/lib/errors";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { RefreshButton } from "@/components/RefreshButton";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { Num } from "@/components/Num";
import { PageHeader } from "@/components/PageHeader";
import { SavedViews } from "@/components/SavedViews";
import { StatusLegend } from "@/components/StatusLegend";
import { Tabs, type TabItem } from "@/components/Tabs";
import { Toolbar } from "@/components/Toolbar";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { FormPanel, FormSection, FieldRow } from "@/components/form/FormPanel";
import { RecordModal } from "@/components/RecordModal";
import { DateInput } from "@/components/DateInput";
import { PartyPicker } from "@/components/DataPicker";
import { LookupSelect } from "@/components/LookupSelect";
import { StateView } from "@/components/StateView";
import { useListHotkeys } from "@/components/useListHotkeys";
import { useToast } from "@/components/ToastProvider";
import { ValidateButton, type ValidateIssue } from "@/components/ValidateButton";
import { apiGet, apiList, apiPost } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";

const TRADE_KINDS = ["ffa", "swap", "option", "physical", "paper"] as const;

type Trade = {
  id: string;
  trade_no: string;
  kind: string;
  buy_sell: string;
  route: string | null;
  period_from: string | null;
  period_to: string | null;
  qty: number;
  price: number;
  index_symbol: string | null;
  counterparty_id: string | null;
  counterparty_name?: string | null;
  status: string;
  trade_date: string;
  notes?: string | null;
  updated_at?: string | null;
};

type PositionRow = {
  id?: string;
  route: string | null;
  period: string | null;
  paper_qty: number;
  physical_qty: number;
  net_qty: number;
};

type MtmRow = {
  id?: string;
  trade_no: string;
  book_price: number;
  market_price: number;
  unrealized_pnl: number;
  realized_pnl?: number;
};

type ExposureRow = {
  id?: string;
  route: string | null;
  period: string | null;
  net_exposure: number;
  limit?: number | null;
  limit_breach?: boolean;
};

type Tab = "blotter" | "positions" | "mtm" | "exposure";
const TAB_IDS: readonly string[] = ["blotter", "positions", "mtm", "exposure"];

function num(v: unknown): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

/** 列表响应宽容取数组：裸数组 / envelope.items / rows / results。 */
function unwrapList(data: unknown): Record<string, unknown>[] {
  if (Array.isArray(data)) return data as Record<string, unknown>[];
  if (data && typeof data === "object") {
    const o = data as { items?: unknown; rows?: unknown; results?: unknown };
    const arr = o.items ?? o.rows ?? o.results;
    if (Array.isArray(arr)) return arr as Record<string, unknown>[];
  }
  return [];
}

function TradingWorkspace() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const { query, setQuery, page, limit } = useListQuery();
  const tab: Tab = TAB_IDS.includes(query.tab ?? "") ? (query.tab as Tab) : "blotter";
  const setTab = (id: Tab) => setQuery({ tab: id === "blotter" ? null : id, page: null });
  useListHotkeys(() => setTradeModal(true));

  // —— shared ——
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState("");
  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);

  // —— blotter ——
  const [trades, setTrades] = useState<Trade[]>([]);
  /** blotter 总条数（分页） */
  const [tradesTotal, setTradesTotal] = useState(0);

  // —— positions ——
  const [positions, setPositions] = useState<PositionRow[]>([]);

  // —— mtm ——
  const [mtmDate, setMtmDate] = useState(today);
  const [mtmRows, setMtmRows] = useState<MtmRow[]>([]);
  const [mtmRunning, setMtmRunning] = useState(false);

  // —— exposure ——
  const [exposure, setExposure] = useState<ExposureRow[]>([]);

  // —— new trade modal ——
  const [tradeModal, setTradeModal] = useState(false);
  const [tradeSaving, setTradeSaving] = useState(false);
  const [tradeForm, setTradeForm] = useState({
    kind: "ffa",
    buy_sell: "buy",
    route: "",
    period_from: "",
    period_to: "",
    qty: "1000",
    price: "0",
    index_symbol: "",
    counterparty_id: "",
    trade_date: today,
  });

  const tradeCtx = useContextMenu<Trade>();
  const posCtx = useContextMenu<PositionRow>();
  const mtmCtx = useContextMenu<MtmRow>();
  const expCtx = useContextMenu<ExposureRow>();

  const load = useCallback(async () => {
    setLoading(true);
    setLoadErr("");
    try {
      if (tab === "blotter") {
        // P1-28：分页取数，不再静默截断到 200 条
        const res = await apiList<Trade>("/api/v1/trading/trades", { limit, offset: (page - 1) * limit });
        setTrades(res.items);
        setTradesTotal(res.total);
      } else if (tab === "positions") {
        const data = await apiGet("/api/v1/trading/positions");
        setPositions(
          unwrapList(data).map((r) => ({
            id: r.id ? String(r.id) : undefined,
            route: (r.route as string) ?? null,
            period: (r.period as string) ?? formatPeriod(r.period_from, r.period_to),
            paper_qty: num(r.paper_qty),
            physical_qty: num(r.physical_qty),
            net_qty: num(r.net_qty ?? num(r.physical_qty) - num(r.paper_qty)),
          })),
        );
      } else if (tab === "mtm") {
        const data = await apiGet(`/api/v1/trading/mtm/summary?date=${encodeURIComponent(mtmDate)}`);
        setMtmRows(
          unwrapList(data).map((r) => ({
            id: r.id ? String(r.id) : undefined,
            trade_no: String(r.trade_no ?? r.trade_no_id ?? ""),
            book_price: num(r.book_price),
            market_price: num(r.market_price),
            unrealized_pnl: num(r.unrealized_pnl),
            realized_pnl: r.realized_pnl != null ? num(r.realized_pnl) : undefined,
          })),
        );
      } else {
        const data = await apiGet("/api/v1/trading/exposure");
        setExposure(
          unwrapList(data).map((r) => ({
            id: r.id ? String(r.id) : undefined,
            route: (r.route as string) ?? null,
            period: (r.period as string) ?? formatPeriod(r.period_from, r.period_to),
            net_exposure: num(r.net_exposure ?? r.exposure),
            limit: r.limit != null ? num(r.limit) : null,
            limit_breach: Boolean(r.limit_breach ?? r.breach),
          })),
        );
      }
    } catch (ex) {
      setLoadErr(msgOf(ex));
    } finally {
      setLoading(false);
    }
  }, [tab, mtmDate, page, limit]);

  useEffect(() => {
    load();
  }, [load]);

  async function runMtm() {
    setMtmRunning(true);
    try {
      await apiPost(`/api/v1/trading/mtm/run?date=${encodeURIComponent(mtmDate)}`);
      toast.success(t("page.trading.mtm_done", "MtM valuation completed"));
      await load();
    } catch (ex) {
      toast.error(msgOf(ex));
    } finally {
      setMtmRunning(false);
    }
  }

  async function createTrade() {
    const qtyNum = Number(tradeForm.qty);
    const priceNum = Number(tradeForm.price);
    if (!Number.isFinite(qtyNum) || !Number.isFinite(priceNum)) {
      toast.error(t("page.trading.bad_number", "Quantity and price must be valid numbers"));
      return;
    }
    setTradeSaving(true);
    try {
      await apiPost("/api/v1/trading/trades", {
        kind: tradeForm.kind,
        buy_sell: tradeForm.buy_sell,
        route: tradeForm.route || null,
        period_from: tradeForm.period_from || null,
        period_to: tradeForm.period_to || null,
        qty: qtyNum,
        price: priceNum,
        index_symbol: tradeForm.index_symbol || null,
        counterparty_id: tradeForm.counterparty_id || null,
        trade_date: tradeForm.trade_date || today,
      });
      toast.success(t("page.trading.trade_created", "Trade booked"));
      setTradeModal(false);
      setTradeForm({ ...tradeForm, route: "", period_from: "", period_to: "", price: "0", counterparty_id: "" });
      await load();
    } catch (ex) {
      toast.error(msgOf(ex));
    } finally {
      setTradeSaving(false);
    }
  }

  function validateTrade(): ValidateIssue[] {
    const issues: ValidateIssue[] = [];
    const qtyNum = Number(tradeForm.qty);
    const priceNum = Number(tradeForm.price);
    if (!Number.isFinite(qtyNum)) issues.push({ level: "error", message: t("page.trading.err_qty", "Quantity must be a number") });
    else if (qtyNum <= 0) issues.push({ level: "error", message: t("page.trading.err_qty_pos", "Quantity must be positive") });
    if (!Number.isFinite(priceNum)) issues.push({ level: "error", message: t("page.trading.err_price", "Price must be a number") });
    else if (priceNum < 0) issues.push({ level: "error", message: t("page.trading.err_price_neg", "Price must not be negative") });
    if (tradeForm.period_from && tradeForm.period_to && tradeForm.period_from > tradeForm.period_to)
      issues.push({ level: "error", message: t("page.trading.err_period", "Period from must be earlier than period to") });
    if (!tradeForm.route.trim()) issues.push({ level: "warn", message: t("page.trading.warn_route", "Route is empty") });
    return issues;
  }

  function copyText(value: string, label: string) {
    void navigator.clipboard.writeText(value);
    toast.success(label);
  }

  function exportTrades(list: Trade[]) {
    downloadCsv(
      "trades",
      ["trade_no", "kind", "buy_sell", "route", "period_from", "period_to", "qty", "price", "status", "trade_date"],
      list.map((r) => [r.trade_no, r.kind, r.buy_sell, r.route ?? "", r.period_from ?? "", r.period_to ?? "", r.qty, r.price, r.status, r.trade_date]),
      { emptyGuard: t("export.empty_confirm", "No rows to export. Export anyway?") },
    );
  }

  const tradeMenuItems = (r: Trade): ContextMenuItem[] => [
    { key: "copy_no", label: t("ctx.copy_trade_no", "Copy trade no"), onClick: () => copyText(r.trade_no, t("ctx.copied_id", "ID copied")) },
    { key: "copy", label: t("ctx.copy_id", "Copy id"), onClick: () => copyText(r.id, t("ctx.copied_id", "ID copied")) },
    { key: "export", label: t("ctx.export_selected", "Export selected"), onClick: () => exportTrades([r]) },
  ];

  const posMenuItems = (r: PositionRow): ContextMenuItem[] => [
    { key: "copy", label: t("ctx.copy_route", "Copy route"), onClick: () => copyText(r.route ?? "", t("ctx.copied_id", "ID copied")) },
    {
      key: "export",
      label: t("ctx.export_selected", "Export selected"),
      onClick: () =>
        downloadCsv("positions", ["route", "period", "paper_qty", "physical_qty", "net_qty"], [[r.route ?? "", r.period ?? "", r.paper_qty, r.physical_qty, r.net_qty]]),
    },
  ];

  const mtmMenuItems = (r: MtmRow): ContextMenuItem[] => [
    { key: "copy", label: t("ctx.copy_trade_no", "Copy trade no"), onClick: () => copyText(r.trade_no, t("ctx.copied_id", "ID copied")) },
    {
      key: "export",
      label: t("ctx.export_selected", "Export selected"),
      onClick: () =>
        downloadCsv("mtm", ["trade_no", "book_price", "market_price", "unrealized_pnl", "realized_pnl"], [[r.trade_no, r.book_price, r.market_price, r.unrealized_pnl, r.realized_pnl ?? ""]]),
    },
  ];

  const expMenuItems = (r: ExposureRow): ContextMenuItem[] => [
    { key: "copy", label: t("ctx.copy_route", "Copy route"), onClick: () => copyText(r.route ?? "", t("ctx.copied_id", "ID copied")) },
    {
      key: "export",
      label: t("ctx.export_selected", "Export selected"),
      onClick: () =>
        downloadCsv("exposure", ["route", "period", "net_exposure", "limit", "limit_breach"], [[r.route ?? "", r.period ?? "", r.net_exposure, r.limit ?? "", r.limit_breach ? "Y" : "N"]]),
    },
  ];

  // —— 列定义 ——
  const blotterCols = useMemo<ColumnDef<Trade>[]>(
    () => [
      { key: "trade_no", title: t("page.trading.trade_no", "Trade no"), width: 120, sortable: true, sticky: true },
      {
        key: "kind",
        title: t("page.trading.kind", "Kind"),
        width: 80,
        render: (v) => <span className="badge badge-info">{String(v ?? "")}</span>,
      },
      {
        key: "buy_sell",
        title: t("page.trading.side", "Side"),
        width: 60,
        render: (v) => (String(v) === "buy" ? t("page.trading.buy", "Buy") : t("page.trading.sell", "Sell")),
      },
      { key: "route", title: t("page.trading.route", "Route"), width: 110, value: (r) => r.route ?? "" },
      {
        key: "period",
        title: t("page.trading.period", "Period"),
        width: 150,
        value: (r) => formatPeriod(r.period_from, r.period_to),
        render: (_v, r) => formatPeriod(r.period_from, r.period_to),
      },
      {
        key: "qty",
        title: t("page.trading.qty", "Qty"),
        width: 90,
        align: "right",
        sortable: true,
        agg: "sum",
        value: (r) => r.qty,
        render: (v) => <Num v={num(v)} digits={2} />,
      },
      {
        key: "price",
        title: t("page.trading.price", "Price"),
        width: 90,
        align: "right",
        sortable: true,
        agg: "avg",
        value: (r) => r.price,
        render: (v) => <Num v={num(v)} digits={3} />,
      },
      { key: "index_symbol", title: t("page.trading.symbol", "Symbol"), width: 100, value: (r) => r.index_symbol ?? "" },
      {
        key: "status",
        title: t("common.status", "Status"),
        width: 90,
        render: (v) => (
          <span
            className={`badge ${
              v === "confirmed" || v === "settled" ? "badge-pass" : v === "cancelled" ? "badge-fail" : "badge-warn"
            }`}
          >
            {String(v ?? "")}
          </span>
        ),
      },
      { key: "trade_date", title: t("page.trading.trade_date", "Trade date"), width: 100, value: (r) => r.trade_date },
      {
        key: "updated_at",
        title: t("list.last_modified", "Last modified"),
        width: 135,
        value: (r) => r.updated_at ?? null,
        render: (v) => (v ? String(v).replace("T", " ").slice(0, 16) : "—"),
      },
    ],
    [t],
  );

  const positionCols = useMemo<ColumnDef<PositionRow>[]>(
    () => [
      { key: "route", title: t("page.trading.route", "Route"), width: 140, sortable: true, sticky: true },
      { key: "period", title: t("page.trading.period", "Period"), width: 160, sortable: true },
      {
        key: "paper_qty",
        title: t("page.trading.paper_qty", "Paper"),
        width: 110,
        align: "right",
        agg: "sum",
        value: (r) => r.paper_qty,
        render: (v) => <Num v={num(v)} digits={2} />,
      },
      {
        key: "physical_qty",
        title: t("page.trading.physical_qty", "Physical"),
        width: 110,
        align: "right",
        agg: "sum",
        value: (r) => r.physical_qty,
        render: (v) => <Num v={num(v)} digits={2} />,
      },
      {
        key: "net_qty",
        title: t("page.trading.net_qty", "Net"),
        width: 110,
        align: "right",
        agg: "sum",
        value: (r) => r.net_qty,
        render: (v) => {
          const n = num(v);
          return <span className={n >= 0 ? "pnl-pos" : "pnl-neg"}><Num v={n} digits={2} /></span>;
        },
      },
    ],
    [t],
  );

  const mtmCols = useMemo<ColumnDef<MtmRow>[]>(
    () => [
      { key: "trade_no", title: t("page.trading.trade_no", "Trade no"), width: 130, sortable: true, sticky: true },
      {
        key: "book_price",
        title: t("page.trading.book_price", "Book price"),
        width: 110,
        align: "right",
        agg: "avg",
        value: (r) => r.book_price,
        render: (v) => <Num v={num(v)} digits={3} />,
      },
      {
        key: "market_price",
        title: t("page.trading.market_price", "Market price"),
        width: 110,
        align: "right",
        agg: "avg",
        value: (r) => r.market_price,
        render: (v) => <Num v={num(v)} digits={3} />,
      },
      {
        key: "unrealized_pnl",
        title: t("page.trading.unrealized_pnl", "Unrealized P&L"),
        width: 130,
        align: "right",
        agg: "sum",
        value: (r) => r.unrealized_pnl,
        render: (v) => {
          const n = num(v);
          return <span className={n >= 0 ? "pnl-pos" : "pnl-neg"}><Num v={n} digits={2} /></span>;
        },
      },
      {
        key: "realized_pnl",
        title: t("page.trading.realized_pnl", "Realized P&L"),
        width: 120,
        align: "right",
        agg: "sum",
        value: (r) => r.realized_pnl ?? 0,
        render: (v) => {
          const n = num(v);
          return <span className={n >= 0 ? "pnl-pos" : "pnl-neg"}><Num v={n} digits={2} /></span>;
        },
      },
    ],
    [t],
  );

  const exposureCols = useMemo<ColumnDef<ExposureRow>[]>(
    () => [
      { key: "route", title: t("page.trading.route", "Route"), width: 140, sortable: true, sticky: true },
      { key: "period", title: t("page.trading.period", "Period"), width: 160, sortable: true },
      {
        key: "net_exposure",
        title: t("page.trading.net_exposure", "Net exposure"),
        width: 130,
        align: "right",
        agg: "sum",
        value: (r) => r.net_exposure,
        render: (v) => {
          const n = num(v);
          return <span className={n >= 0 ? "pnl-pos" : "pnl-neg"}><Num v={n} digits={2} /></span>;
        },
      },
      {
        key: "limit",
        title: t("page.trading.limit", "Limit"),
        width: 110,
        align: "right",
        value: (r) => r.limit ?? 0,
        render: (_v, r) => (r.limit == null || r.limit === 0 ? "—" : <Num v={r.limit} digits={2} />),
      },
      {
        key: "limit_breach",
        title: t("page.trading.breach", "Breach"),
        width: 90,
        render: (_v, r) =>
          r.limit_breach ? (
            <span className="badge badge-fail">{t("page.trading.breach_yes", "BREACH")}</span>
          ) : (
            <span className="badge badge-pass">OK</span>
          ),
      },
    ],
    [t],
  );

  const breaches = exposure.filter((r) => r.limit_breach);
  const tabs: TabItem[] = [
    { key: "blotter", label: t("page.trading.tab_blotter", "Blotter") },
    { key: "positions", label: t("page.trading.tab_positions", "Positions") },
    { key: "mtm", label: t("page.trading.tab_mtm", "MtM P&L") },
    { key: "exposure", label: t("page.trading.tab_exposure", "Exposure") },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.trading", "Trading & Risk") }]}
        title={t("page.trading.title", "Trading & risk")}
        subtitle={t("page.trading.sub", "Positions, market quotes and exposure limits.")}
        actions={
          <SavedViews storageKey="trading_list" onApply={(q) => router.replace(`/trading${q}`)} />
        }
      />

      <Tabs items={tabs} value={tab} onChange={(k) => setTab(k as Tab)} variant="pill" />
      {tab === "blotter" ? <StatusLegend statuses={["draft", "confirmed", "settled", "cancelled"]} /> : null}

      <Toolbar
        filterCount={tab !== "blotter" ? 1 : 0}
        onClearFilters={() => setTab("blotter")}
        right={
          tab === "mtm" && mtmRows.length ? (
            <div className="mtm-tiles" style={{ margin: 0 }}>
              <div className={`mtm-tile ${sum(mtmRows, "unrealized_pnl") >= 0 ? "pos" : "neg"}`}>
                <span>{t("page.trading.total_unrealized", "Total unrealized")}</span>
                <strong><Num v={sum(mtmRows, "unrealized_pnl")} digits={2} /></strong>
              </div>
              <div className={`mtm-tile ${sum(mtmRows, "realized_pnl") >= 0 ? "pos" : "neg"}`}>
                <span>{t("page.trading.total_realized", "Total realized")}</span>
                <strong><Num v={sum(mtmRows, "realized_pnl")} digits={2} /></strong>
              </div>
              <div className="mtm-tile">
                <span>{t("page.trading.marked_trades", "Marked trades")}</span>
                <strong>{mtmRows.length}</strong>
              </div>
            </div>
          ) : null
        }
      >
        <button type="button" className="btn btn-primary btn-sm" onClick={() => setTradeModal(true)}>
          {t("page.trading.new_trade", "New Trade")}
        </button>
        <RefreshButton label={t("common.refresh", "Refresh")} className="btn btn-ghost btn-sm" onClick={load} />
        {tab === "mtm" ? (
          <>
            <span className="field-inline">
              {t("page.trading.valuation_date", "Valuation date")}
              <DateInput value={mtmDate} onChange={setMtmDate} />
            </span>
            <button type="button" className="btn btn-primary btn-sm" disabled={mtmRunning} onClick={runMtm}>
              {mtmRunning ? "…" : t("page.trading.run_mtm", "Run MtM")}
            </button>
          </>
        ) : (
          <span className="muted" style={{ fontSize: "var(--font-label)" }}>
            {tab === "blotter"
              ? t("page.trading.blotter_hint", "All trades on the blotter; use New Trade to book one.")
              : tab === "positions"
                ? t("page.trading.positions_hint", "Paper vs physical net position, aggregated by route/period.")
                : t("page.trading.exposure_hint", "Risk exposure and limit monitoring by route/period.")}
          </span>
        )}
        {tab === "positions" ? (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => router.push("/market-positions")}>
            {t("page.trading.open_board", "Market positions board →")}
          </button>
        ) : null}
      </Toolbar>

      {tab === "exposure" && breaches.length ? (
        <div className="exposure-alert" role="alert">
          <span>⚠</span>
          <span>
            {t("page.trading.breach_alert", "{n} exposure(s) over limit. Take action.", { n: breaches.length })}
          </span>
          <div className="spacer" />
          <span>
            {breaches.map((b) => `${b.route ?? "—"} ${b.period ?? ""}`).join(" · ")}
          </span>
        </div>
      ) : null}

      <StateView loading={loading} error={loadErr} empty={!loading && !loadErr && isEmpty(tab, trades, positions, mtmRows, exposure)} onRetry={load}>
        <div className="trading-grid-wrap">
          {tab === "blotter" ? (
            <>
              <DataGrid<Trade>
                columns={blotterCols}
                data={trades}
                rowKey={(r) => r.id}
                onRowContextMenu={(r, _i, e) => tradeCtx.open(r)(e)}
                storageKey="trading_blotter"
                emptyText={t("common.empty", "No records")}
              />
              <ContextMenu controller={tradeCtx} items={tradeMenuItems} />
              <div className="dt-pager">
                <button
                  type="button"
                  className="btn btn-sm btn-ghost"
                  disabled={page <= 1}
                  onClick={() => setQuery({ page: page - 1 })}
                  aria-label={t("common.prev_page", "Previous page")}
                >
                  ←
                </button>
                <span className="muted">
                  {t("page.trading.page_of", "第 {page} / {pages} 页 · 共 {total} 条", {
                    page,
                    pages: Math.max(1, Math.ceil(tradesTotal / limit)),
                    total: tradesTotal,
                  })}
                </span>
                <button
                  type="button"
                  className="btn btn-sm btn-ghost"
                  disabled={page >= Math.max(1, Math.ceil(tradesTotal / limit))}
                  onClick={() => setQuery({ page: page + 1 })}
                  aria-label={t("common.next_page", "Next page")}
                >
                  →
                </button>
                <select
                  className="input input-sm"
                  value={limit}
                  onChange={(e) => setQuery({ limit: e.target.value, page: 1 })}
                  aria-label={t("common.page_size", "Rows per page")}
                >
                  {[10, 25, 50, 100].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </div>
            </>
          ) : tab === "positions" ? (
            <>
              <DataGrid<PositionRow>
                columns={positionCols}
                data={positions}
                rowKey={(r, i) => r.id ?? `pos-${i}`}
                onRowContextMenu={(r, _i, e) => posCtx.open(r)(e)}
                storageKey="trading_positions"
                emptyText={t("common.empty", "No records")}
              />
              <ContextMenu controller={posCtx} items={posMenuItems} />
            </>
          ) : tab === "mtm" ? (
            <>
              <DataGrid<MtmRow>
                columns={mtmCols}
                data={mtmRows}
                rowKey={(r, i) => r.id ?? `mtm-${r.trade_no}-${i}`}
                onRowContextMenu={(r, _i, e) => mtmCtx.open(r)(e)}
                storageKey="trading_mtm"
                emptyText={t("common.empty", "No records")}
              />
              <ContextMenu controller={mtmCtx} items={mtmMenuItems} />
            </>
          ) : (
            <>
              <DataGrid<ExposureRow>
                columns={exposureCols}
                data={exposure}
                rowKey={(r, i) => r.id ?? `exp-${i}`}
                onRowContextMenu={(r, _i, e) => expCtx.open(r)(e)}
                storageKey="trading_exposure"
                emptyText={t("common.empty", "No records")}
              />
              <ContextMenu controller={expCtx} items={expMenuItems} />
            </>
          )}
        </div>
      </StateView>

      {/* 新建成交 */}
      <RecordModal
        open={tradeModal}
        title={t("page.trading.new_trade", "New Trade")}
        onClose={() => setTradeModal(false)}
        onSave={createTrade}
        canDelete={false}
        saving={tradeSaving}
        size="lg"
      >
        <FormPanel>
          <FormSection title={t("page.trading.trade_terms", "Trade terms")}>
            <FieldRow label={t("page.trading.kind", "Kind")}>
              <select value={tradeForm.kind} onChange={(e) => setTradeForm({ ...tradeForm, kind: e.target.value })}>
                {TRADE_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label={t("page.trading.side", "Side")}>
              <select value={tradeForm.buy_sell} onChange={(e) => setTradeForm({ ...tradeForm, buy_sell: e.target.value })}>
                <option value="buy">{t("page.trading.buy", "Buy")}</option>
                <option value="sell">{t("page.trading.sell", "Sell")}</option>
              </select>
            </FieldRow>
            <FieldRow label={t("page.trading.route", "Route")}>
              <input
                value={tradeForm.route}
                onChange={(e) => setTradeForm({ ...tradeForm, route: e.target.value })}
                placeholder="C5 / P2A …"
              />
            </FieldRow>
            <FieldRow label={t("page.trading.index_symbol", "Index symbol")}>
              <LookupSelect
                dataset="market_symbols"
                value={tradeForm.index_symbol}
                onChange={(v) => setTradeForm({ ...tradeForm, index_symbol: v })}
              />
            </FieldRow>
          </FormSection>
          <FormSection title={t("page.trading.period_qty", "Period & quantity")}>
            <FieldRow label={t("page.trading.period_from", "Period from")}>
              <DateInput value={tradeForm.period_from} onChange={(v) => setTradeForm({ ...tradeForm, period_from: v })} />
            </FieldRow>
            <FieldRow label={t("page.trading.period_to", "Period to")}>
              <DateInput value={tradeForm.period_to} onChange={(v) => setTradeForm({ ...tradeForm, period_to: v })} />
            </FieldRow>
            <FieldRow label={t("page.trading.qty", "Qty")}>
              <input
                type="number"
                value={tradeForm.qty}
                onChange={(e) => setTradeForm({ ...tradeForm, qty: e.target.value })}
                required
              />
            </FieldRow>
            <FieldRow label={t("page.trading.price", "Price")}>
              <input
                type="number"
                step="0.000001"
                value={tradeForm.price}
                onChange={(e) => setTradeForm({ ...tradeForm, price: e.target.value })}
                required
              />
            </FieldRow>
          </FormSection>
          <FormSection title={t("page.trading.deal_info", "Deal info")}>
            <FieldRow label={t("page.trading.counterparty", "Counterparty")}>
              <PartyPicker
                value={tradeForm.counterparty_id}
                onChange={(id) => setTradeForm({ ...tradeForm, counterparty_id: id })}
              />
            </FieldRow>
            <FieldRow label={t("page.trading.trade_date", "Trade date")}>
              <DateInput value={tradeForm.trade_date} onChange={(v) => setTradeForm({ ...tradeForm, trade_date: v })} required />
            </FieldRow>
          </FormSection>
          <FieldRow label={t("validate.label", "Validate")} span={2}>
            <ValidateButton onValidate={validateTrade} />
          </FieldRow>
        </FormPanel>
      </RecordModal>
    </AppShell>
  );
}

export default function TradingPage() {
  return (
    <Suspense fallback={null}>
      <TradingWorkspace />
    </Suspense>
  );
}

// —— helpers ——

function formatPeriod(from: unknown, to: unknown): string {
  const f = from ? String(from).slice(0, 10) : "";
  const tt = to ? String(to).slice(0, 10) : "";
  if (!f && !tt) return "—";
  return `${f || "…"} → ${tt || "…"}`;
}

function sum(rows: MtmRow[], key: "unrealized_pnl" | "realized_pnl"): number {
  return rows.reduce((a, r) => a + num(r[key]), 0);
}

function isEmpty(
  tab: Tab,
  trades: Trade[],
  positions: PositionRow[],
  mtmRows: MtmRow[],
  exposure: ExposureRow[],
): boolean {
  if (tab === "blotter") return !trades.length;
  if (tab === "positions") return !positions.length;
  if (tab === "mtm") return !mtmRows.length;
  return !exposure.length;
}
