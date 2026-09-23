"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type ComplianceSummary = {
  voyage_count: number;
  total_bunker_mt: number;
  total_co2_tonnes: number;
  eu_ets: {
    total_co2_tonnes: number;
    coverage_pct: number;
    liable_tonnes: number;
    co2_price_eur: number;
    cost_eur: number;
    cost_usd: number;
  };
  fueleu: {
    intensity_gco2_mj: number;
    limit_gco2_mj: number;
    compliant: boolean;
    margin_pct: number;
    penalty_usd: number;
  };
  emission_records: number;
  compliance_status: string;
};

type FuelFactor = {
  co2_factor_tonnes_per_tonne: number;
  energy_density_mj_per_kg: number;
};

export default function CompliancePage() {
  const { t } = useI18n();
  const [summary, setSummary] = useState<ComplianceSummary | null>(null);
  const [fuelFactors, setFuelFactors] = useState<Record<string, FuelFactor>>({});
  const [calcTab, setCalcTab] = useState<"emissions" | "euets" | "fueleu" | "cii">("emissions");

  // Calculator inputs
  const [fuelMt, setFuelMt] = useState("1000");
  const [fuelType, setFuelType] = useState("VLSFO");
  const [distanceNm, setDistanceNm] = useState("3000");
  const [cargoMt, setCargoMt] = useState("30000");
  const [co2Tonnes, setCo2Tonnes] = useState("3150");
  const [dwt, setDwt] = useState("50000");
  const [calcResult, setCalcResult] = useState<Record<string, unknown> | null>(null);

  async function load() {
    try {
      const [s, f] = await Promise.all([
        apiGet("/api/v1/compliance/summary"),
        apiGet("/api/v1/compliance/fuel-factors"),
      ]);
      setSummary(s);
      setFuelFactors(f);
    } catch {
      setSummary(null);
    }
  }

  useEffect(() => { load(); }, []);

  async function calculate() {
    const endpoints: Record<string, string> = {
      emissions: "/api/v1/compliance/calculate/emissions",
      euets: "/api/v1/compliance/calculate/eu-ets",
      fueleu: "/api/v1/compliance/calculate/fueleu",
      cii: "/api/v1/compliance/calculate/cii",
    };
    const bodies: Record<string, Record<string, unknown>> = {
      emissions: { fuel_consumption_mt: +fuelMt, fuel_type: fuelType, distance_nm: +distanceNm, cargo_mt: +cargoMt },
      euets: { co2_tonnes: +co2Tonnes, voyage_year: 2025, is_eu_voyage: true },
      fueleu: { fuel_consumption_mt: +fuelMt, fuel_type: fuelType, distance_nm: +distanceNm, cargo_mt: +cargoMt },
      cii: { co2_tonnes: +co2Tonnes, distance_nm: +distanceNm, dwt: +dwt },
    };
    try {
      const res = await apiPost(endpoints[calcTab], bodies[calcTab]);
      setCalcResult(res);
    } catch {
      setCalcResult({ error: "Calculation failed" });
    }
  }

  return (
    <AppShell title="Carbon Compliance" subtitle="EU ETS, FuelEU Maritime, CII — full emissions compliance dashboard">
      {/* Fleet compliance summary */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 16, marginBottom: 24 }}>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>Voyages</div>
          <div style={{ fontSize: 24, fontWeight: 700 }}>{summary?.voyage_count ?? "—"}</div>
        </div>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>Total CO2 (tonnes)</div>
          <div style={{ fontSize: 24, fontWeight: 700 }}>{summary?.total_co2_tonnes.toLocaleString() ?? "—"}</div>
        </div>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>EU ETS Cost</div>
          <div style={{ fontSize: 24, fontWeight: 700 }}>
            {summary ? `$${summary.eu_ets.cost_usd.toLocaleString()}` : "—"}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
            {summary ? `${summary.eu_ets.coverage_pct}% coverage` : ""}
          </div>
        </div>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>FuelEU Status</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: summary?.fueleu.compliant ? "var(--success, #16a34a)" : "var(--danger, #dc2626)" }}>
            {summary?.fueleu.compliant ? "Compliant" : "Non-compliant"}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
            {summary ? `${summary.fueleu.intensity_gco2_mj} vs ${summary.fueleu.limit_gco2_mj} gCO2e/MJ` : ""}
          </div>
        </div>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>Bunker Consumed</div>
          <div style={{ fontSize: 24, fontWeight: 700 }}>
            {summary ? `${summary.total_bunker_mt.toLocaleString()} MT` : "—"}
          </div>
        </div>
      </div>

      {/* Calculator */}
      <div className="card" style={{ padding: 20 }}>
        <h3 style={{ margin: "0 0 16px", fontSize: 16, fontWeight: 600 }}>Compliance Calculator</h3>
        <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
          {(["emissions", "euets", "fueleu", "cii"] as const).map((tab) => (
            <button
              key={tab}
              className={`btn btn-sm ${calcTab === tab ? "btn-primary" : ""}`}
              onClick={() => { setCalcTab(tab); setCalcResult(null); }}
            >
              {tab === "emissions" ? "CO2 Emissions" : tab === "euets" ? "EU ETS" : tab === "fueleu" ? "FuelEU" : "CII Rating"}
            </button>
          ))}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12, marginBottom: 16 }}>
          {(calcTab === "emissions" || calcTab === "fueleu") && (
            <>
              <div>
                <label style={{ fontSize: 12, color: "var(--text-muted)" }}>Fuel consumption (MT)</label>
                <input className="input" type="number" value={fuelMt} onChange={(e) => setFuelMt(e.target.value)} />
              </div>
              <div>
                <label style={{ fontSize: 12, color: "var(--text-muted)" }}>Fuel type</label>
                <select className="input" value={fuelType} onChange={(e) => setFuelType(e.target.value)}>
                  {Object.keys(fuelFactors).length > 0
                    ? Object.keys(fuelFactors).map((f) => <option key={f} value={f}>{f}</option>)
                    : ["HFO", "MGO", "VLSFO", "LNG"].map((f) => <option key={f} value={f}>{f}</option>)}
                </select>
              </div>
              <div>
                <label style={{ fontSize: 12, color: "var(--text-muted)" }}>Distance (NM)</label>
                <input className="input" type="number" value={distanceNm} onChange={(e) => setDistanceNm(e.target.value)} />
              </div>
              <div>
                <label style={{ fontSize: 12, color: "var(--text-muted)" }}>Cargo (MT)</label>
                <input className="input" type="number" value={cargoMt} onChange={(e) => setCargoMt(e.target.value)} />
              </div>
            </>
          )}
          {(calcTab === "euets" || calcTab === "cii") && (
            <div>
              <label style={{ fontSize: 12, color: "var(--text-muted)" }}>CO2 (tonnes)</label>
              <input className="input" type="number" value={co2Tonnes} onChange={(e) => setCo2Tonnes(e.target.value)} />
            </div>
          )}
          {calcTab === "euets" && (
            <div style={{ fontSize: 12, color: "var(--text-muted)", alignSelf: "end" }}>
              CO2 price: EUR 80/t (2025). Phase-in: 70% coverage.
            </div>
          )}
          {calcTab === "cii" && (
            <div>
              <label style={{ fontSize: 12, color: "var(--text-muted)" }}>DWT</label>
              <input className="input" type="number" value={dwt} onChange={(e) => setDwt(e.target.value)} />
            </div>
          )}
          {calcTab === "cii" && (
            <div>
              <label style={{ fontSize: 12, color: "var(--text-muted)" }}>Distance (NM)</label>
              <input className="input" type="number" value={distanceNm} onChange={(e) => setDistanceNm(e.target.value)} />
            </div>
          )}
        </div>

        <button className="btn btn-primary" onClick={calculate}>Calculate</button>

        {calcResult && (
          <div style={{ marginTop: 16, padding: 16, background: "var(--bg-secondary)", borderRadius: 8 }}>
            <h4 style={{ margin: "0 0 8px", fontSize: 14, fontWeight: 600 }}>Result</h4>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
              {Object.entries(calcResult).map(([key, val]) => (
                <div key={key}>
                  <div style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "capitalize" }}>
                    {key.replace(/_/g, " ")}
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 500 }}>
                    {typeof val === "number" ? val.toLocaleString() : String(val)}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Fuel factors reference */}
      {Object.keys(fuelFactors).length > 0 && (
        <div className="card" style={{ padding: 20, marginTop: 24 }}>
          <h3 style={{ margin: "0 0 12px", fontSize: 16, fontWeight: 600 }}>Emission Factors by Fuel Type</h3>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: "var(--bg-secondary)" }}>
                  <th style={{ padding: "8px 12px", textAlign: "left", borderBottom: "1px solid var(--border)" }}>Fuel</th>
                  <th style={{ padding: "8px 12px", textAlign: "right", borderBottom: "1px solid var(--border)" }}>CO2 Factor (t/t)</th>
                  <th style={{ padding: "8px 12px", textAlign: "right", borderBottom: "1px solid var(--border)" }}>Energy Density (MJ/kg)</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(fuelFactors).map(([fuel, f]) => (
                  <tr key={fuel} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ padding: "6px 12px", fontWeight: 500 }}>{fuel}</td>
                    <td style={{ padding: "6px 12px", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{f.co2_factor_tonnes_per_tonne}</td>
                    <td style={{ padding: "6px 12px", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{f.energy_density_mj_per_kg}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </AppShell>
  );
}
