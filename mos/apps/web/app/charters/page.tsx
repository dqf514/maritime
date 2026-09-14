"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { DateInput } from "@/components/DateInput";
import { RecordModal } from "@/components/RecordModal";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type RefItem = { id: string; name: string };
type Charter = {
  id: string;
  charter_no: string;
  charter_type: string;
  status: string;
  vessel_id: string | null;
  counterparty_id: string | null;
  estimate_id: string | null;
  laycan_from: string | null;
  laycan_to: string | null;
  commission_pct: number | null;
  freight_terms: Record<string, unknown>;
  clauses: Record<string, unknown>;
  sanctions_blocked: boolean;
  demurrage_rate: number | null;
  despatch_rate: number | null;
  laytime_terms: string | null;
  cp_form: string | null;
  freight_rate: number | null;
  freight_basis: string | null;
  cargo_qty: number | null;
  load_rate_pd: number | null;
  disch_rate_pd: number | null;
  address_comm_pct: number | null;
  brokerage_pct: number | null;
  hire_per_day: number | null;
  hire_cycle_days: number | null;
  delivery_at: string | null;
  redelivery_at: string | null;
  ets_responsibility: string | null;
};

type HireSummary = {
  charter_id: string;
  hire_per_day: number;
  gross_days: number;
  offhire_days: number;
  billable_days: number;
  amount_due: number;
  currency: string;
};

type Amendment = {
  id: string;
  seq: number;
  status: string;
  reason: string | null;
  changes: Record<string, unknown>;
  created_at: string | null;
};

type Lifting = {
  id: string;
  period_label: string;
  planned_qty: number | null;
  actual_qty?: number | null;
  status?: string;
  voyage_id?: string | null;
  laycan_from?: string | null;
  laycan_to?: string | null;
};

type AmendForm = {
  freight_rate: string;
  demurrage_rate: string;
  cargo_qty: string;
  hire_per_day: string;
  laycan_from: string;
  laycan_to: string;
  reason: string;
};

const EMPTY_AMEND: AmendForm = {
  freight_rate: "",
  demurrage_rate: "",
  cargo_qty: "",
  hire_per_day: "",
  laycan_from: "",
  laycan_to: "",
  reason: "",
};

type TermFields = {
  freight_basis: string;
  demurrage_rate: string;
  despatch_rate: string;
  laytime_terms: string;
  cp_form: string;
  load_rate_pd: string;
  disch_rate_pd: string;
  address_comm_pct: string;
  brokerage_pct: string;
  hire_per_day: string;
  hire_cycle_days: string;
  delivery_at: string;
  redelivery_at: string;
  ets_responsibility: string;
};

const EMPTY_TERMS: TermFields = {
  freight_basis: "",
  demurrage_rate: "",
  despatch_rate: "",
  laytime_terms: "",
  cp_form: "",
  load_rate_pd: "",
  disch_rate_pd: "",
  address_comm_pct: "",
  brokerage_pct: "",
  hire_per_day: "",
  hire_cycle_days: "",
  delivery_at: "",
  redelivery_at: "",
  ets_responsibility: "",
};

const TERM_NUM_KEYS = [
  "demurrage_rate",
  "despatch_rate",
  "load_rate_pd",
  "disch_rate_pd",
  "address_comm_pct",
  "brokerage_pct",
  "hire_per_day",
  "hire_cycle_days",
] as const;

function isTc(charterType: string) {
  return charterType === "time" || charterType === "tct";
}

