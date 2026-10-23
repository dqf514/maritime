"use client";

// U-VESSEL 船舶管理卡片：完整明细页（标准船舶卡片对齐）。
// Tabs: Summary · Consumption · DWT/Draft · Contacts · Routes · Tugs · Bunker Tanks ·
// L/D Performance · TCE Targets · Vetting · Loadline Zones · Certificates · PMS.
// Consumption = IMOS 的 In Port Consumption Table + Speed Consumption Table。

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { Tabs } from "@/components/Tabs";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { VesselCertificates } from "@/components/ShipCertificates";
import { PartyPicker } from "@/components/DataPicker";
import { FormSection } from "@/components/form/FormPanel";
import { formatKv, VesselCrudGrid } from "@/components/ship/VesselCrudGrid";
import { CLASS_SOCIETIES, OWNERSHIP_OPTIONS, TRADE_AREAS } from "@/lib/vessel-catalog";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";
import { apiGet, apiPatch } from "@/lib/api";

type Tab =
  | "summary"
  | "consumption"
  | "spec"
  | "details"
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
  { key: "consumption", labelKey: "page.vessel.tab_consumption", label: "Consumption" },
  { key: "spec", labelKey: "page.vessel.tab_spec", label: "DWT / Draft" },
  { key: "details", labelKey: "page.vessel.tab_details", label: "Details" },
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

// IMOS Vessel Detail > Details：身份 / 主尺度 / 常数与气象安全裕度。
// 分组名对应 summary.imos 下的 identity / commercial / dimensions / safety。
type ImosGroup = "identity" | "commercial" | "dimensions" | "safety";

const IMOS_TEXT_FIELDS: { key: string; label: string; group: ImosGroup; list?: string }[] = [
  { key: "vessel_code", label: "Vessel code", group: "identity" },
  { key: "type_code", label: "Type code", group: "identity" },
  { key: "ownership", label: "Ownership", group: "identity" },
  { key: "trade_area", label: "Trade area", group: "identity" },
  { key: "class_society", label: "Class society", group: "identity" },
  { key: "scrubber", label: "Scrubber", group: "dimensions" },
  { key: "beaufort", label: "Beaufort limit", group: "safety" },
  { key: "sea_state", label: "Sea state limit", group: "safety" },
  { key: "sea_swell", label: "Sea swell limit", group: "safety" },
];

const IMOS_NUM_FIELDS: { key: string; label: string; group: ImosGroup; step?: string }[] = [
  { key: "daily_cost", label: "Daily cost (USD)", group: "commercial", step: "0.01" },
  { key: "speed_laden", label: "Speed laden (kn)", group: "commercial", step: "0.01" },
  { key: "speed_ballast", label: "Speed ballast (kn)", group: "commercial", step: "0.01" },
  { key: "tpc", label: "TPC (MT/cm)", group: "dimensions", step: "0.01" },
  { key: "capacity_bale_ft3", label: "Capacity bale (ft3)", group: "dimensions", step: "0.01" },
  { key: "capacity_grain_ft3", label: "Capacity grain (ft3)", group: "dimensions", step: "0.01" },
  { key: "deck_capacity_m3", label: "Deck capacity (m3)", group: "dimensions", step: "0.01" },
  { key: "vessel_type_corr", label: "Type correction", group: "dimensions", step: "0.001" },
  { key: "constants_sea", label: "Constants · sea (MT)", group: "safety", step: "0.01" },
  { key: "constants_lakes", label: "Constants · lakes (MT)", group: "safety", step: "0.01" },
  { key: "fresh_water", label: "Fresh water (MT)", group: "safety", step: "0.01" },
  { key: "constants_others", label: "Constants · others (MT)", group: "safety", step: "0.01" },
];

// 停泊油耗矩阵（IMOS In Port Consumption）—— 一行一个燃油牌号，列为各工况日耗。
const PORT_CONS_NUM_KEYS = [
  "capacity", "margin", "loading", "discharge", "idle_on", "idle_off", "heat",
  "heat_plus", "heat_plus_plus", "igs", "clean", "manoeuvring", "auxiliary",
  "cooling", "boiler", "incinerator",
] as const;

