"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { StateView } from "@/components/StateView";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type FleetVessel = { name: string; status: string; lat: number | null; lon: number | null };

/** 孪生告警 — title_i18n/body_i18n 由后端按句式补双语（home._ship_alerts 先例） */
type TwinAlertItem = {
  title: string;
  title_i18n?: { en?: string; zh?: string } | null;
  body?: string | null;
  body_i18n?: { en?: string; zh?: string } | null;
  level: string;
};

const LEVEL_TONE: Record<string, StatusTone> = {
  critical: "danger",
  high: "danger",
  warn: "warn",
  warning: "warn",
  info: "info",
};

export default function TwinPage() {
  const { t, locale } = useI18n();
  const zh = locale.startsWith("zh");
  const [fleet, setFleet] = useState<{ vessels: FleetVessel[] } | null>(null);
  const [alerts, setAlerts] = useState<TwinAlertItem[]>([]);
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

  /** title/body 双语择取 —— 无 i18n 结构时回落原文 */
  function alertTitle(a: TwinAlertItem): string {
    return (zh ? a.title_i18n?.zh : a.title_i18n?.en) || a.title;
  }
  function alertBody(a: TwinAlertItem): string | null {
    if (!a.body && !a.body_i18n) return null;
    return (zh ? a.body_i18n?.zh : a.body_i18n?.en) || a.body || null;
  }

  const fleetColumns: ColumnDef<FleetVessel>[] = useMemo(
    () => [
      { key: "name", title: t("page.twin.vessel", "Vessel"), minWidth: 140, value: (r) => r.name },
      { key: "status", title: t("common.status", "Status"), width: 110, value: (r) => r.status },
      {
        key: "lat",
        title: t("page.twin.lat", "LAT"),
        width: 90,
        align: "right",
        value: (r) => r.lat,
        render: (v) => (v == null ? "—" : String(v)),
      },
      {
        key: "lon",
        title: t("page.twin.lon", "LON"),
        width: 90,
        align: "right",
        value: (r) => r.lon,
        render: (v) => (v == null ? "—" : String(v)),
      },
    ],
    [t],
  );

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.twin", "Fleet Twin") }]}
        title={t("page.twin.title", "Fleet Twin")}
        subtitle={t("page.twin.sub", "Positions, alerts and what-if.")}
        actions={
          <button className="btn btn-primary" type="button" onClick={() => runWhatIf().catch(() => setWhatif(t("common.failed", "Failed")))}>
            {t("page.twin.run_whatif", "Run L4 what-if")}
          </button>
        }
      />
      {whatif ? <p>{whatif}</p> : null}
      <div className="panel">
        <h3>{t("page.twin.fleet", "Fleet (L1)")}</h3>
        <StateView loading={loading} error={loadErr} empty={!(fleet?.vessels || []).length} onRetry={load}>
          <DataGrid<FleetVessel>
            columns={fleetColumns}
            data={fleet?.vessels || []}
            rowKey={(r) => r.name}
            storageKey="twin_fleet_grid"
            showFooter={false}
            emptyText={t("common.empty", "No records")}
          />
        </StateView>
      </div>
      <div className="panel">
        <h3>{t("page.twin.alerts", "Alerts")}</h3>
        <StateView loading={loading} error={loadErr} empty={!alerts.length} emptyText={t("page.twin.no_alerts", "No alerts")} onRetry={load}>
          <ul className="twin-alerts">
            {alerts.map((a, i) => {
              const detail = alertBody(a);
              return (
                <li key={i}>
                  <StatusBadge status={a.level} tone={LEVEL_TONE[a.level] || "info"} />
                  <span className="twin-alert-title">{alertTitle(a)}</span>
                  {detail ? <span className="muted twin-alert-body">{detail}</span> : null}
                </li>
              );
            })}
          </ul>
        </StateView>
      </div>
    </AppShell>
  );
}
