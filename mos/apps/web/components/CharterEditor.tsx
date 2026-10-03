"use client";

// U2 单据详情：租约编辑器（原 charters 页弹窗的路由化版本）。
// 自包含：拉取租约 + 船舶/对手方/航次引用，承载编辑/状态推进/变更单/
// hire 汇总/COA liftings 全功能，供 /charters/[id] 详情页挂载。

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DateInput } from "@/components/DateInput";
import { PageHeader } from "@/components/PageHeader";
import { PartyPicker } from "@/components/DataPicker";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";
import { SkeletonCard } from "@/components/Skeleton";

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
  charter_direction: string | null;
  master_contract_id: string | null;
  fixture_type: string | null;
  exposure_amount: number | null;
  pricing_basis: string | null;
  rebill_settings: Record<string, unknown> | null;
  planning_periods: Record<string, unknown> | null;
  rev_exp: Record<string, unknown> | null;
  properties: Record<string, unknown> | null;
};

type MasterContractOpt = { id: string; contract_no: string; title: string; contract_type: string; status: string };

type BrokerRule = {
  id: string;
  charter_id: string;
  broker_party_id: string;
  commission_type: string;
  commission_pct: number | null;
  applies_to: string;
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

function numStr(v: number | null | undefined) {
  return v != null ? String(v) : "";
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
  const toast = useToast();
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

type ClauseOpt = {
  id: string;
  code: string;
  cp_form: string | null;
  category: string;
  title_en: string;
  title_zh: string | null;
  params: Record<string, unknown>;
  is_system: boolean;
};

export function CharterEditor({ charterId }: { charterId: string }) {
  const { t, locale } = useI18n();
  const toast = useToast();
  const [charter, setCharter] = useState<Charter | null>(null);
  const [vessels, setVessels] = useState<RefItem[]>([]);
  const [parties, setParties] = useState<RefItem[]>([]);
  const [voyages, setVoyages] = useState<Array<{ id: string; voyage_no: string }>>([]);
  const [clauseCatalog, setClauseCatalog] = useState<ClauseOpt[]>([]);
  const [clauseCodes, setClauseCodes] = useState<string[]>([]);
  const [edit, setEdit] = useState({
    charter_type: "voyage",
    vessel_id: "",
    counterparty_id: "",
    laycan_from: "",
    laycan_to: "",
    commission_pct: "",
    freight_rate: "",
    cargo_qty: "",
    notes: "",
    fixture_type: "voyage_fixture",
    charter_direction: "out",
    master_contract_id: "",
    exposure_amount: "",
    pricing_basis: "",
    rebill_json: "{}",
    planning_json: "{}",
    revexp_json: "{}",
    properties_json: "{}",
    ...EMPTY_TERMS,
  });
  const [tab, setTab] = useState("general");
  const [masters, setMasters] = useState<MasterContractOpt[]>([]);
  const [brokerRules, setBrokerRules] = useState<BrokerRule[]>([]);
  const [brForm, setBrForm] = useState({ broker_party_id: "", commission_type: "brokerage", commission_pct: "", applies_to: "all" });
  const [hireSummary, setHireSummary] = useState<HireSummary | null>(null);
  const [hireErr, setHireErr] = useState("");
  const [amendments, setAmendments] = useState<Amendment[]>([]);
  const [amendForm, setAmendForm] = useState<AmendForm>(EMPTY_AMEND);
  const [liftings, setLiftings] = useState<Lifting[]>([]);
  const [liftAction, setLiftAction] = useState<{ id: string; kind: "nominate" | "fix" | "complete" } | null>(null);
  const [nomFrom, setNomFrom] = useState("");
  const [nomTo, setNomTo] = useState("");
  const [fixVoyage, setFixVoyage] = useState("");
  const [doneQty, setDoneQty] = useState("");
  const [liftPeriod, setLiftPeriod] = useState("2026-Q4");
  const [liftQty, setLiftQty] = useState("50000");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [confirm, setConfirm] = useState<{ message: string; danger?: boolean; action: () => void } | null>(null);

  const loadCharter = useCallback(async () => {
    const r: Charter = await apiGet(`/api/v1/charters/${charterId}`);
    setCharter(r);
    setClauseCodes(Array.isArray((r.clauses || {}).codes) ? ((r.clauses as { codes?: string[] }).codes || []) : []);
    const ft = r.freight_terms || {};
    setEdit({
      charter_type: r.charter_type,
      vessel_id: r.vessel_id || "",
      counterparty_id: r.counterparty_id || "",
      laycan_from: r.laycan_from || "",
      laycan_to: r.laycan_to || "",
      commission_pct: r.commission_pct != null ? String(r.commission_pct) : "",
      freight_rate: r.freight_rate != null ? String(r.freight_rate) : ft.freight_rate != null ? String(ft.freight_rate) : "",
      cargo_qty: r.cargo_qty != null ? String(r.cargo_qty) : ft.cargo_qty != null ? String(ft.cargo_qty) : "",
      notes: typeof (r.clauses || {}).notes === "string" ? String((r.clauses as { notes?: unknown }).notes) : "",
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
      fixture_type: r.fixture_type || "voyage_fixture",
      charter_direction: r.charter_direction || "out",
      master_contract_id: r.master_contract_id || "",
      exposure_amount: numStr(r.exposure_amount),
      pricing_basis: r.pricing_basis || "",
      rebill_json: JSON.stringify(r.rebill_settings ?? {}, null, 2),
      planning_json: JSON.stringify(r.planning_periods ?? {}, null, 2),
      revexp_json: JSON.stringify(r.rev_exp ?? {}, null, 2),
      properties_json: JSON.stringify(r.properties ?? {}, null, 2),
    });
  }, [charterId]);

  const loadSide = useCallback(async () => {
    const [v, p, voy, ams, cls, mcs, brs] = await Promise.all([
      apiGet("/api/v1/masterdata/vessels"),
      apiGet("/api/v1/masterdata/counterparties"),
      apiGet("/api/v1/voyages").catch(() => []),
      apiGet(`/api/v1/charters/${charterId}/amendments`).catch(() => []),
      apiGet("/api/v1/clauses").catch(() => ({ items: [] })),
      apiGet("/api/v1/master-contracts").catch(() => []),
      apiGet(`/api/v1/charters/${charterId}/broker-rules`).catch(() => []),
    ]);
    setVessels(v);
    setParties(p);
    setVoyages(voy);
    setAmendments(Array.isArray(ams) ? ams : []);
    setClauseCatalog(Array.isArray(cls?.items) ? cls.items : []);
    setMasters(Array.isArray(mcs) ? mcs : (mcs?.items ?? []));
    setBrokerRules(Array.isArray(brs) ? brs : (brs?.items ?? []));
  }, [charterId]);

  useEffect(() => {
    Promise.all([loadCharter(), loadSide()])
      .catch((ex) => {
        if (ex?.status === 404) setNotFound(true);
        else setErr(String(ex));
      });
  }, [loadCharter, loadSide]);

  useEffect(() => {
    if (!charter) return;
    if (charter.charter_type === "coa") {
      apiGet(`/api/v1/charters/${charter.id}/liftings`)
        .then((rows: Lifting[]) => setLiftings(Array.isArray(rows) ? rows : []))
        .catch(() => setLiftings([]));
    }
    if (isTc(charter.charter_type)) {
      apiGet(`/api/v1/charters/${charter.id}/hire-summary`)
        .then((s: HireSummary) => setHireSummary(s))
        .catch((ex: unknown) => setHireErr(ex instanceof Error ? ex.message : String(ex)));
    }
  }, [charter]);

  async function save() {
    if (!charter) return;
    setSaving(true);
    setErr("");
    try {
      const freight_terms: Record<string, number | string> = {
        ...((charter.freight_terms || {}) as Record<string, number | string>),
      };
      if (edit.freight_rate !== "") freight_terms.freight_rate = Number(edit.freight_rate);
      if (edit.cargo_qty !== "") {
        freight_terms.cargo_qty = Number(edit.cargo_qty);
        freight_terms.cargo = `Bulk ${edit.cargo_qty} mt`;
      }
      const jsonField = (s: string): Record<string, unknown> | null => {
        const trimmed = s.trim();
        if (!trimmed) return null;
        return JSON.parse(trimmed);
      };
      await apiPatch(`/api/v1/charters/${charter.id}`, {
        charter_type: edit.charter_type,
        fixture_type: edit.fixture_type,
        charter_direction: edit.charter_direction,
        master_contract_id: edit.master_contract_id || null,
        vessel_id: edit.vessel_id || null,
        counterparty_id: edit.counterparty_id || null,
        clear_vessel: !edit.vessel_id,
        clear_counterparty: !edit.counterparty_id,
        laycan_from: edit.laycan_from || null,
        laycan_to: edit.laycan_to || null,
        commission_pct: edit.commission_pct === "" ? null : Number(edit.commission_pct),
        exposure_amount: edit.exposure_amount === "" ? null : Number(edit.exposure_amount),
        pricing_basis: edit.pricing_basis || null,
        rebill_settings: jsonField(edit.rebill_json),
        planning_periods: jsonField(edit.planning_json),
        rev_exp: jsonField(edit.revexp_json),
        properties: jsonField(edit.properties_json),
        freight_terms,
        ...charterTermsPayload(edit.freight_rate, edit.cargo_qty, edit),
        clauses: {
          ...((charter.clauses || {}) as Record<string, unknown>),
          codes: clauseCodes,
          ...(edit.notes ? { notes: edit.notes } : {}),
        },
      });
      toast.success(t("common.saved", "已保存"));
      await loadCharter();
    } catch (ex: any) {
      if (ex instanceof SyntaxError) {
        setErr(t("page.charters.invalid_json", "JSON 格式有误，请检查 Rebill / Exposure / Rev-Exp / Properties 选项卡"));
      } else if (ex?.status === 409 && ex?.detail?.code === "AMENDMENT_REQUIRED") {
        setErr(t("page.charters.amendment_required", "租约已生效，关键条款请通过变更单修改（见下方变更单区块）。"));
      } else {
        setErr(String(ex));
      }
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!charter) return;
    setSaving(true);
    try {
      await apiDelete(`/api/v1/charters/${charter.id}`);
      window.location.href = "/charters";
    } catch (ex) {
      setErr(String(ex));
      setSaving(false);
    }
  }

  async function move(target: string) {
    if (!charter) return;
    setBusy(true);
    setErr("");
    try {
      await apiPost(`/api/v1/charters/${charter.id}/transition`, { target });
      toast.success(t("page.charters.moved", "Moved to {target}", { target }));
      await loadCharter();
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

  async function addLifting() {
    if (!charter) return;
    setBusy(true);
    setErr("");
    try {
      const q = new URLSearchParams({
        period_label: liftPeriod,
        planned_qty: String(Number(liftQty) || 0),
      });
      const res = await apiPost(`/api/v1/charters/${charter.id}/liftings?${q.toString()}`);
      toast.success(t("page.charters.lifting_ok", "Lifting added: {period}", { period: res.period_label }));
      const rows: Lifting[] = await apiGet(`/api/v1/charters/${charter.id}/liftings`).catch(() => []);
      setLiftings(Array.isArray(rows) ? rows : []);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function addBrokerRule() {
    if (!charter) return;
    if (!brForm.broker_party_id) {
      setErr(t("page.charters.need_broker", "请选择经纪方"));
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await apiPost(`/api/v1/charters/${charter.id}/broker-rules`, {
        broker_party_id: brForm.broker_party_id,
        commission_type: brForm.commission_type,
        commission_pct: Number(brForm.commission_pct) || 0,
        applies_to: brForm.applies_to,
      });
      toast.success(t("page.charters.broker_added", "Broker rule added"));
      setBrForm({ broker_party_id: "", commission_type: "brokerage", commission_pct: "", applies_to: "all" });
      const rows: BrokerRule[] = await apiGet(`/api/v1/charters/${charter.id}/broker-rules`).catch(() => []);
      setBrokerRules(Array.isArray(rows) ? rows : []);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function removeBrokerRule(ruleId: string) {
    setBusy(true);
    setErr("");
    try {
      await apiDelete(`/api/v1/broker-rules/${ruleId}`);
      setBrokerRules((prev) => prev.filter((r) => r.id !== ruleId));
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function createAmendment() {
    if (!charter) return;
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
      await apiPost(`/api/v1/charters/${charter.id}/amendments`, { changes, reason: amendForm.reason || null });
      toast.success(t("page.charters.amend_ok", "变更单已提交，待批准"));
      setAmendForm(EMPTY_AMEND);
      const rows: Amendment[] = await apiGet(`/api/v1/charters/${charter.id}/amendments`).catch(() => []);
      setAmendments(Array.isArray(rows) ? rows : []);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function amendTransition(amendmentId: string, action: "approve" | "reject") {
    setBusy(true);
    setErr("");
    try {
      await apiPost(`/api/v1/charter-amendments/${amendmentId}/${action}`);
      toast.success(action === "approve" ? t("page.charters.amend_approved", "变更单已批准并应用") : t("page.charters.amend_rejected", "变更单已驳回"));
      await loadSide();
      await loadCharter();
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
    if (!liftAction || !charter) return;
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
      const rows: Lifting[] = await apiGet(`/api/v1/charters/${charter.id}/liftings`).catch(() => []);
      setLiftings(Array.isArray(rows) ? rows : []);
      toast.success(t("page.charters.lifting_moved", "Lifting → {status}", { status: updated.status || liftAction.kind }));
      setLiftAction(null);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  if (!charter && !notFound) {
    return <SkeletonCard />;
  }

  if (notFound) {
    return (
      <div className="panel">
        <p>{t("common.not_found", "Not found")}</p>
        <Link href="/charters" className="btn">
          {t("common.back", "返回")}
        </Link>
      </div>
    );
  }

  return (
    <>
      <PageHeader
        title={
          <>
            {charter?.charter_no || "…"}
            {charter ? <span className="badge badge-warn">{charter.status}</span> : null}
            {charter?.sanctions_blocked ? (
              <span className="badge badge-fail">{t("page.charters.blocked", "BLOCKED")}</span>
            ) : null}
          </>
        }
        subtitle={t("page.charters.edit", "编辑租约")}
        actions={
          <>
            <Link href="/charters" className="btn btn-ghost">
              {t("common.back", "返回")}
            </Link>
            <button className="btn btn-sm" type="button" disabled={busy || saving} onClick={() => window.print()}>
              {t("common.print", "打印 / PDF")}
            </button>
          </>
        }
      />

      {err ? <p className="flash-err">{err}</p> : null}

      <div className="panel">
        <div className="desk-tabs" style={{ marginBottom: "0.75rem" }}>
          {[
            { id: "general", label: t("page.charters.tab_general", "General") },
            { id: "cargoes", label: t("page.charters.tab_cargoes", "Cargoes") },
            { id: "pricing", label: t("page.charters.tab_pricing", "Pricing") },
            { id: "rebill", label: t("page.charters.tab_rebill", "Rebill Settings") },
            { id: "exposure", label: t("page.charters.tab_exposure", "Exposure") },
            { id: "revexp", label: t("page.charters.tab_revexp", "Rev/Exp") },
            { id: "properties", label: t("page.charters.tab_properties", "Properties") },
          ].map((tb) => (
            <button
              key={tb.id}
              type="button"
              className={`desk-tab${tab === tb.id ? " active" : ""}`}
              onClick={() => setTab(tb.id)}
            >
              {tb.label}
            </button>
          ))}
        </div>
        <div className="form-grid">
          {tab === "general" ? (
            <>
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
                {t("page.charters.contract_type", "Contract type")}
                <select value={edit.fixture_type} onChange={(e) => setEdit({ ...edit, fixture_type: e.target.value })}>
                  <option value="voyage_fixture">{t("page.charters.fixture_voyage", "Voyage Fixture")}</option>
                  <option value="head">{t("page.charters.fixture_head", "Head Fixture")}</option>
                  <option value="relet">{t("page.charters.fixture_relet", "Relet Fixture")}</option>
                </select>
              </label>
              <label>
                {t("page.charters.direction", "Direction")}
                <select value={edit.charter_direction} onChange={(e) => setEdit({ ...edit, charter_direction: e.target.value })}>
                  <option value="out">out</option>
                  <option value="in">in</option>
                </select>
              </label>
              <label>
                {t("page.charters.master_contract", "Master Contract")}
                <select value={edit.master_contract_id} onChange={(e) => setEdit({ ...edit, master_contract_id: e.target.value })}>
                  <option value="">{t("common.none", "None")}</option>
                  {masters.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.contract_no} — {m.title}
                    </option>
                  ))}
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
                <PartyPicker value={edit.counterparty_id} onChange={(id) => setEdit({ ...edit, counterparty_id: id })} />
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
              <label style={{ gridColumn: "1 / -1" }}>
                {t("page.charters.notes", "条款备注")}
                <input value={edit.notes} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} />
              </label>
              {/* D1 条款库：勾选条款，params 直接驱动 laytime/索赔计算输入 */}
              {clauseCatalog.length ? (
                <div style={{ gridColumn: "1 / -1" }}>
                  <div className="muted" style={{ marginBottom: "0.35rem" }}>
                    {t("page.charters.clause_library", "条款库（勾选后参数随租约生效）")}
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: "0.35rem" }}>
                    {clauseCatalog.map((c) => {
                      const title = locale.startsWith("zh") ? c.title_zh || c.title_en : c.title_en;
                      return (
                        <label key={c.id} style={{ display: "flex", gap: "0.45rem", alignItems: "baseline", margin: 0 }}>
                          <input
                            type="checkbox"
                            checked={clauseCodes.includes(c.code)}
                            onChange={(e) =>
                              setClauseCodes((prev) => (e.target.checked ? [...prev, c.code] : prev.filter((x) => x !== c.code)))
                            }
                          />
                          <span>
                            {title}
                            <span className="muted" style={{ marginLeft: "0.35rem", fontSize: "0.75rem" }}>{c.code}</span>
                          </span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              ) : null}
            </>
          ) : null}
          {tab === "cargoes" ? (
            <>
              <label>
                {t("page.estimates.cargo_qty", "货量")}
                <input value={edit.cargo_qty} onChange={(e) => setEdit({ ...edit, cargo_qty: e.target.value })} />
              </label>
              <div style={{ gridColumn: "1 / -1" }}>
                <div className="muted" style={{ marginBottom: "0.35rem" }}>
                  {t("page.charters.broker_rules", "Cargo broker rules")}
                </div>
                {brokerRules.length ? (
                  <table className="table">
                    <thead>
                      <tr>
                        <th>{t("page.estimates.counterparty", "对手方")}</th>
                        <th>{t("page.charters.commission_type", "Commission type")}</th>
                        <th>{t("page.estimates.commission", "佣金 %")}</th>
                        <th>{t("page.charters.applies_to", "Applies to")}</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {brokerRules.map((r) => (
                        <tr key={r.id}>
                          <td>{parties.find((p) => p.id === r.broker_party_id)?.name || r.broker_party_id.slice(0, 8)}</td>
                          <td>{r.commission_type}</td>
                          <td>{r.commission_pct ?? "—"}</td>
                          <td>{r.applies_to}</td>
                          <td>
                            <button className="btn btn-danger btn-sm" type="button" disabled={busy} onClick={() => removeBrokerRule(r.id)}>
                              {t("common.delete", "删除")}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p className="muted" style={{ margin: "0 0 0.5rem" }}>{t("page.charters.no_broker_rules", "暂无经纪规则")}</p>
                )}
                <div className="form-grid">
                  <label>
                    {t("page.charters.broker_party", "Broker")}
                    <select value={brForm.broker_party_id} onChange={(e) => setBrForm({ ...brForm, broker_party_id: e.target.value })}>
                      <option value="">{t("common.select", "Select…")}</option>
                      {parties.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    {t("page.charters.commission_type", "Commission type")}
                    <select value={brForm.commission_type} onChange={(e) => setBrForm({ ...brForm, commission_type: e.target.value })}>
                      <option value="brokerage">brokerage</option>
                      <option value="address">address</option>
                    </select>
                  </label>
                  <label>
                    {t("page.estimates.commission", "佣金 %")}
                    <input type="number" step="any" value={brForm.commission_pct} onChange={(e) => setBrForm({ ...brForm, commission_pct: e.target.value })} />
                  </label>
                  <label>
                    {t("page.charters.applies_to", "Applies to")}
                    <select value={brForm.applies_to} onChange={(e) => setBrForm({ ...brForm, applies_to: e.target.value })}>
                      <option value="all">all</option>
                      <option value="freight">freight</option>
                      <option value="demurrage">demurrage</option>
                    </select>
                  </label>
                  <div style={{ display: "flex", alignItems: "end" }}>
                    <button className="btn btn-sm" type="button" disabled={busy} onClick={addBrokerRule}>
                      {t("common.add", "添加")}
                    </button>
                  </div>
                </div>
              </div>
            </>
          ) : null}
          {tab === "pricing" ? (
            <>
              <label>
                {t("page.estimates.freight_rate", "运价")}
                <input value={edit.freight_rate} onChange={(e) => setEdit({ ...edit, freight_rate: e.target.value })} />
              </label>
              <label>
                {t("page.charters.pricing_basis", "Pricing basis")}
                <select value={edit.pricing_basis} onChange={(e) => setEdit({ ...edit, pricing_basis: e.target.value })}>
                  <option value="">—</option>
                  <option value="worldscale">worldscale</option>
                  <option value="per_mt">per_mt</option>
                  <option value="lumpsum">lumpsum</option>
                  <option value="afra">afra</option>
                </select>
              </label>
              <TermInputs value={edit} onChange={(k, v) => setEdit({ ...edit, [k]: v })} showTc={isTc(edit.charter_type)} />
            </>
          ) : null}
          {tab === "rebill" ? (
            <label style={{ gridColumn: "1 / -1" }}>
              {t("page.charters.rebill_settings", "Rebill settings (JSON)")}
              <textarea
                rows={8}
                spellCheck={false}
                value={edit.rebill_json}
                onChange={(e) => setEdit({ ...edit, rebill_json: e.target.value })}
                placeholder='{"enabled": true, "markup_pct": 2.5}'
              />
            </label>
          ) : null}
          {tab === "exposure" ? (
            <>
              <label>
                {t("page.charters.exposure_amount", "Exposure amount")}
                <input type="number" step="any" value={edit.exposure_amount} onChange={(e) => setEdit({ ...edit, exposure_amount: e.target.value })} />
              </label>
              <label style={{ gridColumn: "1 / -1" }}>
                {t("page.charters.planning_periods", "Planning periods (JSON)")}
                <textarea
                  rows={8}
                  spellCheck={false}
                  value={edit.planning_json}
                  onChange={(e) => setEdit({ ...edit, planning_json: e.target.value })}
                  placeholder='{"periods": ["2026-Q1", "2026-Q2"]}'
                />
              </label>
            </>
          ) : null}
          {tab === "revexp" ? (
            <label style={{ gridColumn: "1 / -1" }}>
              {t("page.charters.rev_exp", "Revenue / expense (JSON)")}
              <textarea
                rows={8}
                spellCheck={false}
                value={edit.revexp_json}
                onChange={(e) => setEdit({ ...edit, revexp_json: e.target.value })}
                placeholder='{"revenue": 200000, "expense": 150000}'
              />
            </label>
          ) : null}
          {tab === "properties" ? (
            <label style={{ gridColumn: "1 / -1" }}>
              {t("page.charters.properties", "Properties (JSON)")}
              <textarea
                rows={8}
                spellCheck={false}
                value={edit.properties_json}
                onChange={(e) => setEdit({ ...edit, properties_json: e.target.value })}
                placeholder='{"key": "value"}'
              />
            </label>
          ) : null}
        </div>
        <div className="desk-toolbar">
          <button className="btn btn-primary" type="button" disabled={saving || busy} onClick={save}>
            {t("common.save", "保存")}
          </button>
          {charter?.status === "draft" ? (
            <button className="btn btn-sm" type="button" disabled={busy} onClick={() => move("pending_approval")}>
              {t("common.submit", "提交审批")}
            </button>
          ) : null}
          {charter?.status === "pending_approval" ? (
            <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => move("active")}>
              {t("common.activate", "激活")}
            </button>
          ) : null}
          {charter?.status === "active" ? (
            <button className="btn btn-sm" type="button" disabled={busy} onClick={() => move("completed")}>
              {t("page.charters.complete", "完成")}
            </button>
          ) : null}
          <button
            className="btn btn-danger btn-sm"
            type="button"
            disabled={saving || busy}
            onClick={() =>
              setConfirm({
                message: t("common.confirm_delete", "Delete this record? It will move to the recycle bin and can be restored."),
                danger: true,
                action: remove,
              })
            }
          >
            {t("common.delete", "删除")}
          </button>
        </div>
      </div>

      {charter && isTc(charter.charter_type) ? (
        <div className="panel">
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

      {charter?.charter_type === "coa" ? (
        <div className="panel">
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
                        {!l.status || l.status === "planned" ? (
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
          <div className="form-grid" style={{ marginTop: "0.75rem" }}>
            <label>
              {t("page.charters.period", "Period label")}
              <input value={liftPeriod} onChange={(e) => setLiftPeriod(e.target.value)} />
            </label>
            <label>
              {t("page.charters.planned_qty", "Planned qty")}
              <input type="number" step="any" value={liftQty} onChange={(e) => setLiftQty(e.target.value)} />
            </label>
            <div style={{ display: "flex", alignItems: "end" }}>
              <button className="btn btn-sm" type="button" disabled={busy} onClick={addLifting}>
                {t("page.charters.add_lifting", "添加 lifting")}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <div className="panel">
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

      <ConfirmDialog
        open={Boolean(confirm)}
        title={t("common.confirm", "确认操作")}
        message={confirm?.message || ""}
        danger={confirm?.danger}
        onConfirm={() => {
          const fn = confirm?.action;
          setConfirm(null);
          fn?.();
        }}
        onCancel={() => setConfirm(null)}
      />
    </>
  );
}
