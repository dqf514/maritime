"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { LookupSelect } from "@/components/LookupSelect";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Pos = { id: string; symbol: string; var_1d: number; limit_breach: boolean; side?: string; qty?: number; entry_price?: number };
type Quote = { symbol: string; value: number; quote_date: string };

export default function TradingRiskPage() {
  const { t } = useI18n();
  const [positions, setPositions] = useState<Pos[]>([]);
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [symbol, setSymbol] = useState("FFA-C5");
  const [qty, setQty] = useState("10");
  const [price, setPrice] = useState("15000");
  const [side, setSide] = useState("long");
  const [qSymbol, setQSymbol] = useState("BDI");
  const [qValue, setQValue] = useState("1500");

  const load = useCallback(async () => {
    const [p, q] = await Promise.all([
      apiGet("/api/v1/risk/positions"),
      apiGet("/api/v1/market/quotes").catch(() => []),
    ]);
    setPositions(p);
    setQuotes(q);
  }, []);

  useEffect(() => {
    load().catch(() => setErr(t("common.failed", "Failed")));
  }, [load, t]);

  async function createPos(e: FormEvent) {
    e.preventDefault();
    try {
      await apiPost(
        `/api/v1/risk/positions?symbol=${encodeURIComponent(symbol)}&qty=${Number(qty) || 0}&entry_price=${Number(price) || 0}&side=${side}`,
      );
      setMsg(t("page.trading.pos_ok", "Position registered"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  async function addQuote(e: FormEvent) {
    e.preventDefault();
    try {
      await apiPost(`/api/v1/market/quotes?symbol=${encodeURIComponent(qSymbol)}&value=${Number(qValue) || 0}`);
      setMsg(t("page.trading.quote_ok", "Quote saved"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.trading.title", "Trading & risk")}</h1>
          <p className="page-sub">
            {t("page.trading.sub", "Positions, market quotes and exposure limits.")}
          </p>
        </div>
        <Link href="/settings/connectors" className="btn btn-ghost">
          {t("page.connectors.title", "Integration Hub")}
        </Link>
      </div>
      {msg ? <p className="flash">{msg}</p> : null}
      {err ? <p className="flash-err">{err}</p> : null}

      <div className="desk-split">
        <form className="panel" onSubmit={createPos}>
          <h3 style={{ marginTop: 0 }}>{t("page.trading.positions", "Risk positions")}</h3>
          <div className="form-grid">
            <label>
              {t("page.trading.symbol", "Symbol")}
              <LookupSelect dataset="market_symbols" value={symbol} onChange={setSymbol} allowEmpty={false} />
            </label>
            <label>
              {t("page.trading.side", "Side")}
              <select value={side} onChange={(e) => setSide(e.target.value)}>
                <option value="long">long</option>
                <option value="short">short</option>
              </select>
            </label>
            <label>
              {t("page.trading.qty", "Qty")}
              <input value={qty} onChange={(e) => setQty(e.target.value)} />
            </label>
            <label>
              {t("page.trading.entry", "Entry")}
              <input value={price} onChange={(e) => setPrice(e.target.value)} />
            </label>
          </div>
          <button className="btn btn-primary" type="submit">
            {t("common.create", "Create")}
          </button>
          <table className="table" style={{ marginTop: "1rem" }}>
            <thead>
              <tr>
                <th>{t("page.trading.symbol", "Symbol")}</th>
                <th>VaR 1d</th>
                <th>{t("page.trading.breach", "Breach")}</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.id}>
                  <td>{p.symbol}</td>
                  <td>{p.var_1d.toLocaleString()}</td>
                  <td>{p.limit_breach ? "⚠" : "OK"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </form>

        <form className="panel" onSubmit={addQuote}>
          <h3 style={{ marginTop: 0 }}>{t("page.trading.quotes", "Market quotes")}</h3>
          <div className="form-grid">
            <label>
              {t("page.trading.symbol", "Symbol")}
              <LookupSelect dataset="market_symbols" value={qSymbol} onChange={setQSymbol} allowEmpty={false} />
            </label>
            <label>
              {t("page.trading.value", "Value")}
              <input value={qValue} onChange={(e) => setQValue(e.target.value)} />
            </label>
          </div>
          <button className="btn btn-primary" type="submit">
            {t("page.trading.add_quote", "Add quote")}
          </button>
          <table className="table" style={{ marginTop: "1rem" }}>
            <thead>
              <tr>
                <th>{t("page.trading.symbol", "Symbol")}</th>
                <th>{t("page.trading.value", "Value")}</th>
                <th>{t("common.date", "Date")}</th>
              </tr>
            </thead>
            <tbody>
              {quotes.map((q, i) => (
                <tr key={`${q.symbol}-${q.quote_date}-${i}`}>
                  <td>{q.symbol}</td>
                  <td>{q.value}</td>
                  <td>{q.quote_date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </form>
      </div>
    </AppShell>
  );
}
