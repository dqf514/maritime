"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { LookupSelect } from "@/components/LookupSelect";
import { StateView } from "@/components/StateView";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Pos = { id: string; symbol: string; var_1d: number; limit_breach: boolean; side?: string; qty?: number; entry_price?: number };
type Quote = { symbol: string; value: number; quote_date: string };
type HedgeRow = { symbol: string; paper_qty: number; physical_qty: number; net_exposure: number; hedge_ratio: number | null };

export default function TradingRiskPage() {
  const { t } = useI18n();
  const [positions, setPositions] = useState<Pos[]>([]);
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [hedge, setHedge] = useState<HedgeRow[]>([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState("");
  const [symbol, setSymbol] = useState("FFA-C5");
  const [qty, setQty] = useState("10");
  const [price, setPrice] = useState("15000");
  const [side, setSide] = useState("long");
  const [qSymbol, setQSymbol] = useState("BDI");
  const [qValue, setQValue] = useState("1500");

  const load = useCallback(async () => {
    setLoading(true);
    setLoadErr("");
    try {
      const [p, q, h] = await Promise.all([
        apiGet("/api/v1/risk/positions"),
        apiGet("/api/v1/market/quotes").catch(() => []),
        apiGet("/api/v1/risk/hedge-view").catch(() => []),
      ]);
      setPositions(p);
      setQuotes(q);
      setHedge(Array.isArray(h) ? h : []);
    } catch {
      setLoadErr(t("common.failed", "Failed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    load();
  }, [load]);

  async function createPos(e: FormEvent) {
    e.preventDefault();
    setErr("");
    const qtyNum = Number(qty);
    const priceNum = Number(price);
    if (!qty.trim() || Number.isNaN(qtyNum) || !price.trim() || Number.isNaN(priceNum)) {
      setErr(t("page.trading.bad_number", "数量与价格必须是有效数字"));
      return;
    }
    try {
      await apiPost(
        `/api/v1/risk/positions?symbol=${encodeURIComponent(symbol)}&qty=${qtyNum}&entry_price=${priceNum}&side=${side}`,
      );
      setMsg(t("page.trading.pos_ok", "Position registered"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  async function addQuote(e: FormEvent) {
    e.preventDefault();
    setErr("");
    const valueNum = Number(qValue);
    if (!qValue.trim() || Number.isNaN(valueNum)) {
      setErr(t("page.trading.bad_number", "数量与价格必须是有效数字"));
      return;
    }
    try {
      await apiPost(`/api/v1/market/quotes?symbol=${encodeURIComponent(qSymbol)}&value=${valueNum}`);
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
          <StateView loading={loading} error={loadErr} empty={!positions.length} onRetry={load}>
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
          </StateView>
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
          <StateView loading={loading} error={loadErr} empty={!quotes.length} onRetry={load}>
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
          </StateView>
        </form>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.trading.hedge_view", "对冲视图 Hedge view")}</h3>
        <StateView loading={loading} error={loadErr} empty={!hedge.length} onRetry={load}>
          <table className="table">
            <thead>
              <tr>
                <th>{t("page.trading.symbol", "Symbol")}</th>
                <th>{t("page.trading.paper_qty", "纸货 Paper")}</th>
                <th>{t("page.trading.physical_qty", "实货 Physical")}</th>
                <th>{t("page.trading.net_exposure", "净敞口 Net")}</th>
                <th>{t("page.trading.hedge_ratio", "对冲比 Ratio")}</th>
              </tr>
            </thead>
            <tbody>
              {hedge.map((r) => (
                <tr key={r.symbol}>
                  <td>{r.symbol}</td>
                  <td>{r.paper_qty.toLocaleString()}</td>
                  <td>{r.physical_qty.toLocaleString()}</td>
                  <td>{r.net_exposure.toLocaleString()}</td>
                  <td>{r.hedge_ratio != null ? `${(r.hedge_ratio * 100).toFixed(1)}%` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </StateView>
      </div>
    </AppShell>
  );
}
