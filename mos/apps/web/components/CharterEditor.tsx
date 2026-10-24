"use client";

// U2 单据详情：租约编辑器（原 charters 页弹窗的路由化版本）。
// 自包含：拉取租约 + 船舶/对手方/航次引用，承载编辑/状态推进/变更单/
// hire 汇总/COA liftings 全功能，供 /charters/[id] 详情页挂载。

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { DateInput } from "@/components/DateInput";
import { DetailHeader } from "@/components/DetailHeader";
import { Num } from "@/components/Num";
import { RecordModal } from "@/components/RecordModal";
import { RevisionsPanel } from "@/components/RevisionsPanel";
import { StatusLegend } from "@/components/StatusLegend";
import { Tabs } from "@/components/Tabs";
import { PartyPicker } from "@/components/DataPicker";
import { ValidateButton, type ValidateIssue } from "@/components/ValidateButton";
import { useStateActions } from "@/components/useTransitions";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { formatDateInTz } from "@/lib/datetime";
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
  bill_by: string | null;
  tolerance_pct: number | null;
  overage_pct: number | null;
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
  // ── P11 IMOS Fixture header ──
  fixture_no?: string | null;
  voyage_no?: string | null;
  opr_type?: string | null;
  performing_vessel_id?: string | null;
  chtr_specialist?: string | null;
  ops_coordinator?: string | null;
  commence_at?: string | null;
  ballast_bonus?: number | null;
  in_progress_voyage?: boolean;
  ls_only?: boolean;
  piracy_routing?: string | null;
  dwf_pct?: number | null;
  company_code?: string | null;
  lob?: string | null;
  trade_area?: string | null;
};

// P11 — Fixture 内嵌航次计算器（Miles/Spd/SDays/…/PortExp/LinerExp，带页脚合计）
type ItinRow = {
  id: string;
  seq: number;
  port: string | null;
  flag: string;
  cargo: string | null;
  ld_qty: number | null;
  ld_rate: number | null;
  terms: string | null;
  miles: number | null;
  speed: number | null;
  sea_days: number | null;
  xsd: number | null;
  port_days: number | null;
  xpd: number | null;
  port_exp: number | null;
  liner_exp: number | null;
  oexp_per_t: number | null;
  remarks: string | null;
};

