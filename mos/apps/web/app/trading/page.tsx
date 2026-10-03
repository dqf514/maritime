"use client";

// Phase 7 Trading — 交易工作台
// Blotter（成交簿）/ Positions（纸货实货净头寸）/ MtM P&L（逐日盯市）/ Exposure（敞口与限额）。
// 新建成交走 RecordModal；金额表均用 DataGrid 聚合 footer。

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { FormPanel, FormSection, FieldRow } from "@/components/form/FormPanel";
import { RecordModal } from "@/components/RecordModal";
import { DateInput } from "@/components/DateInput";
import { PartyPicker } from "@/components/DataPicker";
import { LookupSelect } from "@/components/LookupSelect";
import { StateView } from "@/components/StateView";
import { useToast } from "@/components/ToastProvider";
import { apiGet, apiList, apiPost } from "@/lib/api";
import { fmt } from "@/lib/fmt";
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
  const { query, setQuery } = useListQuery();
  const tab: Tab = TAB_IDS.includes(query.tab ?? "") ? (query.tab as Tab) : "blotter";
  const setTab = (id: Tab) => setQuery({ tab: id === "blotter" ? null : id });

  // —— shared ——
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState("");
  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);

  // —— blotter ——
  const [trades, setTrades] = useState<Trade[]>([]);

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

  const load = useCallback(async () => {
    setLoading(true);
    setLoadErr("");
    try {
      if (tab === "blotter") {
        const page = await apiList<Trade>("/api/v1/trading/trades", { limit: 200 });
        setTrades(page.items);
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
      setLoadErr(String(ex));
    } finally {
      setLoading(false);
    }
  }, [tab, mtmDate]);

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
      toast.error(String(ex));
    } finally {
      setMtmRunning(false);
    }
  }

  async function createTrade() {
    const qtyNum = Number(tradeForm.qty);
    const priceNum = Number(tradeForm.price);
    if (!Number.isFinite(qtyNum) || !Number.isFinite(priceNum)) {
      toast.error(t("page.trading.bad_number", "数量与价格必须是有效数字"));
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
      toast.error(String(ex));
    } finally {
      setTradeSaving(false);
    }
  }

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
        render: (v) => fmt(num(v)),
      },
      {
        key: "price",
        title: t("page.trading.price", "Price"),
        width: 90,
        align: "right",
        sortable: true,
        agg: "avg",
        value: (r) => r.price,
        render: (v) => fmt(num(v)),
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
        render: (v) => fmt(num(v)),
      },
      {
        key: "physical_qty",
        title: t("page.trading.physical_qty", "Physical"),
        width: 110,
        align: "right",
        agg: "sum",
        value: (r) => r.physical_qty,
        render: (v) => fmt(num(v)),
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
          return <span className={n >= 0 ? "pnl-pos" : "pnl-neg"}>{fmt(n)}</span>;
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
        render: (v) => fmt(num(v)),
      },
      {
        key: "market_price",
        title: t("page.trading.market_price", "Market price"),
        width: 110,
        align: "right",
        agg: "avg",
        value: (r) => r.market_price,
        render: (v) => fmt(num(v)),
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
          return <span className={n >= 0 ? "pnl-pos" : "pnl-neg"}>{fmt(n)}</span>;
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
          return <span className={n >= 0 ? "pnl-pos" : "pnl-neg"}>{fmt(n)}</span>;
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
          return <span className={n >= 0 ? "pnl-pos" : "pnl-neg"}>{fmt(n)}</span>;
        },
      },
      {
        key: "limit",
        title: t("page.trading.limit", "Limit"),
        width: 110,
        align: "right",
        value: (r) => r.limit ?? 0,
        render: (_v, r) => (r.limit == null || r.limit === 0 ? "—" : fmt(r.limit)),
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
  const tabs: Array<{ id: Tab; label: string }> = [
    { id: "blotter", label: t("page.trading.tab_blotter", "Blotter") },
    { id: "positions", label: t("page.trading.tab_positions", "Positions") },
    { id: "mtm", label: t("page.trading.tab_mtm", "MtM P&L") },
    { id: "exposure", label: t("page.trading.tab_exposure", "Exposure") },
  ];

  return (
    <AppShell>
      <PageHeader
        title={t("page.trading.title", "Trading & risk")}
        subtitle={t("page.trading.sub", "Positions, market quotes and exposure limits.")}
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setTradeModal(true)}>
            {t("page.trading.new_trade", "New Trade")}
          </button>
        }
      />

      <div className="trading-tabs">
        {tabs.map((tb) => (
          <button
            key={tb.id}
            type="button"
            className={`trading-tab${tab === tb.id ? " active" : ""}`}
            onClick={() => setTab(tb.id)}
          >
            {tb.label}
          </button>
        ))}
      </div>

      <div className="trading-toolbar">
        {tab === "mtm" ? (
          <>
            <span className="field-inline">
              {t("page.trading.valuation_date", "Valuation date")}
              <DateInput value={mtmDate} onChange={setMtmDate} />
            </span>
            <button type="button" className="btn btn-primary btn-sm" disabled={mtmRunning} onClick={runMtm}>
              {mtmRunning ? "…" : t("page.trading.run_mtm", "Run MtM")}
            </button>
            <div className="spacer" />
            {mtmRows.length ? (
              <div className="mtm-tiles" style={{ margin: 0 }}>
                <div className={`mtm-tile ${sum(mtmRows, "unrealized_pnl") >= 0 ? "pos" : "neg"}`}>
                  <span>{t("page.trading.total_unrealized", "Total unrealized")}</span>
                  <strong>{fmt(sum(mtmRows, "unrealized_pnl"))}</strong>
                </div>
                <div className={`mtm-tile ${sum(mtmRows, "realized_pnl") >= 0 ? "pos" : "neg"}`}>
                  <span>{t("page.trading.total_realized", "Total realized")}</span>
                  <strong>{fmt(sum(mtmRows, "realized_pnl"))}</strong>
                </div>
                <div className="mtm-tile">
                  <span>{t("page.trading.marked_trades", "Marked trades")}</span>
                  <strong>{mtmRows.length}</strong>
                </div>
              </div>
            ) : null}
          </>
        ) : (
          <span className="muted" style={{ fontSize: "var(--font-label)" }}>
            {tab === "blotter"
              ? t("page.trading.blotter_hint", "全部成交簿；双击工具栏「New Trade」录入成交。")
              : tab === "positions"
                ? t("page.trading.positions_hint", "纸货 vs 实货净头寸，按航线/期间聚合。")
                : t("page.trading.exposure_hint", "按航线/期间的风险敞口与限额监控。")}
          </span>
        )}
        <div className="spacer" />
        <button type="button" className="btn btn-ghost btn-sm" onClick={load}>
          {t("common.refresh", "Refresh")}
        </button>
      </div>

      {tab === "exposure" && breaches.length ? (
        <div className="exposure-alert" role="alert">
          <span>⚠</span>
          <span>
            {t("page.trading.breach_alert", "{n} 个敞口超出限额，请及时处理", { n: breaches.length })}
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
            <DataGrid<Trade>
              columns={blotterCols}
              data={trades}
              rowKey={(r) => r.id}
              storageKey="trading_blotter"
              emptyText={t("common.empty", "No records")}
            />
          ) : tab === "positions" ? (
            <DataGrid<PositionRow>
              columns={positionCols}
              data={positions}
              rowKey={(r, i) => r.id ?? `pos-${i}`}
              storageKey="trading_positions"
              emptyText={t("common.empty", "No records")}
            />
          ) : tab === "mtm" ? (
            <DataGrid<MtmRow>
              columns={mtmCols}
              data={mtmRows}
              rowKey={(r, i) => r.id ?? `mtm-${r.trade_no}-${i}`}
              storageKey="trading_mtm"
              emptyText={t("common.empty", "No records")}
            />
          ) : (
            <DataGrid<ExposureRow>
              columns={exposureCols}
              data={exposure}
              rowKey={(r, i) => r.id ?? `exp-${i}`}
              storageKey="trading_exposure"
              emptyText={t("common.empty", "No records")}
            />
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