const PORT_CONS_LABELS: Record<string, string> = {
  capacity: "Tank capacity (MT)",
  margin: "Margin (MT)",
  loading: "Loading",
  discharge: "Discharge",
  idle_on: "Idle · aux on",
  idle_off: "Idle · aux off",
  heat: "Heat",
  heat_plus: "Heat +",
  heat_plus_plus: "Heat ++",
  igs: "IGS",
  clean: "Tank cleaning",
  manoeuvring: "Manoeuvring",
  auxiliary: "Auxiliary",
  cooling: "Cooling",
  boiler: "Boiler",
  incinerator: "Incinerator",
};

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

  // IMOS Details 表单（身份 / 商业 / 主尺度 / 常数与安全裕度）—— 扁平化 summary.imos
  const [imosForm, setImosForm] = useState<Record<string, string>>({});
  const [imosInit, setImosInit] = useState<Record<string, string>>({});
  const [vesselOwner, setVesselOwner] = useState("");
  const [vesselOwnerInit, setVesselOwnerInit] = useState("");

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

    const imos = data?.imos ?? {};
    const imosFlat: Record<string, string> = {};
    for (const f of [...IMOS_TEXT_FIELDS, ...IMOS_NUM_FIELDS]) {
      const v = imos[f.group]?.[f.key];
      imosFlat[f.key] = v === null || v === undefined ? "" : String(v);
    }
    setImosForm(imosFlat);
    setImosInit(imosFlat);
    const ownerId = (imos.vessel_owner_id ?? "") as string;
    setVesselOwner(ownerId);
    setVesselOwnerInit(ownerId);
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

  // Details 表单：只提交改过的键（masterdata PATCH 走 exclude_unset，未提交的字段不动）
  async function saveImos() {
    setBusy(true);
    try {
      const payload: Record<string, unknown> = {};
      for (const f of IMOS_NUM_FIELDS) {
        if (imosForm[f.key] === imosInit[f.key]) continue;
        payload[f.key] = imosForm[f.key] === "" ? null : Number(imosForm[f.key]);
      }
      for (const f of IMOS_TEXT_FIELDS) {
        if (imosForm[f.key] === imosInit[f.key]) continue;
        payload[f.key] = imosForm[f.key] === "" ? null : imosForm[f.key];
      }
      if (vesselOwner !== vesselOwnerInit) payload.vessel_owner_id = vesselOwner || null;
      if (Object.keys(payload).length === 0) {
        toast.success(t("common.saved", "Saved"));
        setBusy(false);
        return;
      }
      await apiPatch(`/api/v1/masterdata/vessels/${vesselId}`, payload);
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

  const routeColumns = useMemo<ColumnDef<any>[]>(
    () => [
      {
        key: "route_name",
        title: t("page.vessel.route_name", "Route"),
        width: 160,
        value: (r: any) => r.route_name,
        render: (v) => fmt(v),
      },
      {
        key: "from_area",
        title: t("page.vessel.route_from", "From"),
        width: 130,
        value: (r: any) => r.from_area,
        render: (v) => fmt(v),
      },
      {
        key: "to_area",
        title: t("page.vessel.route_to", "To"),
        width: 130,
        value: (r: any) => r.to_area,
        render: (v) => fmt(v),
      },
      {
        key: "typical_speed",
        title: t("page.vessel.route_speed", "Speed"),
        width: 90,
        align: "right",
        value: (r: any) => r.typical_speed,
        render: (v) => fmt(v),
      },
      {
        key: "distance_nm",
        title: t("page.vessel.route_dist", "Distance (nm)"),
        width: 110,
        align: "right",
        value: (r: any) => r.distance_nm,
        render: (v) => fmt(v),
      },
    ],
    [t],
  );

  const scaleColumns = useMemo<ColumnDef<ScalePoint>[]>(
    () => [
      {
        key: "draft_m",
        title: t("page.vessel.scale_draft", "Draft (m)"),
        width: 160,
        editor: { type: "number", step: 0.01 },
        value: (r) => r.draft_m,
      },
      {
        key: "deadweight_mt",
        title: t("page.vessel.scale_dwt", "Deadweight (MT)"),
        width: 180,
        editor: { type: "number" },
        value: (r) => r.deadweight_mt,
      },
      {
        key: "actions",
        title: "",
        width: 90,
        align: "right",
        value: () => "",
        render: (_v, _r, i) => (
          <button
            type="button"
            className="btn btn-ghost"
            style={{ color: "var(--danger)", fontSize: "0.75rem" }}
            onClick={() => setScale((prev) => prev.filter((_, j) => j !== i))}
          >
            {t("common.delete", "Delete")}
          </button>
        ),
      },
    ],
    [t],
  );

  const workOrderColumns = useMemo<ColumnDef<any>[]>(
    () => [
      {
        key: "wo_no",
        title: t("page.ship.wo_no", "WO no."),
        width: 120,
        value: (r: any) => r.wo_no,
        render: (v) => fmt(v),
      },
      {
        key: "title",
        title: t("page.ship.wo_title", "Title"),
        width: 220,
        value: (r: any) => r.title,
        render: (v) => fmt(v),
      },
      {
        key: "status",
        title: t("common.status", "Status"),
        width: 110,
        value: (r: any) => r.status,
        render: (_v, r: any) => (
          <span className={`pill ${r.status === "done" || r.status === "closed" ? "valid" : r.status === "blocked" ? "danger" : "warn"}`}>
            {fmt(r.status)}
          </span>
        ),
      },
      {
        key: "priority",
        title: t("common.priority", "Priority"),
        width: 90,
        value: (r: any) => r.priority,
        render: (v) => fmt(v),
      },
      {
        key: "due_on",
        title: t("common.due", "Due"),
        width: 110,
        value: (r: any) => r.due_on,
        render: (v) => fmt(v),
      },
    ],
    [t],
  );

  // ── Consumption tab：IMOS In Port Consumption Table + Speed Consumption Table ──
  const portConsColumns = [
    { key: "fuel_grade", label: t("page.vessel.pc_fuel_grade", "Fuel grade"), width: 116 },
    { key: "unit", label: t("page.vessel.pc_unit", "Unit"), width: 84 },
    ...PORT_CONS_NUM_KEYS.map((k) => ({
      key: k,
      label: t(`page.vessel.pc_${k}`, PORT_CONS_LABELS[k]),
      width: 106,
      align: "right" as const,
      render: (r: Record<string, unknown>) => fmt(r[k]),
    })),
    {
      key: "inactive",
      label: t("common.status", "Status"),
      width: 96,
      render: (r: Record<string, unknown>) => (
        <span className={`pill ${r.inactive ? "warn" : "valid"}`}>
          {r.inactive ? t("common.inactive", "Inactive") : t("common.active", "Active")}
        </span>
      ),
    },
  ];

  const portConsFields = [
    {
      key: "fuel_grade",
      label: t("page.vessel.pc_fuel_grade", "Fuel grade"),
      type: "text" as const,
      required: true,
      placeholder: "VLSFO",
    },
    {
      key: "unit",
      label: t("page.vessel.pc_unit", "Unit"),
      type: "select" as const,
      options: [
        { value: "MT", label: "MT" },
        { value: "MT/day", label: "MT/day" },
        { value: "LT", label: "LT" },
        { value: "BBL", label: "BBL" },
      ],
    },
    { key: "gas_flag", label: t("page.vessel.pc_gas_flag", "L / G"), type: "text" as const, placeholder: "L" },
    { key: "inactive", label: t("page.vessel.pc_inactive", "Inactive — do not use in estimates"), type: "checkbox" as const },
    ...PORT_CONS_NUM_KEYS.map((k) => ({
      key: k,
      label: t(`page.vessel.pc_${k}`, PORT_CONS_LABELS[k]),
      type: "number" as const,
      step: "0.001",
    })),
  ];

  const speedConsColumns = [
    {
      key: "speed",
      label: t("page.vessel.sc_speed", "Speed (kn)"),
      width: 100,
      align: "right" as const,
      render: (r: Record<string, unknown>) => fmt(r.speed),
    },
    {
      key: "ballast_laden",
      label: t("page.vessel.sc_bl", "B / L"),
      width: 96,
      render: (r: Record<string, unknown>) =>
        r.ballast_laden === "B"
          ? t("page.vessel.sc_ballast", "Ballast")
          : r.ballast_laden === "L"
            ? t("page.vessel.sc_laden", "Laden")
            : "—",
    },
    {
      key: "engine_load",
      label: t("page.vessel.sc_load", "Engine load (%)"),
      width: 130,
      align: "right" as const,
      render: (r: Record<string, unknown>) => fmt(r.engine_load),
    },
    {
      key: "fuel_consumption",
      label: t("page.vessel.sc_fuel", "Consumption (MT/day)"),
      width: 240,
      render: (r: Record<string, unknown>) => formatKv(r.fuel_consumption) || "—",
    },
    {
      key: "basis",
      label: t("page.vessel.sc_basis", "Basis"),
      width: 170,
      render: (r: Record<string, unknown>) =>
        r.basis ? t(`page.vessel.basis_${String(r.basis)}`, String(r.basis)) : "—",
    },
  ];

  const speedConsFields = [
    { key: "speed", label: t("page.vessel.sc_speed", "Speed (kn)"), type: "number" as const, step: "0.01" },
    {
      key: "ballast_laden",
      label: t("page.vessel.sc_bl", "B / L"),
      type: "select" as const,
      options: [
        { value: "", label: t("common.none", "None") },
        { value: "B", label: t("page.vessel.sc_ballast", "Ballast") },
        { value: "L", label: t("page.vessel.sc_laden", "Laden") },
      ],
    },
    { key: "engine_load", label: t("page.vessel.sc_load", "Engine load (%)"), type: "number" as const, step: "0.01" },
    {
      key: "fuel_consumption",
      label: t("page.vessel.sc_fuel", "Consumption (MT/day)"),
      type: "kv" as const,
      span: true,
      placeholder: "VLSFO=15.20; MGO=0.30",
    },
    {
      key: "basis",
      label: t("page.vessel.sc_basis", "Basis"),
      type: "select" as const,
      options: [
        { value: "", label: t("common.none", "None") },
        { value: "eco_owner", label: t("page.vessel.basis_eco_owner", "Eco Owner") },
        { value: "warranted_owner", label: t("page.vessel.basis_warranted_owner", "Warranted Owner") },
      ],
    },
  ];

  const imosGroups: { key: ImosGroup; labelKey: string; label: string }[] = [
    { key: "identity", labelKey: "page.vessel.imos_identity", label: "Identity" },
    { key: "commercial", labelKey: "page.vessel.imos_commercial", label: "Commercial" },
    { key: "dimensions", labelKey: "page.vessel.imos_dimensions", label: "Dimensions" },
    { key: "safety", labelKey: "page.vessel.imos_safety", label: "Constants & safety margins" },
  ];

  const defectColumns = useMemo<ColumnDef<any>[]>(
    () => [
      {
        key: "title",
        title: t("common.title", "Title"),
        width: 240,
        value: (r: any) => r.title,
        render: (v) => fmt(v),
      },
      {
        key: "status",
        title: t("common.status", "Status"),
        width: 110,
        value: (r: any) => r.status,
        render: (_v, r: any) => (
          <span className={`pill ${r.status === "closed" ? "valid" : "warn"}`}>{fmt(r.status)}</span>
        ),
      },
      {
        key: "severity",
        title: t("common.severity", "Severity"),
        width: 100,
        value: (r: any) => r.severity,
        render: (v) => fmt(v),
      },
    ],
    [t],
  );

  return (
    <AppShell>
      <PageHeader
        title={vessel?.name || t("page.vessel.card", "Vessel card")}
        subtitle={`${vessel?.imo ? `IMO ${vessel.imo}` : "—"} · ${fmt(vessel?.flag)} · ${fmt(vessel?.vessel_type)} · ${
          vessel?.dwt ? `${vessel.dwt} DWT` : "—"
        }`}
        breadcrumb={[
          { label: t("page.ship.title", "Ship management"), href: "/ship" },
          // A5：第二项返回主数据船舶列表（list masterdata / detail shipyard）
          { label: t("nav.vessels", "Vessels"), href: "/masterdata/vessels" },
          { label: vessel?.name ? `${vessel.name} #${vesselId}` : t("page.vessels.detail", "Vessel") + " #" + vesselId },
        ]}
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

      <Tabs
        items={TABS.map((tb) => ({ key: tb.key, label: t(tb.labelKey, tb.label) }))}
        value={tab}
        onChange={(k) => setTab(k as Tab)}
        variant="line"

      />

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
            <div className="kv-grid">
              <div>
                <label>{t("page.vessel.build", "Built")}</label>
                <div className="kv">
                  {fmt(spec?.vessel_type_detail?.build_year)} · {fmt(spec?.vessel_type_detail?.build_yard)}
                </div>
              </div>
              <div>
                <label>{t("page.vessel.hull", "Hull type")}</label>
                <div className="kv">{fmt(spec?.vessel_type_detail?.hull_type)}</div>
              </div>
              <div>
                <label>{t("page.vessel.flag_state", "Flag state")}</label>
                <div className="kv">{fmt(spec?.vessel_type_detail?.flag_state)}</div>
              </div>
              <div>
                <label>{t("page.vessel.ism", "ISM manager")}</label>
                <div className="kv">{fmt(spec?.vessel_type_detail?.ism_manager)}</div>
              </div>
              <div>
                <label>{t("page.vessel.lightship", "Lightship")}</label>
                <div className="kv">{fmt(spec?.dwt_draft?.lightship)}</div>
              </div>
              <div>
                <label>{t("page.vessel.stowage", "Stowage factor")}</label>
                <div className="kv">{fmt(spec?.capacity?.stowage_factor)}</div>
              </div>
              <div>
                <label>{t("page.vessel.consumption_sea", "Sea consumption")}</label>
                <div className="kv">{fmt(vessel?.consumption_sea)} MT/day</div>
              </div>
              <div>
                <label>{t("page.vessel.consumption_port", "Port consumption")}</label>
                <div className="kv">{fmt(vessel?.consumption_port)} MT/day</div>
              </div>
              <div>
                <label>{t("page.vessel.tank_total", "Tank capacity total")}</label>
                <div className="kv">{fmt(spec?.capacity?.tank_capacity_total)}</div>
              </div>
              <div>
                <label>{t("common.status", "Status")}</label>
                <div className="kv">{fmt(vessel?.status)}</div>
              </div>
            </div>
          </div>

          <div className="panel">
            <h2>{t("page.vessel.routes_short", "Preferred routes")}</h2>
            <DataGrid
              columns={routeColumns}
              data={summary?.routes ?? []}
              rowKey={(r: any, i: number) => String(r.id ?? i)}
              storageKey="vessel_routes_summary"
              emptyText={t("common.empty", "No records")}
              showFooter={false}
            />
          </div>
        </>
      ) : null}

      {tab === "consumption" ? (
        <>
          <VesselCrudGrid
            vesselId={vesselId}
            path="port-consumptions"
            basePath={`/api/v1/masterdata/vessels/${vesselId}/port-consumptions`}
            size="xl"
            title={t("page.vessel.tab_port_cons", "In-port consumption")}
            addLabel={t("page.vessel.add_port_cons", "Add fuel grade")}
            emptyText={t("page.vessel.no_port_cons", "No in-port consumption rows yet")}
            columns={portConsColumns}
            fields={portConsFields}
          />
          <VesselCrudGrid
            vesselId={vesselId}
            path="speed-consumptions"
            basePath={`/api/v1/masterdata/vessels/${vesselId}/speed-consumptions`}
            title={t("page.vessel.tab_speed_cons", "Speed consumption curve")}
            addLabel={t("page.vessel.add_speed_point", "Add speed point")}
            emptyText={t("page.vessel.no_speed_cons", "No speed points yet")}
            columns={speedConsColumns}
            fields={speedConsFields}
          />
        </>
      ) : null}

      {tab === "details" ? (
        <div className="panel">
          <div className="desk-toolbar desk-toolbar-split">
            <h2>{t("page.vessel.tab_details", "Details")}</h2>
            <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={saveImos}>
              {busy ? t("common.saving", "Saving…") : t("common.save", "Save")}
            </button>
          </div>

          {imosGroups.map((g) => (
            <FormSection key={g.key} title={t(g.labelKey, g.label)}>
              {g.key === "identity" ? (
                <label>
                  {t("page.vessel.imos_owner", "Vessel owner")}
                  <PartyPicker
                    value={vesselOwner}
                    onChange={setVesselOwner}
                    allowEmpty
                    placeholder={t("page.vessel.imos_owner_ph", "Search counterparty…")}
                  />
                </label>
              ) : null}

              {IMOS_TEXT_FIELDS.filter((f) => f.group === g.key).map((f) => {
                const label = t(`page.vessel.imos_${f.key}`, f.label);
                const value = imosForm[f.key] ?? "";
                const onChange = (next: string) => setImosForm({ ...imosForm, [f.key]: next });
                if (f.key === "ownership") {
                  return (
                    <label key={f.key}>
                      {label}
                      <select value={value} onChange={(e) => onChange(e.target.value)}>
                        {OWNERSHIP_OPTIONS.map((o) => (
                          <option key={o} value={o}>
                            {o === "" ? t("page.vessels.ownership.none", "Not specified") : t(`page.vessels.ownership.${o}`, o)}
                          </option>
                        ))}
                      </select>
                    </label>
                  );
                }
                if (f.key === "trade_area" || f.key === "class_society") {
                  const opts = f.key === "trade_area" ? TRADE_AREAS : CLASS_SOCIETIES;
                  const listId = `vessel-detail-${f.key}`;
                  return (
                    <label key={f.key}>
                      {label}
                      <input list={listId} value={value} onChange={(e) => onChange(e.target.value)} />
                      <datalist id={listId}>
                        {opts.map((o) => (
                          <option key={o} value={o} />
                        ))}
                      </datalist>
                    </label>
                  );
                }
                return (
                  <label key={f.key}>
                    {label}
                    <input value={value} onChange={(e) => onChange(e.target.value)} />
                  </label>
                );
              })}

              {IMOS_NUM_FIELDS.filter((f) => f.group === g.key).map((f) => (
                <label key={f.key}>
                  {t(`page.vessel.imos_${f.key}`, f.label)}
                  <input
                    type="number"
                    step={f.step}
                    value={imosForm[f.key] ?? ""}
                    onChange={(e) => setImosForm({ ...imosForm, [f.key]: e.target.value })}
                  />
                </label>
              ))}
            </FormSection>
          ))}
        </div>
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
            <DataGrid<ScalePoint>
              columns={scaleColumns}
              data={scale}
              rowKey={(_r, i) => String(i)}
              editable
              onCellSave={(rk, colKey, value) => {
                const idx = Number(rk);
                setScale((prev) =>
                  prev.map((p, j) =>
                    j === idx ? { ...p, [colKey]: value === null || value === undefined ? "" : value } : p,
                  ),
                );
              }}
              storageKey="vessel_dwt_scale"
              emptyText={t("common.empty", "No records")}
              showFooter={false}
            />
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
              <div className="kv-grid" style={{ marginTop: "0.75rem" }}>
                <div>
                  <label>{t("page.vessel.res_avail_dwt", "Available deadweight")}</label>
                  <div className="kv">{fmt(lift.available_deadweight_mt)} MT</div>
                </div>
                <div>
                  <label>{t("page.vessel.res_draft_dwt", "Draft-limited DWT")}</label>
                  <div className="kv">{fmt(lift.draft_limited_deadweight_mt)} MT</div>
                </div>
                <div>
                  <label>{t("page.vessel.res_hold", "Hold volume limit")}</label>
                  <div className="kv">{fmt(lift.hold_volume_limit_mt)} MT</div>
                </div>
                <div>
                  <label>{t("page.vessel.res_gear", "Gear cap")}</label>
                  <div className="kv">{fmt(lift.gear_limit_mt)} MT</div>
                </div>
                <div>
                  <label>{t("page.vessel.res_max", "Max lift")}</label>
                  <div className="kv">
                    <strong>{fmt(lift.max_lift_mt)} MT</strong>
                  </div>
                </div>
                <div>
                  <label>{t("page.vessel.res_limiting", "Limiting factor")}</label>
                  <div className="kv">
                    <span className="pill warn">{fmt(lift.limiting_factor)}</span>
                  </div>
                </div>
                {lift.warnings?.length ? (
                  <div style={{ gridColumn: "1 / -1" }}>
                    <label>{t("page.vessel.res_warnings", "Warnings")}</label>
                    <div className="kv">{lift.warnings.join("; ")}</div>
                  </div>
                ) : null}
              </div>
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
            <DataGrid
              columns={workOrderColumns}
              data={ship?.work_orders || []}
              rowKey={(r: any, i: number) => String(r.id ?? i)}
              storageKey="vessel_work_orders"
              emptyText={t("common.empty", "No records")}
              showFooter={false}
            />
          </div>
          <div className="panel">
            <h2>{t("page.ship.defects", "Defects")}</h2>
            <DataGrid
              columns={defectColumns}
              data={ship?.defects || []}
              rowKey={(r: any, i: number) => String(r.id ?? i)}
              storageKey="vessel_defects"
              emptyText={t("common.empty", "No records")}
              showFooter={false}
            />
          </div>
        </>
      ) : null}
    </AppShell>
  );
}
