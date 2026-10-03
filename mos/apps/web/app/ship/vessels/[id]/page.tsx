"use client";

// U-VESSEL 船舶管理卡片：完整明细页（IMOS vessel card 对齐）。
// Tabs: Summary · DWT/Draft · Contacts · Routes · Tugs · Bunker Tanks ·
// L/D Performance · TCE Targets · Vetting · Loadline Zones · Certificates · PMS.

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { VesselCertificates } from "@/components/ShipCertificates";
import { VesselCrudGrid } from "@/components/ship/VesselCrudGrid";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";
import { apiGet, apiPatch } from "@/lib/api";

type Tab =
  | "summary"
  | "spec"
  | "contacts"
  | "routes"
  | "tugs"
  | "tanks"
  | "performance"
  | "tce"
  | "vetting"
  | "loadline"
  | "certs"
  | "pms";

const TABS: { key: Tab; labelKey: string; label: string }[] = [
  { key: "summary", labelKey: "page.vessel.tab_summary", label: "Summary" },
  { key: "spec", labelKey: "page.vessel.tab_spec", label: "DWT / Draft" },
  { key: "contacts", labelKey: "page.vessel.tab_contacts", label: "Contacts" },
  { key: "routes", labelKey: "page.vessel.tab_routes", label: "Routes" },
  { key: "tugs", labelKey: "page.vessel.tab_tugs", label: "Tugs" },
  { key: "tanks", labelKey: "page.vessel.tab_tanks", label: "Bunker Tanks" },
  { key: "performance", labelKey: "page.vessel.tab_performance", label: "L/D Performance" },
  { key: "tce", labelKey: "page.vessel.tab_tce", label: "TCE Targets" },
  { key: "vetting", labelKey: "page.vessel.tab_vetting", label: "Vetting" },
  { key: "loadline", labelKey: "page.vessel.tab_loadline", label: "Loadline Zones" },
  { key: "certs", labelKey: "page.vessel.tab_certs", label: "Certificates" },
  { key: "pms", labelKey: "page.vessel.tab_pms", label: "PMS / Work Orders" },
];

type ScalePoint = { draft_m: number | string; deadweight_mt: number | string };

const SPEC_NUM_FIELDS: { key: string; group: "dwt_draft" | "consumption_detail" | "capacity"; label: string; step?: string }[] = [
  { key: "summer_dwt", group: "dwt_draft", label: "Summer DWT (MT)" },
  { key: "tropical_dwt", group: "dwt_draft", label: "Tropical DWT (MT)" },
  { key: "winter_dwt", group: "dwt_draft", label: "Winter DWT (MT)" },
  { key: "summer_draft", group: "dwt_draft", label: "Summer draft (m)", step: "0.01" },
  { key: "tropical_draft", group: "dwt_draft", label: "Tropical draft (m)", step: "0.01" },
  { key: "winter_draft", group: "dwt_draft", label: "Winter draft (m)", step: "0.01" },
  { key: "lightship", group: "dwt_draft", label: "Lightship (MT)" },
  { key: "sea_speed_25", group: "consumption_detail", label: "Sea speed 25% (kn)", step: "0.01" },
  { key: "sea_speed_75", group: "consumption_detail", label: "Sea speed 75% (kn)", step: "0.01" },
  { key: "sea_speed_100", group: "consumption_detail", label: "Sea speed 100% (kn)", step: "0.01" },
  { key: "port_working", group: "consumption_detail", label: "Port working (MT/day)" },
  { key: "port_idle", group: "consumption_detail", label: "Port idle (MT/day)" },
  { key: "port_maneuvering", group: "consumption_detail", label: "Maneuvering (MT/day)" },
  { key: "ifo_mdo_ratio", group: "consumption_detail", label: "IFO/MDO ratio", step: "0.001" },
  { key: "max_lift_qty", group: "capacity", label: "Max lift qty (MT)" },
  { key: "stowage_factor", group: "capacity", label: "Stowage factor (m3/MT)", step: "0.001" },
  { key: "design_speed", group: "capacity", label: "Design speed (kn)", step: "0.01" },
  { key: "tank_capacity_total", group: "capacity", label: "Tank capacity total (MT)" },
];

const SPEC_TEXT_FIELDS: { key: string; label: string }[] = [
  { key: "hull_type", label: "Hull type" },
  { key: "build_yard", label: "Build yard" },
  { key: "flag_state", label: "Flag state" },
  { key: "ism_manager", label: "ISM manager" },
  { key: "isps_manager", label: "ISPS manager" },
];

function fmt(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  return String(v);
}