function TermInputs({
  value,
  onChange,
  showTc,
}: {
  value: TermFields;
  onChange: (key: keyof TermFields, v: string) => void;
  showTc: boolean;
}) {
  const { t } = useI18n();
  return (
    <>
      <label>
        {t("page.charters.freight_basis", "Freight basis")}
        <select value={value.freight_basis} onChange={(e) => onChange("freight_basis", e.target.value)}>
          <option value="">—</option>
          <option value="per_mt">per_mt</option>
          <option value="lumpsum">lumpsum</option>
          <option value="worldscale">worldscale</option>
        </select>
      </label>
      <label>
        {t("page.charters.demurrage_rate", "Demurrage rate")}
        <input type="number" step="any" value={value.demurrage_rate} onChange={(e) => onChange("demurrage_rate", e.target.value)} />
      </label>
      <label>
        {t("page.charters.despatch_rate", "Despatch rate")}
        <input type="number" step="any" value={value.despatch_rate} onChange={(e) => onChange("despatch_rate", e.target.value)} />
      </label>
      <label>
        {t("page.charters.laytime_terms", "Laytime terms")}
        <select value={value.laytime_terms} onChange={(e) => onChange("laytime_terms", e.target.value)}>
          <option value="">—</option>
          <option value="SHINC">SHINC</option>
          <option value="SHEX">SHEX</option>
          <option value="SSHEX">SSHEX</option>
          <option value="SSHINC">SSHINC</option>
          <option value="FHEX">FHEX</option>
        </select>
      </label>
      <label>
        {t("page.charters.cp_form", "CP form")}
        <input list="cp-form-opts" value={value.cp_form} onChange={(e) => onChange("cp_form", e.target.value)} placeholder="GENCON / NYPE / …" />
        <datalist id="cp-form-opts">
          <option value="GENCON" />
          <option value="NYPE" />
          <option value="SHELLTIME" />
        </datalist>
      </label>
      <label>
        {t("page.charters.load_rate_pd", "Load rate / day")}
        <input type="number" step="any" value={value.load_rate_pd} onChange={(e) => onChange("load_rate_pd", e.target.value)} />
      </label>
      <label>
        {t("page.charters.disch_rate_pd", "Disch rate / day")}
        <input type="number" step="any" value={value.disch_rate_pd} onChange={(e) => onChange("disch_rate_pd", e.target.value)} />
      </label>
      <label>
        {t("page.charters.address_comm", "Address comm %")}
        <input type="number" step="any" value={value.address_comm_pct} onChange={(e) => onChange("address_comm_pct", e.target.value)} />
      </label>
      <label>
        {t("page.charters.brokerage", "Brokerage %")}
        <input type="number" step="any" value={value.brokerage_pct} onChange={(e) => onChange("brokerage_pct", e.target.value)} />
      </label>
      {showTc ? (
        <>
          <label>
            {t("page.charters.hire_per_day", "Hire / day")}
            <input type="number" step="any" value={value.hire_per_day} onChange={(e) => onChange("hire_per_day", e.target.value)} />
          </label>
          <label>
            {t("page.charters.hire_cycle_days", "Hire cycle days")}
            <input type="number" step="any" value={value.hire_cycle_days} onChange={(e) => onChange("hire_cycle_days", e.target.value)} />
          </label>
          <label>
            {t("page.charters.delivery_at", "Delivery at")}
            <DateInput value={value.delivery_at} onChange={(v) => onChange("delivery_at", v)} />
          </label>
          <label>
            {t("page.charters.redelivery_at", "Redelivery at")}
            <DateInput value={value.redelivery_at} onChange={(v) => onChange("redelivery_at", v)} />
          </label>
          <label>
            {t("page.charters.ets_responsibility", "ETS responsibility")}
            <select value={value.ets_responsibility} onChange={(e) => onChange("ets_responsibility", e.target.value)}>
              <option value="">—</option>
              <option value="owner">owner</option>
              <option value="charterer">charterer</option>
            </select>
          </label>
        </>
      ) : null}
    </>
  );
}

function charterTermsPayload(freightRate: string, cargoQty: string, tm: TermFields) {
  const out: Record<string, number | string> = {};
  if (freightRate !== "") out.freight_rate = Number(freightRate);
  if (cargoQty !== "") out.cargo_qty = Number(cargoQty);
  TERM_NUM_KEYS.forEach((k) => {
    if (tm[k] !== "") out[k] = Number(tm[k]);
  });
  if (tm.freight_basis) out.freight_basis = tm.freight_basis;
  if (tm.laytime_terms) out.laytime_terms = tm.laytime_terms.toUpperCase();
  if (tm.cp_form) out.cp_form = tm.cp_form.toUpperCase();
  if (tm.delivery_at) out.delivery_at = tm.delivery_at;
  if (tm.redelivery_at) out.redelivery_at = tm.redelivery_at;
  if (tm.ets_responsibility) out.ets_responsibility = tm.ets_responsibility;
  return out;
}

