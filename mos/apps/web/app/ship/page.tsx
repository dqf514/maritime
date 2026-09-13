"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type FleetRow = {
  vessel_id: string;
  name: string;
  imo: string;
  flag: string;
  vessel_type: string;
  technical_status: string;
  management_mode: string;
  class_society: string | null;
  next_drydock: string | null;
  superintendent: string | null;
  external_system: string | null;
  open_work_orders: number;
  open_defects: number;
  expiring_certs: number;
};

type Fleet = {
  fleet_size: number;
  open_work_orders: number;
  open_defects: number;
  expiring_certificates: number;
  vessels: FleetRow[];
};

type Adapter = { code: string; name: string; capabilities: string[]; status: string };

export default function ShipManagementPage() {
  const { t } = useI18n();
  const [fleet, setFleet] = useState<Fleet | null>(null);
  const [adapters, setAdapters] = useState<Adapter[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [logs, setLogs] = useState<any[]>([]);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    apiGet("/api/v1/ship/fleet").then(setFleet).catch(() => setMsg(t("page.ship.module_required", "Ship management module required")));
    apiGet("/api/v1/ship/integrations/adapters").then(setAdapters).catch(() => undefined);
    apiGet("/api/v1/ship/integrations/sync-logs").then(setLogs).catch(() => undefined);
  }, [t]);

  async function openVessel(id: string) {
    setSelected(id);
    try {
      setDetail(await apiGet(`/api/v1/ship/vessels/${id}`));
    } catch (e: any) {
      setDetail(null);
      setMsg(e?.message || t("common.failed", "Failed"));
    }
  }

  async function inboundDemo() {
    if (!fleet?.vessels?.[0]) {
      setMsg(t("page.ship.no_vessel", "No vessel in fleet"));
      return;
    }
    const imo = fleet.vessels[0].imo;
    const token = localStorage.getItem("voyageos_token");
    const API = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";
    try {
      const res = await fetch(`${API}/api/v1/ship/integrations/inbound`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          system: "pms.mock",
          entity_type: "work_order",
          external_ref: `UI-${Date.now()}`,
          vessel_imo: imo,
          data: { title: "External PMS corrective job", priority: "high", status: "open", category: "defect" },
        }),
      });
      setMsg(
        res.ok
          ? t("page.ship.inbound_ok", "Inbound PMS sync accepted — refresh fleet.")
          : t("page.ship.inbound_fail", "Inbound sync failed"),
      );
      if (res.ok) {
        setFleet(await apiGet("/api/v1/ship/fleet"));
        setLogs(await apiGet("/api/v1/ship/integrations/sync-logs"));
      }
    } catch (e: any) {
      setMsg(e?.message || t("page.ship.inbound_fail", "Inbound sync failed"));
    }
  }

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.ship.title", "Ship management")}</h1>
          <p className="page-sub">
            {t("page.ship.sub", "Technical fleet for owners & managers — certificates, PMS, crew, defects.")}
          </p>
        </div>
        <div className="quick-row">
          <Link href="/dashboards/technical" className="btn btn-primary">
            {t("page.ship.wall", "Technical live wall")}
          </Link>
          <button type="button" className="btn btn-ghost" onClick={inboundDemo}>
            {t("page.ship.simulate", "Simulate PMS inbound")}
          </button>
        </div>
      </div>
      {msg ? <p className="flash">{msg}</p> : null}

      <div className="kpi-row">
        <div className="kpi-card">
          <span>{t("page.ship.kpi_fleet", "Fleet")}</span>
          <strong>{fleet?.fleet_size ?? "—"}</strong>
        </div>
        <div className="kpi-card">
          <span>{t("page.ship.kpi_wo", "Open WOs")}</span>
          <strong>{fleet?.open_work_orders ?? "—"}</strong>
        </div>
        <div className="kpi-card">
          <span>{t("page.ship.kpi_def", "Defects")}</span>
          <strong>{fleet?.open_defects ?? "—"}</strong>
        </div>
        <div className="kpi-card warn">
          <span>{t("page.ship.kpi_cert", "Certs at risk")}</span>
          <strong>{fleet?.expiring_certificates ?? "—"}</strong>
        </div>
      </div>

      <div className="ship-layout">
        <div className="panel">
          <h2>{t("page.ship.fleet", "Technical fleet")}</h2>
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("page.ship.col_vessel", "Vessel")}</th>
                <th>{t("common.status", "Status")}</th>
                <th>{t("page.ship.col_mode", "Mode")}</th>
                <th>{t("page.ship.col_wo", "WO")}</th>
                <th>{t("page.ship.col_def", "Def")}</th>
                <th>{t("page.ship.col_cert", "Cert")}</th>
                <th>{t("page.ship.col_drydock", "Drydock")}</th>
              </tr>
            </thead>
            <tbody>
              {(fleet?.vessels || []).map((v) => (
                <tr key={v.vessel_id} className={selected === v.vessel_id ? "active" : ""} onClick={() => openVessel(v.vessel_id)}>
                  <td>
                    <strong>{v.name}</strong>
                    <div className="muted">
                      {v.imo} · {v.flag}
                    </div>
                  </td>
                  <td>{v.technical_status}</td>
                  <td>{v.management_mode}</td>
                  <td>{v.open_work_orders}</td>
                  <td>{v.open_defects}</td>
                  <td>{v.expiring_certs}</td>
                  <td>{v.next_drydock || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel">
          <h2>{detail?.vessel?.name || t("page.ship.select", "Select a vessel")}</h2>
          {detail ? (
            <>
              <p className="muted">
                {detail.profile.class_society} · {detail.profile.engine_maker} {detail.profile.engine_type} · Super{" "}
                {detail.profile.superintendent || "—"}
                {detail.profile.external_system ? ` · Ext: ${detail.profile.external_system}` : ""}
              </p>
              <h3>{t("page.ship.certs", "Certificates")}</h3>
              <ul className="compact-list">
                {detail.certificates.map((c: any) => (
                  <li key={c.id}>
                    <span className={`pill ${c.status}`}>{c.status}</span> {c.cert_name} · {c.expires_on || "n/a"}
                  </li>
                ))}
              </ul>
              <h3>{t("page.ship.wos", "Work orders")}</h3>
              <ul className="compact-list">
                {detail.work_orders.map((w: any) => (
                  <li key={w.id}>
                    <span className={`pill ${w.priority}`}>{w.priority}</span> {w.wo_no} {w.title} ({w.status})
                  </li>
                ))}
              </ul>
              <h3>{t("page.ship.crew", "Crew")}</h3>
              <ul className="compact-list">
                {detail.crew.map((c: any) => (
                  <li key={c.id}>
                    {c.rank}: {c.full_name}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="muted">{t("page.ship.select_hint", "Click a vessel to open technical card.")}</p>
          )}
        </div>
      </div>

      <div className="panel">
        <h2>{t("page.ship.adapters", "External ship management adapters")}</h2>
        <p className="page-sub">{t("page.ship.adapters_sub", "Reserved interfaces for SpecTec / ABS NS / ShipNet / generic webhook.")}</p>
        <div className="adapter-grid">
          {adapters.map((a) => (
            <div key={a.code} className="adapter-card">
              <strong>{a.name}</strong>
              <div className="muted">{a.code}</div>
              <div className="pill">{a.status}</div>
              <div className="muted">{a.capabilities.join(" · ")}</div>
            </div>
          ))}
        </div>
        <h3>{t("page.ship.sync_logs", "Recent sync logs")}</h3>
        <ul className="compact-list">
          {logs.slice(0, 8).map((l) => (
            <li key={l.id}>
              [{l.direction}] {l.entity_type} — {l.status} {l.message || ""}
            </li>
          ))}
          {!logs.length ? <li className="muted">{t("page.ship.sync_empty", "No sync yet — use Simulate PMS inbound.")}</li> : null}
        </ul>
      </div>
    </AppShell>
  );
}
