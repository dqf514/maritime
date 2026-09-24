"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { RecordModal } from "@/components/RecordModal";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Holiday = {
  id: string;
  port_unlocode: string;
  country: string;
  holiday_date: string;
  holiday_name: string;
  holiday_type: string;
  recurring: boolean;
};

type PortRate = {
  id: string;
  port_unlocode: string;
  rate_type: string;
  vessel_size_band: string;
  amount_usd: number;
  currency: string;
  basis: string;
  source: string;
};

type Restriction = {
  port_unlocode: string;
  max_draft_m: number | null;
  max_loa_m: number | null;
  max_beam_m: number | null;
  max_dwt: number | null;
  working_hours: string | null;
  night_work_allowed: boolean;
  requires_pilot: boolean;
};

type Tab = "holidays" | "rates" | "restrictions";

export default function PortReferencePage() {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>("holidays");
  const [holidays, setHolidays] = useState<Holiday[]>([]);
  const [rates, setRates] = useState<PortRate[]>([]);
  const [msg, setMsg] = useState("");

  // Holiday form
  const [hPort, setHPort] = useState("");
  const [hCountry, setHCountry] = useState("CN");
  const [hDate, setHDate] = useState("");
  const [hName, setHName] = useState("");
  const [hType, setHType] = useState("public");
  const [hRecurring, setHRecurring] = useState(false);

  // Rate form
  const [rPort, setRPort] = useState("");
  const [rType, setRType] = useState("pilotage");
  const [rAmount, setRAmount] = useState("");
  const [rBand, setRBand] = useState("medium");
  const [rBasis, setRBasis] = useState("per_call");

  // Restriction lookup
  const [resPort, setResPort] = useState("");
  const [restriction, setRestriction] = useState<Restriction | null>(null);

  async function loadHolidays() {
    setHolidays(await apiGet("/api/v1/reference/ports/holidays"));
  }

  async function loadRates() {
    if (resPort) {
      setRates(await apiGet(`/api/v1/reference/ports/rates?port_unlocode=${resPort}`));
    }
  }

  useEffect(() => {
    if (tab === "holidays") loadHolidays().catch(() => {});
  }, [tab]);

  useEffect(() => {
    if (tab === "rates" && resPort) loadRates().catch(() => setRates([]));
  }, [tab, resPort]);

  async function addHoliday(e: FormEvent) {
    e.preventDefault();
    await apiPost("/api/v1/reference/ports/holidays", {
      port_unlocode: hPort.toUpperCase(),
      country: hCountry.toUpperCase(),
      holiday_date: hDate,
      holiday_name: hName,
      holiday_type: hType,
      recurring: hRecurring,
    });
    setMsg(t("page.portRef.holiday_added", "Holiday added"));
    setHPort(""); setHDate(""); setHName("");
    await loadHolidays();
  }

  async function addRate(e: FormEvent) {
    e.preventDefault();
    await apiPost("/api/v1/reference/ports/rates", {
      port_unlocode: rPort.toUpperCase(),
      rate_type: rType,
      amount_usd: parseFloat(rAmount),
      vessel_size_band: rBand,
      basis: rBasis,
    });
    setMsg(t("page.portRef.rate_added", "Rate added"));
    setRPort(""); setRAmount("");
    await loadRates();
  }

  async function lookupRestriction() {
    if (!resPort) return;
    const r = await apiGet(`/api/v1/reference/ports/${resPort.toUpperCase()}/restrictions`);
    setRestriction(r);
  }

  const tabStyle = (t: Tab) => ({
    padding: "8px 16px",
    borderRadius: "6px 6px 0 0",
    border: "none",
    borderBottom: tab === t ? "2px solid var(--primary)" : "2px solid transparent",
    background: "transparent",
    cursor: "pointer" as const,
    fontWeight: tab === t ? 600 : 400,
    color: tab === t ? "var(--primary)" : "var(--text-secondary)",
  });

  return (
    <AppShell>
      <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 24 }}>
        {t("page.portRef.title", "Port Reference Data")}
      </h1>

      {msg && (
        <div style={{ padding: "8px 12px", background: "var(--green-50)", color: "var(--green-700)", borderRadius: 6, marginBottom: 16 }}>
          {msg}
        </div>
      )}

      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--border)", marginBottom: 24 }}>
        <button style={tabStyle("holidays")} onClick={() => setTab("holidays")}>
          {t("page.portRef.holidays", "Holidays")}
        </button>
        <button style={tabStyle("rates")} onClick={() => setTab("rates")}>
          {t("page.portRef.rates", "Port Rates")}
        </button>
        <button style={tabStyle("restrictions")} onClick={() => setTab("restrictions")}>
          {t("page.portRef.restrictions", "Restrictions")}
        </button>
      </div>

      {tab === "holidays" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
          <form onSubmit={addHoliday} className="card" style={{ padding: 16 }}>
            <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>
              {t("page.portRef.add_holiday", "Add Holiday")}
            </h3>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <input placeholder="Port UNLOCODE" value={hPort} onChange={(e) => setHPort(e.target.value)} required maxLength={5} style={inputStyle} />
              <input placeholder="Country (e.g. CN)" value={hCountry} onChange={(e) => setHCountry(e.target.value)} required maxLength={2} style={inputStyle} />
              <input type="date" value={hDate} onChange={(e) => setHDate(e.target.value)} required style={inputStyle} />
              <input placeholder="Holiday name" value={hName} onChange={(e) => setHName(e.target.value)} required style={inputStyle} />
              <select value={hType} onChange={(e) => setHType(e.target.value)} style={inputStyle}>
                <option value="public">{t("page.portRef.public", "Public")}</option>
                <option value="religious">{t("page.portRef.religious", "Religious")}</option>
                <option value="local">{t("page.portRef.local", "Local")}</option>
              </select>
              <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                <input type="checkbox" checked={hRecurring} onChange={(e) => setHRecurring(e.target.checked)} />
                {t("page.portRef.recurring", "Recurring annually")}
              </label>
              <button type="submit" className="btn btn-primary">{t("common.add", "Add")}</button>
            </div>
          </form>
          <div className="card" style={{ padding: 16, overflow: "auto" }}>
            <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>
              {t("page.portRef.holiday_list", "Holiday List")} ({holidays.length})
            </h3>
            <table className="dataTable" style={{ width: "100%" }}>
              <thead>
                <tr>
                  <th>Port</th>
                  <th>Date</th>
                  <th>Name</th>
                  <th>{t("page.portRef.recurring_short", "Rec.")}</th>
                </tr>
              </thead>
              <tbody>
                {holidays.map((h) => (
                  <tr key={h.id}>
                    <td style={{ fontFamily: "monospace" }}>{h.port_unlocode}</td>
                    <td>{h.holiday_date}</td>
                    <td>{h.holiday_name}</td>
                    <td>{h.recurring ? "✓" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "rates" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
          <form onSubmit={addRate} className="card" style={{ padding: 16 }}>
            <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>
              {t("page.portRef.add_rate", "Add Port Rate")}
            </h3>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <input placeholder="Port UNLOCODE" value={rPort} onChange={(e) => setRPort(e.target.value)} required maxLength={5} style={inputStyle} />
              <select value={rType} onChange={(e) => setRType(e.target.value)} style={inputStyle}>
                <option value="pilotage">Pilotage</option>
                <option value="towage">Towage</option>
                <option value="mooring">Mooring</option>
                <option value="wharfage">Wharfage</option>
                <option value="light_dues">Light Dues</option>
              </select>
              <input placeholder="Amount (USD)" type="number" step="0.01" value={rAmount} onChange={(e) => setRAmount(e.target.value)} required style={inputStyle} />
              <select value={rBand} onChange={(e) => setRBand(e.target.value)} style={inputStyle}>
                <option value="small">Small (≤10k DWT)</option>
                <option value="medium">Medium (10-50k DWT)</option>
                <option value="large">Large (50-150k DWT)</option>
                <option value="xl">XL {'>'}150k DWT</option>
              </select>
              <select value={rBasis} onChange={(e) => setRBasis(e.target.value)} style={inputStyle}>
                <option value="per_call">Per Call</option>
                <option value="per_day">Per Day</option>
                <option value="per_gt">Per GT</option>
                <option value="per_dwt">Per DWT</option>
              </select>
              <button type="submit" className="btn btn-primary">{t("common.add", "Add")}</button>
            </div>
          </form>
          <div className="card" style={{ padding: 16, overflow: "auto" }}>
            <div style={{ display: "flex", gap: 8, marginBottom: 12, alignItems: "center" }}>
              <input
                placeholder="Port UNLOCODE to filter"
                value={resPort}
                onChange={(e) => setResPort(e.target.value)}
                style={{ ...inputStyle, flex: 1 }}
              />
            </div>
            <table className="dataTable" style={{ width: "100%" }}>
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Band</th>
                  <th>Amount</th>
                  <th>Basis</th>
                </tr>
              </thead>
              <tbody>
                {rates.map((r) => (
                  <tr key={r.id}>
                    <td>{r.rate_type}</td>
                    <td>{r.vessel_size_band}</td>
                    <td>${r.amount_usd.toLocaleString()}</td>
                    <td>{r.basis}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "restrictions" && (
        <div className="card" style={{ padding: 16 }}>
          <div style={{ display: "flex", gap: 8, marginBottom: 16, alignItems: "center" }}>
            <input
              placeholder="Port UNLOCODE (e.g. CNSHA)"
              value={resPort}
              onChange={(e) => setResPort(e.target.value)}
              style={{ ...inputStyle, flex: 1, maxWidth: 300 }}
            />
            <button className="btn btn-primary" onClick={lookupRestriction}>
              {t("common.lookup", "Lookup")}
            </button>
          </div>
          {restriction && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              <div>
                <h4 style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 8 }}>Size Limits</h4>
                <div style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 14 }}>
                  <span>Max Draft: {restriction.max_draft_m ? `${restriction.max_draft_m}m` : "—"}</span>
                  <span>Max LOA: {restriction.max_loa_m ? `${restriction.max_loa_m}m` : "—"}</span>
                  <span>Max Beam: {restriction.max_beam_m ? `${restriction.max_beam_m}m` : "—"}</span>
                  <span>Max DWT: {restriction.max_dwt ? `${restriction.max_dwt.toLocaleString()}t` : "—"}</span>
                </div>
              </div>
              <div>
                <h4 style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 8 }}>Operations</h4>
                <div style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 14 }}>
                  <span>Working Hours: {restriction.working_hours || "—"}</span>
                  <span>Night Work: {restriction.night_work_allowed ? "✓ Allowed" : "✗ Not allowed"}</span>
                  <span>Pilot Required: {restriction.requires_pilot ? "✓ Yes" : "✗ No"}</span>
                </div>
              </div>
            </div>
          )}
          {!restriction && resPort && (
            <p style={{ color: "var(--text-secondary)" }}>No restrictions found for {resPort.toUpperCase()}</p>
          )}
        </div>
      )}
    </AppShell>
  );
}

const inputStyle: React.CSSProperties = {
  padding: "8px 12px",
  borderRadius: 6,
  border: "1px solid var(--border)",
  fontSize: 13,
};
