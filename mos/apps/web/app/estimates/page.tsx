"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
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
  freight_basis?: string;
  total_days?: number;
  total_revenue?: number;
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
  freight_rate: string;
  lump_sum_freight: string;
  ws_flat: string;
  ws_pct: string;
  commission_pct: string;
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
};

const EMPTY_INPUTS: InputFields = {
  cargo_qty: "",
  freight_rate: "",
  lump_sum_freight: "",
  ws_flat: "",
  ws_pct: "",
  commission_pct: "2.5",
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
};

const DRY_BULK: Partial<InputFields> = {
  cargo_qty: "50000",
  freight_rate: "18.5",
  commission_pct: "2.5",
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
  commission_pct: "1.25",
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

function buildPayload(fields: InputFields): Record<string, number> {
  const out: Record<string, number> = {};
  (Object.keys(EMPTY_INPUTS) as Array<keyof InputFields>).forEach((k) => {
    const v = num(fields[k]);
    if (v !== undefined) out[k] = v;
  });
  return out;
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
  const [results, setResults] = useState<EstResults>({});
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [compareRows, setCompareRows] = useState<Array<{ id: string; title: string; version: number; tce?: number }>>([]);
  const [sensitivity, setSensitivity] = useState<Array<{ delta_pct: number; tce: number }>>([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

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
    setResults(est.results || {});
    setSensitivity([]);
  }

  function setField(key: keyof InputFields, value: string) {
    setFields((prev) => ({ ...prev, [key]: value }));
  }

  async function createDraft(preset?: Partial<InputFields>, presetTitle?: string) {
    setBusy(true);
    setErr("");
    try {
      const merged = { ...EMPTY_INPUTS, ...(preset || fields) };
      const est: Estimate = await apiPost("/api/v1/estimates", {
        title: presetTitle || title || "Draft estimate",
        mode,
        vessel_id: vesselId || vessels[0]?.id || null,
        counterparty_id: partyId || parties[0]?.id || null,
        inputs: buildPayload(merged),
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
        inputs: buildPayload(fields),
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
        inputs: buildPayload(fields),
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

  async function runSensitivity() {
    if (!selectedId) return;
    setBusy(true);
    try {
      const rowsSens = await apiPost(`/api/v1/estimates/${selectedId}/sensitivity?field=freight_rate`);
      setSensitivity(rowsSens);
      setMsg(t("page.estimates.sensitivity_ok", "Sensitivity ready"));
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
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
    if (!window.confirm(t("common.confirm_delete", "Delete this record? It will move to the recycle bin and can be restored."))) return;
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
    { key: "freight_rate", label: t("page.estimates.freight_rate", "Freight rate") },
    { key: "lump_sum_freight", label: t("page.estimates.lump_sum", "Lump sum freight") },
    { key: "ws_flat", label: t("page.estimates.ws_flat", "WS flat") },
    { key: "ws_pct", label: t("page.estimates.ws_pct", "WS %") },
    { key: "commission_pct", label: t("page.estimates.commission", "Commission %") },
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
              {t("page.estimates.new", "New")}
            </button>
            <button className="btn btn-sm" type="button" disabled={busy || compareIds.length < 2} onClick={compare}>
              {t("page.estimates.compare", "Compare")}
            </button>
          </div>
          <table className="table">
            <thead>
              <tr>
                <th></th>
                <th>{t("common.title", "Title")}</th>
                <th>{t("common.status", "Status")}</th>
                <th>TCE</th>
                <th>{t("page.estimates.ver", "Ver")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className={r.id === selectedId ? "selected" : ""} onClick={() => selectEstimate(r)}>
                  <td onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={compareIds.includes(r.id)} onChange={() => toggleCompare(r.id)} />
                  </td>
                  <td>{r.title}</td>
                  <td>{r.status}</td>
                  <td>{fmt(r.results?.tce)}</td>
                  <td>v{r.version}</td>
                </tr>
              ))}
              {!rows.length ? (
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
            <button className="btn btn-danger btn-sm" type="button" disabled={busy || !selectedId} onClick={removeEstimate}>
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
                <input type="number" step="any" value={fields[d.key]} onChange={(e) => setField(d.key, e.target.value)} />
              </label>
            ))}
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
              <div className="kv-box">
                <span>{t("page.estimates.freight_basis", "Freight basis")}</span>
                <strong>{results.freight_basis || "—"}</strong>
              </div>
              <div className="kv-box">
                <span>{t("page.estimates.total_days", "Total days")}</span>
                <strong>{fmt(results.total_days)}</strong>
              </div>
            </div>
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
    </AppShell>
  );
}
