"use client";

import { msgOf } from "@/lib/errors";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { SavedViews } from "@/components/SavedViews";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { PartyPicker } from "@/components/DataPicker";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { EstimateCompare, type CompareFieldDef } from "@/components/EstimateCompare";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { Num } from "@/components/Num";
import { StatusLegend } from "@/components/StatusLegend";
import { ValidateButton, type ValidateIssue } from "@/components/ValidateButton";
import { PageGuide } from "@/components/PageGuide";
import { AiFill } from "@/components/ai/AiFill";
import { useAiContextBinder } from "@/components/ai/aiContextStore";
import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";
import { StateView } from "@/components/StateView";
import { downloadCsv } from "@/lib/csv";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";
import { useToast } from "@/components/ToastProvider";

type SensitivityRow = { delta_pct: number; tce: number };

type RefItem = { id: string; name: string };
type EstResults = {
  tce?: number;
  gross_freight?: number;
  net_freight?: number;
  voyage_cost?: number;
  bunker_cost?: number;
  net_result?: number;
  address_commission?: number;
  brokerage?: number;
  freight_basis?: string;
  total_days?: number;
  total_revenue?: number;
  fuel_mt?: number;
  co2_mt?: number;
  emissions_cost?: number;
  cargo_qty_min?: number;
  cargo_qty_max?: number;
  cargo_count?: number;
  parcel_qty_total?: number;
  cargoes?: Array<{
    index: number;
    qty: number;
    freight_basis: string;
    base_freight: number;
    cargo_type?: string;
    load_port?: string;
    disch_port?: string;
    differentials_total?: number;
  }>;
  inputs_enriched?: Record<string, string>;
  warnings?: Array<{ code: string; message: string }>;
};
type Estimate = {
  id: string;
  title: string;
  mode: string;
  vessel_id: string | null;
  counterparty_id: string | null;
  version: number;
  status: string;
  inputs: Record<string, number | string>;
  results: EstResults;
};

type InputFields = {
  cargo_qty: string;
  cargo_tolerance_pct: string;
  stowage_factor: string;
  hold_capacity_m3: string;
  vessel_deadweight: string;
  freight_rate: string;
  lump_sum_freight: string;
  ws_flat: string;
  ws_pct: string;
  address_comm_pct: string;
  brokerage_pct: string;
  sea_days: string;
  port_days: string;
  eca_days: string;
  waiting_days: string;
  bunker_sea_tpd: string;
  bunker_port_tpd: string;
  bunker_eca_tpd: string;
  bunker_price: string;
  port_costs: string;
  canal_costs: string;
  other_costs: string;
  eca_extra_cost: string;
  hire_per_day: string;
  demurrage_income: string;
  other_income: string;
  eu_ets_share: string;
  ets_price: string;
  co2_factor: string;
};

const COMPARE_FIELDS: CompareFieldDef[] = [
  // Core metrics
  { key: "tce", label: "TCE ($/day)", labelEn: "TCE ($/day)", labelZh: "TCE ($/天)", category: "core", categoryEn: "Core Metrics", categoryZh: "核心指标", format: "money", preference: "higher" },
  { key: "voyage_days", label: "Voyage days", labelEn: "Voyage days", labelZh: "航次天数", category: "core", categoryEn: "Core Metrics", categoryZh: "核心指标", format: "number", unit: "days", preference: "lower" },
  { key: "freight_revenue", label: "Freight revenue", labelEn: "Freight revenue", labelZh: "运费收入", category: "core", categoryEn: "Core Metrics", categoryZh: "核心指标", format: "money", preference: "higher" },
  { key: "voyage_cost", label: "Voyage cost", labelEn: "Voyage cost", labelZh: "航次成本", category: "core", categoryEn: "Core Metrics", categoryZh: "核心指标", format: "money", preference: "lower" },
  // Cost breakdown
  { key: "bunker_cost", label: "Bunker cost", labelEn: "Bunker cost", labelZh: "燃油成本", category: "cost", categoryEn: "Cost Breakdown", categoryZh: "成本分解", format: "money", preference: "lower" },
  { key: "port_cost", label: "Port cost", labelEn: "Port cost", labelZh: "港口费用", category: "cost", categoryEn: "Cost Breakdown", categoryZh: "成本分解", format: "money", preference: "lower" },
  { key: "commission", label: "Commission", labelEn: "Commission", labelZh: "佣金", category: "cost", categoryEn: "Cost Breakdown", categoryZh: "成本分解", format: "money", preference: "lower" },
  { key: "eu_ets_cost", label: "EU ETS cost", labelEn: "EU ETS cost", labelZh: "EU ETS 碳配额", category: "cost", categoryEn: "Cost Breakdown", categoryZh: "成本分解", format: "money", preference: "lower" },
  // Cargo & rates
  { key: "cargo_qty", label: "Cargo qty", labelEn: "Cargo qty", labelZh: "货量", category: "cargo", categoryEn: "Cargo & Rates", categoryZh: "货物与运价", format: "number", unit: "MT" },
  { key: "freight_rate", label: "Freight rate", labelEn: "Freight rate", labelZh: "运价", category: "cargo", categoryEn: "Cargo & Rates", categoryZh: "货物与运价", format: "money", unit: "/MT" },
  { key: "demurrage_rate", label: "Demurrage rate", labelEn: "Demurrage rate", labelZh: "滞期费率", category: "cargo", categoryEn: "Cargo & Rates", categoryZh: "货物与运价", format: "money", unit: "/day" },
  { key: "despatch_rate", label: "Despatch rate", labelEn: "Despatch rate", labelZh: "速遣费率", category: "cargo", categoryEn: "Cargo & Rates", categoryZh: "货物与运价", format: "money", unit: "/day" },
  // Navigation
  { key: "sea_days", label: "Sea days", labelEn: "Sea days", labelZh: "海上天数", category: "nav", categoryEn: "Navigation", categoryZh: "航行参数", format: "number", unit: "days" },
  { key: "port_days", label: "Port days", labelEn: "Port days", labelZh: "在港天数", category: "nav", categoryEn: "Navigation", categoryZh: "航行参数", format: "number", unit: "days" },
  { key: "speed_kn", label: "Speed", labelEn: "Speed", labelZh: "航速", category: "nav", categoryEn: "Navigation", categoryZh: "航行参数", format: "number", unit: "kn", preference: "higher" },
  { key: "consumption_mt_day", label: "Consumption", labelEn: "Consumption", labelZh: "日耗油", category: "nav", categoryEn: "Navigation", categoryZh: "航行参数", format: "number", unit: "MT/d", preference: "lower" },
  { key: "fuel_price", label: "Fuel price", labelEn: "Fuel price", labelZh: "油价", category: "nav", categoryEn: "Navigation", categoryZh: "航行参数", format: "money", unit: "/MT", preference: "lower" },
];

