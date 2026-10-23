"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { Num } from "@/components/Num";
import { PageHeader } from "@/components/PageHeader";
import { SavedViews } from "@/components/SavedViews";
import { Toolbar } from "@/components/Toolbar";
import { apiGet, apiPost } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";
import { useToast } from "@/components/ToastProvider";

type Quote = {
  symbol: string;
  label: string;
  category: string;
  value: number;
  date: string;
  source: string;
};

type BunkerPrice = {
  symbol: string;
  port: string;
  fuel_type: string;
  price_usd: number;
  date: string;
};

type HistoryPoint = { date: string; value: number; source: string };

function MarketDataPageInner() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const { query, setQuery } = useListQuery();
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [bunkerComp, setBunkerComp] = useState<BunkerPrice[]>([]);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const selectedSymbol = typeof query.symbol === "string" ? query.symbol : "";
  const setSelectedSymbol = (s: string) => setQuery({ symbol: s || null });
  const quoteCtx = useContextMenu<Quote>();
  const bunkerCtx = useContextMenu<BunkerPrice>();

  async function load() {
    try {
      const [q, b] = await Promise.all([
        apiGet("/api/v1/market-data/latest"),
        apiGet("/api/v1/market-data/bunker-comparison"),
      ]);
      setQuotes(q);
      setBunkerComp(b);
      if (q.length > 0 && !selectedSymbol) setQuery({ symbol: q[0].symbol });
    } catch {
      setQuotes([]);
    }
  }

  async function loadHistory(symbol: string) {
    if (!symbol) return;
    try {
      const data = await apiGet(`/api/v1/market-data/history/${symbol}?days=30`);
      setHistory(data);
    } catch {
      setHistory([]);
    }
  }

  useEffect(() => {
    load().catch(() => {});
  }, []);

  useEffect(() => {
    loadHistory(selectedSymbol);
  }, [selectedSymbol]);

  async function seedDemo() {
    const result = await apiPost("/api/v1/market-data/seed-demo", {});
    toast.success(t("market.seeded", "Seeded {n} data points", { n: result.seeded }));
    await load();
  }

  const bunkerQuotes = quotes.filter((q) => q.category === "bunker");
  const indexQuotes = quotes.filter((q) => q.category === "index");
  const tceQuotes = quotes.filter((q) => q.category === "tce");

  const maxBunker = Math.max(...bunkerComp.map((b) => b.price_usd), 1);

  function copySymbol(symbol: string) {
    void navigator.clipboard.writeText(symbol);
    toast.success(t("ctx.copied_id", "ID copied"));
  }

  function exportQuotes(list: Quote[]) {
    downloadCsv(
      "market_quotes",
      ["symbol", "label", "category", "value", "date", "source"],
      list.map((q) => [q.symbol, q.label, q.category, q.value, q.date, q.source]),
      { emptyGuard: t("export.empty_confirm", "No rows to export. Export anyway?") },
    );
  }

  const quoteMenuItems = (q: Quote): ContextMenuItem[] => [
    { key: "select", label: t("market.show_trend", "Show trend"), onClick: () => setSelectedSymbol(q.symbol) },
    { key: "copy", label: t("ctx.copy_symbol", "Copy symbol"), onClick: () => copySymbol(q.symbol) },
    { key: "export", label: t("ctx.export_selected", "Export selected"), onClick: () => exportQuotes([q]) },
  ];

  const bunkerMenuItems = (b: BunkerPrice): ContextMenuItem[] => [
    { key: "copy", label: t("ctx.copy_symbol", "Copy symbol"), onClick: () => copySymbol(b.symbol) },
    {
      key: "export",
      label: t("ctx.export_selected", "Export selected"),
      onClick: () =>
        downloadCsv("bunker_prices", ["symbol", "port", "fuel_type", "price_usd", "date"], [[b.symbol, b.port, b.fuel_type, b.price_usd, b.date]], {
          emptyGuard: t("export.empty_confirm", "No rows to export. Export anyway?"),
        }),
    },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[
          { label: t("nav.analytics", "Analytics"), href: "/analytics" },
          { label: t("nav.market", "Market data") },
        ]}
        title={t("market.title", "Market Data")}
        subtitle={t("market.sub", "Freight indices, bunker prices, TCE rates and 30-day trends.")}
        actions={<SavedViews storageKey="market_data" onApply={(q) => router.replace(`/analytics/market${q}`)} />}
      />
      <Toolbar
        filterCount={selectedSymbol ? 1 : 0}
        onClearFilters={() => setSelectedSymbol("")}
        right={<span className="hint">{t("market.quote_count", "{n} quotes", { n: quotes.length })}</span>}
      >
        <button type="button" className="btn btn-sm" onClick={() => load().catch(() => undefined)} title={t("common.refresh", "Refresh")}>
          ↻
        </button>
        {quotes.length === 0 ? (
          <button type="button" className="btn btn-primary btn-sm" onClick={seedDemo}>
            {t("market.seed", "Load demo data")}
          </button>
        ) : null}
      </Toolbar>
      <div className="market-page">
        {/* Freight Indices */}
        {indexQuotes.length > 0 && (
          <div className="panel">
            <div className="panel-header">{t("market.indices", "Freight Indices")}</div>
            <div className="panel-body market-tiles">
              {indexQuotes.map((q) => (
                <button
                  key={q.symbol}
                  type="button"
                  onClick={() => setSelectedSymbol(q.symbol)}
                  onContextMenu={quoteCtx.open(q)}
                  className={`market-tile${selectedSymbol === q.symbol ? " active" : ""}`}
                >
                  <span className="market-tile-label">{q.label}</span>
                  <span className="market-tile-value"><Num v={q.value} digits={2} /></span>
                  <span className="market-tile-date">{q.date}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Bunker prices */}
        {bunkerComp.length > 0 && (
          <div className="panel">
            <div className="panel-header">{t("market.bunker", "Bunker Prices (USD/MT)")}</div>
            <div className="panel-body market-bars">
              {bunkerComp.map((b) => (
                <div key={b.symbol} className="market-bar-row" onContextMenu={bunkerCtx.open(b)}>
                  <span className="market-bar-port">{b.port}</span>
                  <span className="market-bar-fuel">{b.fuel_type}</span>
                  <span className="market-bar-track">
                    <span
                      className={`market-bar-fill${b.fuel_type === "VLSFO" ? " vlsfo" : " other"}`}
                      style={{ width: `${(b.price_usd / maxBunker) * 100}%` }}
                    />
                  </span>
                  <span className="market-bar-val"><Num v={b.price_usd} digits={0} /></span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* TCE rates */}
        {tceQuotes.length > 0 && (
          <div className="panel">
            <div className="panel-header">{t("market.tce", "TCE Rates (USD/day)")}</div>
            <div className="panel-body market-tiles market-tiles-3">
              {tceQuotes.map((q) => (
                <button
                  key={q.symbol}
                  type="button"
                  onClick={() => setSelectedSymbol(q.symbol)}
                  onContextMenu={quoteCtx.open(q)}
                  className={`market-tile${selectedSymbol === q.symbol ? " active" : ""}`}
                >
                  <span className="market-tile-label">{q.label}</span>
                  <span className="market-tile-value">$<Num v={q.value} digits={0} /></span>
                  <span className="market-tile-date">{q.date}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* History chart (simple sparkline) */}
        {history.length > 0 && (
          <div className="panel">
            <div className="panel-header">
              {t("market.history", "30-day trend")} — {selectedSymbol}
            </div>
            <div className="panel-body">
              <div className="market-spark">
                {history.map((h, i) => {
                  const max = Math.max(...history.map((p) => p.value));
                  const min = Math.min(...history.map((p) => p.value));
                  const range = max - min || 1;
                  const pct = ((h.value - min) / range) * 100;
                  return (
                    <div
                      key={i}
                      className="market-spark-bar"
                      style={{ height: `${Math.max(pct, 5)}%` }}
                      title={`${h.date}: ${h.value.toLocaleString()}`}
                    />
                  );
                })}
              </div>
              <div className="market-spark-foot">
                <span>{history[0]?.date}</span>
                <span>
                  {t("market.range", "Range")} <Num v={Math.min(...history.map((p) => p.value))} digits={2} /> –{" "}
                  <Num v={Math.max(...history.map((p) => p.value))} digits={2} /> · {t("market.last", "Last")}{" "}
                  <Num v={history[history.length - 1]?.value ?? null} digits={2} />
                </span>
                <span>{history[history.length - 1]?.date}</span>
              </div>
            </div>
          </div>
        )}
      </div>
      <ContextMenu controller={quoteCtx} items={quoteMenuItems} />
      <ContextMenu controller={bunkerCtx} items={bunkerMenuItems} />
    </AppShell>
  );
}

export default function MarketDataPage() {
  return (
    <Suspense fallback={null}>
      <MarketDataPageInner />
    </Suspense>
  );
}
