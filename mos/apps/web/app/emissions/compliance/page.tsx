"use client";

import { msgOf } from "@/lib/errors";
import { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
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
    /** 后端标记：是否有运输功可评估（false 时不应断言「合规」） */
    assessable?: boolean;
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
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(""); // 汇总取数失败 —— 必须与「真的不合规」区分开
  const [factorsErr, setFactorsErr] = useState(""); // 燃料系数（参考数据）取数失败
  const [calcErr, setCalcErr] = useState("");
  const [calcTab, setCalcTab] = useState<"emissions" | "euets" | "fueleu" | "cii">("emissions");

  // Calculator inputs
  const [fuelMt, setFuelMt] = useState("1000");
  const [fuelType, setFuelType] = useState("VLSFO");
  const [distanceNm, setDistanceNm] = useState("3000");
  const [cargoMt, setCargoMt] = useState("30000");
  const [co2Tonnes, setCo2Tonnes] = useState("3150");
  const [dwt, setDwt] = useState("50000");
  const [calcResult, setCalcResult] = useState<Record<string, unknown> | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    // 汇总与参考数据分开取：任一失败都不许把空指标渲染成「不合规」
    const [s, f] = await Promise.allSettled([
      apiGet("/api/v1/compliance/summary"),
      apiGet("/api/v1/compliance/fuel-factors"),
    ]);
    if (s.status === "fulfilled") {
      setSummary(s.value as ComplianceSummary);
      setErr("");
    } else {
      setSummary(null);
      setErr(msgOf(s.reason));
    }
    if (f.status === "fulfilled") {
      setFuelFactors((f.value as Record<string, FuelFactor>) || {});
      setFactorsErr("");
    } else {
      setFuelFactors({});
      setFactorsErr(msgOf(f.reason));
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function calculate() {
    const endpoints: Record<string, string> = {
      emissions: "/api/v1/compliance/calculate/emissions",
      euets: "/api/v1/compliance/calculate/eu-ets",
      fueleu: "/api/v1/compliance/calculate/fueleu",
      cii: "/api/v1/compliance/calculate/cii",
    };
    const num = (raw: string, label: string): number | null => {
      const s = (raw ?? "").trim();
      if (s === "") return 0;
      const n = Number(s);
      if (!Number.isFinite(n)) {
        setCalcErr(t("page.compliance.err_numeric", "{field} must be a valid number", { field: label }));
        return null;
      }
      return n;
    };
    const fuel = num(fuelMt, t("page.compliance.fuel_consumption", "Fuel consumption (MT)"));
    if (fuel === null) return;
    const dist = num(distanceNm, t("page.compliance.distance", "Distance (NM)"));
    if (dist === null) return;
    const cargo = num(cargoMt, t("page.compliance.cargo", "Cargo (MT)"));
    if (cargo === null) return;
    const co2 = num(co2Tonnes, t("page.compliance.co2_tonnes", "CO2 (tonnes)"));
    if (co2 === null) return;
    const dw = num(dwt, t("page.compliance.dwt", "DWT"));
    if (dw === null) return;
    const bodies: Record<string, Record<string, unknown>> = {
      emissions: { fuel_consumption_mt: fuel, fuel_type: fuelType, distance_nm: dist, cargo_mt: cargo },
      euets: { co2_tonnes: co2, voyage_year: 2025, is_eu_voyage: true },
      fueleu: { fuel_consumption_mt: fuel, fuel_type: fuelType, distance_nm: dist, cargo_mt: cargo },
      cii: { co2_tonnes: co2, distance_nm: dist, dwt: dw },
    };
    setCalcErr("");
    try {
      const res = await apiPost(endpoints[calcTab], bodies[calcTab]);
      setCalcResult(res);
    } catch (ex) {
      setCalcResult(null);
      setCalcErr(msgOf(ex, t("page.compliance.calc_failed", "Calculation failed")));
    }
  }

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[
          { label: t("nav.emissions", "Emissions / FuelEU"), href: "/emissions" },
          { label: t("nav.compliance", "Carbon compliance") },
        ]}
        title={t("page.compliance.title", "Carbon Compliance")}
        subtitle={t("page.compliance.sub", "EU ETS, FuelEU Maritime, CII — full emissions compliance dashboard")}
      />
      {/* 加载失败 / 参考数据失败 —— 明确报错，绝不把空指标画成「不合规」 */}
      {err ? (
        <div className="panel panel-warn">
          <p className="flash-err">
            {t("page.compliance.load_failed", "Compliance summary could not be loaded — status is unknown.")}
          </p>
          <p className="muted">{err}</p>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => void load()}>
            {t("common.retry", "重试")}
          </button>
        </div>
      ) : null}
      {factorsErr ? (
        <p className="flash-warn">
          {t("page.compliance.factors_failed", "Emission factors could not be loaded.")} {factorsErr}
        </p>
      ) : null}
      {/* Fleet compliance summary */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 16, marginBottom: 24 }}>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>{t("page.compliance.kpi_voyages", "Voyages")}</div>
          <div style={{ fontSize: 24, fontWeight: 700 }}>{summary?.voyage_count ?? "—"}</div>
        </div>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>{t("page.compliance.kpi_co2", "Total CO2 (tonnes)")}</div>
          <div style={{ fontSize: 24, fontWeight: 700 }}>{summary?.total_co2_tonnes?.toLocaleString() ?? "—"}</div>
        </div>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>{t("page.compliance.kpi_euets", "EU ETS Cost")}</div>
          <div style={{ fontSize: 24, fontWeight: 700 }}>
            {summary?.eu_ets?.cost_usd != null ? `$${summary.eu_ets.cost_usd.toLocaleString()}` : "—"}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
            {summary?.eu_ets ? t("page.compliance.coverage", "{n}% coverage", { n: summary.eu_ets.coverage_pct }) : ""}
          </div>
        </div>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>{t("page.compliance.kpi_fueleu", "FuelEU Status")}</div>
          {/* 没有取到数据时是「未知」，不是「不合规」；无可评估运输功时是「不可评估」，不是「合规」 */}
          <div
            style={{
              fontSize: 24,
              fontWeight: 700,
              color: !summary
                ? "var(--text-secondary)"
                : summary.fueleu?.assessable === false
                  ? "var(--text-secondary)"
                  : summary.fueleu?.compliant
                    ? "var(--success, #16a34a)"
                    : "var(--danger, #dc2626)",
            }}
          >
            {!summary
              ? loading
                ? t("common.loading", "加载中…")
                : t("page.compliance.unknown", "Unknown")
              : summary.fueleu?.assessable === false
                ? t("page.compliance.not_assessable", "Not assessable")
                : summary.fueleu?.compliant
                  ? t("page.compliance.compliant", "Compliant")
                  : t("page.compliance.non_compliant", "Non-compliant")}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
            {summary ? t("page.compliance.fueleu_line", "{a} vs {b} gCO2e/MJ", { a: summary.fueleu?.intensity_gco2_mj ?? 0, b: summary.fueleu?.limit_gco2_mj ?? 0 }) : ""}
          </div>
        </div>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>{t("page.compliance.kpi_bunker", "Bunker Consumed")}</div>
          <div style={{ fontSize: 24, fontWeight: 700 }}>
            {summary ? `${summary.total_bunker_mt?.toLocaleString() ?? "—"} MT` : "—"}
          </div>
        </div>
      </div>
      {summary && summary.voyage_count === 0 ? (
        <p className="muted">{t("page.compliance.no_data", "No voyage emissions recorded yet — nothing to assess.")}</p>
      ) : null}

      {/* Calculator */}
      <div className="card" style={{ padding: 20 }}>
        <h3 style={{ margin: "0 0 16px", fontSize: 16, fontWeight: 600 }}>{t("page.compliance.calc_title", "Compliance Calculator")}</h3>
        <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
          {(["emissions", "euets", "fueleu", "cii"] as const).map((tab) => (
            <button
              key={tab}
              className={`btn btn-sm ${calcTab === tab ? "btn-primary" : ""}`}
              onClick={() => { setCalcTab(tab); setCalcResult(null); setCalcErr(""); }}
            >
              {tab === "emissions"
                ? t("page.compliance.tab_emissions", "CO2 Emissions")
                : tab === "euets"
                  ? t("page.compliance.tab_euets", "EU ETS")
                  : tab === "fueleu"
                    ? t("page.compliance.tab_fueleu", "FuelEU")
                    : t("page.compliance.tab_cii", "CII Rating")}
            </button>
          ))}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12, marginBottom: 16 }}>
          {(calcTab === "emissions" || calcTab === "fueleu") && (
            <>
              <div>
                <label style={{ fontSize: 12, color: "var(--text-muted)" }}>{t("page.compliance.fuel_consumption", "Fuel consumption (MT)")}</label>
                <input className="input" type="number" value={fuelMt} onChange={(e) => setFuelMt(e.target.value)} />
              </div>
              <div>
                <label style={{ fontSize: 12, color: "var(--text-muted)" }}>{t("page.compliance.fuel_type", "Fuel type")}</label>
                <select className="input" value={fuelType} onChange={(e) => setFuelType(e.target.value)}>
                  {Object.keys(fuelFactors).length > 0
                    ? Object.keys(fuelFactors).map((f) => <option key={f} value={f}>{f}</option>)
                    : ["HFO", "MGO", "VLSFO", "LNG"].map((f) => <option key={f} value={f}>{f}</option>)}
                </select>
              </div>
              <div>
                <label style={{ fontSize: 12, color: "var(--text-muted)" }}>{t("page.compliance.distance", "Distance (NM)")}</label>
                <input className="input" type="number" value={distanceNm} onChange={(e) => setDistanceNm(e.target.value)} />
              </div>
              <div>
                <label style={{ fontSize: 12, color: "var(--text-muted)" }}>{t("page.compliance.cargo", "Cargo (MT)")}</label>
                <input className="input" type="number" value={cargoMt} onChange={(e) => setCargoMt(e.target.value)} />
              </div>
            </>
          )}
          {(calcTab === "euets" || calcTab === "cii") && (
            <div>
              <label style={{ fontSize: 12, color: "var(--text-muted)" }}>{t("page.compliance.co2_tonnes", "CO2 (tonnes)")}</label>
              <input className="input" type="number" value={co2Tonnes} onChange={(e) => setCo2Tonnes(e.target.value)} />
            </div>
          )}
          {calcTab === "euets" && (
            <div style={{ fontSize: 12, color: "var(--text-muted)", alignSelf: "end" }}>
              {t("page.compliance.co2_price_note", "CO2 price: EUR 80/t (2025). Phase-in: 70% coverage.")}
            </div>
          )}
          {calcTab === "cii" && (
            <div>
              <label style={{ fontSize: 12, color: "var(--text-muted)" }}>{t("page.compliance.dwt", "DWT")}</label>
              <input className="input" type="number" value={dwt} onChange={(e) => setDwt(e.target.value)} />
            </div>
          )}
          {calcTab === "cii" && (
            <div>
              <label style={{ fontSize: 12, color: "var(--text-muted)" }}>{t("page.compliance.distance", "Distance (NM)")}</label>
              <input className="input" type="number" value={distanceNm} onChange={(e) => setDistanceNm(e.target.value)} />
            </div>
          )}
        </div>

        <button className="btn btn-primary" onClick={calculate}>{t("page.compliance.calculate", "Calculate")}</button>

        {calcErr ? <p className="flash-err">{calcErr}</p> : null}

        {calcResult && (
          <div style={{ marginTop: 16, padding: 16, background: "var(--bg-secondary)", borderRadius: 8 }}>
            <h4 style={{ margin: "0 0 8px", fontSize: 14, fontWeight: 600 }}>{t("page.compliance.result", "Result")}</h4>
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
          <h3 style={{ margin: "0 0 12px", fontSize: 16, fontWeight: 600 }}>{t("page.compliance.factors_title", "Emission Factors by Fuel Type")}</h3>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: "var(--bg-secondary)" }}>
                  <th style={{ padding: "8px 12px", textAlign: "left", borderBottom: "1px solid var(--border)" }}>{t("page.compliance.col_fuel", "Fuel")}</th>
                  <th style={{ padding: "8px 12px", textAlign: "right", borderBottom: "1px solid var(--border)" }}>{t("page.compliance.col_co2_factor", "CO2 Factor (t/t)")}</th>
                  <th style={{ padding: "8px 12px", textAlign: "right", borderBottom: "1px solid var(--border)" }}>{t("page.compliance.col_energy", "Energy Density (MJ/kg)")}</th>
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
