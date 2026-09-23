"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

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

export default function MarketDataPage() {
  const { t } = useI18n();
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [bunkerComp, setBunkerComp] = useState<BunkerPrice[]>([]);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [msg, setMsg] = useState("");

  async function load() {
    try {
      const [q, b] = await Promise.all([
        apiGet("/api/v1/market-data/latest"),
        apiGet("/api/v1/market-data/bunker-comparison"),
      ]);
      setQuotes(q);
      setBunkerComp(b);
      if (q.length > 0 && !selectedSymbol) setSelectedSymbol(q[0].symbol);
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
    setMsg(t("market.seeded", `Seeded ${result.seeded} data points`));
    await load();
  }

  const bunkerQuotes = quotes.filter((q) => q.category === "bunker");
  const indexQuotes = quotes.filter((q) => q.category === "index");
  const tceQuotes = quotes.filter((q) => q.category === "tce");

  const maxBunker = Math.max(...bunkerComp.map((b) => b.price_usd), 1);

  return (
    <AppShell title="Market Data">
      <div className="space-y-6">
        {msg && <div className="rounded bg-blue-50 p-3 text-sm text-blue-800">{msg}</div>}

        {quotes.length === 0 && (
          <div className="rounded-lg border bg-white p-8 text-center">
            <p className="mb-3 text-gray-500">{t("market.no_data", "No market data yet")}</p>
            <button onClick={seedDemo} className="rounded bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700">
              {t("market.seed", "Load demo data")}
            </button>
          </div>
        )}

        {/* Freight Indices */}
        {indexQuotes.length > 0 && (
          <div className="rounded-lg border bg-white p-4">
            <h3 className="mb-3 font-semibold">{t("market.indices", "Freight Indices")}</h3>
            <div className="grid grid-cols-5 gap-3">
              {indexQuotes.map((q) => (
                <button
                  key={q.symbol}
                  onClick={() => setSelectedSymbol(q.symbol)}
                  className={`rounded-lg border p-3 text-center transition ${
                    selectedSymbol === q.symbol ? "border-blue-500 bg-blue-50" : "hover:bg-gray-50"
                  }`}
                >
                  <div className="text-xs text-gray-500">{q.label}</div>
                  <div className="text-xl font-bold">{q.value.toLocaleString()}</div>
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
                <div key={b.symbol} className="flex items-center gap-3">
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
                  <div className="w-20 text-right text-sm font-semibold">${b.price_usd.toFixed(0)}</div>
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
                  className={`rounded-lg border p-3 text-center transition ${
                    selectedSymbol === q.symbol ? "border-blue-500 bg-blue-50" : "hover:bg-gray-50"
                  }`}
                >
                  <div className="text-xs text-gray-500">{q.label}</div>
                  <div className="text-xl font-bold">${q.value.toLocaleString()}</div>
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
              <span>{history[history.length - 1]?.date}</span>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