type ItinTotals = {
  rows: number;
  miles: number;
  sea_days: number;
  port_days: number;
  xpd: number;
  port_exp: number;
  liner_exp: number;
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
  bill_by: string;
  tolerance_pct: string;
  overage_pct: string;
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
  bill_by: "",
  tolerance_pct: "",
  overage_pct: "",
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
  const out: Record<string, number | string | null> = {};
  if (freightRate !== "") out.freight_rate = Number(freightRate);
  if (cargoQty !== "") out.cargo_qty = Number(cargoQty);
  TERM_NUM_KEYS.forEach((k) => {
    if (tm[k] !== "") out[k] = Number(tm[k]);
  });
  if (tm.freight_basis) out.freight_basis = tm.freight_basis;
  // C1-P1 cargo CP terms — send null when cleared so PATCH can unset them
  out.bill_by = tm.bill_by || null;
  if (tm.tolerance_pct !== "") out.tolerance_pct = Number(tm.tolerance_pct);
  else out.tolerance_pct = null;
  if (tm.overage_pct !== "") out.overage_pct = Number(tm.overage_pct);
  else out.overage_pct = null;
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
      {/* C1-P1 货物 CP 条款：计费量基准 / MOL 公差 / 超量加价 */}
      <label>
        {t("page.charters.bill_by", "Bill by")}
        <select value={value.bill_by} onChange={(e) => onChange("bill_by", e.target.value)}>
          <option value="">—</option>
          <option value="weight">weight</option>
          <option value="measure">measure</option>
          <option value="volume">volume</option>
        </select>
      </label>
      <label>
        {t("page.charters.tolerance_pct", "Tolerance % (0–50)")}
        <input
          type="number"
          step="any"
          min={0}
          max={50}
          value={value.tolerance_pct}
          onChange={(e) => onChange("tolerance_pct", e.target.value)}
        />
      </label>
      <label>
        {t("page.charters.overage_pct", "Overage % (0–100)")}
        <input
          type="number"
          step="any"
          min={0}
          max={100}
          value={value.overage_pct}
          onChange={(e) => onChange("overage_pct", e.target.value)}
        />
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

export function CharterEditor({ charterId, breadcrumb }: { charterId: string; breadcrumb?: { label: string; href?: string }[] }) {
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
    // P11 IMOS Fixture header
    voyage_no: "",
    opr_type: "",
    chtr_specialist: "",
    ops_coordinator: "",
    ballast_bonus: "",
    ls_only: false as boolean,
    piracy_routing: "",
    dwf_pct: "",
    company_code: "",
    lob: "",
    trade_area: "",
    in_progress_voyage: false as boolean,
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
  const [brModalOpen, setBrModalOpen] = useState(false);
  // P11 — Fixture 航次计算器
  const [itinRows, setItinRows] = useState<ItinRow[]>([]);
  const [itinTotals, setItinTotals] = useState<ItinTotals | null>(null);
  const [itinBusy, setItinBusy] = useState(false);
  const [itinForm, setItinForm] = useState({
    seq: "",
    port: "",
    flag: "L",
    cargo: "",
    ld_qty: "",
    ld_rate: "",
    terms: "",
    miles: "",
    speed: "",
    sea_days: "",
    xsd: "",
    port_days: "",
    xpd: "",
    port_exp: "",
    liner_exp: "",
  });
  const [liftModalOpen, setLiftModalOpen] = useState(false);
  const [amendModalOpen, setAmendModalOpen] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [confirm, setConfirm] = useState<{ message: string; danger?: boolean; action: () => void } | null>(null);

  // 状态机动作可见性：只渲染当前状态可执行的转移
  const nextStatuses = useStateActions("charter", charter?.status);

  function validateCharter(): ValidateIssue[] {
    const issues: ValidateIssue[] = [];
    if (!edit.counterparty_id) {
      issues.push({ level: "error", message: t("validate.charter.no_counterparty", "Counterparty is required") });
    }
    if (edit.laycan_from && edit.laycan_to && edit.laycan_from > edit.laycan_to) {
      issues.push({ level: "error", message: t("validate.charter.laycan", "Laycan from is after laycan to") });
    }
    if (isTc(edit.charter_type) && (edit.hire_per_day === "" || Number(edit.hire_per_day) <= 0)) {
      issues.push({ level: "error", message: t("validate.charter.no_hire", "Hire rate is required for time charters") });
    }
    const comm = Number(edit.commission_pct);
    if (edit.commission_pct !== "" && Number.isFinite(comm) && comm > 100) {
      issues.push({ level: "error", message: t("validate.charter.comm", "Commission exceeds 100%") });
    }
    const addr = Number(edit.address_comm_pct);
    if (edit.address_comm_pct !== "" && Number.isFinite(addr) && addr > 100) {
      issues.push({ level: "error", message: t("validate.charter.addr_comm", "Address commission exceeds 100%") });
    }
    const brok = Number(edit.brokerage_pct);
    if (edit.brokerage_pct !== "" && Number.isFinite(brok) && brok > 100) {
      issues.push({ level: "error", message: t("validate.charter.brokerage", "Brokerage exceeds 100%") });
    }
    const tol = Number(edit.tolerance_pct);
    if (edit.tolerance_pct !== "" && (!Number.isFinite(tol) || tol < 0 || tol > 50)) {
      issues.push({ level: "error", message: t("validate.charter.tolerance", "Tolerance must be between 0 and 50") });
    }
    const over = Number(edit.overage_pct);
    if (edit.overage_pct !== "" && (!Number.isFinite(over) || over < 0 || over > 100)) {
      issues.push({ level: "error", message: t("validate.charter.overage", "Overage must be between 0 and 100") });
    }
    return issues;
  }

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
      bill_by: r.bill_by || "",
      tolerance_pct: numStr(r.tolerance_pct),
      overage_pct: numStr(r.overage_pct),
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
      // P11 IMOS Fixture header
      voyage_no: r.voyage_no || "",
      opr_type: r.opr_type || "",
      chtr_specialist: r.chtr_specialist || "",
      ops_coordinator: r.ops_coordinator || "",
      ballast_bonus: numStr(r.ballast_bonus),
      ls_only: Boolean(r.ls_only),
      piracy_routing: r.piracy_routing || "",
      dwf_pct: numStr(r.dwf_pct),
      company_code: r.company_code || "",
      lob: r.lob || "",
      trade_area: r.trade_area || "",
      in_progress_voyage: Boolean(r.in_progress_voyage),
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

  const loadItinerary = useCallback(async () => {
    setItinBusy(true);
    try {
      const res = await apiGet(`/api/v1/charters/${charterId}/itinerary-rows`);
      setItinRows(Array.isArray(res?.items) ? res.items : []);
      setItinTotals(res?.totals ?? null);
    } catch {
      setItinRows([]);
      setItinTotals(null);
    } finally {
      setItinBusy(false);
    }
  }, [charterId]);

  // P11 — voyage calculator row CRUD（合计由后端 totals 计算）
  async function addItinRow() {
    try {
      await apiPost(`/api/v1/charters/${charterId}/itinerary-rows`, {
        seq: itinForm.seq === "" ? itinRows.length + 1 : Number(itinForm.seq),
        port: itinForm.port || null,
        flag: itinForm.flag,
        cargo: itinForm.cargo || null,
        ld_qty: itinForm.ld_qty === "" ? null : Number(itinForm.ld_qty),
        ld_rate: itinForm.ld_rate === "" ? null : Number(itinForm.ld_rate),
        terms: itinForm.terms || null,
        miles: itinForm.miles === "" ? null : Number(itinForm.miles),
        speed: itinForm.speed === "" ? null : Number(itinForm.speed),
        sea_days: itinForm.sea_days === "" ? null : Number(itinForm.sea_days),
        xsd: itinForm.xsd === "" ? null : Number(itinForm.xsd),
        port_days: itinForm.port_days === "" ? null : Number(itinForm.port_days),
        xpd: itinForm.xpd === "" ? null : Number(itinForm.xpd),
        port_exp: itinForm.port_exp === "" ? null : Number(itinForm.port_exp),
        liner_exp: itinForm.liner_exp === "" ? null : Number(itinForm.liner_exp),
      });
      setItinForm({ ...itinForm, seq: "", port: "", cargo: "", ld_qty: "", ld_rate: "", terms: "", miles: "", speed: "", sea_days: "", xsd: "", port_days: "", xpd: "", port_exp: "", liner_exp: "" });
      toast.success(t("common.saved", "已保存"));
      await loadItinerary();
    } catch (ex) {
      toast.error(String(ex));
    }
  }

  async function delItinRow(id: string) {
    try {
      await apiDelete(`/api/v1/charters/${charterId}/itinerary-rows/${id}`);
      await loadItinerary();
    } catch (ex) {
      toast.error(String(ex));
    }
  }

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
    // P11 — voyage calculator rows（任何 fixture 类型都可有行程）
    loadItinerary();
  }, [charter, loadItinerary]);

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
        // ── P11 IMOS Fixture header ──
        voyage_no: edit.voyage_no || null,
        opr_type: edit.opr_type || null,
        chtr_specialist: edit.chtr_specialist || null,
        ops_coordinator: edit.ops_coordinator || null,
        ballast_bonus: edit.ballast_bonus === "" ? null : Number(edit.ballast_bonus),
        ls_only: Boolean(edit.ls_only),
        piracy_routing: edit.piracy_routing || null,
        dwf_pct: edit.dwf_pct === "" ? null : Number(edit.dwf_pct),
        company_code: edit.company_code || null,
        lob: edit.lob || null,
        trade_area: edit.trade_area || null,
        in_progress_voyage: Boolean(edit.in_progress_voyage),
      });
      toast.success(t("common.saved", "已保存"));
      await loadCharter();
    } catch (ex: any) {
      if (ex instanceof SyntaxError) {
        setErr(t("page.charters.invalid_json", "JSON 格式有误，请检查 Rebill / Exposure / Rev-Exp / Properties 选项卡"));
      } else if (ex?.status === 409 && ex?.detail?.code === "AMENDMENT_REQUIRED") {
        setErr(t("page.charters.amendment_required", "租约已生效，关键条款请通过变更单修改（见下方变更单区块）。"));
      } else if (ex?.status === 422) {
        const msg = ex?.message || t("page.charters.cp_terms_invalid", "Cargo CP terms invalid — check bill by / tolerance / overage");
        toast.error(msg);
        setErr(msg);
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
      setLiftModalOpen(false);
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
      setBrModalOpen(false);
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
      setAmendModalOpen(false);
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
        body = { laycan_from: `${nomFrom}T00:00:00`, laycan_to: `${nomTo}T23:59:59` };
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

  // P11 IMOS Fixture voyage calculator — 页脚合计：Miles / S Days / P Days / XPD / PortExp / LinerExp
  const itinColumns: ColumnDef<ItinRow>[] = [
    { key: "seq", title: "#", width: 46, align: "right", value: (r) => r.seq },
    { key: "port", title: t("page.fixtures.port", "Port"), minWidth: 130, value: (r) => r.port || "", render: (v) => (v == null || v === "" ? "—" : String(v)) },
    { key: "flag", title: t("page.fixtures.flag", "F"), width: 44, value: (r) => r.flag },
    { key: "cargo", title: t("page.fixtures.cargo", "Cargo"), minWidth: 120, value: (r) => r.cargo || "", render: (v) => (v == null || v === "" ? "—" : String(v)) },
    {
      key: "ld_qty",
      title: t("page.fixtures.ld_qty", "L/D Qty"),
      width: 100,
      align: "right",
      agg: "sum",
      value: (r) => r.ld_qty ?? null,
      render: (v) => (v == null ? "—" : Number(v).toLocaleString()),
    },
    {
      key: "ld_rate",
      title: t("page.fixtures.ld_rate", "L/D Rate"),
      width: 95,
      align: "right",
      value: (r) => r.ld_rate ?? null,
      render: (v) => (v == null ? "—" : Number(v).toLocaleString()),
    },
    { key: "terms", title: t("page.fixtures.terms", "Terms"), width: 90, value: (r) => r.terms || "", render: (v) => (v == null || v === "" ? "—" : String(v)) },
    {
      key: "miles",
      title: t("page.fixtures.miles", "Miles"),
      width: 85,
      align: "right",
      agg: "sum",
      value: (r) => r.miles ?? null,
      render: (v) => (v == null ? "—" : Number(v).toLocaleString()),
    },
    {
      key: "speed",
      title: t("page.fixtures.speed", "Spd"),
      width: 65,
      align: "right",
      value: (r) => r.speed ?? null,
      render: (v) => (v == null ? "—" : Number(v).toFixed(1)),
    },
    {
      key: "sea_days",
      title: t("page.fixtures.sea_days", "S Days"),
      width: 80,
      align: "right",
      agg: "sum",
      value: (r) => r.sea_days ?? null,
      render: (v) => (v == null ? "—" : Number(v).toFixed(2)),
    },
    {
      key: "xsd",
      title: t("page.fixtures.xsd", "XSD"),
      width: 70,
      align: "right",
      value: (r) => r.xsd ?? null,
      render: (v) => (v == null ? "—" : Number(v).toFixed(2)),
    },
    {
      key: "port_days",
      title: t("page.fixtures.port_days", "P Days"),
      width: 80,
      align: "right",
      agg: "sum",
      value: (r) => r.port_days ?? null,
      render: (v) => (v == null ? "—" : Number(v).toFixed(2)),
    },
    {
      key: "xpd",
      title: t("page.fixtures.xpd", "XPD"),
      width: 95,
      align: "right",
      agg: "sum",
      value: (r) => r.xpd ?? null,
      render: (v) => (v == null ? "—" : Number(v).toLocaleString()),
    },
    {
      key: "port_exp",
      title: t("page.fixtures.port_exp", "PortExp"),
      width: 100,
      align: "right",
      agg: "sum",
      value: (r) => r.port_exp ?? null,
      render: (v) => (v == null ? "—" : Number(v).toLocaleString()),
    },
    {
      key: "liner_exp",
      title: t("page.fixtures.liner_exp", "LinerExp"),
      width: 100,
      align: "right",
      agg: "sum",
      value: (r) => r.liner_exp ?? null,
      render: (v) => (v == null ? "—" : Number(v).toLocaleString()),
    },
    {
      key: "oexp_per_t",
      title: t("page.fixtures.oexp_per_t", "OExp/t"),
      width: 90,
      align: "right",
      value: (r) => r.oexp_per_t ?? null,
      render: (v) => (v == null ? "—" : Number(v).toFixed(2)),
    },
    { key: "remarks", title: t("page.fixtures.remarks", "Remarks"), minWidth: 120, value: (r) => r.remarks || "", render: (v) => (v == null || v === "" ? "—" : String(v)) },
    {
      key: "actions",
      title: "",
      width: 72,
      render: (_v, r) => (
        <button className="btn btn-danger btn-sm" type="button" disabled={itinBusy} onClick={() => void delItinRow(r.id)}>
          {t("common.delete", "删除")}
        </button>
      ),
    },
  ];

  const brokerRuleColumns: ColumnDef<BrokerRule>[] = [
    {
      key: "broker_party_id",
      title: t("page.estimates.counterparty", "对手方"),
      minWidth: 130,
      value: (r) => parties.find((p) => p.id === r.broker_party_id)?.name || r.broker_party_id.slice(0, 8),
    },
    { key: "commission_type", title: t("page.charters.commission_type", "Commission type"), width: 130, value: (r) => r.commission_type },
    {
      key: "commission_pct",
      title: t("page.estimates.commission", "佣金 %"),
      width: 90,
      align: "right",
      value: (r) => r.commission_pct ?? null,
      render: (_v, r) => <Num v={r.commission_pct} digits={2} />,
    },
    { key: "applies_to", title: t("page.charters.applies_to", "Applies to"), width: 100, value: (r) => r.applies_to },
    {
      key: "actions",
      title: "",
      width: 90,
      render: (_v, r) => (
        <button className="btn btn-danger btn-sm" type="button" disabled={busy} onClick={() => removeBrokerRule(r.id)}>
          {t("common.delete", "删除")}
        </button>
      ),
    },
  ];

  const liftingColumns: ColumnDef<Lifting>[] = [
    { key: "period_label", title: t("page.charters.period", "Period"), minWidth: 110, value: (r) => r.period_label },
    {
      key: "planned_qty",
      title: t("page.charters.planned_qty", "Planned qty"),
      width: 110,
      align: "right",
      value: (r) => r.planned_qty ?? null,
      render: (_v, r) => <Num v={r.planned_qty} digits={2} />,
    },
    {
      key: "status",
      title: t("common.status", "状态"),
      width: 100,
      value: (r) => r.status || "planned",
    },
    {
      key: "actions",
      title: "",
      width: 130,
      render: (_v, l) => (
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
      ),
    },
  ];

  const amendmentColumns: ColumnDef<Amendment>[] = [
    { key: "seq", title: "#", width: 50, value: (r) => r.seq },
    { key: "status", title: t("common.status", "状态"), width: 100, value: (r) => r.status },
    {
      key: "reason",
      title: t("page.finance.reason", "Reason"),
      minWidth: 120,
      value: (r) => r.reason || "",
      render: (_v, r) => r.reason || "—",
    },
    {
      key: "changes",
      title: t("page.charters.amend_changes", "变更内容"),
      minWidth: 160,
      value: (r) => Object.entries(r.changes || {}).map(([k, v]) => `${k}=${v}`).join(", "),
      render: (v) => String(v) || "—",
    },
    {
      key: "created_at",
      title: t("common.created_at", "创建时间"),
      width: 110,
      value: (r) => r.created_at || "",
      render: (_v, r) => (r.created_at ? formatDateInTz(r.created_at, null, locale) : "—"),
    },
    {
      key: "actions",
      title: "",
      width: 150,
      render: (_v, a) =>
        a.status === "proposed" ? (
          <div className="desk-toolbar" style={{ margin: 0 }}>
            <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => amendTransition(a.id, "approve")}>
              {t("common.approve", "批准")}
            </button>
            <button className="btn btn-danger btn-sm" type="button" disabled={busy} onClick={() => amendTransition(a.id, "reject")}>
              {t("common.reject", "驳回")}
            </button>
          </div>
        ) : null,
    },
  ];

  return (
    <>
      <DetailHeader
        breadcrumb={breadcrumb}
        title={charter?.charter_no || "…"}
        status={charter?.status}
        subtitle={t("page.charters.edit", "编辑租约")}
        entityType="charter"
        entityId={charterId}
        badges={
          charter?.sanctions_blocked ? (
            <span className="badge badge-fail">{t("page.charters.blocked", "BLOCKED")}</span>
          ) : null
        }
        actions={[
          ...nextStatuses.map((s) => ({
            key: `go-${s}`,
            label: t(`page.charters.go_${s}`, s.replace(/_/g, " ")),
            variant: s === "cancelled" ? ("danger" as const) : s === "active" || s === "completed" ? ("primary" as const) : ("default" as const),
            disabled: busy || saving,
            onClick: () => void move(s),
          })),
          {
            key: "back",
            label: t("common.back", "返回"),
            onClick: () => window.location.href = "/charters",
          },
          {
            key: "print",
            label: t("common.print", "打印 / PDF"),
            disabled: busy || saving,
            onClick: () => window.print(),
          },
        ]}
      />
      <StatusLegend statuses={["draft", "pending_approval", "active", "completed", "cancelled"]} />

      {err ? <p className="flash-err">{err}</p> : null}

      <div className="panel">
        <Tabs
          className="charters-editor-tabs"
          value={tab}
          onChange={setTab}
          items={[
            { key: "general", label: t("page.charters.tab_general", "General") },
            { key: "itinerary", label: t("page.charters.tab_itinerary", "Voyage Calc") },
            { key: "cargoes", label: t("page.charters.tab_cargoes", "Cargoes") },
            { key: "pricing", label: t("page.charters.tab_pricing", "Pricing") },
            { key: "rebill", label: t("page.charters.tab_rebill", "Rebill Settings") },
            { key: "exposure", label: t("page.charters.tab_exposure", "Exposure") },
            { key: "revexp", label: t("page.charters.tab_revexp", "Rev/Exp") },
            { key: "properties", label: t("page.charters.tab_properties", "Properties") },
          ]}
        />
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
              {/* P11 IMOS Fixture header — Fixture No. 只读，其余可编辑 */}
              <label>
                {t("page.fixtures.fixture_no", "Fixture No.")}
                <input value={charter?.fixture_no || ""} readOnly placeholder="auto" />
              </label>
              <label>
                {t("page.fixtures.voyage_no", "Voyage No.")}
                <input value={edit.voyage_no} onChange={(e) => setEdit({ ...edit, voyage_no: e.target.value })} />
              </label>
              <label>
                {t("page.fixtures.opr_type", "Opr type")}
                <input value={edit.opr_type} onChange={(e) => setEdit({ ...edit, opr_type: e.target.value })} placeholder="TCOV…" />
              </label>
              <label>
                {t("page.fixtures.chtr_specialist", "Chtr specialist")}
                <input value={edit.chtr_specialist} onChange={(e) => setEdit({ ...edit, chtr_specialist: e.target.value })} />
              </label>
              <label>
                {t("page.fixtures.ops_coordinator", "Ops coordinator")}
                <input value={edit.ops_coordinator} onChange={(e) => setEdit({ ...edit, ops_coordinator: e.target.value })} />
              </label>
              <label>
                {t("page.fixtures.ballast_bonus", "Ballast bonus")}
                <input type="number" step="any" value={edit.ballast_bonus} onChange={(e) => setEdit({ ...edit, ballast_bonus: e.target.value })} />
              </label>
              <label>
                {t("page.fixtures.piracy_routing", "Piracy routing")}
                <select value={edit.piracy_routing} onChange={(e) => setEdit({ ...edit, piracy_routing: e.target.value })}>
                  <option value="">—</option>
                  <option value="default">{t("page.fixtures.piracy_default", "Default")}</option>
                  <option value="best">{t("page.fixtures.piracy_best", "Best route")}</option>
                  <option value="avoid">{t("page.fixtures.piracy_avoid", "Avoid HRA")}</option>
                </select>
              </label>
              <label>
                {t("page.fixtures.dwf_pct", "DWF %")}
                <input type="number" step="any" value={edit.dwf_pct} onChange={(e) => setEdit({ ...edit, dwf_pct: e.target.value })} />
              </label>
              <label>
                {t("page.fixtures.lob", "LOB")}
                <input value={edit.lob} onChange={(e) => setEdit({ ...edit, lob: e.target.value })} placeholder="BULK…" />
              </label>
              <label>
                {t("page.fixtures.trade_area", "Trade area")}
                <input value={edit.trade_area} onChange={(e) => setEdit({ ...edit, trade_area: e.target.value })} />
              </label>
              <label>
                {t("page.fixtures.company_code", "Company code")}
                <input value={edit.company_code} onChange={(e) => setEdit({ ...edit, company_code: e.target.value })} />
              </label>
              <label>
                {t("page.fixtures.ls_only", "LS only")}
                <select value={edit.ls_only ? "1" : "0"} onChange={(e) => setEdit({ ...edit, ls_only: e.target.value === "1" })}>
                  <option value="0">{t("common.no", "No")}</option>
                  <option value="1">{t("common.yes", "Yes")}</option>
                </select>
              </label>
              <label>
                {t("page.fixtures.in_progress", "In progress voyage")}
                <select
                  value={edit.in_progress_voyage ? "1" : "0"}
                  onChange={(e) => setEdit({ ...edit, in_progress_voyage: e.target.value === "1" })}
                >
                  <option value="0">{t("common.no", "No")}</option>
                  <option value="1">{t("common.yes", "Yes")}</option>
                </select>
              </label>
              <label className="span-all">
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
          {tab === "itinerary" ? (
            <div className="span-all">
              <div className="desk-toolbar desk-toolbar-split">
                <span className="muted">
                  {t("page.fixtures.calc_hint", "Voyage calculator — miles / days / port & liner expenses; totals recompute on every change.")}
                </span>
                <span className="muted">
                  {itinTotals
                    ? t("page.fixtures.calc_totals", "{rows} rows · {miles} sm · sea {sea} d · port {port} d · port exp {pexp} · liner {lexp}", {
                        rows: itinTotals.rows,
                        miles: itinTotals.miles,
                        sea: Number(itinTotals.sea_days).toFixed(2),
                        port: Number(itinTotals.port_days).toFixed(2),
                        pexp: Number(itinTotals.port_exp).toLocaleString(),
                        lexp: Number(itinTotals.liner_exp).toLocaleString(),
                      })
                    : t("page.fixtures.calc_empty", "No itinerary rows yet")}
                </span>
              </div>
              <DataGrid<ItinRow>
                columns={itinColumns}
                data={itinRows}
                rowKey={(r) => r.id}
                loading={itinBusy}
                showFooter
                storageKey="charter_itinerary_grid"
                emptyText={t("page.fixtures.calc_no_rows", "Add the first leg below")}
              />
              <div className="desk-toolbar mt-sm">
                <input
                  type="number"
                  placeholder={t("page.fixtures.seq", "Seq")}
                  value={itinForm.seq}
                  onChange={(e) => setItinForm((f) => ({ ...f, seq: e.target.value }))}
                />
                <input
                  placeholder={t("page.fixtures.port", "Port")}
                  value={itinForm.port}
                  onChange={(e) => setItinForm((f) => ({ ...f, port: e.target.value }))}
                />
                <select
                  aria-label={t("page.fixtures.flag", "Flag")}
                  value={itinForm.flag}
                  onChange={(e) => setItinForm((f) => ({ ...f, flag: e.target.value }))}
                >
                  <option value="L">L — Load</option>
                  <option value="D">D — Discharge</option>
                  <option value="F">F — Forward</option>
                  <option value="Z">Z — Zero</option>
                  <option value="P">P — Pass</option>
                  <option value="Y">Y — Yard</option>
                </select>
                <input
                  placeholder={t("page.fixtures.cargo", "Cargo")}
                  value={itinForm.cargo}
                  onChange={(e) => setItinForm((f) => ({ ...f, cargo: e.target.value }))}
                />
                <input
                  type="number"
                  step="any"
                  placeholder={t("page.fixtures.ld_qty", "L/D qty")}
                  value={itinForm.ld_qty}
                  onChange={(e) => setItinForm((f) => ({ ...f, ld_qty: e.target.value }))}
                />
                <input
                  type="number"
                  step="any"
                  placeholder={t("page.fixtures.ld_rate", "L/D rate")}
                  value={itinForm.ld_rate}
                  onChange={(e) => setItinForm((f) => ({ ...f, ld_rate: e.target.value }))}
                />
                <input
                  placeholder={t("page.fixtures.terms", "Terms")}
                  value={itinForm.terms}
                  onChange={(e) => setItinForm((f) => ({ ...f, terms: e.target.value }))}
                />
                <input
                  type="number"
                  step="any"
                  placeholder={t("page.fixtures.miles", "Miles")}
                  value={itinForm.miles}
                  onChange={(e) => setItinForm((f) => ({ ...f, miles: e.target.value }))}
                />
                <input
                  type="number"
                  step="any"
                  placeholder={t("page.fixtures.speed", "Spd")}
                  value={itinForm.speed}
                  onChange={(e) => setItinForm((f) => ({ ...f, speed: e.target.value }))}
                />
                <input
                  type="number"
                  step="any"
                  placeholder={t("page.fixtures.sea_days", "S days")}
                  value={itinForm.sea_days}
                  onChange={(e) => setItinForm((f) => ({ ...f, sea_days: e.target.value }))}
                />
                <input
                  type="number"
                  step="any"
                  placeholder={t("page.fixtures.xsd", "XSD")}
                  value={itinForm.xsd}
                  onChange={(e) => setItinForm((f) => ({ ...f, xsd: e.target.value }))}
                />
                <input
                  type="number"
                  step="any"
                  placeholder={t("page.fixtures.port_days", "P days")}
                  value={itinForm.port_days}
                  onChange={(e) => setItinForm((f) => ({ ...f, port_days: e.target.value }))}
                />
                <input
                  type="number"
                  step="any"
                  placeholder={t("page.fixtures.xpd", "XPD")}
                  value={itinForm.xpd}
                  onChange={(e) => setItinForm((f) => ({ ...f, xpd: e.target.value }))}
                />
                <input
                  type="number"
                  step="any"
                  placeholder={t("page.fixtures.port_exp", "Port exp")}
                  value={itinForm.port_exp}
                  onChange={(e) => setItinForm((f) => ({ ...f, port_exp: e.target.value }))}
                />
                <input
                  type="number"
                  step="any"
                  placeholder={t("page.fixtures.liner_exp", "Liner exp")}
                  value={itinForm.liner_exp}
                  onChange={(e) => setItinForm((f) => ({ ...f, liner_exp: e.target.value }))}
                />
                <button type="button" className="btn btn-primary" onClick={() => void addItinRow()}>
                  {t("common.add", "Add")}
                </button>
              </div>
            </div>
          ) : null}
          {tab === "cargoes" ? (
            <>
              <label>
                {t("page.estimates.cargo_qty", "货量")}
                <input value={edit.cargo_qty} onChange={(e) => setEdit({ ...edit, cargo_qty: e.target.value })} />
              </label>
              <div style={{ gridColumn: "1 / -1" }}>
                <div className="desk-toolbar" style={{ margin: "0 0 0.35rem" }}>
                  <span className="muted">{t("page.charters.broker_rules", "Cargo broker rules")}</span>
                  <button className="btn btn-sm" type="button" disabled={busy} onClick={() => setBrModalOpen(true)}>
                    + {t("common.add", "添加")}
                  </button>
                </div>
                {brokerRules.length ? (
                  <DataGrid<BrokerRule>
                    columns={brokerRuleColumns}
                    data={brokerRules}
                    rowKey={(r) => r.id}
                    storageKey="charters_broker_rules_grid"
                    showFooter={false}
                    showColumnMenu={false}
                    emptyText={t("page.charters.no_broker_rules", "No broker rules")}
                  />
                ) : (
                  <p className="muted" style={{ margin: "0 0 0.5rem" }}>{t("page.charters.no_broker_rules", "暂无经纪规则")}</p>
                )}
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
          <ValidateButton onValidate={validateCharter} />
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
          <div className="desk-toolbar" style={{ marginTop: 0 }}>
            <h3 style={{ margin: 0 }}>{t("page.charters.liftings", "COA liftings")}</h3>
            <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => setLiftModalOpen(true)}>
              + {t("page.charters.add_lifting", "添加 lifting")}
            </button>
          </div>
          {liftings.length ? (
            <DataGrid<Lifting>
              columns={liftingColumns}
              data={liftings}
              rowKey={(r) => r.id}
              storageKey="charters_liftings_grid"
              showFooter={false}
              showColumnMenu={false}
              emptyText={t("page.charters.no_liftings", "No liftings")}
            />
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

      <div className="panel">
        <div className="desk-toolbar" style={{ marginTop: 0 }}>
          <h3 style={{ margin: 0 }}>{t("page.charters.amendments", "变更单 Amendments")}</h3>
          <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => setAmendModalOpen(true)}>
            + {t("page.charters.new_amendment", "新建变更单")}
          </button>
        </div>
        {amendments.length ? (
          <DataGrid<Amendment>
            columns={amendmentColumns}
            data={amendments}
            rowKey={(r) => r.id}
            storageKey="charters_amendments_grid"
            showFooter={false}
            showColumnMenu={false}
            emptyText={t("page.charters.no_amendments", "No amendments")}
          />
        ) : (
          <p className="muted" style={{ margin: 0 }}>{t("page.charters.no_amendments", "暂无变更单")}</p>
        )}
      </div>

      {charter ? <RevisionsPanel entityType="charter" entityId={charter.id} /> : null}

      <RecordModal
        open={brModalOpen}
        title={t("page.charters.broker_rules", "Cargo broker rules")}
        onClose={() => setBrModalOpen(false)}
        onSave={addBrokerRule}
        canDelete={false}
        saving={busy}
      >
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
      </RecordModal>

      <RecordModal
        open={liftModalOpen}
        title={t("page.charters.add_lifting", "添加 lifting")}
        onClose={() => setLiftModalOpen(false)}
        onSave={addLifting}
        canDelete={false}
        saving={busy}
      >
        <label>
          {t("page.charters.period", "Period label")}
          <input value={liftPeriod} onChange={(e) => setLiftPeriod(e.target.value)} />
        </label>
        <label>
          {t("page.charters.planned_qty", "Planned qty")}
          <input type="number" step="any" value={liftQty} onChange={(e) => setLiftQty(e.target.value)} />
        </label>
      </RecordModal>

      <RecordModal
        open={amendModalOpen}
        title={t("page.charters.new_amendment", "新建变更单")}
        onClose={() => setAmendModalOpen(false)}
        onSave={createAmendment}
        canDelete={false}
        saving={busy}
        size="lg"
      >
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
      </RecordModal>

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
