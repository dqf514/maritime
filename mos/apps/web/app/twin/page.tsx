"use client";

import { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { StateView } from "@/components/StateView";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function TwinPage() {
  const { t } = useI18n();
  const [fleet, setFleet] = useState<{ vessels: Array<{ name: string; status: string; lat: number | null; lon: number | null }> } | null>(null);
  const [alerts, setAlerts] = useState<Array<{ title: string; level: string }>>([]);
  const [whatif, setWhatif] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setLoadErr("");
    try {
      const [f, a] = await Promise.all([apiGet("/api/v1/twin/fleet"), apiGet("/api/v1/twin/alerts")]);
      setFleet(f);
      setAlerts(Array.isArray(a) ? a : []);
    } catch {
      setLoadErr(t("common.failed", "Failed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    load();
  }, [load]);

  async function runWhatIf() {
    const res = await apiPost("/api/v1/twin/what-if", {
      lump_sum_freight: 100000,
      sea_days: 10,
      port_days: 2,
      port_costs: 10000,
    });
    setWhatif(
      t("page.twin.whatif_result", "L4 base TCE {base} → faster {faster} (Δ {delta})", {
        base: res.base_tce,
        faster: res.faster_tce,
        delta: res.delta_tce,
      }),
    );
  }

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("page.twin.title", "Fleet Twin")}</h1>
      <p style={{ color: "var(--muted)" }}>{t("page.twin.sub", "Positions, alerts and what-if.")}</p>
      <button className="btn btn-primary" type="button" onClick={() => runWhatIf().catch(() => setWhatif(t("common.failed", "Failed")))}>
        {t("page.twin.run_whatif", "Run L4 what-if")}
      </button>
      {whatif ? <p>{whatif}</p> : null}
      <div className="panel" style={{ marginTop: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>{t("page.twin.fleet", "Fleet (L1)")}</h3>
        <StateView loading={loading} error={loadErr} empty={!(fleet?.vessels || []).length} onRetry={load}>
          <table className="table">
            <thead>
              <tr>
                <th>{t("page.twin.vessel", "Vessel")}</th>
                <th>{t("common.status", "Status")}</th>
                <th>Lat</th>
                <th>Lon</th>
              </tr>
            </thead>
            <tbody>
              {(fleet?.vessels || []).map((v) => (
                <tr key={v.name}>
                  <td>{v.name}</td>
                  <td>{v.status}</td>
                  <td>{v.lat ?? "—"}</td>
                  <td>{v.lon ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </StateView>
      </div>
      <div className="panel" style={{ marginTop: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>{t("page.twin.alerts", "Alerts")}</h3>
        <StateView loading={loading} error={loadErr} empty={!alerts.length} emptyText={t("page.twin.no_alerts", "No alerts")} onRetry={load}>
          <ul>
            {alerts.map((a, i) => (
              <li key={i}>
                [{a.level}] {a.title}
              </li>
            ))}
          </ul>
        </StateView>
      </div>
    </AppShell>
  );
}
