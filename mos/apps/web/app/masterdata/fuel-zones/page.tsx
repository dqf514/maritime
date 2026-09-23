"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type FuelZone = {
  id: string;
  zone_name: string;
  zone_type: string;
  is_active: boolean;
  fuel_requirements: Record<string, unknown> | null;
  eu_ets_factor: number | null;
  fueleu_limit: number | null;
};

type PositionResult = {
  lat: number;
  lon: number;
  zones: { id: string; zone_name: string; zone_type: string; fuel_requirements: Record<string, unknown> | null }[];
};

export default function FuelZonesPage() {
  const { t } = useI18n();
  const [zones, setZones] = useState<FuelZone[]>([]);
  const [msg, setMsg] = useState("");

  // Position lookup
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [posResult, setPosResult] = useState<PositionResult | null>(null);

  // Compliance check
  const [cLat, setCLat] = useState("");
  const [cLon, setCLon] = useState("");
  const [cFuel, setCFuel] = useState("HFO");
  const [cSulfur, setCSulfur] = useState("");
  const [complianceResult, setComplianceResult] = useState<Record<string, unknown> | null>(null);

  // Create zone
  const [zName, setZName] = useState("");
  const [zType, setZType] = useState("eca");
  const [zSulfur, setZSulfur] = useState("");

  async function load() {
    setZones(await apiGet("/api/v1/reference/fuel-zones"));
  }

  useEffect(() => {
    load().catch(() => setZones([]));
  }, []);

  async function lookupPosition() {
    const res = await apiGet(`/api/v1/reference/fuel-zones/position?lat=${lat}&lon=${lon}`);
    setPosResult(res);
  }

  async function checkCompliance() {
    const sulfurParam = cSulfur ? `&sulfur_pct=${cSulfur}` : "";
    const res = await apiGet(`/api/v1/reference/fuel-zones/compliance?lat=${cLat}&lon=${cLon}&fuel_type=${cFuel}${sulfurParam}`);
    setComplianceResult(res);
  }

  async function createZone(e: FormEvent) {
    e.preventDefault();
    const fuelReqs = zSulfur ? { sulfur_max: parseFloat(zSulfur), fuel_type: "MGO" } : null;
    await apiPost("/api/v1/reference/fuel-zones", {
      zone_name: zName,
      zone_type: zType,
      fuel_requirements: fuelReqs,
    });
    setMsg(t("page.fuelZones.zone_created", "Zone created"));
    setZName(""); setZSulfur("");
    await load();
  }

  async function seedPresets() {
    await apiPost("/api/v1/reference/fuel-zones/seed-presets", {});
    setMsg(t("page.fuelZones.presets_seeded", "Preset zones seeded"));
    await load();
  }

  const zoneTypeColor = (t: string) => {
    if (t === "eca") return "var(--blue-700)";
    if (t === "eu_ets") return "var(--purple-700)";
    if (t === "fueleu") return "var(--amber-700)";
    return "var(--text-secondary)";
  };

  return (
    <AppShell>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <h1 style={{ fontSize: 20, fontWeight: 600, margin: 0 }}>
          {t("page.fuelZones.title", "Fuel Zone Management")}
        </h1>
        <button onClick={seedPresets} className="btn btn-secondary">
          {t("page.fuelZones.seed_presets", "Seed Preset Zones")}
        </button>
      </div>

      {msg && (
        <div style={{ padding: "8px 12px", background: "var(--green-50)", color: "var(--green-700)", borderRadius: 6, marginBottom: 16 }}>
          {msg}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, marginBottom: 24 }}>
        <div className="card" style={{ padding: 16 }}>
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>
            {t("page.fuelZones.position_lookup", "Position Lookup")}
          </h3>
          <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
            <input placeholder="Latitude" value={lat} onChange={(e) => setLat(e.target.value)} style={inputStyle} />
            <input placeholder="Longitude" value={lon} onChange={(e) => setLon(e.target.value)} style={inputStyle} />
            <button className="btn btn-primary" onClick={lookupPosition}>
              {t("common.lookup", "Lookup")}
            </button>
          </div>
          {posResult && (
            <div>
              <p style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 8 }}>
                Position ({posResult.lat}, {posResult.lon}) — {posResult.zones.length} zone(s)
              </p>
              {posResult.zones.map((z) => (
                <div key={z.id} style={{ padding: "6px 0", borderBottom: "1px solid var(--border)" }}>
                  <span style={{ fontWeight: 500 }}>{z.zone_name}</span>
                  <span style={{ marginLeft: 8, fontSize: 12, color: zoneTypeColor(z.zone_type) }}>
                    {z.zone_type.toUpperCase()}
                  </span>
                  {z.fuel_requirements && (
                    <span style={{ marginLeft: 8, fontSize: 12, color: "var(--text-secondary)" }}>
                      S≤{(z.fuel_requirements as Record<string, number>).sulfur_max || "?"}%
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="card" style={{ padding: 16 }}>
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>
            {t("page.fuelZones.compliance_check", "Fuel Compliance Check")}
          </h3>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
            <input placeholder="Latitude" value={cLat} onChange={(e) => setCLat(e.target.value)} style={inputStyle} />
            <input placeholder="Longitude" value={cLon} onChange={(e) => setCLon(e.target.value)} style={inputStyle} />
            <select value={cFuel} onChange={(e) => setCFuel(e.target.value)} style={inputStyle}>
              <option value="HFO">HFO</option>
              <option value="MGO">MGO</option>
              <option value="MDO">MDO</option>
              <option value="LNG">LNG</option>
            </select>
            <input placeholder="Sulfur %" type="number" step="0.01" value={cSulfur} onChange={(e) => setCSulfur(e.target.value)} style={inputStyle} />
          </div>
          <button className="btn btn-primary" onClick={checkCompliance} style={{ marginBottom: 12 }}>
            {t("page.fuelZones.check", "Check Compliance")}
          </button>
          {complianceResult && (
            <div>
              <div style={{
                padding: "8px 12px",
                borderRadius: 6,
                background: (complianceResult as Record<string, boolean>).compliant ? "var(--green-50)" : "var(--red-50)",
                color: (complianceResult as Record<string, boolean>).compliant ? "var(--green-700)" : "var(--red-700)",
                fontWeight: 500,
              }}>
                {(complianceResult as Record<string, boolean>).compliant ? "✓ COMPLIANT" : "✗ NON-COMPLIANT"}
              </div>
              {((complianceResult as Record<string, unknown>).violations as unknown[])?.length > 0 && (
                <ul style={{ marginTop: 8, fontSize: 13, color: "var(--red-700)" }}>
                  {((complianceResult as Record<string, unknown>).violations as string[]).map((v, i) => (
                    <li key={i}>{v}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 24 }}>
        <form onSubmit={createZone} className="card" style={{ padding: 16 }}>
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>
            {t("page.fuelZones.create_zone", "Create Zone")}
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <input placeholder="Zone name" value={zName} onChange={(e) => setZName(e.target.value)} required style={inputStyle} />
            <select value={zType} onChange={(e) => setZType(e.target.value)} style={inputStyle}>
              <option value="eca">ECA</option>
              <option value="eu_ets">EU ETS</option>
              <option value="fueleu">FuelEU</option>
              <option value="cii">CII</option>
              <option value="non_eca">Non-ECA</option>
            </select>
            <input placeholder="Max sulfur % (optional)" type="number" step="0.01" value={zSulfur} onChange={(e) => setZSulfur(e.target.value)} style={inputStyle} />
            <button type="submit" className="btn btn-primary">{t("common.create", "Create")}</button>
          </div>
        </form>

        <div className="card" style={{ padding: 16, overflow: "auto" }}>
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>
            {t("page.fuelZones.zone_list", "Zone List")} ({zones.length})
          </h3>
          <table className="dataTable" style={{ width: "100%" }}>
            <thead>
              <tr>
                <th>{t("page.fuelZones.name", "Name")}</th>
                <th>{t("page.fuelZones.type", "Type")}</th>
                <th>{t("page.fuelZones.sulfur_limit", "Sulfur Limit")}</th>
                <th>{t("page.fuelZones.active", "Active")}</th>
              </tr>
            </thead>
            <tbody>
              {zones.map((z) => (
                <tr key={z.id}>
                  <td style={{ fontWeight: 500 }}>{z.zone_name}</td>
                  <td>
                    <span style={{ color: zoneTypeColor(z.zone_type), fontWeight: 500, fontSize: 12 }}>
                      {z.zone_type.toUpperCase()}
                    </span>
                  </td>
                  <td>
                    {z.fuel_requirements
                      ? `${(z.fuel_requirements as Record<string, number>).sulfur_max || "—"}%`
                      : "—"
                    }
                  </td>
                  <td>{z.is_active ? "✓" : "✗"}</td>
                </tr>
              ))}
              {zones.length === 0 && (
                <tr>
                  <td colSpan={4} style={{ textAlign: "center", padding: 24, color: "var(--text-secondary)" }}>
                    {t("page.fuelZones.no_zones", "No fuel zones defined. Seed presets to get started.")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </AppShell>
  );
}

const inputStyle: React.CSSProperties = {
  padding: "8px 12px",
  borderRadius: 6,
  border: "1px solid var(--border)",
  fontSize: 13,
};
