"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageGuide } from "@/components/PageGuide";
import { CertOverview, VesselCertificates } from "@/components/ShipCertificates";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

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
  const [tab, setTab] = useState<"fleet" | "certs">("fleet");
  const [fleet, setFleet] = useState<Fleet | null>(null);
  const [adapters, setAdapters] = useState<Adapter[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [logs, setLogs] = useState<any[]>([]);
  const [msg, setMsg] = useState("");
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
    apiGet("/api/v1/ship/fleet").then(setFleet).catch(() => setMsg(t("page.ship.module_required", "Ship management module required")));
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
      setMsg(e?.message || t("common.failed", "Failed"));
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
      setMsg(t("page.ship.wo_moved", "工单状态 → {target}", { target }));
      setSelWo((prev: any) => (prev ? { ...prev, status: res?.status || target } : prev));
      await refreshDetail();
    } catch (e: any) {
      setMsg(e?.message || t("common.failed", "Failed"));
    } finally {
      setBusy(false);
    }
  }

  async function addWoSpare() {
    if (!selWo || !woPart || !(Number(woQty) > 0)) {
      setMsg(t("page.ship.spare_need", "请选择备件并填写数量"));
      return;
    }
    setBusy(true);
    try {
      const res = await apiPost(`/api/v1/ship/work-orders/${selWo.id}/spares`, { part_id: woPart, qty: Number(woQty) });
      setWoWarnings(Array.isArray(res?.warnings) ? res.warnings.map((w: unknown) => String(w)) : []);
      setMsg(t("page.ship.spare_ok", "备件消耗已登记"));
      const rows = await apiGet(`/api/v1/ship/work-orders/${selWo.id}/spares`).catch(() => []);
      setWoSpares(Array.isArray(rows) ? rows : []);
    } catch (e: any) {
      setMsg(e?.message || t("common.failed", "Failed"));
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
        setMsg(t("page.ship.crew_certs_ok", "船员证书已更新"));
      } else {
        if (!crewName.trim() || !crewRank.trim()) {
          setMsg(t("page.ship.crew_need", "请填写船员姓名与职务"));
          setBusy(false);
          return;
        }
        await apiPost("/api/v1/ship/crew", {
          vessel_id: selected,
          full_name: crewName.trim(),
          rank: crewRank.trim(),
          certificates,
        });
        setMsg(t("page.ship.crew_ok", "船员已登记"));
      }
      setCrewName("");
      setCrewRank("");
      setCertRows([]);
      setEditingCrew(null);
      await refreshDetail();
      await refreshCertAlerts();
    } catch (e: any) {
      setMsg(e?.message || t("common.failed", "Failed"));
    } finally {
      setBusy(false);
    }
  }

  async function inboundDemo() {
    if (!fleet?.vessels?.[0]) {
      setMsg(t("page.ship.no_vessel", "No vessel in fleet"));
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
      setMsg(t("page.ship.inbound_ok", "Inbound PMS sync accepted — refresh fleet."));
      setFleet(await apiGet("/api/v1/ship/fleet"));
      setLogs(await apiGet("/api/v1/ship/integrations/sync-logs"));
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
          <PageGuide pageKey="ship" />
          <Link href="/dashboards/technical" className="btn btn-primary">
            {t("page.ship.wall", "Technical live wall")}
          </Link>
          {DEMO_TOOLS ? (
            <button type="button" className="btn btn-ghost" onClick={inboundDemo}>
              {t("page.ship.simulate", "Simulate PMS inbound")}
            </button>
          ) : null}
        </div>
      </div>
      {msg ? <p className="flash">{msg}</p> : null}

      <div className="page-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "fleet"}
          className={`page-tab ${tab === "fleet" ? "active" : ""}`}
          onClick={() => setTab("fleet")}
        >
          {t("page.ship.tab_fleet", "舰队")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "certs"}
          className={`page-tab ${tab === "certs" ? "active" : ""}`}
          onClick={() => setTab("certs")}
        >
          {t("page.ship.tab_certs", "证书总览")}
        </button>
      </div>

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
                        {t("page.ship.wo_start", "开工")}
                      </button>
                    ) : null}
                    {selWo.status === "in_progress" || selWo.status === "open" ? (
                      <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => woTransition("done")}>
                        {t("page.ship.wo_done", "转 done")}
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
                  <h3 style={{ fontSize: "0.95rem" }}>{t("page.ship.spares", "备件消耗 Spares")}</h3>
                  {woSpares.length ? (
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>{t("page.ship.part_no", "Part no")}</th>
                          <th>{t("page.ship.part_desc", "Description")}</th>
                          <th>{t("page.ship.spare_qty", "Qty")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {woSpares.map((s: any) => (
                          <tr key={s.id}>
                            <td>{s.part_no || s.part_id?.slice(0, 8)}</td>
                            <td>{s.description || "—"}</td>
                            <td>{s.qty}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <p className="muted" style={{ margin: "0.25rem 0" }}>{t("page.ship.no_spares", "暂无备件登记")}</p>
                  )}
                  <div className="form-grid" style={{ marginTop: "0.5rem" }}>
                    <label>
                      {t("page.ship.part", "备件")}
                      <select value={woPart} onChange={(e) => setWoPart(e.target.value)}>
                        <option value="">{t("common.select", "Select…")}</option>
                        {(detail.spares || []).map((s: any) => (
                          <option key={s.id} value={s.id}>
                            {s.part_no} · {s.description || ""} ({t("page.ship.on_hand", "在库")} {s.qty_on_hand})
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
                        {t("page.ship.add_spare", "登记消耗")}
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
                      {t("page.ship.edit_certs", "证书")}
                    </button>
                  </li>
                ))}
              </ul>
              <div className="desk-section" style={{ margin: "0.5rem 0" }}>
                <h3 style={{ marginTop: 0, fontSize: "0.95rem" }}>
                  {editingCrew
                    ? t("page.ship.edit_crew_certs", "编辑证书 · {name}", { name: editingCrew.full_name })
                    : t("page.ship.new_crew", "登记船员")}
                </h3>
                {!editingCrew ? (
                  <div className="form-grid">
                    <label>
                      {t("page.ship.crew_name", "姓名")}
                      <input value={crewName} onChange={(e) => setCrewName(e.target.value)} />
                    </label>
                    <label>
                      {t("page.ship.crew_rank", "职务")}
                      <input value={crewRank} onChange={(e) => setCrewRank(e.target.value)} placeholder="C/O" />
                    </label>
                  </div>
                ) : null}
                {certRows.map((r, i) => (
                  <div key={i} className="form-grid" style={{ marginTop: "0.5rem" }}>
                    <label>
                      {t("page.ship.cert_code", "证书代码")}
                      <input value={r.code} onChange={(e) => setCert(i, "code", e.target.value)} placeholder="STCW-II/1" />
                    </label>
                    <label>
                      {t("page.ship.cert_expires", "到期日")}
                      <input type="date" value={r.expires_on} onChange={(e) => setCert(i, "expires_on", e.target.value)} />
                    </label>
                    <div style={{ display: "flex", alignItems: "end" }}>
                      <button className="btn btn-danger btn-sm" type="button" onClick={() => setCertRows((prev) => prev.filter((_, x) => x !== i))}>
                        {t("common.delete", "删除")}
                      </button>
                    </div>
                  </div>
                ))}
                <div className="desk-toolbar" style={{ marginTop: "0.5rem" }}>
                  <button className="btn btn-sm" type="button" onClick={() => setCertRows((prev) => [...prev, { code: "", expires_on: "" }])}>
                    {t("page.ship.add_cert", "添加证书")}
                  </button>
                  <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={saveCrew}>
                    {editingCrew ? t("common.save", "保存") : t("common.create", "Create")}
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
                      {t("common.cancel", "取消")}
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
        <h2>{t("page.ship.cert_alerts", "船员证书预警（60 天）")}</h2>
        {certAlerts.length ? (
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("page.ship.crew_name", "船员")}</th>
                <th>{t("page.ship.cert_code", "证书")}</th>
                <th>{t("page.ship.cert_expires", "到期日")}</th>
                <th>{t("page.ship.days_left", "剩余天数")}</th>
              </tr>
            </thead>
            <tbody>
              {certAlerts.map((a, i) => (
                <tr key={`${a.crew_id}-${a.code}-${i}`}>
                  <td>{a.crew_name}</td>
                  <td>{a.code}</td>
                  <td>{a.expires_on}</td>
                  <td>
                    {a.days_left < 0 ? (
                      <span style={{ color: "var(--danger)", fontWeight: 600 }}>{t("page.ship.expired", "已过期")} ({a.days_left})</span>
                    ) : (
                      a.days_left
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">{t("page.ship.no_cert_alerts", "60 天内无到期船员证书")}</p>
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
