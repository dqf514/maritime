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
      <div className="space-y-6">

        {/* Freight Indices */}
        {indexQuotes.length > 0 && (
          <div className="rounded-lg border bg-white p-4">
            <h3 className="mb-3 font-semibold">{t("market.indices", "Freight Indices")}</h3>
            <div className="grid grid-cols-5 gap-3">
              {indexQuotes.map((q) => (
                <button
                  key={q.symbol}
                  onClick={() => setSelectedSymbol(q.symbol)}
                  onContextMenu={quoteCtx.open(q)}
                  className={`rounded-lg border p-3 text-center transition ${
                    selectedSymbol === q.symbol ? "border-blue-500 bg-blue-50" : "hover:bg-gray-50"
                  }`}
                >
                  <div className="text-xs text-gray-500">{q.label}</div>
                  <div className="text-xl font-bold"><Num v={q.value} digits={2} /></div>
                  <div className="text-[10px] text-gray-400">{q.date}</div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Bunker prices */}
        {bunkerComp.length > 0 && (
          <div className="rounded-lg border bg-white p-4">
            <h3 className="mb-3 font-semibold">{t("market.bunker", "Bunker Prices (USD/MT)")}</h3>
            <div className="space-y-2">
              {bunkerComp.map((b) => (
                <div key={b.symbol} className="flex items-center gap-3" onContextMenu={bunkerCtx.open(b)}>
                  <div className="w-24 text-sm font-medium">{b.port}</div>
                  <div className="text-xs text-gray-500 w-12">{b.fuel_type}</div>
                  <div className="flex-1">
                    <div className="h-6 rounded bg-gray-100 overflow-hidden">
                      <div
                        className={`h-full rounded ${b.fuel_type === "VLSFO" ? "bg-blue-500" : "bg-green-500"}`}
                        style={{ width: `${(b.price_usd / maxBunker) * 100}%` }}
                      />
                    </div>
                  </div>
                  <div className="w-20 text-right text-sm font-semibold"><Num v={b.price_usd} digits={0} /></div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* TCE rates */}
        {tceQuotes.length > 0 && (
          <div className="rounded-lg border bg-white p-4">
            <h3 className="mb-3 font-semibold">{t("market.tce", "TCE Rates (USD/day)")}</h3>
            <div className="grid grid-cols-3 gap-3">
              {tceQuotes.map((q) => (
                <button
                  key={q.symbol}
                  onClick={() => setSelectedSymbol(q.symbol)}
                  onContextMenu={quoteCtx.open(q)}
                  className={`rounded-lg border p-3 text-center transition ${
                    selectedSymbol === q.symbol ? "border-blue-500 bg-blue-50" : "hover:bg-gray-50"
                  }`}
                >
                  <div className="text-xs text-gray-500">{q.label}</div>
                  <div className="text-xl font-bold">$<Num v={q.value} digits={0} /></div>
                  <div className="text-[10px] text-gray-400">{q.date}</div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* History chart (simple sparkline) */}
        {history.length > 0 && (
          <div className="rounded-lg border bg-white p-4">
            <h3 className="mb-3 font-semibold">
              {t("market.history", "30-day trend")} — {selectedSymbol}
            </h3>
            <div className="flex h-40 items-end gap-1">
              {history.map((h, i) => {
                const max = Math.max(...history.map((p) => p.value));
                const min = Math.min(...history.map((p) => p.value));
                const range = max - min || 1;
                const pct = ((h.value - min) / range) * 100;
                return (
                  <div
                    key={i}
                    className="flex-1 rounded-t bg-blue-400 hover:bg-blue-600 transition"
                    style={{ height: `${Math.max(pct, 5)}%` }}
                    title={`${h.date}: ${h.value.toLocaleString()}`}
                  />
                );
              })}
            </div>
            <div className="mt-2 flex justify-between text-[10px] text-gray-400">
              <span>{history[0]?.date}</span>
              <span>
                {t("market.range", "Range")} <Num v={Math.min(...history.map((p) => p.value))} digits={2} /> –{" "}
                <Num v={Math.max(...history.map((p) => p.value))} digits={2} /> · {t("market.last", "Last")}{" "}
                <Num v={history[history.length - 1]?.value ?? null} digits={2} />
              </span>
              <span>{history[history.length - 1]?.date}</span>
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
