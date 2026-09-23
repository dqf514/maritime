"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageGuide } from "@/components/PageGuide";
import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

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

type LegRow = {
  from_port: string;
  to_port: string;
  distance_nm: string;
  speed_kn: string;
  port_days: string;
  cargo_qty: string;
};

type PriceRow = { grade: string; price: string };

const EMPTY_LEG: LegRow = { from_port: "", to_port: "", distance_nm: "", speed_kn: "", port_days: "", cargo_qty: "" };

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

function fmt(n: number | string | undefined | null) {
  if (n === undefined || n === null || n === "") return "—";
  const v = typeof n === "number" ? n : Number(n);
  if (!Number.isFinite(v)) return String(n);
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export default function EstimatesPage() {
  const { t } = useI18n();
  const [rows, setRows] = useState<Estimate[]>([]);
  const [vessels, setVessels] = useState<RefItem[]>([]);
  const [parties, setParties] = useState<RefItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [title, setTitle] = useState("New voyage estimate");
  const [mode, setMode] = useState<"voyage" | "tct">("voyage");
  const [vesselId, setVesselId] = useState("");
  const [partyId, setPartyId] = useState("");
  const [fields, setFields] = useState<InputFields>(EMPTY_INPUTS);
  const [legRows, setLegRows] = useState<LegRow[]>([]);
  const [bunkerGrade, setBunkerGrade] = useState("VLSFO");
  const [bunkerEcaGrade, setBunkerEcaGrade] = useState("MGO");
  const [priceRows, setPriceRows] = useState<PriceRow[]>([]);
  const [results, setResults] = useState<EstResults>({});
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [compareRows, setCompareRows] = useState<Array<{ id: string; title: string; version: number; tce?: number }>>([]);
  const [sensitivity, setSensitivity] = useState<Array<{ delta_pct: number; tce: number }>>([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);

  const selected = useMemo(() => rows.find((r) => r.id === selectedId) || null, [rows, selectedId]);

  const loadMaster = useCallback(async () => {
    const [v, p] = await Promise.all([
      apiGet("/api/v1/masterdata/vessels"),
      apiGet("/api/v1/masterdata/counterparties"),
    ]);
    setVessels(v);
    setParties(p);
    if (!vesselId && v[0]?.id) setVesselId(v[0].id);
    if (!partyId && p[0]?.id) setPartyId(p[0].id);
  }, [vesselId, partyId]);

  const load = useCallback(async () => {
    const data: Estimate[] = await apiGet("/api/v1/estimates");
    setRows(data);
    return data;
  }, []);

  useEffect(() => {
    Promise.all([loadMaster(), load()])
      .then(([, data]) => {
        if (data[0] && !selectedId) selectEstimate(data[0]);
      })
      .catch(() => setErr(t("common.failed", "Failed")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function selectEstimate(est: Estimate) {
    setSelectedId(est.id);
    setTitle(est.title);
    setMode((est.mode as "voyage" | "tct") || "voyage");
    setVesselId(est.vessel_id || "");
    setPartyId(est.counterparty_id || "");
    setFields(inputsFromEst(est.inputs));
    const inp = (est.inputs || {}) as Record<string, unknown>;
    setLegRows(legRowsFromEst(inp));
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
    return { legs, bunker_grade: bunkerGrade, bunker_eca_grade: bunkerEcaGrade, bunker_prices };
  }

  function setLeg(idx: number, key: keyof LegRow, value: string) {
    setLegRows((prev) => prev.map((l, i) => (i === idx ? { ...l, [key]: value } : l)));
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
        setPriceRows([]);
      }
      const est: Estimate = await apiPost("/api/v1/estimates", {
        title: presetTitle || title || "Draft estimate",
        mode,
        vessel_id: vesselId || vessels[0]?.id || null,
        counterparty_id: partyId || parties[0]?.id || null,
        inputs: buildPayload(merged, extras),
      });
      setMsg(t("page.estimates.created", "Draft created"));
      const data = await load();
      const fresh = data.find((r) => r.id === est.id) || est;
      selectEstimate(fresh);
    } catch (e) {
      setErr(String(e));
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
      setMsg(t("page.estimates.saved", "Saved"));
      await load();
    } catch (e) {
      setErr(String(e));
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
      setMsg(t("page.estimates.calculated", "Calculated TCE {tce}", { tce: fmt(est.results?.tce) }));
      await load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function clone() {
    if (!selectedId) return;
    setBusy(true);
    try {
      const est: Estimate = await apiPost(`/api/v1/estimates/${selectedId}/clone`);
      setMsg(t("page.estimates.cloned", "Cloned to {title}", { title: est.title }));
      const data = await load();
      const fresh = data.find((r) => r.id === est.id) || est;
      selectEstimate(fresh);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  function runSensitivity() {
    if (!selectedId) return;
    window.location.href = `/estimates/${selectedId}/sensitivity`;
  }

  async function compare() {
    if (compareIds.length < 2) {
      setErr(t("page.estimates.compare_need", "Select at least 2 estimates to compare"));
      return;
    }
    setBusy(true);
    try {
      const data = await apiPost("/api/v1/estimates/compare", compareIds);
      setCompareRows(data);
      setMsg(t("page.estimates.compare_ok", "Compare ready"));
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function toCp() {
    if (!selectedId) return;
    setBusy(true);
    try {
      const cp = await apiPost(`/api/v1/estimates/${selectedId}/to-charter`);
      setMsg(t("page.estimates.cp_msg", "Created charter {no}", { no: cp.charter_no }));
      await load();
    } catch (e) {
      setErr(String(e));
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
      setMsg(t("common.recycled", "已移入回收站"));
      await load();
    } catch (e) {
      setErr(String(e));
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

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.estimates.title", "Estimate Desk")}</h1>
          <p className="page-sub">
            {t("page.estimates.sub", "Build voyage / TCT estimates, calculate TCE, compare and convert to CP.")}
          </p>
        </div>
        <div className="quick-row">
          <PageGuide pageKey="estimates" />
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
      </div>

      {msg ? <p className="flash">{msg}</p> : null}
      {err ? <p className="flash-err">{err}</p> : null}

      <div className="desk-split">
        <div className="panel desk-list">
          <div className="desk-toolbar">
            <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => createDraft()}>
              {t("page.estimates.new", "新建")}
            </button>
            <button className="btn btn-sm" type="button" disabled={busy || compareIds.length < 2} onClick={compare}>
              {t("page.estimates.compare", "对比")}
            </button>
          </div>
          <ul className="desk-item-list">
            {rows.map((r) => (
              <li key={r.id} className={r.id === selectedId ? "selected" : ""}>
                <label className="desk-item-check" onClick={(e) => e.stopPropagation()} title={t("page.estimates.compare", "对比")}>
                  <input type="checkbox" checked={compareIds.includes(r.id)} onChange={() => toggleCompare(r.id)} />
                </label>
                <button type="button" className="desk-item-main" onClick={() => selectEstimate(r)}>
                  <span className="desk-item-title">{r.title}</span>
                  <span className="desk-item-meta">
                    <span>{r.status}</span>
                    <span>TCE {fmt(r.results?.tce)}</span>
                    <span>v{r.version}</span>
                  </span>
                </button>
              </li>
            ))}
            {!rows.length ? <li className="desk-item-empty muted">{t("common.empty", "暂无记录")}</li> : null}
          </ul>
        </div>

        <div className="panel">
          <div className="desk-toolbar">
            <button className="btn btn-primary btn-sm" type="button" disabled={busy || !selectedId} onClick={save}>
              {t("common.save", "Save")}
            </button>
            <button className="btn btn-sm" type="button" disabled={busy || !selectedId} onClick={calculate}>
              {t("page.estimates.calculate", "Calculate")}
            </button>
            <button className="btn btn-sm" type="button" disabled={busy || !selectedId} onClick={clone}>
              {t("page.estimates.clone", "Clone")}
            </button>
            <button className="btn btn-sm" type="button" disabled={busy || !selectedId} onClick={runSensitivity}>
              {t("page.estimates.sensitivity", "Sensitivity")}
            </button>
            <button className="btn btn-sm" type="button" disabled={busy || !selectedId} onClick={toCp}>
              {t("page.estimates.to_cp", "To CP")}
            </button>
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
              <select value={partyId} onChange={(e) => setPartyId(e.target.value)}>
                <option value="">{t("common.select", "Select…")}</option>
                {parties.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
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
                  <span>{t("page.estimates.address_comm", "Address comm")}</span>
                  <strong>{fmt(results.address_commission)}</strong>
                </div>
              ) : null}
              {results.brokerage !== undefined ? (
                <div className="kv-box">
                  <span>{t("page.estimates.brokerage", "Brokerage")}</span>
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
            {results.warnings?.length ? (
              <div style={{ marginTop: "0.75rem" }}>
                {results.warnings.map((w, i) => (
                  <p key={i} style={{ color: "var(--warn)", fontWeight: 600, margin: "0.25rem 0" }}>
                    <span className="badge badge-warn" style={{ marginRight: "0.4rem" }}>{w.code}</span>
                    {w.message}
                  </p>
                ))}
              </div>
            ) : null}
            {selected ? (
              <p className="muted" style={{ marginTop: "0.75rem" }}>
                {selected.status} · v{selected.version}
              </p>
            ) : null}
          </div>

          {sensitivity.length ? (
            <div className="desk-section">
              <h3>{t("page.estimates.sensitivity_table", "Sensitivity (freight_rate)")}</h3>
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("page.estimates.delta", "Delta %")}</th>
                    <th>TCE</th>
                  </tr>
                </thead>
                <tbody>
                  {sensitivity.map((s, i) => (
                    <tr key={i}>
                      <td>{(s.delta_pct * 100).toFixed(1)}%</td>
                      <td>{fmt(s.tce)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          {compareRows.length ? (
            <div className="desk-section">
              <h3>{t("page.estimates.compare_table", "Compare")}</h3>
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("common.title", "Title")}</th>
                    <th>{t("page.estimates.ver", "Ver")}</th>
                    <th>TCE</th>
                  </tr>
                </thead>
                <tbody>
                  {compareRows.map((r) => (
                    <tr key={r.id}>
                      <td>{r.title}</td>
                      <td>v{r.version}</td>
                      <td>{fmt(r.tce)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      </div>
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