const EMPTY_INPUTS: InputFields = {
  cargo_qty: "",
  cargo_tolerance_pct: "",
  stowage_factor: "",
  hold_capacity_m3: "",
  vessel_deadweight: "",
  freight_rate: "",
  lump_sum_freight: "",
  ws_flat: "",
  ws_pct: "",
  address_comm_pct: "1.25",
  brokerage_pct: "1.25",
  sea_days: "",
  port_days: "",
  eca_days: "",
  waiting_days: "",
  bunker_sea_tpd: "",
  bunker_port_tpd: "",
  bunker_eca_tpd: "",
  bunker_price: "",
  port_costs: "",
  canal_costs: "",
  other_costs: "",
  eca_extra_cost: "",
  hire_per_day: "",
  demurrage_income: "",
  other_income: "",
  eu_ets_share: "",
  ets_price: "",
  co2_factor: "",
};

const BUNKER_GRADES = ["VLSFO", "HSFO", "MGO", "LNG"];

const ESTIMATE_STATUSES = ["draft", "calculated", "confirmed", "converted", "cancelled"];

type LegRow = {
  from_port: string;
  to_port: string;
  distance_nm: string;
  speed_kn: string;
  port_days: string;
  cargo_qty: string;
};

type PriceRow = { grade: string; price: string };

// 多货估算（IMOS parity）：每票货独立计价；空白字段继承顶层输入
type CargoRow = {
  qty: string;
  freight_basis: string; // "" = 继承顶层
  freight_rate: string;
  lump_sum_freight: string;
  ws_flat: string;
  ws_pct: string;
  cargo_type: string;
  load_port: string;
  disch_port: string;
};

const EMPTY_LEG: LegRow = { from_port: "", to_port: "", distance_nm: "", speed_kn: "", port_days: "", cargo_qty: "" };

const EMPTY_CARGO: CargoRow = {
  qty: "",
  freight_basis: "",
  freight_rate: "",
  lump_sum_freight: "",
  ws_flat: "",
  ws_pct: "",
  cargo_type: "",
  load_port: "",
  disch_port: "",
};

const CARGO_BASES = ["per_mt", "lump_sum", "worldscale", "ws_differential"];

const DRY_BULK: Partial<InputFields> = {
  cargo_qty: "50000",
  freight_rate: "18.5",
  address_comm_pct: "1.25",
  brokerage_pct: "1.25",
  sea_days: "30",
  port_days: "10",
  bunker_sea_tpd: "28",
  bunker_port_tpd: "3.5",
  bunker_price: "450",
  port_costs: "80000",
  canal_costs: "20000",
  other_costs: "10000",
};

const TANKER: Partial<InputFields> = {
  cargo_qty: "80000",
  ws_flat: "12.5",
  ws_pct: "95",
  address_comm_pct: "1.25",
  sea_days: "22",
  port_days: "6",
  eca_days: "3",
  bunker_sea_tpd: "32",
  bunker_port_tpd: "4",
  bunker_eca_tpd: "36",
  bunker_price: "620",
  port_costs: "95000",
  canal_costs: "0",
  other_costs: "15000",
  eca_extra_cost: "12000",
};

function num(v: string): number | undefined {
  if (v === "" || v == null) return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

function inputsFromEst(inputs: Record<string, number | string> | undefined): InputFields {
  const src = inputs || {};
  const next = { ...EMPTY_INPUTS };
  (Object.keys(EMPTY_INPUTS) as Array<keyof InputFields>).forEach((k) => {
    const val = src[k];
    if (val !== undefined && val !== null && val !== "") next[k] = String(val);
  });
  return next;
}

type PayloadExtras = {
  legs?: Array<Record<string, number | string>>;
  cargoes?: Array<Record<string, unknown>>;
  bunker_grade?: string;
  bunker_eca_grade?: string;
  bunker_prices?: Record<string, number>;
};

function buildPayload(fields: InputFields, extras?: PayloadExtras): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  (Object.keys(EMPTY_INPUTS) as Array<keyof InputFields>).forEach((k) => {
    const v = num(fields[k]);
    if (v !== undefined) out[k] = v;
  });
  if (extras?.legs?.length) {
    out.legs = extras.legs;
    // legs drive sea/port days automatically — drop the manual entries
    delete out.sea_days;
    delete out.port_days;
  }
  if (extras?.cargoes?.length) out.cargoes = extras.cargoes;
  if (extras?.bunker_grade) out.bunker_grade = extras.bunker_grade;
  if (extras?.bunker_eca_grade) out.bunker_eca_grade = extras.bunker_eca_grade;
  if (extras?.bunker_prices && Object.keys(extras.bunker_prices).length) out.bunker_prices = extras.bunker_prices;
  return out;
}

function legRowsFromEst(inputs: Record<string, unknown> | undefined): LegRow[] {
  const raw = inputs?.legs;
  if (!Array.isArray(raw)) return [];
  return raw.map((l) => {
    const o = (l || {}) as Record<string, unknown>;
    const s = (v: unknown) => (v === undefined || v === null ? "" : String(v));
    return {
      from_port: s(o.from_port),
      to_port: s(o.to_port),
      distance_nm: s(o.distance_nm),
      speed_kn: s(o.speed_kn),
      port_days: s(o.port_days),
      cargo_qty: s(o.cargo_qty),
    };
  });
}

function cargoRowsFromEst(inputs: Record<string, unknown> | undefined): CargoRow[] {
  const raw = inputs?.cargoes;
  if (!Array.isArray(raw)) return [];
  return raw.map((c) => {
    const o = (c || {}) as Record<string, unknown>;
    const s = (v: unknown) => (v === undefined || v === null ? "" : String(v));
    return {
      qty: s(o.qty),
      freight_basis: s(o.freight_basis),
      freight_rate: s(o.freight_rate),
      lump_sum_freight: s(o.lump_sum_freight),
      ws_flat: s(o.ws_flat),
      ws_pct: s(o.ws_pct),
      cargo_type: s(o.cargo_type),
      load_port: s(o.load_port),
      disch_port: s(o.disch_port),
    };
  });
}