export default function ChartersPage() {
  const { t } = useI18n();
  const [rows, setRows] = useState<Charter[]>([]);
  const [vessels, setVessels] = useState<RefItem[]>([]);
  const [parties, setParties] = useState<RefItem[]>([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const [charterType, setCharterType] = useState("voyage");
  const [vesselId, setVesselId] = useState("");
  const [partyId, setPartyId] = useState("");
  const [laycanFrom, setLaycanFrom] = useState("");
  const [laycanTo, setLaycanTo] = useState("");
  const [commission, setCommission] = useState("2.5");
  const [freightRate, setFreightRate] = useState("");
  const [cargoQty, setCargoQty] = useState("");
  const [terms, setTerms] = useState<TermFields>(EMPTY_TERMS);
  const [clausesNotes, setClausesNotes] = useState("");
  const [liftPeriod, setLiftPeriod] = useState("2026-Q4");
  const [liftQty, setLiftQty] = useState("50000");
  const [open, setOpen] = useState<Charter | null>(null);
  const [edit, setEdit] = useState({
    charter_type: "voyage",
    vessel_id: "",
    counterparty_id: "",
    laycan_from: "",
    laycan_to: "",
    commission_pct: "2.5",
    freight_rate: "",
    cargo_qty: "",
    notes: "",
    ...EMPTY_TERMS,
  });
  const [hireSummary, setHireSummary] = useState<HireSummary | null>(null);
  const [hireErr, setHireErr] = useState("");
  const [saving, setSaving] = useState(false);
  const [voyages, setVoyages] = useState<Array<{ id: string; voyage_no: string }>>([]);
  const [amendments, setAmendments] = useState<Amendment[]>([]);
  const [amendForm, setAmendForm] = useState<AmendForm>(EMPTY_AMEND);
  const [liftings, setLiftings] = useState<Lifting[]>([]);
  const [liftAction, setLiftAction] = useState<{ id: string; kind: "nominate" | "fix" | "complete" } | null>(null);
  const [nomFrom, setNomFrom] = useState("");
  const [nomTo, setNomTo] = useState("");
  const [fixVoyage, setFixVoyage] = useState("");
  const [doneQty, setDoneQty] = useState("");

  function setTerm(key: keyof TermFields, value: string) {
    setTerms((prev) => ({ ...prev, [key]: value }));
  }

  const load = useCallback(async () => {
    const [c, v, p, voy] = await Promise.all([
      apiGet("/api/v1/charters"),
      apiGet("/api/v1/masterdata/vessels"),
      apiGet("/api/v1/masterdata/counterparties"),
      apiGet("/api/v1/voyages").catch(() => []),
    ]);
    setRows(c);
    setVessels(v);
    setParties(p);
    setVoyages(voy);
    if (!vesselId && v[0]?.id) setVesselId(v[0].id);
    if (!partyId && p[0]?.id) setPartyId(p[0].id);
  }, [vesselId, partyId]);

  useEffect(() => {
    load().catch(() => setErr(t("common.failed", "Failed")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const freight_terms: Record<string, number | string> = {};
      if (freightRate !== "") freight_terms.freight_rate = Number(freightRate);
      if (cargoQty !== "") {
        freight_terms.cargo_qty = Number(cargoQty);
        freight_terms.cargo = `Bulk ${cargoQty} mt`;
      }
      const cp = await apiPost("/api/v1/charters", {
        charter_type: charterType,
        vessel_id: vesselId || null,
        counterparty_id: partyId || null,
        laycan_from: laycanFrom || null,
        laycan_to: laycanTo || null,
        commission_pct: commission === "" ? null : Number(commission),
        freight_terms,
        ...charterTermsPayload(freightRate, cargoQty, terms),
        clauses: clausesNotes ? { notes: clausesNotes } : {},
      });
      setMsg(t("page.charters.created", "Created {no}", { no: cp.charter_no }));
      setFreightRate("");
      setCargoQty("");
      setTerms(EMPTY_TERMS);
      setClausesNotes("");
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function move(id: string, target: string) {
    setBusy(true);
    setErr("");
    try {
      await apiPost(`/api/v1/charters/${id}/transition`, { target });
      setMsg(t("page.charters.moved", "Moved to {target}", { target }));
      await load();
    } catch (ex: any) {
      const code = ex?.detail?.code || "";
      if (code === "WORKFLOW_REQUIRED" || String(ex?.message || "").includes("workflow")) {
        setErr(
          t(
            "page.charters.workflow_required",
            "Approval required via workflow inbox — open Approvals, or activate as tenant admin.",
          ),
        );
      } else if (code === "SANCTIONS_BLOCKED") {
        setErr(t("page.charters.sanctions_block", "Cannot activate — counterparty sanctions blocked."));
      } else {
        setErr(ex?.message || String(ex));
      }
    } finally {
      setBusy(false);
    }
  }

  async function loadLiftings(charterId: string) {
    const rows: Lifting[] = await apiGet(`/api/v1/charters/${charterId}/liftings`).catch(() => []);
    setLiftings(Array.isArray(rows) ? rows : []);
  }

  async function addLifting(id: string) {
    setBusy(true);
    setErr("");
    try {
      const q = new URLSearchParams({
        period_label: liftPeriod,
        planned_qty: String(Number(liftQty) || 0),
      });
      const res = await apiPost(`/api/v1/charters/${id}/liftings?${q.toString()}`);
      setMsg(t("page.charters.lifting_ok", "Lifting added: {period}", { period: res.period_label }));
      if (open?.id === id) await loadLiftings(id);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function loadAmendments(charterId: string) {
    const rows: Amendment[] = await apiGet(`/api/v1/charters/${charterId}/amendments`).catch(() => []);
    setAmendments(Array.isArray(rows) ? rows : []);
  }

  async function createAmendment() {
    if (!open) return;
    const changes: Record<string, number | string> = {};
    if (amendForm.freight_rate !== "") changes.freight_rate = Number(amendForm.freight_rate);
    if (amendForm.demurrage_rate !== "") changes.demurrage_rate = Number(amendForm.demurrage_rate);
    if (amendForm.cargo_qty !== "") changes.cargo_qty = Number(amendForm.cargo_qty);
    if (amendForm.hire_per_day !== "") changes.hire_per_day = Number(amendForm.hire_per_day);
    if (amendForm.laycan_from) changes.laycan_from = amendForm.laycan_from;
    if (amendForm.laycan_to) changes.laycan_to = amendForm.laycan_to;
    if (!Object.keys(changes).length) {
      setErr(t("page.charters.amend_empty", "请至少填写一个要变更的字段"));
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await apiPost(`/api/v1/charters/${open.id}/amendments`, { changes, reason: amendForm.reason || null });
      setMsg(t("page.charters.amend_ok", "变更单已提交，待批准"));
      setAmendForm(EMPTY_AMEND);
      await loadAmendments(open.id);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function amendTransition(amendmentId: string, action: "approve" | "reject") {
    if (!open) return;
    setBusy(true);
    setErr("");
    try {
      await apiPost(`/api/v1/charter-amendments/${amendmentId}/${action}`);
      setMsg(action === "approve" ? t("page.charters.amend_approved", "变更单已批准并应用") : t("page.charters.amend_rejected", "变更单已驳回"));
      await loadAmendments(open.id);
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  function startLiftAction(id: string, kind: "nominate" | "fix" | "complete") {
    setLiftAction({ id, kind });
    setNomFrom("");
    setNomTo("");
    setFixVoyage(voyages[0]?.id || "");
    setDoneQty("");
    setErr("");
  }

  async function runLiftAction() {
    if (!liftAction) return;
    setBusy(true);
    setErr("");
    try {
      let body: Record<string, unknown> | undefined;
      if (liftAction.kind === "nominate") {
        if (!nomFrom || !nomTo) {
          setErr(t("page.charters.need_laycan", "请填写 laycan 窗口"));
          setBusy(false);
          return;
        }
        body = { laycan_from: `${nomFrom}T00:00:00`, laycan_to: `${nomTo}T00:00:00` };
      } else if (liftAction.kind === "fix") {
        if (!fixVoyage) {
          setErr(t("page.charters.need_voyage", "请选择航次"));
          setBusy(false);
          return;
        }
        body = { voyage_id: fixVoyage };
      } else {
        body = doneQty !== "" ? { actual_qty: Number(doneQty) } : {};
      }
      const updated: Lifting = await apiPost(`/api/v1/coa-liftings/${liftAction.id}/${liftAction.kind}`, body);
      if (open) await loadLiftings(open.id);
      setMsg(t("page.charters.lifting_moved", "Lifting → {status}", { status: updated.status || liftAction.kind }));
      setLiftAction(null);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  function vesselName(id: string | null) {
    if (!id) return "—";
    return vessels.find((v) => v.id === id)?.name || id.slice(0, 8);
  }

  function partyName(id: string | null) {
    if (!id) return "—";
    return parties.find((p) => p.id === id)?.name || id.slice(0, 8);
  }

  function openRow(r: Charter) {
    const ft = r.freight_terms || {};
    const numStr = (v: number | null | undefined) => (v != null ? String(v) : "");
    setOpen(r);
    setHireSummary(null);
    setHireErr("");
    setAmendments([]);
    setAmendForm(EMPTY_AMEND);
    setLiftings([]);
    setLiftAction(null);
    loadAmendments(r.id).catch(() => undefined);
    if (r.charter_type === "coa") loadLiftings(r.id).catch(() => undefined);
    if (isTc(r.charter_type)) {
      apiGet(`/api/v1/charters/${r.id}/hire-summary`)
        .then((s: HireSummary) => setHireSummary(s))
        .catch((ex: any) => setHireErr(ex?.message || String(ex)));
    }
    setEdit({
      charter_type: r.charter_type,
      vessel_id: r.vessel_id || "",
      counterparty_id: r.counterparty_id || "",
      laycan_from: r.laycan_from || "",
      laycan_to: r.laycan_to || "",
      commission_pct: r.commission_pct != null ? String(r.commission_pct) : "",
      freight_rate: r.freight_rate != null ? String(r.freight_rate) : ft.freight_rate != null ? String(ft.freight_rate) : "",
      cargo_qty: r.cargo_qty != null ? String(r.cargo_qty) : ft.cargo_qty != null ? String(ft.cargo_qty) : "",
      notes: typeof (r.clauses || {}).notes === "string" ? String((r.clauses as any).notes) : "",
      freight_basis: r.freight_basis || "",
      demurrage_rate: numStr(r.demurrage_rate),
      despatch_rate: numStr(r.despatch_rate),
      laytime_terms: r.laytime_terms || "",
      cp_form: r.cp_form || "",
      load_rate_pd: numStr(r.load_rate_pd),
      disch_rate_pd: numStr(r.disch_rate_pd),
      address_comm_pct: numStr(r.address_comm_pct),
      brokerage_pct: numStr(r.brokerage_pct),
      hire_per_day: numStr(r.hire_per_day),
      hire_cycle_days: numStr(r.hire_cycle_days),
      delivery_at: r.delivery_at || "",
      redelivery_at: r.redelivery_at || "",
      ets_responsibility: r.ets_responsibility || "",
    });
  }

  async function saveCharter() {
    if (!open) return;
    setSaving(true);
    setErr("");
    try {
      const freight_terms: Record<string, number | string> = {
        ...((open.freight_terms || {}) as Record<string, number | string>),
      };
      if (edit.freight_rate !== "") freight_terms.freight_rate = Number(edit.freight_rate);
      if (edit.cargo_qty !== "") {
        freight_terms.cargo_qty = Number(edit.cargo_qty);
        freight_terms.cargo = `Bulk ${edit.cargo_qty} mt`;
      }
      await apiPatch(`/api/v1/charters/${open.id}`, {
        charter_type: edit.charter_type,
        vessel_id: edit.vessel_id || null,
        counterparty_id: edit.counterparty_id || null,
        clear_vessel: !edit.vessel_id,
        clear_counterparty: !edit.counterparty_id,
        laycan_from: edit.laycan_from || null,
        laycan_to: edit.laycan_to || null,
        commission_pct: edit.commission_pct === "" ? null : Number(edit.commission_pct),
        freight_terms,
        ...charterTermsPayload(edit.freight_rate, edit.cargo_qty, edit),
        clauses: edit.notes ? { notes: edit.notes } : {},
      });
      setMsg(t("common.saved", "已保存"));
      setOpen(null);
      await load();
    } catch (ex: any) {
      if (ex?.status === 409 && ex?.detail?.code === "AMENDMENT_REQUIRED") {
        setErr(t("page.charters.amendment_required", "租约已生效，关键条款请通过变更单修改（见下方变更单区块）。"));
      } else {
        setErr(String(ex));
      }
    } finally {
      setSaving(false);
    }
  }

  async function removeCharter() {
    if (!open) return;
    setSaving(true);
    try {
      await apiDelete(`/api/v1/charters/${open.id}`);
      setMsg(t("common.recycled", "已移入回收站"));
      setOpen(null);
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setSaving(false);
    }
  }

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.charters.title", "租约工作台")}</h1>
          <p className="page-sub">
            {t("page.charters.sub", "新建租约；点击行打开弹窗编辑、删除或推进状态。")}
          </p>
        </div>
        <Link href="/settings/recycle" className="btn btn-ghost">
          {t("nav.recycle", "回收站")}
        </Link>
      </div>

      {msg ? <p className="flash">{msg}</p> : null}
      {err ? <p className="flash-err">{err}</p> : null}

      <form className="panel" onSubmit={create}>
        <h3 style={{ marginTop: 0 }}>{t("page.charters.create", "New charter")}</h3>
        <div className="form-grid">
          <label>
            {t("page.charters.type", "Charter type")}
            <select value={charterType} onChange={(e) => setCharterType(e.target.value)}>
              <option value="voyage">voyage</option>
              <option value="time">time</option>
              <option value="tct">tct</option>
              <option value="coa">coa</option>
              <option value="bb">bb</option>
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
          <label>
            {t("page.charters.laycan_from", "Laycan from")}
            <DateInput value={laycanFrom} onChange={setLaycanFrom} />
          </label>
          <label>
            {t("page.charters.laycan_to", "Laycan to")}
            <DateInput value={laycanTo} onChange={setLaycanTo} />
          </label>
          <label>
            {t("page.estimates.commission", "Commission %")}
            <input type="number" step="any" value={commission} onChange={(e) => setCommission(e.target.value)} />
          </label>
          <label>
            {t("page.estimates.freight_rate", "Freight rate")}
            <input type="number" step="any" value={freightRate} onChange={(e) => setFreightRate(e.target.value)} />
          </label>
          <label>
            {t("page.estimates.cargo_qty", "Cargo qty")}
            <input type="number" step="any" value={cargoQty} onChange={(e) => setCargoQty(e.target.value)} />
          </label>
          <TermInputs value={terms} onChange={setTerm} showTc={isTc(charterType)} />
          <label style={{ gridColumn: "1 / -1" }}>
            {t("page.charters.clauses", "Clauses / notes")}
            <input value={clausesNotes} onChange={(e) => setClausesNotes(e.target.value)} placeholder="CP notes" />
          </label>
        </div>
        <div className="desk-toolbar">
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {t("common.create", "Create")}
          </button>
        </div>
      </form>

      {charterType === "coa" || rows.some((r) => r.charter_type === "coa") ? (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>{t("page.charters.lifting_form", "COA lifting defaults")}</h3>
          <div className="form-grid">
            <label>
              {t("page.charters.period", "Period label")}
              <input value={liftPeriod} onChange={(e) => setLiftPeriod(e.target.value)} />
            </label>
            <label>
              {t("page.charters.planned_qty", "Planned qty")}
              <input type="number" step="any" value={liftQty} onChange={(e) => setLiftQty(e.target.value)} />
            </label>
          </div>
        </div>
      ) : null}

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.charters.list", "Fixtures")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.charters.no", "编号")}</th>
              <th>{t("common.type", "类型")}</th>
              <th>{t("common.status", "状态")}</th>
              <th>{t("page.estimates.vessel", "船舶")}</th>
              <th>{t("page.estimates.counterparty", "对手方")}</th>
              <th>{t("page.charters.sanctions", "制裁")}</th>
              <th>{t("page.charters.estimate", "估算")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="row-openable" onClick={() => openRow(r)}>
                <td>{r.charter_no}</td>
                <td>{r.charter_type}</td>
                <td>{r.status}</td>
                <td>{vesselName(r.vessel_id)}</td>
                <td>{partyName(r.counterparty_id)}</td>
                <td>
                  {r.sanctions_blocked ? (
                    <span className="badge badge-fail">{t("page.charters.blocked", "BLOCKED")}</span>
                  ) : (
                    <span className="badge badge-pass">{t("page.charters.clear", "clear")}</span>
                  )}
                </td>
                <td>
                  {r.estimate_id ? (
                    <Link href="/estimates" onClick={(e) => e.stopPropagation()}>
                      {r.estimate_id.slice(0, 8)}
                    </Link>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
            {!rows.length ? (
              <tr>
                <td colSpan={7} className="muted">
                  {t("common.empty", "暂无记录")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <RecordModal
        open={Boolean(open)}
        title={open ? `${t("page.charters.edit", "编辑租约")} · ${open.charter_no}` : ""}
        onClose={() => setOpen(null)}
        onSave={saveCharter}
        onDelete={removeCharter}
        saving={saving || busy}
      >
        <p className="muted">
          {t("common.status", "状态")}: {open?.status}
        </p>
        <label>
          {t("page.charters.type", "类型")}
          <select value={edit.charter_type} onChange={(e) => setEdit({ ...edit, charter_type: e.target.value })}>
            <option value="voyage">voyage</option>
            <option value="time">time</option>
            <option value="tct">tct</option>
            <option value="coa">coa</option>
            <option value="bb">bb</option>
          </select>
        </label>
        <label>
          {t("page.estimates.vessel", "船舶")}
          <select value={edit.vessel_id} onChange={(e) => setEdit({ ...edit, vessel_id: e.target.value })}>
            <option value="">—</option>
            {vessels.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("page.estimates.counterparty", "对手方")}
          <select value={edit.counterparty_id} onChange={(e) => setEdit({ ...edit, counterparty_id: e.target.value })}>
            <option value="">—</option>
            {parties.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("page.charters.laycan_from", "Laycan from")}
          <DateInput value={edit.laycan_from} onChange={(v) => setEdit({ ...edit, laycan_from: v })} />
        </label>
        <label>
          {t("page.charters.laycan_to", "Laycan to")}
          <DateInput value={edit.laycan_to} onChange={(v) => setEdit({ ...edit, laycan_to: v })} />
        </label>
        <label>
          {t("page.estimates.commission", "佣金 %")}
          <input value={edit.commission_pct} onChange={(e) => setEdit({ ...edit, commission_pct: e.target.value })} />
        </label>
        <label>
          {t("page.estimates.freight_rate", "运价")}
          <input value={edit.freight_rate} onChange={(e) => setEdit({ ...edit, freight_rate: e.target.value })} />
        </label>
        <label>
          {t("page.estimates.cargo_qty", "货量")}
          <input value={edit.cargo_qty} onChange={(e) => setEdit({ ...edit, cargo_qty: e.target.value })} />
        </label>
        <TermInputs value={edit} onChange={(k, v) => setEdit({ ...edit, [k]: v })} showTc={isTc(edit.charter_type)} />
        {open && isTc(open.charter_type) ? (
          <div className="desk-section" style={{ margin: "0.5rem 0" }}>
            <h3 style={{ marginTop: 0 }}>{t("page.charters.hire_summary", "Hire summary")}</h3>
            {hireSummary ? (
              <div className="desk-results">
                <div className="kv-box">
                  <span>{t("page.charters.billable_days", "Billable days")}</span>
                  <strong>{hireSummary.billable_days}</strong>
                </div>
                <div className="kv-box">
                  <span>{t("page.charters.amount_due", "Amount due")}</span>
                  <strong>
                    {hireSummary.amount_due.toLocaleString(undefined, { maximumFractionDigits: 2 })} {hireSummary.currency}
                  </strong>
                </div>
              </div>
            ) : (
              <p className="muted" style={{ margin: 0 }}>
                {hireErr || t("common.loading", "Loading…")}
              </p>
            )}
          </div>
        ) : null}
        {open?.charter_type === "coa" ? (
          <div className="desk-section" style={{ margin: "0.5rem 0" }}>
            <h3 style={{ marginTop: 0 }}>{t("page.charters.liftings", "COA liftings")}</h3>
            {liftings.length ? (
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("page.charters.period", "Period")}</th>
                    <th>{t("page.charters.planned_qty", "Planned qty")}</th>
                    <th>{t("common.status", "状态")}</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {liftings.map((l) => (
                    <tr key={l.id}>
                      <td>{l.period_label}</td>
                      <td>{l.planned_qty ?? "—"}</td>
                      <td>{l.status || "planned"}</td>
                      <td>
                        <div className="desk-toolbar" style={{ margin: 0 }}>
                          {(!l.status || l.status === "planned") ? (
                            <button className="btn btn-sm" type="button" disabled={busy} onClick={() => startLiftAction(l.id, "nominate")}>
                              {t("page.charters.nominate", "Nominate")}
                            </button>
                          ) : null}
                          {l.status === "nominated" ? (
                            <button className="btn btn-sm" type="button" disabled={busy} onClick={() => startLiftAction(l.id, "fix")}>
                              {t("page.charters.fix", "Fix")}
                            </button>
                          ) : null}
                          {l.status === "fixed" ? (
                            <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => startLiftAction(l.id, "complete")}>
                              {t("page.charters.complete", "完成")}
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted" style={{ margin: 0 }}>{t("page.charters.no_liftings", "暂无 lifting")}</p>
            )}
            {liftAction ? (
              <div className="form-grid" style={{ marginTop: "0.5rem" }}>
                {liftAction.kind === "nominate" ? (
                  <>
                    <label>
                      {t("page.charters.laycan_from", "Laycan from")}
                      <DateInput value={nomFrom} onChange={setNomFrom} />
                    </label>
                    <label>
                      {t("page.charters.laycan_to", "Laycan to")}
                      <DateInput value={nomTo} onChange={setNomTo} />
                    </label>
                  </>
                ) : null}
                {liftAction.kind === "fix" ? (
                  <label>
                    {t("page.voyages.list", "Voyages")}
                    <select value={fixVoyage} onChange={(e) => setFixVoyage(e.target.value)}>
                      <option value="">{t("common.select", "Select…")}</option>
                      {voyages.map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.voyage_no}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
                {liftAction.kind === "complete" ? (
                  <label>
                    {t("page.charters.actual_qty", "Actual qty")}
                    <input type="number" step="any" value={doneQty} onChange={(e) => setDoneQty(e.target.value)} placeholder={t("common.optional", "Optional")} />
                  </label>
                ) : null}
                <div style={{ display: "flex", alignItems: "end", gap: "0.5rem" }}>
                  <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={runLiftAction}>
                    {t("common.confirm", "确认")}
                  </button>
                  <button className="btn btn-ghost btn-sm" type="button" onClick={() => setLiftAction(null)}>
                    {t("common.cancel", "取消")}
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
        <div className="desk-section" style={{ margin: "0.5rem 0" }}>
          <h3 style={{ marginTop: 0 }}>{t("page.charters.amendments", "变更单 Amendments")}</h3>
          {amendments.length ? (
            <table className="table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>{t("common.status", "状态")}</th>
                  <th>{t("page.finance.reason", "Reason")}</th>
                  <th>{t("page.charters.amend_changes", "变更内容")}</th>
                  <th>{t("common.created_at", "创建时间")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {amendments.map((a) => (
                  <tr key={a.id}>
                    <td>{a.seq}</td>
                    <td>{a.status}</td>
                    <td>{a.reason || "—"}</td>
                    <td>
                      {Object.entries(a.changes || {})
                        .map(([k, v]) => `${k}=${v}`)
                        .join(", ") || "—"}
                    </td>
                    <td>{a.created_at ? new Date(a.created_at).toLocaleDateString() : "—"}</td>
                    <td>
                      {a.status === "proposed" ? (
                        <div className="desk-toolbar" style={{ margin: 0 }}>
                          <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => amendTransition(a.id, "approve")}>
                            {t("common.approve", "批准")}
                          </button>
                          <button className="btn btn-danger btn-sm" type="button" disabled={busy} onClick={() => amendTransition(a.id, "reject")}>
                            {t("common.reject", "驳回")}
                          </button>
                        </div>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted" style={{ margin: 0 }}>{t("page.charters.no_amendments", "暂无变更单")}</p>
          )}
          <div className="form-grid" style={{ marginTop: "0.5rem" }}>
            <label>
              {t("page.estimates.freight_rate", "运价")}
              <input type="number" step="any" value={amendForm.freight_rate} onChange={(e) => setAmendForm({ ...amendForm, freight_rate: e.target.value })} />
            </label>
            <label>
              {t("page.charters.demurrage_rate", "Demurrage rate")}
              <input type="number" step="any" value={amendForm.demurrage_rate} onChange={(e) => setAmendForm({ ...amendForm, demurrage_rate: e.target.value })} />
            </label>
            <label>
              {t("page.estimates.cargo_qty", "货量")}
              <input type="number" step="any" value={amendForm.cargo_qty} onChange={(e) => setAmendForm({ ...amendForm, cargo_qty: e.target.value })} />
            </label>
            <label>
              {t("page.charters.hire_per_day", "Hire / day")}
              <input type="number" step="any" value={amendForm.hire_per_day} onChange={(e) => setAmendForm({ ...amendForm, hire_per_day: e.target.value })} />
            </label>
            <label>
              {t("page.charters.laycan_from", "Laycan from")}
              <DateInput value={amendForm.laycan_from} onChange={(v) => setAmendForm({ ...amendForm, laycan_from: v })} />
            </label>
            <label>
              {t("page.charters.laycan_to", "Laycan to")}
              <DateInput value={amendForm.laycan_to} onChange={(v) => setAmendForm({ ...amendForm, laycan_to: v })} />
            </label>
            <label style={{ gridColumn: "1 / -1" }}>
              {t("page.finance.reason", "Reason")}
              <input value={amendForm.reason} onChange={(e) => setAmendForm({ ...amendForm, reason: e.target.value })} />
            </label>
          </div>
          <div className="desk-toolbar" style={{ marginTop: "0.5rem" }}>
            <button className="btn btn-sm" type="button" disabled={busy} onClick={createAmendment}>
              {t("page.charters.new_amendment", "新建变更单")}
            </button>
          </div>
        </div>
        <label>
          {t("page.charters.notes", "条款备注")}
          <input value={edit.notes} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} />
        </label>
        <div className="desk-toolbar" style={{ marginTop: "0.5rem" }}>
          {open?.status === "draft" ? (
            <button className="btn btn-sm" type="button" disabled={busy} onClick={() => open && move(open.id, "pending_approval").then(() => setOpen(null))}>
              {t("common.submit", "提交审批")}
            </button>
          ) : null}
          {open?.status === "pending_approval" ? (
            <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => open && move(open.id, "active").then(() => setOpen(null))}>
              {t("common.activate", "激活")}
            </button>
          ) : null}
          {open?.status === "active" ? (
            <button className="btn btn-sm" type="button" disabled={busy} onClick={() => open && move(open.id, "completed").then(() => setOpen(null))}>
              {t("page.charters.complete", "完成")}
            </button>
          ) : null}
          {open?.charter_type === "coa" ? (
            <button className="btn btn-sm" type="button" disabled={busy} onClick={() => open && addLifting(open.id)}>
              {t("page.charters.add_lifting", "添加 lifting")}
            </button>
          ) : null}
        </div>
      </RecordModal>
    </AppShell>
  );
}
