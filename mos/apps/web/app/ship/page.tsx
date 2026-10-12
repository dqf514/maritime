"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { PageGuide } from "@/components/PageGuide";
import { Tabs } from "@/components/Tabs";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { CertOverview, VesselCertificates } from "@/components/ShipCertificates";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

const DEMO_TOOLS = process.env.NEXT_PUBLIC_DEMO_TOOLS === "1";

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
  updated_at?: string | null;
};

type Fleet = {
  fleet_size: number;
  open_work_orders: number;
  open_defects: number;
  expiring_certificates: number;
  vessels: FleetRow[];
};

type Adapter = { code: string; name: string; capabilities: string[]; status: string };

type CertAlert = { crew_id: string; crew_name: string; code: string; expires_on: string; days_left: number };
type CertRow = { code: string; expires_on: string };

export default function ShipManagementPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [tab, setTab] = useState<"fleet" | "certs">("fleet");
  const [fleet, setFleet] = useState<Fleet | null>(null);
  const [adapters, setAdapters] = useState<Adapter[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [logs, setLogs] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);

  const [selWo, setSelWo] = useState<any>(null);
  const [woSpares, setWoSpares] = useState<any[]>([]);
  const [woPart, setWoPart] = useState("");
  const [woQty, setWoQty] = useState("1");
  const [woWarnings, setWoWarnings] = useState<string[]>([]);

  const [crewName, setCrewName] = useState("");
  const [crewRank, setCrewRank] = useState("");
  const [certRows, setCertRows] = useState<CertRow[]>([]);
  const [editingCrew, setEditingCrew] = useState<{ id: string; full_name: string } | null>(null);
  const [certAlerts, setCertAlerts] = useState<CertAlert[]>([]);

  useEffect(() => {
    apiGet("/api/v1/ship/fleet").then(setFleet).catch(() => toast.error(t("page.ship.module_required", "Ship management module required")));
    apiGet("/api/v1/ship/integrations/adapters").then(setAdapters).catch(() => undefined);
    apiGet("/api/v1/ship/integrations/sync-logs").then(setLogs).catch(() => undefined);
    apiGet("/api/v1/ship/crew/cert-alerts?days=60")
      .then((rows) => setCertAlerts(Array.isArray(rows) ? rows : []))
      .catch(() => undefined);
  }, [t]);

  async function openVessel(id: string) {
    setSelected(id);
    setSelWo(null);
    setWoSpares([]);
    setWoWarnings([]);
    setEditingCrew(null);
    setCertRows([]);
    try {
      setDetail(await apiGet(`/api/v1/ship/vessels/${id}`));
    } catch (e: any) {
      setDetail(null);
      toast.error(e?.message || t("common.failed", "Failed"));
    }
  }

  async function refreshDetail() {
    if (!selected) return;
    setDetail(await apiGet(`/api/v1/ship/vessels/${selected}`));
  }

  async function refreshCertAlerts() {
    const rows = await apiGet("/api/v1/ship/crew/cert-alerts?days=60").catch(() => []);
    setCertAlerts(Array.isArray(rows) ? rows : []);
  }

  async function selectWo(w: any) {
    setSelWo(w);
    setWoWarnings([]);
    setWoPart("");
    try {
      const rows = await apiGet(`/api/v1/ship/work-orders/${w.id}/spares`);
      setWoSpares(Array.isArray(rows) ? rows : []);
    } catch {
      setWoSpares([]);
    }
  }

  async function woTransition(target: string) {
    if (!selWo) return;
    setBusy(true);
    try {
      const res = await apiPatch(`/api/v1/ship/work-orders/${selWo.id}`, { status: target });
      setWoWarnings(Array.isArray(res?.warnings) ? res.warnings.map((w: unknown) => String(w)) : []);
      toast.success(t("page.ship.wo_moved", "Work order status → {target}", { target }));
      setSelWo((prev: any) => (prev ? { ...prev, status: res?.status || target } : prev));
      await refreshDetail();
    } catch (e: any) {
      toast.error(e?.message || t("common.failed", "Failed"));
    } finally {
      setBusy(false);
    }
  }

  async function addWoSpare() {
    if (!selWo || !woPart || !(Number(woQty) > 0)) {
      toast.success(t("page.ship.spare_need", "Select a spare part and enter quantity"));
      return;
    }
    setBusy(true);
    try {
      const res = await apiPost(`/api/v1/ship/work-orders/${selWo.id}/spares`, { part_id: woPart, qty: Number(woQty) });
      setWoWarnings(Array.isArray(res?.warnings) ? res.warnings.map((w: unknown) => String(w)) : []);
      toast.success(t("page.ship.spare_ok", "Spare consumption logged"));
      const rows = await apiGet(`/api/v1/ship/work-orders/${selWo.id}/spares`).catch(() => []);
      setWoSpares(Array.isArray(rows) ? rows : []);
    } catch (e: any) {
      toast.error(e?.message || t("common.failed", "Failed"));
    } finally {
      setBusy(false);
    }
  }

  function setCert(idx: number, key: keyof CertRow, value: string) {
    setCertRows((prev) => prev.map((r, i) => (i === idx ? { ...r, [key]: value } : r)));
  }

  async function saveCrew() {
    setBusy(true);
    try {
      const certificates = certRows
        .filter((r) => r.code.trim())
        .map((r) => ({ code: r.code.trim(), expires_on: r.expires_on || null }));
      if (editingCrew) {
        await apiPatch(`/api/v1/ship/crew/${editingCrew.id}`, { certificates });
        toast.success(t("page.ship.crew_certs_ok", "Crew certificates updated"));
      } else {
        if (!crewName.trim() || !crewRank.trim()) {
          toast.success(t("page.ship.crew_need", "Enter crew name and rank"));
          setBusy(false);
          return;
        }
        await apiPost("/api/v1/ship/crew", {
          vessel_id: selected,
          full_name: crewName.trim(),
          rank: crewRank.trim(),
          certificates,
        });
        toast.success(t("page.ship.crew_ok", "Crew registered"));
      }
      setCrewName("");
      setCrewRank("");
      setCertRows([]);
      setEditingCrew(null);
      await refreshDetail();
      await refreshCertAlerts();
    } catch (e: any) {
      toast.error(e?.message || t("common.failed", "Failed"));
    } finally {
      setBusy(false);
    }
  }

  async function inboundDemo() {
    if (!fleet?.vessels?.[0]) {
      toast.success(t("page.ship.no_vessel", "No vessel in fleet"));
      return;
    }
    const imo = fleet.vessels[0].imo;
    try {
      await apiPost("/api/v1/ship/integrations/inbound", {
        system: "pms.mock",
        entity_type: "work_order",
        external_ref: `UI-${Date.now()}`,
        vessel_imo: imo,
        data: { title: "External PMS corrective job", priority: "high", status: "open", category: "defect" },
      });
      toast.success(t("page.ship.inbound_ok", "Inbound PMS sync accepted — refresh fleet."));
      setFleet(await apiGet("/api/v1/ship/fleet"));
      setLogs(await apiGet("/api/v1/ship/integrations/sync-logs"));
    } catch (e: any) {
      toast.error(e?.message || t("page.ship.inbound_fail", "Inbound sync failed"));
    }
  }

  const fleetColumns = useMemo<ColumnDef<FleetRow>[]>(
    () => [
      {
        key: "name",
        title: t("page.ship.col_vessel", "Vessel"),
        width: 220,
        value: (r) => r.name,
        render: (_v, r) => (
          <div>
            <strong>
              <Link
                href={`/ship/vessels/${r.vessel_id}`}
                onClick={(e) => e.stopPropagation()}
                style={{ color: "inherit", textDecoration: "none" }}
              >
                {r.name}
              </Link>
            </strong>
            <div className="muted">
              {r.imo} · {r.flag} ·{" "}
              <Link href={`/ship/vessels/${r.vessel_id}`} onClick={(e) => e.stopPropagation()}>
                {t("page.ship.vessel_card", "Vessel card")}
              </Link>
            </div>
          </div>
        ),
      },
      {
        key: "technical_status",
        title: t("common.status", "Status"),
        width: 110,
        value: (r) => r.technical_status,
      },
      {
        key: "management_mode",
        title: t("page.ship.col_mode", "Mode"),
        width: 110,
        value: (r) => r.management_mode,
      },
      {
        key: "open_work_orders",
        title: t("page.ship.col_wo", "WO"),
        width: 70,
        value: (r) => r.open_work_orders,
      },
      {
        key: "open_defects",
        title: t("page.ship.col_def", "Def"),
        width: 70,
        value: (r) => r.open_defects,
      },
      {
        key: "expiring_certs",
        title: t("page.ship.col_cert", "Cert"),
        width: 70,
        value: (r) => r.expiring_certs,
      },
      {
        key: "next_drydock",
        title: t("page.ship.col_drydock", "Drydock"),
        width: 110,
        value: (r) => r.next_drydock,
        render: (v) => String(v || "—"),
      },
      {
        key: "updated_at",
        title: t("list.last_modified", "Last modified"),
        width: 135,
        value: (r) => r.updated_at ?? null,
        render: (v) => (v ? String(v).replace("T", " ").slice(0, 16) : "—"),
      },
    ],
    [t],
  );

  const spareColumns = useMemo<ColumnDef<any>[]>(
    () => [
      {
        key: "part_no",
        title: t("page.ship.part_no", "Part no"),
        width: 140,
        value: (r: any) => r.part_no || r.part_id?.slice(0, 8),
      },
      {
        key: "description",
        title: t("page.ship.part_desc", "Description"),
        width: 200,
        value: (r: any) => r.description,
        render: (v) => String(v || "—"),
      },
      {
        key: "qty",
        title: t("page.ship.spare_qty", "Qty"),
        width: 80,
        align: "right",
        value: (r: any) => r.qty,
      },
    ],
    [t],
  );

  const certAlertColumns = useMemo<ColumnDef<CertAlert>[]>(
    () => [
      {
        key: "crew_name",
        title: t("page.ship.crew_name", "Crew"),
        width: 150,
        value: (r) => r.crew_name,
      },
      {
        key: "code",
        title: t("page.ship.cert_code", "Cert"),
        width: 130,
        value: (r) => r.code,
      },
      {
        key: "expires_on",
        title: t("page.ship.cert_expires", "Expires"),
        width: 120,
        value: (r) => r.expires_on,
      },
      {
        key: "days_left",
        title: t("page.ship.days_left", "Days left"),
        width: 110,
        align: "right",
        value: (r) => r.days_left,
        render: (v, r) =>
          r.days_left < 0 ? (
            <span style={{ color: "var(--danger)", fontWeight: 600 }}>
              {t("page.ship.expired", "Expired")} ({r.days_left})
            </span>
          ) : (
            r.days_left
          ),
      },
    ],
    [t],
  );

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.ship", "Ship management") }]}
        title={t("page.ship.title", "Ship management")}
        subtitle={t("page.ship.sub", "Technical fleet for owners & managers — certificates, PMS, crew, defects.")}
        actions={
          <>
            <PageGuide pageKey="ship" />
            <Link href="/dashboards/technical" className="btn btn-primary">
              {t("page.ship.wall", "Technical live wall")}
            </Link>
            {DEMO_TOOLS ? (
              <button type="button" className="btn btn-ghost" onClick={inboundDemo}>
                {t("page.ship.simulate", "Simulate PMS inbound")}
              </button>
            ) : null}
          </>
        }
      />

      <Tabs
        items={[
          { key: "fleet", label: t("page.ship.tab_fleet", "Fleet") },
          { key: "certs", label: t("page.ship.tab_certs", "Certificates overview") },
        ]}
        value={tab}
        onChange={(k) => setTab(k as "fleet" | "certs")}
        variant="line"

      />

      {tab === "certs" ? (
        <CertOverview
          onOpenVessel={(id) => {
            setTab("fleet");
            openVessel(id);
          }}
        />
      ) : (
        <>
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
          <DataGrid<FleetRow>
            columns={fleetColumns}
            data={fleet?.vessels || []}
            rowKey={(r) => String(r.vessel_id)}
            storageKey="ship_fleet"
            emptyText={t("common.empty", "No records")}
            showFooter={false}
            onRowClick={(r) => openVessel(r.vessel_id)}
          />
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
              <VesselCertificates certs={detail.certificates || []} onChanged={refreshDetail} />
              <h3>{t("page.ship.wos", "Work orders")}</h3>
              <ul className="compact-list">
                {detail.work_orders.map((w: any) => (
                  <li key={w.id} style={{ cursor: "pointer" }} onClick={() => selectWo(w)}>
                    <span className={`pill ${w.priority}`}>{w.priority}</span> {w.wo_no} {w.title} ({w.status})
                  </li>
                ))}
              </ul>
              {selWo ? (
                <div className="desk-section" style={{ margin: "0.5rem 0" }}>
                  <div className="desk-toolbar" style={{ margin: 0 }}>
                    <h3 style={{ margin: 0, fontSize: "0.95rem" }}>
                      {selWo.wo_no} · {selWo.status}
                    </h3>
                    {selWo.status === "open" ? (
                      <button className="btn btn-sm" type="button" disabled={busy} onClick={() => woTransition("in_progress")}>
                        {t("page.ship.wo_start", "Start work")}
                      </button>
                    ) : null}
                    {selWo.status === "in_progress" || selWo.status === "open" ? (
                      <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => woTransition("done")}>
                        {t("page.ship.wo_done", "Mark done")}
                      </button>
                    ) : null}
                  </div>
                  {woWarnings.length ? (
                    <div style={{ marginTop: "0.5rem" }}>
                      {woWarnings.map((w, i) => (
                        <p key={i} style={{ color: "var(--warn)", fontWeight: 600, margin: "0.25rem 0" }}>
                          {w}
                        </p>
                      ))}
                    </div>
                  ) : null}
                  <h3 style={{ fontSize: "0.95rem" }}>{t("page.ship.spares", "Spares")}</h3>
                  {woSpares.length ? (
                    <DataGrid
                      columns={spareColumns}
                      data={woSpares}
                      rowKey={(r: any, i: number) => String(r.id ?? i)}
                      storageKey="ship_wo_spares"
                      emptyText={t("common.empty", "No records")}
                      showFooter={false}
                    />
                  ) : (
                    <p className="muted" style={{ margin: "0.25rem 0" }}>{t("page.ship.no_spares", "No spare parts logged")}</p>
                  )}
                  <div className="form-grid" style={{ marginTop: "0.5rem" }}>
                    <label>
                      {t("page.ship.part", "Spare parts")}
                      <select value={woPart} onChange={(e) => setWoPart(e.target.value)}>
                        <option value="">{t("common.select", "Select…")}</option>
                        {(detail.spares || []).map((s: any) => (
                          <option key={s.id} value={s.id}>
                            {s.part_no} · {s.description || ""} ({t("page.ship.on_hand", "On hand")} {s.qty_on_hand})
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      {t("page.ship.spare_qty", "Qty")}
                      <input type="number" step="any" min="0" value={woQty} onChange={(e) => setWoQty(e.target.value)} />
                    </label>
                    <div style={{ display: "flex", alignItems: "end" }}>
                      <button className="btn btn-sm" type="button" disabled={busy} onClick={addWoSpare}>
                        {t("page.ship.add_spare", "Log consumption")}
                      </button>
                    </div>
                  </div>
                </div>
              ) : null}
              <h3>{t("page.ship.crew", "Crew")}</h3>
              <ul className="compact-list">
                {detail.crew.map((c: any) => (
                  <li key={c.id}>
                    {c.rank}: {c.full_name}{" "}
                    <button
                      className="btn btn-ghost btn-sm"
                      type="button"
                      onClick={() => {
                        setEditingCrew({ id: c.id, full_name: c.full_name });
                        setCertRows([]);
                      }}
                    >
                      {t("page.ship.edit_certs", "Certificates")}
                    </button>
                  </li>
                ))}
              </ul>
              <div className="desk-section" style={{ margin: "0.5rem 0" }}>
                <h3 style={{ marginTop: 0, fontSize: "0.95rem" }}>
                  {editingCrew
                    ? t("page.ship.edit_crew_certs", "Edit certificates · {name}", { name: editingCrew.full_name })
                    : t("page.ship.new_crew", "Add crew")}
                </h3>
                {!editingCrew ? (
                  <div className="form-grid">
                    <label>
                      {t("page.ship.crew_name", "Crew")}
                      <input value={crewName} onChange={(e) => setCrewName(e.target.value)} />
                    </label>
                    <label>
                      {t("page.ship.crew_rank", "Rank")}
                      <input value={crewRank} onChange={(e) => setCrewRank(e.target.value)} placeholder="C/O" />
                    </label>
                  </div>
                ) : null}
                {certRows.map((r, i) => (
                  <div key={i} className="form-grid" style={{ marginTop: "0.5rem" }}>
                    <label>
                      {t("page.ship.cert_code", "Cert")}
                      <input value={r.code} onChange={(e) => setCert(i, "code", e.target.value)} placeholder="STCW-II/1" />
                    </label>
                    <label>
                      {t("page.ship.cert_expires", "Expires")}
                      <input type="date" value={r.expires_on} onChange={(e) => setCert(i, "expires_on", e.target.value)} />
                    </label>
                    <div style={{ display: "flex", alignItems: "end" }}>
                      <button className="btn btn-danger btn-sm" type="button" onClick={() => setCertRows((prev) => prev.filter((_, x) => x !== i))}>
                        {t("common.delete", "Delete")}
                      </button>
                    </div>
                  </div>
                ))}
                <div className="desk-toolbar" style={{ marginTop: "0.5rem" }}>
                  <button className="btn btn-sm" type="button" onClick={() => setCertRows((prev) => [...prev, { code: "", expires_on: "" }])}>
                    {t("page.ship.add_cert", "Add certificate")}
                  </button>
                  <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={saveCrew}>
                    {editingCrew ? t("common.save", "Save") : t("common.create", "Create")}
                  </button>
                  {editingCrew ? (
                    <button
                      className="btn btn-ghost btn-sm"
                      type="button"
                      onClick={() => {
                        setEditingCrew(null);
                        setCertRows([]);
                      }}
                    >
                      {t("common.cancel", "Cancel")}
                    </button>
                  ) : null}
                </div>
              </div>
            </>
          ) : (
            <p className="muted">{t("page.ship.select_hint", "Click a vessel to open technical card.")}</p>
          )}
        </div>
      </div>

      <div className="panel">
        <h2>{t("page.ship.cert_alerts", "Crew certificate alerts (60 days)")}</h2>
        {certAlerts.length ? (
          <DataGrid<CertAlert>
            columns={certAlertColumns}
            data={certAlerts}
            rowKey={(r, i) => `${r.crew_id}-${r.code}-${i}`}
            storageKey="ship_cert_alerts"
            emptyText={t("common.empty", "No records")}
            showFooter={false}
          />
        ) : (
          <p className="muted">{t("page.ship.no_cert_alerts", "No crew certificates expiring within 60 days")}</p>
        )}
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
        </>
      )}
    </AppShell>
  );
}