function fmt(n: number | string | undefined | null) {
  if (n === undefined || n === null || n === "") return "—";
  const v = typeof n === "number" ? n : Number(n);
  if (!Number.isFinite(v)) return String(n);
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function EstimatesPage() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  // U1 列表协议：选中项 / 搜索 / 状态进 URL，视图可分享、后退不丢状态
  const { query, setQuery } = useListQuery();
  const searchQ = typeof query.q === "string" ? query.q : "";
  const statusFilter = typeof query.status === "string" ? query.status : "";
  const [rows, setRows] = useState<Estimate[]>([]);
  const [vessels, setVessels] = useState<RefItem[]>([]);
  const [parties, setParties] = useState<RefItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(typeof query.id === "string" ? query.id : null);
  // 全局 AI 助手上下文：把当前选中的估算交给 Copilot
  useAiContextBinder({ entity_type: "estimate", entity_id: selectedId, page: "/estimates" });
  const [title, setTitle] = useState("New voyage estimate");
  const [mode, setMode] = useState<"voyage" | "tct">("voyage");
  const [vesselId, setVesselId] = useState("");
  const [partyId, setPartyId] = useState("");
  const [fields, setFields] = useState<InputFields>(EMPTY_INPUTS);
  const [legRows, setLegRows] = useState<LegRow[]>([]);
  const [cargoRows, setCargoRows] = useState<CargoRow[]>([]);
  const [bunkerGrade, setBunkerGrade] = useState("VLSFO");
  const [bunkerEcaGrade, setBunkerEcaGrade] = useState("MGO");
  const [priceRows, setPriceRows] = useState<PriceRow[]>([]);
  const [results, setResults] = useState<EstResults>({});
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [compareRows, setCompareRows] = useState<Array<{ id: string; title: string; version: number; tce?: number }>>([]);
  const [compareVariants, setCompareVariants] = useState<Array<{ id: string; name: string; subtitle?: string; values: Record<string, unknown> }>>([]);
  // 对比结果从右缘滑出（无遮罩 — 不挡左侧勾选区），edge tab 作开关
  const [compareOpen, setCompareOpen] = useState(false);
  const [sensitivity, setSensitivity] = useState<SensitivityRow[]>([]);
  const [err, setErr] = useState("");
  /** 主列表加载失败 */
  const [listErr, setListErr] = useState<string | null>(null);
  /** 参考数据（船/对手方）加载失败 */
  const [refErr, setRefErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);
  const rowCtx = useContextMenu<Estimate>();

  const selected = useMemo(() => rows.find((r) => r.id === selectedId) || null, [rows, selectedId]);

  // B6 列表热键：按 N 新建估算
  useListHotkeys(() => {
    void createDraft();
  });

  const loadMaster = useCallback(async () => {
    // 参考数据（船/对手方）取数失败不能连累主列表：逐项结算，只做局部提示
    const [vR, pR] = await Promise.allSettled([
      apiGet("/api/v1/masterdata/vessels"),
      apiGet("/api/v1/masterdata/counterparties"),
    ]);
    const v = vR.status === "fulfilled" ? (vR.value as RefItem[]) : [];
    const p = pR.status === "fulfilled" ? (pR.value as RefItem[]) : [];
    setVessels(v);
    setParties(p);
    if (!vesselId && v[0]?.id) setVesselId(v[0].id);
    if (!partyId && p[0]?.id) setPartyId(p[0].id);
    const failed = [vR, pR].filter((r) => r.status === "rejected") as PromiseRejectedResult[];
    if (failed.length) setRefErr(msgOf(failed[0].reason));
    else setRefErr(null);
  }, [vesselId, partyId]);

  const load = useCallback(async () => {
    const data: Estimate[] = await apiGet("/api/v1/estimates");
    setRows(data);
    return data;
  }, []);

  /** 主列表重新加载（失败 → 错误态，可重试） */
  const reload = useCallback(async () => {
    setLoading(true);
    try {
      await load();
      setListErr(null);
    } catch (ex) {
      setListErr(msgOf(ex));
    } finally {
      setLoading(false);
    }
  }, [load]);

  useEffect(() => {
    const urlId = typeof query.id === "string" ? query.id : null;
    setLoading(true);
    Promise.allSettled([loadMaster(), load()])
      .then(([masterR, listR]) => {
        if (listR.status === "fulfilled") {
          setListErr(null);
          const data = listR.value;
          const preferred = (urlId && data.find((r) => r.id === urlId)) || data[0];
          if (preferred) selectEstimate(preferred);
        } else {
          // 主列表失败 → 错误态（不能伪装成空列表）
          setListErr(msgOf(listR.reason));
        }
        if (masterR.status === "rejected") setRefErr(msgOf(masterR.reason));
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filteredRows = useMemo(() => {
    const q = searchQ.trim().toLowerCase();
    return rows.filter((r) => {
      if (statusFilter && r.status !== statusFilter) return false;
      if (q && !`${r.title} ${r.status} ${r.id}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [rows, searchQ, statusFilter]);

  const filterCount = (searchQ.trim() ? 1 : 0) + (statusFilter ? 1 : 0);

  function selectEstimate(est: Estimate) {
    setSelectedId(est.id);
    setQuery({ id: est.id });
    setTitle(est.title);
    setMode((est.mode as "voyage" | "tct") || "voyage");
    setVesselId(est.vessel_id || "");
    setPartyId(est.counterparty_id || "");
    setFields(inputsFromEst(est.inputs));
    const inp = (est.inputs || {}) as Record<string, unknown>;
    setLegRows(legRowsFromEst(inp));
    setCargoRows(cargoRowsFromEst(inp));
    setBunkerGrade(typeof inp.bunker_grade === "string" ? inp.bunker_grade : "VLSFO");
    setBunkerEcaGrade(typeof inp.bunker_eca_grade === "string" ? inp.bunker_eca_grade : "MGO");
    const bp = inp.bunker_prices;
    setPriceRows(
      bp && typeof bp === "object" && !Array.isArray(bp)
        ? Object.entries(bp as Record<string, unknown>).map(([grade, price]) => ({ grade, price: String(price) }))
        : [],
    );
    setResults(est.results || {});
    setSensitivity([]);
  }

  function currentExtras(): PayloadExtras {
    const legs = legRows
      .filter((l) => num(l.distance_nm) !== undefined && num(l.speed_kn) !== undefined)
      .map((l) => {
        const leg: Record<string, number | string> = {
          distance_nm: Number(l.distance_nm),
          speed_kn: Number(l.speed_kn),
        };
        if (l.from_port.trim()) leg.from_port = l.from_port.trim();
        if (l.to_port.trim()) leg.to_port = l.to_port.trim();
        const pd = num(l.port_days);
        if (pd !== undefined) leg.port_days = pd;
        const cq = num(l.cargo_qty);
        if (cq !== undefined) leg.cargo_qty = cq;
        return leg;
      });
    const bunker_prices: Record<string, number> = {};
    priceRows.forEach((r) => {
      const p = num(r.price);
      if (r.grade && p !== undefined) bunker_prices[r.grade] = p;
    });
    // 多货：仅有货量的票货才提交（空行忽略）；空白计价字段继承顶层
    const cargoes = cargoRows
      .filter((c) => num(c.qty) !== undefined && (num(c.qty) ?? 0) > 0)
      .map((c) => {
        const cargo: Record<string, unknown> = { qty: Number(c.qty) };
        if (c.freight_basis.trim()) cargo.freight_basis = c.freight_basis.trim();
        const fr = num(c.freight_rate);
        if (fr !== undefined) cargo.freight_rate = fr;
        const ls = num(c.lump_sum_freight);
        if (ls !== undefined) cargo.lump_sum_freight = ls;
        const wf = num(c.ws_flat);
        if (wf !== undefined) cargo.ws_flat = wf;
        const wp = num(c.ws_pct);
        if (wp !== undefined) cargo.ws_pct = wp;
        if (c.cargo_type.trim()) cargo.cargo_type = c.cargo_type.trim();
        if (c.load_port.trim()) cargo.load_port = c.load_port.trim();
        if (c.disch_port.trim()) cargo.disch_port = c.disch_port.trim();
        return cargo;
      });
    return { legs, cargoes, bunker_grade: bunkerGrade, bunker_eca_grade: bunkerEcaGrade, bunker_prices };
  }

  function setLeg(idx: number, key: keyof LegRow, value: string) {
    setLegRows((prev) => prev.map((l, i) => (i === idx ? { ...l, [key]: value } : l)));
  }

  function setCargo(idx: number, key: keyof CargoRow, value: string) {
    setCargoRows((prev) => prev.map((c, i) => (i === idx ? { ...c, [key]: value } : c)));
  }

  function setPrice(idx: number, key: keyof PriceRow, value: string) {
    setPriceRows((prev) => prev.map((r, i) => (i === idx ? { ...r, [key]: value } : r)));
  }

  function setField(key: keyof InputFields, value: string) {
    setFields((prev) => ({ ...prev, [key]: value }));
  }

  async function createDraft(preset?: Partial<InputFields>, presetTitle?: string) {
    setBusy(true);
    setErr("");
    try {
      const merged = { ...EMPTY_INPUTS, ...(preset || fields) };
      const extras = preset ? undefined : currentExtras();
      if (preset) {
        setLegRows([]);
        setCargoRows([]);
        setPriceRows([]);
      }
      const est: Estimate = await apiPost("/api/v1/estimates", {
        title: presetTitle || title || "Draft estimate",
        mode,
        vessel_id: vesselId || vessels[0]?.id || null,
        counterparty_id: partyId || parties[0]?.id || null,
        inputs: buildPayload(merged, extras),
      });
      toast.success(t("page.estimates.created", "Draft created"));
      const data = await load();
      const fresh = data.find((r) => r.id === est.id) || est;
      selectEstimate(fresh);
    } catch (e) {
      setErr(msgOf(e));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!selectedId) return;
    setBusy(true);
    setErr("");
    try {
      const est: Estimate = await apiPut(`/api/v1/estimates/${selectedId}`, {
        title,
        mode,
        vessel_id: vesselId || null,
        counterparty_id: partyId || null,
        inputs: buildPayload(fields, currentExtras()),
      });
      setResults(est.results || {});
      toast.success(t("page.estimates.saved", "Saved"));
      await load();
    } catch (e) {
      setErr(msgOf(e));
    } finally {
      setBusy(false);
    }
  }

  async function calculate() {
    if (!selectedId) return;
    setBusy(true);
    setErr("");
    try {
      await apiPut(`/api/v1/estimates/${selectedId}`, {
        title,
        mode,
        vessel_id: vesselId || null,
        counterparty_id: partyId || null,
        inputs: buildPayload(fields, currentExtras()),
      });
      const est: Estimate = await apiPost(`/api/v1/estimates/${selectedId}/calculate`);
      setResults(est.results || {});
      toast.success(t("page.estimates.calculated", "Calculated TCE {tce}", { tce: fmt(est.results?.tce) }));
      await load();
    } catch (e) {
      setErr(msgOf(e));
    } finally {
      setBusy(false);
    }
  }

  async function clone(id?: string) {
    const target = id || selectedId;
    if (!target) return;
    setBusy(true);
    try {
      const est: Estimate = await apiPost(`/api/v1/estimates/${target}/clone`);
      toast.success(t("page.estimates.cloned", "Cloned to {title}", { title: est.title }));
      const data = await load();
      const fresh = data.find((r) => r.id === est.id) || est;
      selectEstimate(fresh);
    } catch (e) {
      setErr(msgOf(e));
    } finally {
      setBusy(false);
    }
  }

  function runSensitivity(id?: string) {
    const target = id || selectedId;
    if (!target) return;
    window.location.href = `/estimates/${target}/sensitivity`;
  }

  function exportEstimates(list: Estimate[]) {
    const rows = list.length ? list : selected ? [selected] : [];
    downloadCsv(
      "estimates",
      ["id", "title", "mode", "status", "version", "tce", "cargo_qty", "freight_rate"],
      rows.map((r) => [
        r.id,
        r.title,
        r.mode,
        r.status,
        r.version,
        r.results?.tce ?? "",
        r.inputs?.cargo_qty ?? "",
        r.inputs?.freight_rate ?? "",
      ]),
      { emptyGuard: t("page.estimates.export_empty", "No rows selected — export nothing?") },
    );
  }

  /** Frontend-only estimate checks — rules limited to fields actually on this form. */
  function validateEstimate(): ValidateIssue[] {
    const issues: ValidateIssue[] = [];
    const cargoQty = num(fields.cargo_qty);
    const legCargo = legRows.some((l) => (num(l.cargo_qty) ?? 0) > 0);
    const hasLump = num(fields.lump_sum_freight) !== undefined || num(fields.ws_flat) !== undefined;
    if ((cargoQty === undefined || cargoQty <= 0) && !legCargo && !hasLump) {
      issues.push({ level: "error", message: t("validate.est.no_cargo", "Cargo quantity is missing") });
    }
    const nonNeg: Array<keyof InputFields> = [
      "cargo_qty",
      "freight_rate",
      "bunker_price",
      "port_costs",
      "canal_costs",
      "other_costs",
      "sea_days",
      "port_days",
      "bunker_sea_tpd",
      "bunker_port_tpd",
      "hire_per_day",
    ];
    for (const k of nonNeg) {
      const v = num(fields[k]);
      if (v !== undefined && v < 0) {
        issues.push({
          level: "error",
          message: t("validate.est.neg", "{field} must not be negative", { field: k }),
        });
      }
    }
    if (results.tce !== undefined && results.tce < 0) {
      issues.push({ level: "warn", message: t("validate.est.tce_neg", "TCE is below zero") });
    }
    const hasDist = legRows.some((l) => (num(l.distance_nm) ?? 0) > 0);
    if (legRows.length === 0) {
      issues.push({
        level: "warn",
        message: t("validate.est.no_distance", "No distance data — using manual sea/port days"),
      });
    } else if (!hasDist) {
      issues.push({
        level: "warn",
        message: t("validate.est.leg_no_dist", "Legs have no distance — sea days may be wrong"),
      });
    }
    if (num(fields.bunker_price) === undefined && priceRows.length === 0) {
      issues.push({ level: "warn", message: t("validate.est.no_bunker", "Bunker price is not set") });
    }
    return issues;
  }

  function rowMenuItems(target: Estimate): ContextMenuItem[] {
    return [
      { key: "open", label: t("common.open", "Open"), onClick: () => selectEstimate(target) },
      { key: "duplicate", label: t("page.estimates.clone", "Clone"), onClick: () => void clone(target.id) },
      { key: "d1", label: "", divider: true },
      {
        key: "compare",
        label: t("page.estimates.compare", "对比"),
        onClick: () => {
          const next = compareIds.includes(target.id) ? compareIds : [...compareIds, target.id];
          setCompareIds(next);
          if (next.length >= 2) void compare(next);
          else setErr(t("page.estimates.compare_need", "Select at least 2 estimates to compare"));
        },
      },
      { key: "sensitivity", label: t("page.estimates.sensitivity", "Sensitivity"), onClick: () => runSensitivity(target.id) },
      { key: "d2", label: "", divider: true },
      {
        key: "export",
        label: t("common.export", "Export"),
        onClick: () => exportEstimates(compareIds.length ? rows.filter((r) => compareIds.includes(r.id)) : [target]),
      },
    ];
  }

  async function compare(ids?: string[]) {
    const targetIds = ids ?? compareIds;
    if (targetIds.length < 2) {
      setErr(t("page.estimates.compare_need", "Select at least 2 estimates to compare"));
      return;
    }
    setBusy(true);
    try {
      const data = await apiPost("/api/v1/estimates/compare", targetIds);
      setCompareRows(data);
      // Fetch full details for comparison matrix
      const variants = await Promise.all(
        targetIds.map(async (id, i) => {
          try {
            const full = await apiGet(`/api/v1/estimates/${id}`);
            const inputs = full.inputs || {};
            const results = full.results || {};
            return {
              id,
              name: full.title || `Estimate ${i + 1}`,
              subtitle: `v${full.version || 1}`,
              values: {
                tce: results.tce,
                voyage_days: results.total_days ?? inputs.voyage_days,
                freight_revenue: results.freight_revenue ?? inputs.lump_sum_freight ?? (inputs.cargo_qty && inputs.freight_rate ? Number(inputs.cargo_qty) * Number(inputs.freight_rate) : undefined),
                bunker_cost: results.bunker_cost,
                port_cost: results.port_cost,
                commission: results.commission_cost ?? results.commission,
                eu_ets_cost: results.emissions_cost ?? results.eu_ets_cost,
                voyage_cost: results.voyage_cost,
                cargo_qty: inputs.cargo_qty,
                freight_rate: inputs.freight_rate,
                demurrage_rate: inputs.demurrage_rate,
                despatch_rate: inputs.despatch_rate,
                sea_days: results.sea_days,
                port_days: results.port_days,
                speed_kn: inputs.speed_kn,
                consumption_mt_day: inputs.consumption_mt_day,
                fuel_price: inputs.fuel_price,
              },
            };
          } catch {
            return { id, name: `Estimate ${i + 1}`, values: {} as Record<string, unknown> };
          }
        }),
      );
      setCompareVariants(variants);
      setCompareOpen(true);
      toast.success(t("page.estimates.compare_ok", "Compare ready"));
    } catch (e) {
      setErr(msgOf(e));
    } finally {
      setBusy(false);
    }
  }

  async function toCp() {
    if (!selectedId) return;
    setBusy(true);
    try {
      const cp = await apiPost(`/api/v1/estimates/${selectedId}/to-charter`);
      toast.success(t("page.estimates.cp_msg", "Created charter {no}", { no: cp.charter_no }));
      await load();
    } catch (e) {
      setErr(msgOf(e));
    } finally {
      setBusy(false);
    }
  }

  async function removeEstimate() {
    if (!selectedId) return;
    setBusy(true);
    try {
      await apiDelete(`/api/v1/estimates/${selectedId}`);
      setSelectedId(null);
      toast.success(t("common.recycled", "已移入回收站"));
      await load();
    } catch (e) {
      setErr(msgOf(e));
    } finally {
      setBusy(false);
    }
  }

  function toggleCompare(id: string) {
    setCompareIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  const inputDefs: Array<{ key: keyof InputFields; label: string }> = [
    { key: "cargo_qty", label: t("page.estimates.cargo_qty", "Cargo qty") },
    { key: "cargo_tolerance_pct", label: t("page.estimates.cargo_tolerance", "Cargo tolerance %") },
    { key: "stowage_factor", label: t("page.estimates.stowage_factor", "Stowage factor m³/mt") },
    { key: "hold_capacity_m3", label: t("page.estimates.hold_capacity", "Hold capacity m³") },
    { key: "vessel_deadweight", label: t("page.estimates.deadweight", "Vessel DWT") },
    { key: "freight_rate", label: t("page.estimates.freight_rate", "Freight rate") },
    { key: "lump_sum_freight", label: t("page.estimates.lump_sum", "Lump sum freight") },
    { key: "ws_flat", label: t("page.estimates.ws_flat", "WS flat") },
    { key: "ws_pct", label: t("page.estimates.ws_pct", "WS %") },
    { key: "address_comm_pct", label: t("page.estimates.address_comm", "Address comm %") },
    { key: "brokerage_pct", label: t("page.estimates.brokerage", "Brokerage %") },
    { key: "sea_days", label: t("page.estimates.sea_days", "Sea days") },
    { key: "port_days", label: t("page.estimates.port_days", "Port days") },
    { key: "eca_days", label: t("page.estimates.eca_days", "ECA days") },
    { key: "waiting_days", label: t("page.estimates.waiting_days", "Waiting days") },
    { key: "bunker_sea_tpd", label: t("page.estimates.bunker_sea", "Bunker sea tpd") },
    { key: "bunker_port_tpd", label: t("page.estimates.bunker_port", "Bunker port tpd") },
    { key: "bunker_eca_tpd", label: t("page.estimates.bunker_eca", "Bunker ECA tpd") },
    { key: "bunker_price", label: t("page.estimates.bunker_price", "Bunker price") },
    { key: "port_costs", label: t("page.estimates.port_costs", "Port costs") },
    { key: "canal_costs", label: t("page.estimates.canal_costs", "Canal costs") },
    { key: "other_costs", label: t("page.estimates.other_costs", "Other costs") },
    { key: "eca_extra_cost", label: t("page.estimates.eca_extra", "ECA extra cost") },
    { key: "hire_per_day", label: t("page.estimates.hire", "Hire / day") },
    { key: "demurrage_income", label: t("page.estimates.demurrage", "Demurrage income") },
    { key: "other_income", label: t("page.estimates.other_income", "Other income") },
  ];

  const sensitivityColumns = useMemo<ColumnDef<SensitivityRow>[]>(() => [
    {
      key: "delta_pct",
      title: t("page.estimates.delta", "Delta %"),
      width: 120,
      value: (s) => s.delta_pct,
      render: (v) => `${(Number(v) * 100).toFixed(1)}%`,
    },
    {
      key: "tce",
      title: "TCE",
      width: 130,
      align: "right",
      value: (s) => s.tce,
      render: (v) => <Num v={Number(v)} digits={2} />,
    },
  ], [t]);

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.estimates", "Estimates") }]}
        title={t("page.estimates.title", "Estimate Desk")}
        subtitle={t("page.estimates.sub", "Build voyage / TCT estimates, calculate TCE, compare and convert to CP.")}
        actions={
          <div className="quick-row">
            <PageGuide pageKey="estimates" />
            <SavedViews storageKey="estimates_list" onApply={(q) => router.replace(`/estimates${q}`)} />
            <Link href="/settings/recycle" className="btn btn-ghost">
              {t("nav.recycle", "回收站")}
            </Link>
            <button className="btn btn-ghost" type="button" disabled={busy} onClick={() => createDraft(DRY_BULK, "Dry bulk sample")}>
              {t("page.estimates.tpl_dry", "Template: dry bulk")}
            </button>
            <button className="btn btn-ghost" type="button" disabled={busy} onClick={() => createDraft(TANKER, "Tanker WS sample")}>
              {t("page.estimates.tpl_tanker", "Template: tanker")}
            </button>
          </div>
        }
      />

      {err ? <p className="flash-err">{err}</p> : null}
      {refErr ? (
        <p className="flash-err">
          {t("page.estimates.ref_load_failed", "Reference data failed to load: {msg}", { msg: refErr })}
        </p>
      ) : null}

      <div className="desk-split">
        <div className="panel desk-list">
          <Toolbar
            filterCount={filterCount}
            onClearFilters={() => setQuery({ q: null, status: null }, { resetPage: true })}
            right={
              <>
                <input
                  className="input input-sm"
                  placeholder={t("page.estimates.search", "Search estimates…")}
                  value={searchQ}
                  onChange={(e) => setQuery({ q: e.target.value || null }, { resetPage: true })}
                  aria-label={t("page.estimates.search", "Search estimates…")}
                />
                <select
                  className="input input-sm"
                  value={statusFilter}
                  onChange={(e) => setQuery({ status: e.target.value || null }, { resetPage: true })}
                  aria-label={t("common.status", "Status")}
                >
                  <option value="">{t("page.estimates.all_status", "All statuses")}</option>
                  {ESTIMATE_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {t(`status.${s}`, s)}
                    </option>
                  ))}
                </select>
              </>
            }
          >
            <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => createDraft()}>
              {t("page.estimates.new", "新建")}
            </button>
            <button className="btn btn-sm" type="button" disabled={busy || compareIds.length < 2} onClick={() => void compare()}>
              {t("page.estimates.compare", "对比")}
            </button>
          </Toolbar>
          <StatusLegend statuses={ESTIMATE_STATUSES} />
          <StateView
            loading={loading}
            error={listErr ?? undefined}
            empty={!loading && !listErr && filteredRows.length === 0}
            emptyText={t("common.empty", "暂无记录")}
            onRetry={() => void reload()}
          >
            <ul className="desk-item-list">
              {filteredRows.map((r) => (
                <li key={r.id} className={r.id === selectedId ? "selected" : ""} onContextMenu={rowCtx.open(r)}>
                  <label className="desk-item-check" onClick={(e) => e.stopPropagation()} title={t("page.estimates.compare", "对比")}>
                    <input type="checkbox" checked={compareIds.includes(r.id)} onChange={() => toggleCompare(r.id)} />
                  </label>
                  <button type="button" className="desk-item-main" onClick={() => selectEstimate(r)}>
                    <span className="desk-item-title">{r.title}</span>
                    <span className="desk-item-meta">
                      <span>{t(`status.${r.status}`, r.status)}</span>
                      <span>
                        TCE <Num v={r.results?.tce} digits={2} />
                      </span>
                      <span>v{r.version}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </StateView>
          <ContextMenu controller={rowCtx} items={rowMenuItems} />
        </div>

        <div className="panel">
          <div className="desk-toolbar">
            <button className="btn btn-primary btn-sm" type="button" disabled={busy || !selectedId} onClick={save}>
              {t("common.save", "Save")}
            </button>
            <button className="btn btn-sm" type="button" disabled={busy || !selectedId} onClick={calculate}>
              {t("page.estimates.calculate", "Calculate")}
            </button>
            <button className="btn btn-sm" type="button" disabled={busy || !selectedId} onClick={() => void clone()}>
              {t("page.estimates.clone", "Clone")}
            </button>
            <button className="btn btn-sm" type="button" disabled={busy || !selectedId} onClick={() => runSensitivity()}>
              {t("page.estimates.sensitivity", "Sensitivity")}
            </button>
            <button className="btn btn-sm" type="button" disabled={busy || !selectedId} onClick={toCp}>
              {t("page.estimates.to_cp", "To CP")}
            </button>
            <ValidateButton onValidate={validateEstimate} disabled={!selectedId} />
            <AiFill
              formFields={fields as unknown as Record<string, unknown>}
              entityType="estimate"
              entityId={selectedId || undefined}
              onApply={(sug) => {
                setFields((prev) => {
                  const next = { ...prev };
                  for (const [k, v] of Object.entries(sug)) {
                    if (k in next) (next as Record<string, string>)[k] = v == null ? "" : String(v);
                  }
                  return next;
                });
                toast.success(t("ai.fill.applied", "已应用 AI 建议值 — 请复核后保存"));
              }}
            />
            <button className="btn btn-danger btn-sm" type="button" disabled={busy || !selectedId} onClick={() => setConfirmDel(true)}>
              {t("common.delete", "删除")}
            </button>
          </div>

          <div className="form-grid">
            <label>
              {t("common.title", "Title")}
              <input value={title} onChange={(e) => setTitle(e.target.value)} />
            </label>
            <label>
              {t("page.estimates.mode", "Mode")}
              <select value={mode} onChange={(e) => setMode(e.target.value as "voyage" | "tct")}>
                <option value="voyage">voyage</option>
                <option value="tct">tct</option>
              </select>
            </label>
            <label>
              {t("page.estimates.vessel", "Vessel")}
              <select value={vesselId} onChange={(e) => setVesselId(e.target.value)}>
                <option value="">{t("common.select", "Select…")}</option>
                {vessels.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("page.estimates.counterparty", "Counterparty")}
              <PartyPicker value={partyId} onChange={setPartyId} />
            </label>
            {inputDefs.map((d) => (
              <label key={d.key}>
                {d.label}
                <input
                  type="number"
                  step="any"
                  value={fields[d.key]}
                  onChange={(e) => setField(d.key, e.target.value)}
                  disabled={legRows.length > 0 && (d.key === "sea_days" || d.key === "port_days")}
                  title={
                    legRows.length > 0 && (d.key === "sea_days" || d.key === "port_days")
                      ? t("page.estimates.legs_auto", "由航段自动推导")
                      : undefined
                  }
                />
              </label>
            ))}
          </div>
          {legRows.length > 0 ? (
            <p className="muted" style={{ marginTop: "0.35rem" }}>
              {t("page.estimates.legs_auto_hint", "已配置航段（legs）：sea days / port days 由航段距离、航速与港口天自动推导。")}
            </p>
          ) : null}

          <div className="desk-section">
            <h3>{t("page.estimates.legs", "航段 Legs")}</h3>
            {legRows.map((leg, i) => (
              <div key={i} className="form-grid" style={{ marginBottom: "0.5rem" }}>
                <label>
                  {t("page.estimates.leg_from", "From")}
                  <input value={leg.from_port} onChange={(e) => setLeg(i, "from_port", e.target.value)} placeholder="SIN" />
                </label>
                <label>
                  {t("page.estimates.leg_to", "To")}
                  <input value={leg.to_port} onChange={(e) => setLeg(i, "to_port", e.target.value)} placeholder="RTM" />
                </label>
                <label>
                  {t("page.estimates.leg_distance", "Distance nm")}
                  <input type="number" step="any" value={leg.distance_nm} onChange={(e) => setLeg(i, "distance_nm", e.target.value)} />
                </label>
                <label>
                  {t("page.estimates.leg_speed", "Speed kn")}
                  <input type="number" step="any" value={leg.speed_kn} onChange={(e) => setLeg(i, "speed_kn", e.target.value)} />
                </label>
                <label>
                  {t("page.estimates.port_days", "Port days")}
                  <input type="number" step="any" value={leg.port_days} onChange={(e) => setLeg(i, "port_days", e.target.value)} />
                </label>
                <label>
                  {t("page.estimates.cargo_qty", "Cargo qty")}
                  <input type="number" step="any" value={leg.cargo_qty} onChange={(e) => setLeg(i, "cargo_qty", e.target.value)} />
                </label>
                <div style={{ display: "flex", alignItems: "end" }}>
                  <button className="btn btn-danger btn-sm" type="button" onClick={() => setLegRows((prev) => prev.filter((_, x) => x !== i))}>
                    {t("common.delete", "删除")}
                  </button>
                </div>
              </div>
            ))}
            <button className="btn btn-sm" type="button" onClick={() => setLegRows((prev) => [...prev, { ...EMPTY_LEG }])}>
              {t("page.estimates.add_leg", "添加航段")}
            </button>
          </div>

          <div className="desk-section">
            <h3>{t("page.estimates.cargoes", "多货 Parcels")}</h3>
            <p className="muted editor-hint">
              {t(
                "page.estimates.cargoes_hint",
                "每票货独立计价（per MT / Lump / WS）；空白字段继承上方顶层输入。填一票以上即按多货模式计总运费。",
              )}
            </p>
            {cargoRows.map((cargo, i) => (
              <div key={i} className="form-grid editor-row">
                <label>
                  {t("page.estimates.cargo_qty", "Cargo qty")}
                  <input type="number" step="any" value={cargo.qty} onChange={(e) => setCargo(i, "qty", e.target.value)} />
                </label>
                <label>
                  {t("page.estimates.cargo_basis", "Freight basis")}
                  <select value={cargo.freight_basis} onChange={(e) => setCargo(i, "freight_basis", e.target.value)}>
                    <option value="">{t("page.estimates.cargo_basis_inherit", "继承顶层")}</option>
                    {CARGO_BASES.map((b) => (
                      <option key={b} value={b}>
                        {b}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  {t("page.estimates.cargo_rate", "Rate / MT")}
                  <input type="number" step="any" value={cargo.freight_rate} onChange={(e) => setCargo(i, "freight_rate", e.target.value)} />
                </label>
                <label>
                  {t("page.estimates.cargo_lump", "Lump sum")}
                  <input type="number" step="any" value={cargo.lump_sum_freight} onChange={(e) => setCargo(i, "lump_sum_freight", e.target.value)} />
                </label>
                <label>
                  {t("page.estimates.cargo_ws_flat", "WS flat")}
                  <input type="number" step="any" value={cargo.ws_flat} onChange={(e) => setCargo(i, "ws_flat", e.target.value)} />
                </label>
                <label>
                  {t("page.estimates.cargo_ws_pct", "WS %")}
                  <input type="number" step="any" value={cargo.ws_pct} onChange={(e) => setCargo(i, "ws_pct", e.target.value)} />
                </label>
                <label>
                  {t("page.estimates.cargo_type", "Cargo type")}
                  <input value={cargo.cargo_type} onChange={(e) => setCargo(i, "cargo_type", e.target.value)} placeholder="Coal" />
                </label>
                <label>
                  {t("page.estimates.leg_from", "From")}
                  <input value={cargo.load_port} onChange={(e) => setCargo(i, "load_port", e.target.value)} placeholder="CNTXG" />
                </label>
                <label>
                  {t("page.estimates.leg_to", "To")}
                  <input value={cargo.disch_port} onChange={(e) => setCargo(i, "disch_port", e.target.value)} placeholder="NLRTM" />
                </label>
                <div className="editor-actions">
                  <button className="btn btn-danger btn-sm" type="button" onClick={() => setCargoRows((prev) => prev.filter((_, x) => x !== i))}>
                    {t("common.delete", "删除")}
                  </button>
                </div>
              </div>
            ))}
            <button className="btn btn-sm" type="button" onClick={() => setCargoRows((prev) => [...prev, { ...EMPTY_CARGO }])}>
              {t("page.estimates.add_cargo", "添加票货")}
            </button>
          </div>

          <div className="desk-section">
            <h3>{t("page.estimates.bunker_pricing", "燃油价格（多牌号）")}</h3>
            <div className="form-grid">
              <label>
                {t("page.estimates.bunker_grade", "Bunker grade")}
                <select value={bunkerGrade} onChange={(e) => setBunkerGrade(e.target.value)}>
                  {BUNKER_GRADES.map((g) => (
                    <option key={g} value={g}>
                      {g}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("page.estimates.bunker_eca_grade", "ECA grade")}
                <select value={bunkerEcaGrade} onChange={(e) => setBunkerEcaGrade(e.target.value)}>
                  {BUNKER_GRADES.map((g) => (
                    <option key={g} value={g}>
                      {g}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {priceRows.map((r, i) => (
              <div key={i} className="form-grid" style={{ marginTop: "0.5rem" }}>
                <label>
                  {t("page.bunker.grade", "Grade")}
                  <select value={r.grade} onChange={(e) => setPrice(i, "grade", e.target.value)}>
                    {BUNKER_GRADES.map((g) => (
                      <option key={g} value={g}>
                        {g}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  {t("page.bunker.price", "Unit price")}
                  <input type="number" step="any" value={r.price} onChange={(e) => setPrice(i, "price", e.target.value)} />
                </label>
                <div style={{ display: "flex", alignItems: "end" }}>
                  <button className="btn btn-danger btn-sm" type="button" onClick={() => setPriceRows((prev) => prev.filter((_, x) => x !== i))}>
                    {t("common.delete", "删除")}
                  </button>
                </div>
              </div>
            ))}
            <div style={{ marginTop: "0.5rem" }}>
              <button className="btn btn-sm" type="button" onClick={() => setPriceRows((prev) => [...prev, { grade: "VLSFO", price: "" }])}>
                {t("page.estimates.add_price", "添加牌号价格")}
              </button>
            </div>
          </div>

          <div className="desk-section">
            <h3>{t("page.estimates.carbon", "碳成本 EU ETS")}</h3>
            <div className="form-grid">
              <label>
                {t("page.estimates.eu_ets_share", "EU ETS share (0-1)")}
                <input type="number" step="any" min="0" max="1" value={fields.eu_ets_share} onChange={(e) => setField("eu_ets_share", e.target.value)} />
              </label>
              <label>
                {t("page.emissions.ets_price", "ETS price (EUR)")}
                <input type="number" step="any" value={fields.ets_price} onChange={(e) => setField("ets_price", e.target.value)} />
              </label>
              <label>
                {t("page.estimates.co2_factor", "CO₂ factor")}
                <input type="number" step="any" value={fields.co2_factor} onChange={(e) => setField("co2_factor", e.target.value)} placeholder="3.114" />
              </label>
            </div>
          </div>

          <div className="desk-section">
            <h3>{t("page.estimates.results", "Results")}</h3>
            <div className="desk-results">
              <div className="kv-box">
                <span>TCE</span>
                <strong>{fmt(results.tce)}</strong>
              </div>
              <div className="kv-box">
                <span>{t("page.estimates.gross_freight", "Gross freight")}</span>
                <strong>{fmt(results.gross_freight)}</strong>
              </div>
              <div className="kv-box">
                <span>{t("page.estimates.net_freight", "Net freight")}</span>
                <strong>{fmt(results.net_freight)}</strong>
              </div>
              <div className="kv-box">
                <span>{t("page.estimates.voyage_cost", "Voyage cost")}</span>
                <strong>{fmt(results.voyage_cost)}</strong>
              </div>
              <div className="kv-box">
                <span>{t("page.estimates.bunker_cost", "Bunker cost")}</span>
                <strong>{fmt(results.bunker_cost)}</strong>
              </div>
              <div className="kv-box">
                <span>{t("page.estimates.net_result", "Net result")}</span>
                <strong>{fmt(results.net_result)}</strong>
              </div>
              {results.address_commission !== undefined ? (
                <div className="kv-box">
                  <span>{t("page.estimates.address_comm_amt", "Address comm")}</span>
                  <strong>{fmt(results.address_commission)}</strong>
                </div>
              ) : null}
              {results.brokerage !== undefined ? (
                <div className="kv-box">
                  <span>{t("page.estimates.brokerage_amt", "Brokerage")}</span>
                  <strong>{fmt(results.brokerage)}</strong>
                </div>
              ) : null}
              <div className="kv-box">
                <span>{t("page.estimates.freight_basis", "Freight basis")}</span>
                <strong>{results.freight_basis || "—"}</strong>
              </div>
              <div className="kv-box">
                <span>{t("page.estimates.total_days", "Total days")}</span>
                <strong>{fmt(results.total_days)}</strong>
              </div>
              {results.fuel_mt !== undefined ? (
                <div className="kv-box">
                  <span>{t("page.estimates.fuel_mt", "Fuel mt")}</span>
                  <strong>{fmt(results.fuel_mt)}</strong>
                </div>
              ) : null}
              {results.co2_mt !== undefined ? (
                <div className="kv-box">
                  <span>{t("page.estimates.co2_mt", "CO₂ mt")}</span>
                  <strong>{fmt(results.co2_mt)}</strong>
                </div>
              ) : null}
              {results.emissions_cost !== undefined ? (
                <div className="kv-box">
                  <span>{t("page.estimates.emissions_cost", "Emissions cost")}</span>
                  <strong>{fmt(results.emissions_cost)}</strong>
                </div>
              ) : null}
              {results.cargo_qty_min !== undefined ? (
                <div className="kv-box">
                  <span>{t("page.estimates.cargo_qty_min", "Cargo qty min")}</span>
                  <strong>{fmt(results.cargo_qty_min)}</strong>
                </div>
              ) : null}
              {results.cargo_qty_max !== undefined ? (
                <div className="kv-box">
                  <span>{t("page.estimates.cargo_qty_max", "Cargo qty max")}</span>
                  <strong>{fmt(results.cargo_qty_max)}</strong>
                </div>
              ) : null}
            </div>
            {results.cargoes?.length ? (
              <div className="editor-block">
                <p className="muted editor-caption">
                  {t("page.estimates.cargo_breakdown", "票货明细")} · {t("page.estimates.cargo_count", "票数")}{" "}
                  {results.cargo_count} · {t("page.estimates.parcel_qty_total", "总货量")} {fmt(results.parcel_qty_total)} MT
                </p>
                <table className="table table-sm">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>{t("page.estimates.cargo_qty", "Cargo qty")}</th>
                      <th>{t("page.estimates.cargo_basis", "Freight basis")}</th>
                      <th>{t("page.estimates.base_freight", "Base freight")}</th>
                      <th>{t("page.estimates.cargo_type", "Cargo type")}</th>
                      <th>{t("page.estimates.leg_from", "From")}</th>
                      <th>{t("page.estimates.leg_to", "To")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.cargoes.map((c) => (
                      <tr key={c.index}>
                        <td>{c.index + 1}</td>
                        <td>{fmt(c.qty)}</td>
                        <td>{c.freight_basis}</td>
                        <td>{fmt(c.base_freight)}</td>
                        <td>{c.cargo_type || "—"}</td>
                        <td>{c.load_port || "—"}</td>
                        <td>{c.disch_port || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            {results.inputs_enriched && Object.keys(results.inputs_enriched).length ? (
              <p className="muted enriched-note" title={JSON.stringify(results.inputs_enriched)}>
                {t("page.estimates.enriched_note", "已按船舶档案/燃油区/行情自动补全")}：{" "}
                {Object.keys(results.inputs_enriched).join(" · ")}
              </p>
            ) : null}
            {results.warnings?.length ? (
              <div style={{ marginTop: "0.75rem" }}>
                {results.warnings.map((w, i) => (
                  <p key={i} style={{ color: "var(--warn-text)", fontWeight: 600, margin: "0.25rem 0" }}>
                    <span className="badge badge-warn" style={{ marginRight: "0.4rem" }}>{w.code}</span>
                    {w.message}
                  </p>
                ))}
              </div>
            ) : null}
            {selected ? (
              <p className="muted">
                {t(`status.${selected.status}`, selected.status)} · v{selected.version}
              </p>
            ) : null}
          </div>

          {sensitivity.length ? (
            <div className="desk-section">
              <h3>{t("page.estimates.sensitivity_table", "Sensitivity (freight_rate)")}</h3>
              <DataGrid<SensitivityRow>
                columns={sensitivityColumns}
                data={sensitivity}
                rowKey={(_s, i) => String(i)}
                storageKey="estimates_sensitivity_grid"
                showFooter={false}
                showColumnMenu={false}
                emptyText={t("common.empty", "No records")}
              />
            </div>
          ) : null}

        </div>
      </div>

      {/* 对比结果：右缘滑出面板 — 无遮罩，列表/勾选区保持可操作 */}
      {compareVariants.length >= 2 ? (
        <>
          <button
            type="button"
            className={`compare-edge-tab ${compareOpen ? "open" : ""}`}
            onClick={() => setCompareOpen((v) => !v)}
            aria-expanded={compareOpen}
            aria-controls="estimate-compare-panel"
            title={t("page.estimates.compare_toggle", "Toggle compare panel")}
          >
            <span className="compare-edge-chevron" aria-hidden>
              {compareOpen ? "›" : "‹"}
            </span>
            <span>{t("page.estimates.compare_table", "Compare")}</span>
            <span className="compare-edge-count">{compareVariants.length}</span>
          </button>
          <aside
            id="estimate-compare-panel"
            className={`compare-slideover ${compareOpen ? "open" : ""}`}
            aria-hidden={!compareOpen}
          >
            <div className="compare-slideover-head">
              <strong>{t("page.estimates.compare_table", "Compare")}</strong>
              <span className="muted">
                {compareVariants.length} {t("compare.variants", "方案")}
              </span>
              <button
                type="button"
                className="icon-btn"
                onClick={() => setCompareOpen(false)}
                aria-label={t("common.close", "关闭")}
              >
                ×
              </button>
            </div>
            <div className="compare-slideover-body">
              <EstimateCompare
                variants={compareVariants}
                fields={COMPARE_FIELDS}
                highlightBest
              />
            </div>
          </aside>
        </>
      ) : null}
      <ConfirmDialog
        open={confirmDel}
        title={t("common.confirm", "确认操作")}
        message={t("common.confirm_delete", "Delete this record? It will move to the recycle bin and can be restored.")}
        danger
        onConfirm={() => {
          setConfirmDel(false);
          removeEstimate();
        }}
        onCancel={() => setConfirmDel(false)}
      />
    </AppShell>
  );
}

// Next 16: useSearchParams（useListQuery）须位于 Suspense 边界内
export default function Page() {
  return (
    <Suspense fallback={null}>
      <EstimatesPage />
    </Suspense>
  );
}
