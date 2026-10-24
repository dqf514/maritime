"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, type MouseEvent as ReactMouseEvent } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { PageGuide } from "@/components/PageGuide";
import { Tabs } from "@/components/Tabs";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { DeskSection } from "@/components/DeskSection";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StateView } from "@/components/StateView";
import { CertOverview, VesselCertificates } from "@/components/ShipCertificates";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { msgOf } from "@/lib/errors";
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
  const [woDeletePending, setWoDeletePending] = useState<(() => void) | null>(null);
  const [woSpares, setWoSpares] = useState<any[]>([]);
  /** 备件清单加载失败（≠ 没有备件） */
  const [woSparesErr, setWoSparesErr] = useState<string | null>(null);
  const [woPart, setWoPart] = useState("");
  const [woQty, setWoQty] = useState("1");
  const [woWarnings, setWoWarnings] = useState<string[]>([]);

  const [crewName, setCrewName] = useState("");
  const [crewRank, setCrewRank] = useState("");
  const [certRows, setCertRows] = useState<CertRow[]>([]);
  const [editingCrew, setEditingCrew] = useState<{ id: string; full_name: string } | null>(null);
  const [certAlerts, setCertAlerts] = useState<CertAlert[]>([]);
  /** 证书告警加载失败（≠ 没有证书告警） */
  const [certAlertErr, setCertAlertErr] = useState<string | null>(null);
  // 主列表（船队）失败必须走错误态，不能静默变成空列表（P1-4）。
  const [fleetErr, setFleetErr] = useState("");
  const [fleetLoading, setFleetLoading] = useState(true);
  // 参考数据（接口适配器 / 同步日志 / 证书告警）失败不阻断整页，但要可见（P1-4）。
  const [refWarn, setRefWarn] = useState("");

  // 三栏工作台：船队列表 | 船舶技术卡 | 证书告警/接口（分隔条可拖拽，localStorage 记忆）
  const [leftW, setLeftW] = useState(340);
  const [rightW, setRightW] = useState(320);
  useEffect(() => {
    const l = Number(localStorage.getItem("ship_split_left"));
    const r = Number(localStorage.getItem("ship_split_right"));
    if (l >= 260 && l <= 560) setLeftW(l);
    if (r >= 260 && r <= 520) setRightW(r);
  }, []);
  useEffect(() => {
    localStorage.setItem("ship_split_left", String(leftW));
  }, [leftW]);
  useEffect(() => {
    localStorage.setItem("ship_split_right", String(rightW));
  }, [rightW]);
  function startSplitDrag(side: "left" | "right", e: ReactMouseEvent) {
    e.preventDefault();
    const startX = e.clientX;
    const startL = leftW;
    const startR = rightW;
    const onMove = (ev: MouseEvent) => {
      const dx = ev.clientX - startX;
      if (side === "left") setLeftW(Math.min(560, Math.max(260, startL + dx)));
      else setRightW(Math.min(520, Math.max(260, startR - dx)));
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }

  useEffect(() => {
    apiGet("/api/v1/ship/fleet")
      .then((f) => {
        setFleet(f);
        setFleetErr("");
      })
      .catch((e) => {
        setFleet(null);
        setFleetErr(
          msgOf(e, t("page.ship.module_required", "Ship management module required")),
        );
      })
      .finally(() => setFleetLoading(false));
    // 参考数据失败：不全页报错，但在右栏显式提示，避免「看起来就是空的」。
    const refFail = () =>
      setRefWarn(t("page.ship.ref_load_fail", "Some reference data failed to load — this panel may be incomplete."));
    apiGet("/api/v1/ship/integrations/adapters").then(setAdapters).catch(refFail);
    apiGet("/api/v1/ship/integrations/sync-logs").then(setLogs).catch(refFail);
    apiGet("/api/v1/ship/crew/cert-alerts?days=60")
      .then((rows) => setCertAlerts(Array.isArray(rows) ? rows : []))
      .catch(refFail);
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
    try {
      const rows = await apiGet("/api/v1/ship/crew/cert-alerts?days=60");
      setCertAlerts(Array.isArray(rows) ? rows : []);
      setCertAlertErr(null);
    } catch (ex) {
      // P1-4：取数失败 ≠ 「没有证书告警」——必须让用户看见错误。
      setCertAlerts([]);
      setCertAlertErr(msgOf(ex, t("page.ship.cert_alerts_fail", "Could not load crew certificate alerts.")));
    }
  }

  async function selectWo(w: any) {
    setSelWo(w);
    setWoWarnings([]);
    setWoPart("");
    try {
      const rows = await apiGet(`/api/v1/ship/work-orders/${w.id}/spares`);
      setWoSpares(Array.isArray(rows) ? rows : []);
      setWoSparesErr(null);
    } catch (ex) {
      setWoSpares([]);
      setWoSparesErr(msgOf(ex, t("page.ship.spares_fail", "Could not load spare parts.")));
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

  async function deleteWo(id: string) {
    setBusy(true);
    try {
      await apiDelete(`/api/v1/ship/work-orders/${id}`);
      toast.success(t("page.ship.wo_deleted", "Work order deleted"));
      setSelWo(null);
      setWoSpares([]);
      await refreshDetail();
    } catch (e: any) {
      toast.error(e?.message || t("common.failed", "Failed"));
    } finally {
      setBusy(false);
    }
  }

  async function addWoSpare() {
    if (!selWo || !woPart || !(Number(woQty) > 0)) {
      // 校验失败不是成功 —— 必须报错并中止提交（P1-26）。
      toast.error(t("page.ship.spare_need", "Select a spare part and enter quantity"));
      return;
    }
    setBusy(true);
    try {
      const res = await apiPost(`/api/v1/ship/work-orders/${selWo.id}/spares`, { part_id: woPart, qty: Number(woQty) });
      setWoWarnings(Array.isArray(res?.warnings) ? res.warnings.map((w: unknown) => String(w)) : []);
      toast.success(t("page.ship.spare_ok", "Spare consumption logged"));
      try {
        const rows = await apiGet(`/api/v1/ship/work-orders/${selWo.id}/spares`);
        setWoSpares(Array.isArray(rows) ? rows : []);
        setWoSparesErr(null);
      } catch (ex) {
        setWoSpares([]);
        setWoSparesErr(msgOf(ex, t("page.ship.spares_fail", "Could not load spare parts.")));
      }
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
          // 校验失败不是成功 —— 必须报错并中止提交（P1-26）。
          toast.error(t("page.ship.crew_need", "Enter crew name and rank"));
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
      // 校验失败不是成功 —— 必须报错并中止提交（P1-26）。
      toast.error(t("page.ship.no_vessel", "No vessel in fleet"));
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
        // 不定宽：与其余列均分栏宽，窄栏下不出现横向滚动条
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
      // 窄列表（默认 340px 栏）：仅数字列定宽，名称/状态均分剩余 → 无横向滚动条。
      // Mode / Drydock / Last-modified 明细见中栏技术卡与船舶档案页。
      {
        key: "technical_status",
        title: t("common.status", "Status"),
        width: 64,
        value: (r) => r.technical_status,
      },
      {
        key: "open_work_orders",
        title: t("page.ship.col_wo", "WO"),
        width: 34,
        value: (r) => r.open_work_orders,
      },
      {
        key: "open_defects",
        title: t("page.ship.col_def", "Def"),
        width: 34,
        value: (r) => r.open_defects,
      },
      {
        key: "expiring_certs",
        title: t("page.ship.col_cert", "Cert"),
        width: 36,
        value: (r) => r.expiring_certs,
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
      // 右栏窄网格（默认 320px 栏）：仅天数列定宽，其余均分 → 无横向滚动条
      {
        key: "crew_name",
        title: t("page.ship.crew_name", "Crew"),
        value: (r) => r.crew_name,
      },
      {
        key: "code",
        title: t("page.ship.cert_code", "Cert"),
        value: (r) => r.code,
      },
      {
        key: "expires_on",
        title: t("page.ship.cert_expires", "Expires"),
        value: (r) => r.expires_on,
      },
      {
        key: "days_left",
        title: t("page.ship.days_left", "Days left"),
        width: 48,
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

      {/* 三栏工作台：船队列表 | 技术卡 | 证书告警/接口；分隔条可拖拽改宽，右栏吸顶独立滚动 */}
      <div
        className="desk-split voy3"
        style={{ gridTemplateColumns: `${leftW}px 6px minmax(0, 1fr) 6px ${rightW}px` }}
      >
        <div className="panel desk-list">
          <h2>{t("page.ship.fleet", "Technical fleet")}</h2>
          <StateView
            loading={fleetLoading}
            error={fleetErr || undefined}
            empty={!fleetErr && !(fleet?.vessels || []).length}
            emptyText={t("common.empty", "No records")}
            onRetry={() => {
              setFleetLoading(true);
              setFleetErr("");
              apiGet("/api/v1/ship/fleet")
                .then((f) => setFleet(f))
                .catch((e) => setFleetErr(msgOf(e, t("page.ship.module_required", "Ship management module required"))))
                .finally(() => setFleetLoading(false));
            }}
          >
            <DataGrid<FleetRow>
              columns={fleetColumns}
              data={fleet?.vessels || []}
              rowKey={(r) => String(r.vessel_id)}
              storageKey="ship_fleet"
              emptyText={t("common.empty", "No records")}
              showFooter={false}
              onRowClick={(r) => openVessel(r.vessel_id)}
            />
          </StateView>
        </div>

        <div
          className="splitter"
          role="separator"
          aria-orientation="vertical"
          aria-label={t("page.voyages.split_hint", "Drag to resize")}
          onMouseDown={(e) => startSplitDrag("left", e)}
        />

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
                    {selWo.status === "done" || selWo.status === "closed" ? (
                      <button
                        className="btn btn-sm"
                        type="button"
                        disabled
                        title={t("page.ship.wo_delete_locked", "Completed/closed work orders cannot be deleted")}
                      >
                        {t("page.ship.wo_delete", "Delete")}
                      </button>
                    ) : (
                      <button
                        className="btn btn-sm"
                        type="button"
                        disabled={busy}
                        onClick={() => setWoDeletePending(() => () => deleteWo(selWo.id))}
                      >
                        {t("page.ship.wo_delete", "Delete")}
                      </button>
                    )}
                  </div>
                  {woWarnings.length ? (
                    <div style={{ marginTop: "0.5rem" }}>
                      {woWarnings.map((w, i) => (
                        <p key={i} style={{ color: "var(--warn-text)", fontWeight: 600, margin: "0.25rem 0" }}>
                          {w}
                        </p>
                      ))}
                    </div>
                  ) : null}
                  <h3 style={{ fontSize: "0.95rem" }}>{t("page.ship.spares", "Spares")}</h3>
                  {woSparesErr ? <p className="flash-err">{woSparesErr}</p> : null}
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

        <div
          className="splitter"
          role="separator"
          aria-orientation="vertical"
          aria-label={t("page.voyages.split_hint", "Drag to resize")}
          onMouseDown={(e) => startSplitDrag("right", e)}
        />

        {/* 右栏 = 监控/上下文区（证书告警 + 外部接口）：原底部整幅面板上移，吸顶独立滚动，⤢ 可局部放大 */}
        <div className="panel desk-side">
          {refWarn ? <p className="flash-err">{refWarn}</p> : null}
          <DeskSection title={t("page.ship.cert_alerts", "Crew certificate alerts (60 days)")}>
            {certAlertErr ? <p className="flash-err">{certAlertErr}</p> : null}
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
          </DeskSection>

          <DeskSection title={t("page.ship.adapters", "External ship management adapters")}>
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
              {/* 截断必须对用户可见 —— 说明只展示了最近 8 条（P1-28）。 */}
              {logs.length > 8 ? (
                <li className="muted">
                  {t("page.ship.sync_more", "Showing the 8 most recent of {n} entries.", { n: logs.length })}
                </li>
              ) : null}
            </ul>
          </DeskSection>
        </div>
      </div>
        </>
      )}
      <ConfirmDialog
        open={Boolean(woDeletePending)}
        title={t("page.ship.wo_delete", "Delete")}
        message={t("common.confirm_delete_named", 'Delete "{name}"?', { name: selWo?.wo_no ?? "" })}
        danger
        onConfirm={() => {
          const fn = woDeletePending;
          setWoDeletePending(null);
          fn?.();
        }}
        onCancel={() => setWoDeletePending(null)}
      />
    </AppShell>
  );
}