export default function VesselDetailPage() {
  const { t } = useI18n();
  const toast = useToast();
  const params = useParams<{ id: string }>();
  const vesselId = params.id;

  const [tab, setTab] = useState<Tab>("summary");
  const [summary, setSummary] = useState<any>(null);
  const [ship, setShip] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  // spec form state (flat) + deadweight scale editor
  const [specForm, setSpecForm] = useState<Record<string, string>>({});
  const [specInit, setSpecInit] = useState<Record<string, string>>({});
  const [scale, setScale] = useState<ScalePoint[]>([]);
  const [buildYear, setBuildYear] = useState("");

  // max lift calculator
  const [lift, setLift] = useState<any>(null);
  const [liftInput, setLiftInput] = useState({ cargo_type: "", draft: "", bunkers_mt: "0", stores_mt: "0", fresh_water_mt: "0", hold_capacity_cbm: "" });

  const loadSummary = useCallback(async () => {
    const data = await apiGet(`/api/v1/vessels/${vesselId}/summary`);
    setSummary(data);
    const spec = data?.spec ?? {};
    const flat: Record<string, string> = {};
    for (const f of SPEC_NUM_FIELDS) {
      const v = spec[f.group]?.[f.key];
      flat[f.key] = v === null || v === undefined ? "" : String(v);
    }
    for (const f of SPEC_TEXT_FIELDS) {
      const v = spec.vessel_type_detail?.[f.key];
      flat[f.key] = v === null || v === undefined ? "" : String(v);
    }
    const by = spec.vessel_type_detail?.build_year;
    setBuildYear(by === null || by === undefined ? "" : String(by));
    setSpecForm(flat);
    setSpecInit(flat);
    setScale((spec.dwt_draft?.deadweight_scale ?? []).map((p: any) => ({ draft_m: p.draft_m ?? "", deadweight_mt: p.deadweight_mt ?? "" })));
  }, [vesselId]);

  const loadShip = useCallback(async () => {
    try {
      setShip(await apiGet(`/api/v1/ship/vessels/${vesselId}`));
    } catch {
      setShip(null);
    }
  }, [vesselId]);

  useEffect(() => {
    if (!vesselId) return;
    Promise.all([loadSummary().catch((e: any) => toast.error(e?.message || t("common.failed", "Failed"))), loadShip()]);
  }, [vesselId, loadSummary, loadShip, t, toast]);

  const vessel = summary?.vessel;
  const spec = summary?.spec;

  async function saveSpec() {
    setBusy(true);
    try {
      const payload: Record<string, unknown> = {};
      for (const f of SPEC_NUM_FIELDS) {
        if (specForm[f.key] !== specInit[f.key]) {
          payload[f.key] = specForm[f.key] === "" ? null : Number(specForm[f.key]);
        }
      }
      for (const f of SPEC_TEXT_FIELDS) {
        if (specForm[f.key] !== specInit[f.key]) {
          payload[f.key] = specForm[f.key] === "" ? null : specForm[f.key];
        }
      }
      if (buildYear !== specInit.build_year) {
        payload.build_year = buildYear === "" ? null : Number(buildYear);
      }
      const initScale = (summary?.spec?.dwt_draft?.deadweight_scale ?? []).map((p: any) => ({
        draft_m: p.draft_m ?? "",
        deadweight_mt: p.deadweight_mt ?? "",
      }));
      if (JSON.stringify(scale) !== JSON.stringify(initScale)) {
        payload.deadweight_scale = scale
          .filter((p) => String(p.draft_m) !== "" && String(p.deadweight_mt) !== "")
          .map((p) => ({ draft_m: Number(p.draft_m), deadweight_mt: Number(p.deadweight_mt) }));
      }
      if (Object.keys(payload).length === 0) {
        toast.success(t("common.saved", "Saved"));
        setBusy(false);
        return;
      }
      await apiPatch(`/api/v1/vessels/${vesselId}/dwt-draft`, payload);
      toast.success(t("common.saved", "Saved"));
      await loadSummary();
    } catch (e: any) {
      toast.error(e?.message || t("common.failed", "Failed"));
    } finally {
      setBusy(false);
    }
  }

  async function runMaxLift() {
    try {
      const q = new URLSearchParams();
      if (liftInput.cargo_type) q.set("cargo_type", liftInput.cargo_type);
      if (liftInput.draft) q.set("draft", liftInput.draft);
      if (liftInput.bunkers_mt) q.set("bunkers_mt", liftInput.bunkers_mt);
      if (liftInput.stores_mt) q.set("stores_mt", liftInput.stores_mt);
      if (liftInput.fresh_water_mt) q.set("fresh_water_mt", liftInput.fresh_water_mt);
      if (liftInput.hold_capacity_cbm) q.set("hold_capacity_cbm", liftInput.hold_capacity_cbm);
      setLift(await apiGet(`/api/v1/vessels/${vesselId}/max-lift?${q.toString()}`));
    } catch (e: any) {
      toast.error(e?.message || t("page.vessel.lift_fail", "Max lift calculation failed"));
    }
  }

  const vettingPill = useMemo(() => {
    const rows = summary?.vettings ?? [];
    return rows.length ? rows[0] : null;
  }, [summary]);

  return (
    <AppShell
      breadcrumbs={[
        { label: t("page.ship.title", "Ship management"), href: "/ship" },
        { label: vessel?.name || t("page.vessel.card", "Vessel card") },
      ]}
    >
      <PageHeader
        title={vessel?.name || t("page.vessel.card", "Vessel card")}
        subtitle={`${vessel?.imo ? `IMO ${vessel.imo}` : "—"} · ${fmt(vessel?.flag)} · ${fmt(vessel?.vessel_type)} · ${
          vessel?.dwt ? `${vessel.dwt} DWT` : "—"
        }`}
        actions={
          <>
            <Link href={`/masterdata/vessels`} className="btn btn-ghost">
              {t("page.vessel.back_master", "Master data")}
            </Link>
            <Link href="/ship" className="btn btn-primary">
              {t("page.ship.title", "Ship management")}
            </Link>
          </>
        }
      />

      <div className="page-tabs" role="tablist">
        {TABS.map((tb) => (
          <button
            key={tb.key}
            type="button"
            role="tab"
            aria-selected={tab === tb.key}
            className={`page-tab ${tab === tb.key ? "active" : ""}`}
            onClick={() => setTab(tb.key)}
          >
            {t(tb.labelKey, tb.label)}
          </button>
        ))}
      </div>

      {tab === "summary" ? (
        <>
          <div className="kpi-row">
            <div className="kpi-card">
              <span>{t("page.vessel.kpi_dwt", "Summer DWT")}</span>
              <strong>{fmt(spec?.dwt_draft?.summer_dwt ?? vessel?.dwt)}</strong>
            </div>
            <div className="kpi-card">
              <span>{t("page.vessel.kpi_draft", "Summer draft")}</span>
              <strong>{fmt(spec?.dwt_draft?.summer_draft)}</strong>
            </div>
            <div className="kpi-card">
              <span>{t("page.vessel.kpi_lift", "Max lift qty")}</span>
              <strong>{fmt(spec?.capacity?.max_lift_qty)}</strong>
            </div>
            <div className="kpi-card">
              <span>{t("page.vessel.kpi_speed", "Design speed")}</span>
              <strong>{fmt(spec?.capacity?.design_speed ?? vessel?.speed_knots)}</strong>
            </div>
          </div>
          <div className="kpi-row">
            <div className="kpi-card">
              <span>{t("page.vessel.kpi_contacts", "Contacts")}</span>
              <strong>{summary?.counts?.contacts ?? 0}</strong>
            </div>
            <div className="kpi-card">
              <span>{t("page.vessel.kpi_tce", "TCE targets")}</span>
              <strong>{summary?.counts?.tce_targets ?? 0}</strong>
            </div>
            <div className="kpi-card">
              <span>{t("page.vessel.kpi_vetting", "Vetting records")}</span>
              <strong>{summary?.counts?.vettings ?? 0}</strong>
            </div>
            <div className={`kpi-card ${vettingPill && vettingPill.result === "fail" ? "warn" : ""}`}>
              <span>{t("page.vessel.kpi_last_vetting", "Last vetting")}</span>
              <strong>{vettingPill ? `${fmt(vettingPill.vetting_type)} · ${fmt(vettingPill.result)}` : "—"}</strong>
            </div>
          </div>

          <div className="panel">
            <h2>{t("page.vessel.key_specs", "Key specifications")}</h2>
            <table className="data-table">
              <tbody>
                <tr>
                  <th>{t("page.vessel.build", "Built")}</th>
                  <td>
                    {fmt(spec?.vessel_type_detail?.build_year)} · {fmt(spec?.vessel_type_detail?.build_yard)}
                  </td>
                  <th>{t("page.vessel.hull", "Hull type")}</th>
                  <td>{fmt(spec?.vessel_type_detail?.hull_type)}</td>
                </tr>
                <tr>
                  <th>{t("page.vessel.flag_state", "Flag state")}</th>
                  <td>{fmt(spec?.vessel_type_detail?.flag_state)}</td>
                  <th>{t("page.vessel.ism", "ISM manager")}</th>
                  <td>{fmt(spec?.vessel_type_detail?.ism_manager)}</td>
                </tr>
                <tr>
                  <th>{t("page.vessel.lightship", "Lightship")}</th>
                  <td>{fmt(spec?.dwt_draft?.lightship)}</td>
                  <th>{t("page.vessel.stowage", "Stowage factor")}</th>
                  <td>{fmt(spec?.capacity?.stowage_factor)}</td>
                </tr>
                <tr>
                  <th>{t("page.vessel.consumption_sea", "Sea consumption")}</th>
                  <td>{fmt(vessel?.consumption_sea)} MT/day</td>
                  <th>{t("page.vessel.consumption_port", "Port consumption")}</th>
                  <td>{fmt(vessel?.consumption_port)} MT/day</td>
                </tr>
                <tr>
                  <th>{t("page.vessel.tank_total", "Tank capacity total")}</th>
                  <td>{fmt(spec?.capacity?.tank_capacity_total)}</td>
                  <th>{t("common.status", "Status")}</th>
                  <td>{fmt(vessel?.status)}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div className="panel">
            <h2>{t("page.vessel.routes_short", "Preferred routes")}</h2>
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("page.vessel.route_name", "Route")}</th>
                  <th>{t("page.vessel.route_from", "From")}</th>
                  <th>{t("page.vessel.route_to", "To")}</th>
                  <th>{t("page.vessel.route_speed", "Speed")}</th>
                  <th>{t("page.vessel.route_dist", "Distance (nm)")}</th>
                </tr>
              </thead>
              <tbody>
                {(summary?.routes ?? []).map((r: any) => (
                  <tr key={r.id}>
                    <td>{fmt(r.route_name)}</td>
                    <td>{fmt(r.from_area)}</td>
                    <td>{fmt(r.to_area)}</td>
                    <td>{fmt(r.typical_speed)}</td>
                    <td>{fmt(r.distance_nm)}</td>
                  </tr>
                ))}
                {!(summary?.routes ?? []).length ? (
                  <tr>
                    <td colSpan={5} className="muted">
                      {t("common.empty", "No records")}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      {tab === "spec" ? (
        <>
          <div className="panel">
            <h2>{t("page.vessel.tab_spec", "DWT / Draft")}</h2>
            <div className="form-grid">
              {SPEC_NUM_FIELDS.map((f) => (
                <label key={f.key}>
                  {t(`page.vessel.field_${f.key}`, f.label)}
                  <input
                    type="number"
                    step={f.step}
                    value={specForm[f.key] ?? ""}
                    onChange={(e) => setSpecForm({ ...specForm, [f.key]: e.target.value })}
                  />
                </label>
              ))}
              <label>
                {t("page.vessel.field_build_year", "Build year")}
                <input type="number" value={buildYear} onChange={(e) => setBuildYear(e.target.value)} />
              </label>
              {SPEC_TEXT_FIELDS.map((f) => (
                <label key={f.key}>
                  {t(`page.vessel.field_${f.key}`, f.label)}
                  <input value={specForm[f.key] ?? ""} onChange={(e) => setSpecForm({ ...specForm, [f.key]: e.target.value })} />
                </label>
              ))}
            </div>

            <h3 style={{ marginTop: "1rem" }}>{t("page.vessel.deadweight_scale", "Deadweight scale (draft → DWT)")}</h3>
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("page.vessel.scale_draft", "Draft (m)")}</th>
                  <th>{t("page.vessel.scale_dwt", "Deadweight (MT)")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {scale.map((p, i) => (
                  <tr key={i}>
                    <td>
                      <input
                        type="number"
                        step="0.01"
                        value={String(p.draft_m)}
                        onChange={(e) => setScale(scale.map((q, j) => (i === j ? { ...q, draft_m: e.target.value } : q)))}
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        value={String(p.deadweight_mt)}
                        onChange={(e) => setScale(scale.map((q, j) => (i === j ? { ...q, deadweight_mt: e.target.value } : q)))}
                      />
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <button
                        type="button"
                        className="btn btn-ghost"
                        style={{ color: "var(--danger)", fontSize: "0.75rem" }}
                        onClick={() => setScale(scale.filter((_, j) => j !== i))}
                      >
                        {t("common.delete", "Delete")}
                      </button>
                    </td>
                  </tr>
                ))}
                {!scale.length ? (
                  <tr>
                    <td colSpan={3} className="muted">
                      {t("common.empty", "No records")}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
            <div className="desk-toolbar" style={{ justifyContent: "flex-end" }}>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setScale([...scale, { draft_m: "", deadweight_mt: "" }])}>
                + {t("page.vessel.add_scale_point", "Add scale point")}
              </button>
              <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={saveSpec}>
                {busy ? t("common.saving", "Saving…") : t("common.save", "Save")}
              </button>
            </div>
          </div>

          <div className="panel">
            <h2>{t("page.vessel.max_lift_calc", "Max lift calculation")}</h2>
            <p className="muted" style={{ marginTop: 0 }}>
              {t("page.vessel.max_lift_hint", "Max cargo lift = min(available deadweight, draft limitation, hold volume, gear cap).")}
            </p>
            <div className="form-grid">
              <label>
                {t("page.vessel.cargo_type", "Cargo type")}
                <input
                  value={liftInput.cargo_type}
                  onChange={(e) => setLiftInput({ ...liftInput, cargo_type: e.target.value })}
                  placeholder={t("page.vessel.cargo_type_ph", "e.g. coal")}
                />
              </label>
              <label>
                {t("page.vessel.load_draft", "Load port draft (m)")}
                <input type="number" step="0.01" value={liftInput.draft} onChange={(e) => setLiftInput({ ...liftInput, draft: e.target.value })} />
              </label>
              <label>
                {t("page.vessel.bunkers", "Bunkers (MT)")}
                <input type="number" value={liftInput.bunkers_mt} onChange={(e) => setLiftInput({ ...liftInput, bunkers_mt: e.target.value })} />
              </label>
              <label>
                {t("page.vessel.stores", "Stores (MT)")}
                <input type="number" value={liftInput.stores_mt} onChange={(e) => setLiftInput({ ...liftInput, stores_mt: e.target.value })} />
              </label>
              <label>
                {t("page.vessel.freshwater", "Fresh water (MT)")}
                <input type="number" value={liftInput.fresh_water_mt} onChange={(e) => setLiftInput({ ...liftInput, fresh_water_mt: e.target.value })} />
              </label>
              <label>
                {t("page.vessel.hold_cap", "Hold capacity (m3)")}
                <input type="number" value={liftInput.hold_capacity_cbm} onChange={(e) => setLiftInput({ ...liftInput, hold_capacity_cbm: e.target.value })} />
              </label>
            </div>
            <div className="desk-toolbar" style={{ justifyContent: "flex-end" }}>
              <button type="button" className="btn btn-primary btn-sm" onClick={runMaxLift}>
                {t("page.vessel.calc", "Calculate")}
              </button>
            </div>
            {lift ? (
              <table className="data-table" style={{ marginTop: "0.75rem" }}>
                <tbody>
                  <tr>
                    <th>{t("page.vessel.res_avail_dwt", "Available deadweight")}</th>
                    <td>{fmt(lift.available_deadweight_mt)} MT</td>
                    <th>{t("page.vessel.res_draft_dwt", "Draft-limited DWT")}</th>
                    <td>{fmt(lift.draft_limited_deadweight_mt)} MT</td>
                  </tr>
                  <tr>
                    <th>{t("page.vessel.res_hold", "Hold volume limit")}</th>
                    <td>{fmt(lift.hold_volume_limit_mt)} MT</td>
                    <th>{t("page.vessel.res_gear", "Gear cap")}</th>
                    <td>{fmt(lift.gear_limit_mt)} MT</td>
                  </tr>
                  <tr>
                    <th>{t("page.vessel.res_max", "Max lift")}</th>
                    <td>
                      <strong>{fmt(lift.max_lift_mt)} MT</strong>
                    </td>
                    <th>{t("page.vessel.res_limiting", "Limiting factor")}</th>
                    <td>
                      <span className="pill warn">{fmt(lift.limiting_factor)}</span>
                    </td>
                  </tr>
                  {lift.warnings?.length ? (
                    <tr>
                      <th>{t("page.vessel.res_warnings", "Warnings")}</th>
                      <td colSpan={3}>{lift.warnings.join("; ")}</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            ) : null}
          </div>
        </>
      ) : null}

      {tab === "contacts" ? (
        <VesselCrudGrid
          vesselId={vesselId}
          path="contacts"
          title={t("page.vessel.tab_contacts", "Contacts")}
          addLabel={t("page.vessel.add_contact", "Add contact")}
          emptyText={t("page.vessel.no_contacts", "No vessel contacts yet")}
          columns={[
            { key: "contact_role", label: t("page.vessel.role", "Role") },
            { key: "name", label: t("common.name", "Name") },
            { key: "email", label: t("common.email", "Email") },
            { key: "phone", label: t("common.phone", "Phone") },
          ]}
          fields={[
            {
              key: "contact_role",
              label: t("page.vessel.role", "Role"),
              type: "select",
              required: true,
              options: [
                { value: "captain", label: "captain" },
                { value: "superintendent", label: "superintendent" },
                { value: "agent", label: "agent" },
                { value: "owner", label: "owner" },
              ],
            },
            { key: "name", label: t("common.name", "Name"), type: "text", required: true },
            { key: "email", label: t("common.email", "Email"), type: "text" },
            { key: "phone", label: t("common.phone", "Phone"), type: "text" },
          ]}
        />
      ) : null}

      {tab === "routes" ? (
        <VesselCrudGrid
          vesselId={vesselId}
          path="routes"
          title={t("page.vessel.tab_routes", "Routes")}
          addLabel={t("page.vessel.add_route", "Add route")}
          emptyText={t("page.vessel.no_routes", "No preferred routes yet")}
          columns={[
            { key: "route_name", label: t("page.vessel.route_name", "Route") },
            { key: "from_area", label: t("page.vessel.route_from", "From") },
            { key: "to_area", label: t("page.vessel.route_to", "To") },
            { key: "typical_speed", label: t("page.vessel.route_speed", "Speed (kn)") },
            { key: "distance_nm", label: t("page.vessel.route_dist", "Distance (nm)") },
            { key: "notes", label: t("common.notes", "Notes") },
          ]}
          fields={[
            { key: "route_name", label: t("page.vessel.route_name", "Route"), type: "text", required: true },
            { key: "from_area", label: t("page.vessel.route_from", "From area"), type: "text" },
            { key: "to_area", label: t("page.vessel.route_to", "To area"), type: "text" },
            { key: "typical_speed", label: t("page.vessel.route_speed", "Typical speed (kn)"), type: "number", step: "0.01" },
            { key: "distance_nm", label: t("page.vessel.route_dist", "Distance (nm)"), type: "number" },
            { key: "notes", label: t("common.notes", "Notes"), type: "text", span: true },
          ]}
        />
      ) : null}

      {tab === "tugs" ? (
        <VesselCrudGrid
          vesselId={vesselId}
          path="tugs"
          title={t("page.vessel.tab_tugs", "Tugs")}
          addLabel={t("page.vessel.add_tug", "Add tug")}
          emptyText={t("page.vessel.no_tugs", "No tug records yet")}
          columns={[
            { key: "tug_name", label: t("page.vessel.tug_name", "Tug") },
            { key: "power_hp", label: t("page.vessel.tug_power", "Power (HP)") },
            { key: "notes", label: t("common.notes", "Notes") },
          ]}
          fields={[
            { key: "tug_name", label: t("page.vessel.tug_name", "Tug name"), type: "text", required: true },
            { key: "power_hp", label: t("page.vessel.tug_power", "Power (HP)"), type: "number" },
            { key: "notes", label: t("common.notes", "Notes"), type: "text", span: true },
          ]}
        />
      ) : null}

      {tab === "tanks" ? (
        <VesselCrudGrid
          vesselId={vesselId}
          path="tanks"
          title={t("page.vessel.tab_tanks", "Bunker Tanks")}
          addLabel={t("page.vessel.add_tank", "Add tank")}
          emptyText={t("page.vessel.no_tanks", "No tanks yet")}
          columns={[
            { key: "tank_name", label: t("page.vessel.tank_name", "Tank") },
            { key: "tank_type", label: t("page.vessel.tank_type", "Type") },
            { key: "capacity_mt", label: t("page.vessel.tank_cap", "Capacity (MT)") },
            { key: "max_fill_pct", label: t("page.vessel.tank_fill", "Max fill (%)") },
            { key: "notes", label: t("common.notes", "Notes") },
          ]}
          fields={[
            { key: "tank_name", label: t("page.vessel.tank_name", "Tank name"), type: "text", required: true },
            {
              key: "tank_type",
              label: t("page.vessel.tank_type", "Type"),
              type: "select",
              required: true,
              options: [
                { value: "fuel", label: "fuel" },
                { value: "lube", label: "lube" },
                { value: "water", label: "water" },
                { value: "ballast", label: "ballast" },
              ],
            },
            { key: "capacity_mt", label: t("page.vessel.tank_cap", "Capacity (MT)"), type: "number" },
            { key: "max_fill_pct", label: t("page.vessel.tank_fill", "Max fill (%)"), type: "number", step: "0.01" },
            { key: "notes", label: t("common.notes", "Notes"), type: "text", span: true },
          ]}
        />
      ) : null}

      {tab === "performance" ? (
        <VesselCrudGrid
          vesselId={vesselId}
          path="performance"
          title={t("page.vessel.tab_performance", "L/D Performance")}
          addLabel={t("page.vessel.add_perf", "Add cargo profile")}
          emptyText={t("page.vessel.no_perf", "No cargo profiles yet")}
          columns={[
            { key: "cargo_type", label: t("page.vessel.cargo_type", "Cargo type") },
            { key: "load_rate_mt_hr", label: t("page.vessel.load_rate", "Load rate (MT/h)") },
            { key: "discharge_rate_mt_hr", label: t("page.vessel.disch_rate", "Discharge rate (MT/h)") },
            { key: "stowage_factor", label: t("page.vessel.stowage", "Stowage factor (m3/MT)") },
            { key: "notes", label: t("common.notes", "Notes") },
          ]}
          fields={[
            { key: "cargo_type", label: t("page.vessel.cargo_type", "Cargo type"), type: "text", required: true },
            { key: "load_rate_mt_hr", label: t("page.vessel.load_rate", "Load rate (MT/h)"), type: "number" },
            { key: "discharge_rate_mt_hr", label: t("page.vessel.disch_rate", "Discharge rate (MT/h)"), type: "number" },
            { key: "stowage_factor", label: t("page.vessel.stowage", "Stowage factor (m3/MT)"), type: "number", step: "0.001" },
            { key: "notes", label: t("common.notes", "Notes"), type: "text", span: true },
          ]}
        />
      ) : null}

      {tab === "tce" ? (
        <VesselCrudGrid
          vesselId={vesselId}
          path="tce-targets"
          title={t("page.vessel.tab_tce", "TCE Targets")}
          addLabel={t("page.vessel.add_tce", "Add TCE target")}
          emptyText={t("page.vessel.no_tce", "No TCE targets yet")}
          columns={[
            { key: "year_month", label: t("page.vessel.tce_month", "Month") },
            { key: "target_tce_usd", label: t("page.vessel.tce_target", "Target TCE (USD)") },
            { key: "notes", label: t("common.notes", "Notes") },
          ]}
          fields={[
            { key: "year_month", label: t("page.vessel.tce_month", "Month (YYYY-MM)"), type: "text", required: true },
            { key: "target_tce_usd", label: t("page.vessel.tce_target", "Target TCE (USD)"), type: "number" },
            { key: "notes", label: t("common.notes", "Notes"), type: "text", span: true },
          ]}
        />
      ) : null}

      {tab === "vetting" ? (
        <VesselCrudGrid
          vesselId={vesselId}
          path="vettings"
          title={t("page.vessel.tab_vetting", "Vetting")}
          addLabel={t("page.vessel.add_vetting", "Add vetting record")}
          emptyText={t("page.vessel.no_vetting", "No vetting records yet")}
          columns={[
            { key: "vetting_type", label: t("page.vessel.vetting_type", "Type") },
            { key: "vetting_date", label: t("page.vessel.vetting_date", "Date") },
            {
              key: "result",
              label: t("page.vessel.vetting_result", "Result"),
              render: (r) => (
                <span className={`pill ${r.result === "pass" ? "valid" : r.result === "fail" ? "danger" : "warn"}`}>{String(r.result ?? "—")}</span>
              ),
            },
            { key: "expiry_date", label: t("page.vessel.vetting_expiry", "Expiry") },
            { key: "inspector", label: t("page.vessel.vetting_inspector", "Inspector") },
            { key: "notes", label: t("common.notes", "Notes") },
          ]}
          fields={[
            {
              key: "vetting_type",
              label: t("page.vessel.vetting_type", "Type"),
              type: "select",
              required: true,
              options: [
                { value: "sire", label: "SIRE" },
                { value: "cdi", label: "CDI" },
                { value: "psc", label: "PSC" },
              ],
            },
            { key: "vetting_date", label: t("page.vessel.vetting_date", "Date"), type: "date" },
            {
              key: "result",
              label: t("page.vessel.vetting_result", "Result"),
              type: "select",
              required: true,
              options: [
                { value: "pass", label: "pass" },
                { value: "conditional", label: "conditional" },
                { value: "fail", label: "fail" },
              ],
            },
            { key: "expiry_date", label: t("page.vessel.vetting_expiry", "Expiry date"), type: "date" },
            { key: "inspector", label: t("page.vessel.vetting_inspector", "Inspector"), type: "text" },
            { key: "notes", label: t("common.notes", "Notes"), type: "text", span: true },
          ]}
        />
      ) : null}

      {tab === "loadline" ? (
        <VesselCrudGrid
          vesselId={vesselId}
          path="loadline-zones"
          title={t("page.vessel.tab_loadline", "Loadline Zones")}
          addLabel={t("page.vessel.add_zone", "Add zone")}
          emptyText={t("page.vessel.no_zone", "No loadline zones yet")}
          columns={[
            { key: "zone_name", label: t("page.vessel.zone_name", "Zone") },
            { key: "max_draft_m", label: t("page.vessel.zone_draft", "Max draft (m)") },
            { key: "valid_from", label: t("page.vessel.zone_from", "Valid from") },
            { key: "valid_to", label: t("page.vessel.zone_to", "Valid to") },
          ]}
          fields={[
            {
              key: "zone_name",
              label: t("page.vessel.zone_name", "Zone"),
              type: "select",
              required: true,
              options: [
                { value: "summer", label: "summer" },
                { value: "tropical", label: "tropical" },
                { value: "winter", label: "winter" },
                { value: "winter_north_atlantic", label: "winter N. Atlantic" },
              ],
            },
            { key: "max_draft_m", label: t("page.vessel.zone_draft", "Max draft (m)"), type: "number", step: "0.01" },
            { key: "valid_from", label: t("page.vessel.zone_from", "Valid from"), type: "date" },
            { key: "valid_to", label: t("page.vessel.zone_to", "Valid to"), type: "date" },
          ]}
        />
      ) : null}

      {tab === "certs" ? (
        <div className="panel">
          <h2>{t("page.vessel.tab_certs", "Certificates")}</h2>
          <VesselCertificates certs={ship?.certificates || []} onChanged={loadShip} />
        </div>
      ) : null}

      {tab === "pms" ? (
        <>
          <div className="kpi-row">
            <div className="kpi-card">
              <span>{t("page.ship.kpi_wo", "Open WOs")}</span>
              <strong>{(ship?.work_orders || []).filter((w: any) => w.status !== "done" && w.status !== "closed").length}</strong>
            </div>
            <div className="kpi-card">
              <span>{t("page.ship.kpi_def", "Defects")}</span>
              <strong>{(ship?.defects || []).filter((d: any) => d.status !== "closed").length}</strong>
            </div>
            <div className="kpi-card">
              <span>{t("page.vessel.next_drydock", "Next drydock")}</span>
              <strong>{fmt(ship?.profile?.next_drydock)}</strong>
            </div>
            <div className="kpi-card">
              <span>{t("page.vessel.tech_status", "Technical status")}</span>
              <strong>{fmt(ship?.profile?.technical_status)}</strong>
            </div>
          </div>
          <div className="panel">
            <h2>{t("page.vessel.work_orders", "Work orders")}</h2>
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("page.ship.wo_no", "WO no.")}</th>
                  <th>{t("page.ship.wo_title", "Title")}</th>
                  <th>{t("common.status", "Status")}</th>
                  <th>{t("common.priority", "Priority")}</th>
                  <th>{t("common.due", "Due")}</th>
                </tr>
              </thead>
              <tbody>
                {(ship?.work_orders || []).map((w: any) => (
                  <tr key={w.id}>
                    <td>{fmt(w.wo_no)}</td>
                    <td>{fmt(w.title)}</td>
                    <td>
                      <span className={`pill ${w.status === "done" || w.status === "closed" ? "valid" : w.status === "blocked" ? "danger" : "warn"}`}>{fmt(w.status)}</span>
                    </td>
                    <td>{fmt(w.priority)}</td>
                    <td>{fmt(w.due_on)}</td>
                  </tr>
                ))}
                {!(ship?.work_orders || []).length ? (
                  <tr>
                    <td colSpan={5} className="muted">
                      {t("common.empty", "No records")}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
          <div className="panel">
            <h2>{t("page.ship.defects", "Defects")}</h2>
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("common.title", "Title")}</th>
                  <th>{t("common.status", "Status")}</th>
                  <th>{t("common.severity", "Severity")}</th>
                </tr>
              </thead>
              <tbody>
                {(ship?.defects || []).map((d: any) => (
                  <tr key={d.id}>
                    <td>{fmt(d.title)}</td>
                    <td>
                      <span className={`pill ${d.status === "closed" ? "valid" : "warn"}`}>{fmt(d.status)}</span>
                    </td>
                    <td>{fmt(d.severity)}</td>
                  </tr>
                ))}
                {!(ship?.defects || []).length ? (
                  <tr>
                    <td colSpan={3} className="muted">
                      {t("common.empty", "No records")}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </AppShell>
  );
}
