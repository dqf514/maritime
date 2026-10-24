"use client";

// Phase 5 — TC Manager workspace：合同条款 / Hire & Off-hire / 账单计划 / 利润分成 /
// 经纪规则 / 交还船检验 / 子合同。行详情页 /charters/tc/{id}。

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { FormPanel, FormSection, FieldRow } from "@/components/form/FormPanel";
import { DateInput } from "@/components/DateInput";
import { DetailHeader } from "@/components/DetailHeader";
import { Num } from "@/components/Num";
import { RevisionsPanel } from "@/components/RevisionsPanel";
import { StatusLegend } from "@/components/StatusLegend";
import { Tabs } from "@/components/Tabs";
import { PartyPicker } from "@/components/DataPicker";
import { ValidateButton, type ValidateIssue } from "@/components/ValidateButton";
import { useStateActions, useTransitionTable } from "@/components/useTransitions";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type RefItem = { id: string; name: string };

type TcContract = {
  id: string;
  charter_id: string;
  contract_type: string;
  contract_style: string;
  parent_contract_id: string | null;
  vessel_id: string;
  counterparty_id: string;
  delivery_port: string | null;
  delivery_date: string | null;
  redelivery_port: string | null;
  redelivery_date: string | null;
  hire_rate: number;
  hire_currency: string;
  payment_frequency: string;
  cancel_date: string | null;
  profit_share_pct: number | null;
  profit_share_threshold: number | null;
  address_comm_pct: number | null;
  brokerage_pct: number | null;
  status: string;
  // ── P11 IMOS TC header ──
  tc_code: string | null;
  beneficiary: string | null;
  date_fixed_at: string | null;
  fixed_by: string | null;
  company_code: string | null;
  trade_area: string | null;
  contract_form: string | null;
  payment_terms: string | null;
  duration_min_days: number | null;
  duration_max_days: number | null;
  duration_minus_days: number | null;
  duration_plus_days: number | null;
  el_redel_min: string | null;
  el_redel_max: string | null;
  duration_basis: string | null;
  use_local_time: boolean;
  billing_period: string | null;
  billing_schedule: string | null;
  chtr_specialist: string | null;
  owner_comm_pct: number | null;
  intercompany: boolean;
  ic_company: string | null;
  remarks: string | null;
  notes_to_operations: string | null;
};

// P11 — Delivery/Redelivery lay event（Est / Proj-Act GMT / Difference 计算列）
type LayEventRow = {
  id: string;
  kind: string;
  port: string | null;
  est_gmt: string | null;
  proj_act_gmt: string | null;
  difference_hours: number | null;
  remarks: string | null;
};

// P11 — Pricing ladder（Hire Rate / Rate Type / From-To GMT / Duration / TCL Ins）
type PricingRow = {
  id: string;
  hire_rate: number;
  rate_type: string;
  from_gmt: string | null;
  to_gmt: string | null;
  duration_days: number | null;
  tcl_ins: number | null;
  locked: boolean;
  comments: string | null;
};

// P11 — Other-items expense grid（BALLA/CABLE/VICTU/ALLOW/LASHS/ILOHC/INTHC）
type OtherItemRow = {
  id: string;
  code: string;
  description: string | null;
  rate_type: string;
  rate: number;
  comm: boolean;
  currency: string;
};

const OTHER_ITEM_CODES = ["BALLA", "CABLE", "VICTU", "ALLOW", "LASHS", "ILOHC", "INTHC"] as const;

type BillingRow = {
  id: string;
  tc_contract_id: string;
  period_start: string;
  period_end: string;
  due_date: string;
  amount: number;
  status: string;
  hire_statement_id: string | null;
  invoice_id: string | null;
};

type PsRow = {
  id: string;
  tier_from: number | null;
  tier_to: number | null;
  share_pct: number | null;
  basis: string;
  isNew?: boolean;
};

type BrokerRow = {
  id: string;
  tc_contract_id: string;
  broker_party_id: string;
  commission_type: string;
  commission_pct: number;
  applies_to: string;
  // ── P11 IMOS broker grid columns ──
  payment_method?: string;
  m_method?: number;
  from_gmt?: string | null;
  to_gmt?: string | null;
  remarks?: string | null;
};

type StatementRow = {
  id: string;
  contract_id: string;
  statement_number: string;
  period_start: string;
  period_end: string;
  hire_days: number;
  off_hire_days: number;
  gross_hire: number;
  off_hire_deduction: number;
  bunker_adjustment: number;
  other_adjustments: number;
  net_hire: number;
  currency: string;
  status: string;
};

type OffHireRow = {
  id: string;
  voyage_id: string;
  voyage_no: string;
  start_at: string;
  end_at: string | null;
  reason: string | null;
  deduct_hire: boolean;
  status: string;
  deducted_days: number | null;
};

type SurveyRow = { id: string; kind: string; surveyed_at: string };

type HireSummary = {
  contract_id: string;
  contract_type: string;
  status: string;
  voyage_count: number;
  voyages: { id: string; voyage_no: string | null; seq: number | null; status: string }[];
  statement_count: number;
  total_billed: number;
  total_paid: number;
  outstanding: number;
  currency: string;
  contract_style: string;
  parent_contract_id: string | null;
  billing_schedule_count: number;
  billing_total: number;
  billing_by_status: Record<string, number>;
  profit_share: { threshold: number | null; pct: number | null; rule_count: number };
  broker_rules: { count: number; total_commission_pct: number };
};

const TABS = [
  "contract",
  "lay_events",
  "pricing",
  "hire",
  "billing",
  "profit_share",
  "broker",
  "other_items",
  "surveys",
  "children",
] as const;
type TabId = (typeof TABS)[number];

function d(v: unknown): string {
  return v == null ? "" : String(v).slice(0, 10);
}
function dt(v: unknown): string {
  return v == null ? "" : String(v).slice(0, 16).replace("T", " ");
}

export default function TcWorkspacePage() {
  const { t } = useI18n();
  const toast = useToast();
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const contractId = params.id;

  const [contract, setContract] = useState<TcContract | null>(null);
  const [summary, setSummary] = useState<HireSummary | null>(null);
  const [vessels, setVessels] = useState<RefItem[]>([]);
  const [parties, setParties] = useState<RefItem[]>([]);
  const [err, setErr] = useState("");
  /** 子列表（对账单/停租记录等）加载失败 */
  const [subErr, setSubErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<TabId>("contract");

  // Contract edit form
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  /** 待确认删除的子行（经纪规则/停租事件/价格档/其他条目） */
  const [confirmRowDel, setConfirmRowDel] = useState<{ label: string; action: () => void } | null>(null);

  // 仅 draft 可编辑/删除（后端 _assert_tc_editable 同步约束）
  const isDraft = contract?.status === "draft";
  const inUse =
    (summary?.statement_count ?? 0) > 0 || (summary?.voyage_count ?? 0) > 0;

  // Tab data
  const [billing, setBilling] = useState<BillingRow[]>([]);
  const [psRows, setPsRows] = useState<PsRow[]>([]);
  const [brokerRows, setBrokerRows] = useState<BrokerRow[]>([]);
  // P11 — lay events / pricing ladder / other items
  const [layRows, setLayRows] = useState<LayEventRow[]>([]);
  const [pricingRows, setPricingRows] = useState<PricingRow[]>([]);
  const [otherRows, setOtherRows] = useState<OtherItemRow[]>([]);
  const [statements, setStatements] = useState<StatementRow[]>([]);
  const [offHire, setOffHire] = useState<OffHireRow[]>([]);
  const [surveys, setSurveys] = useState<SurveyRow[]>([]);
  const [children, setChildren] = useState<TcContract[]>([]);
  const [tabBusy, setTabBusy] = useState(false);

  // Inline add forms
  const [brokerForm, setBrokerForm] = useState({ broker_party_id: "", commission_type: "brokerage", commission_pct: "", applies_to: "all", payment_method: "pay_directly", m_method: "0" });
  const [layForm, setLayForm] = useState({ kind: "delivery", port: "", est_gmt: "", proj_act_gmt: "", remarks: "" });
  const [pricingForm, setPricingForm] = useState({ hire_rate: "", rate_type: "per_day", from_gmt: "", to_gmt: "", duration_days: "", tcl_ins: "", comments: "" });
  const [otherForm, setOtherForm] = useState({ code: "BALLA", description: "", rate_type: "lumpsum", rate: "", comm: true });
  const [surveyForm, setSurveyForm] = useState({ kind: "on_hire", surveyed_at: "" });
  const [childForm, setChildForm] = useState({ contract_type: "tci", contract_style: "time_charter", hire_rate: "", hire_currency: "USD", delivery_date: "", redelivery_date: "" });

  // 状态机动作可见性：只渲染当前状态可执行的转移（time_charter 表）
  // 转移表取数失败时不能静默地「没有可用动作」
  const { error: transitionErr } = useTransitionTable();
  const nextStatuses = useStateActions("time_charter", contract?.status);

  function validateTc(): ValidateIssue[] {
    const issues: ValidateIssue[] = [];
    const hire = Number(draft.hire_rate);
    if (draft.hire_rate === "" || !Number.isFinite(hire) || hire <= 0) {
      issues.push({ level: "error", message: t("validate.tc.no_hire", "Hire rate is required") });
    }
    if (!contract?.counterparty_id) {
      issues.push({ level: "error", message: t("validate.tc.no_counterparty", "Counterparty is required") });
    }
    if (draft.delivery_date && draft.redelivery_date && draft.delivery_date > draft.redelivery_date) {
      issues.push({ level: "error", message: t("validate.tc.dates", "Delivery date is after redelivery date") });
    }
    const addr = Number(draft.address_comm_pct);
    if (draft.address_comm_pct !== "" && Number.isFinite(addr) && addr > 100) {
      issues.push({ level: "error", message: t("validate.tc.addr_comm", "Address commission exceeds 100%") });
    }
    const brok = Number(draft.brokerage_pct);
    if (draft.brokerage_pct !== "" && Number.isFinite(brok) && brok > 100) {
      issues.push({ level: "error", message: t("validate.tc.brokerage", "Brokerage exceeds 100%") });
    }
    return issues;
  }

  const toDraft = useCallback((c: TcContract) => {
    setDraft({
      contract_style: c.contract_style || "time_charter",
      delivery_port: c.delivery_port || "",
      delivery_date: d(c.delivery_date),
      redelivery_port: c.redelivery_port || "",
      redelivery_date: d(c.redelivery_date),
      hire_rate: String(c.hire_rate ?? ""),
      hire_currency: c.hire_currency || "USD",
      payment_frequency: c.payment_frequency || "monthly",
      cancel_date: d(c.cancel_date),
      profit_share_pct: c.profit_share_pct == null ? "" : String(c.profit_share_pct),
      profit_share_threshold: c.profit_share_threshold == null ? "" : String(c.profit_share_threshold),
      address_comm_pct: c.address_comm_pct == null ? "" : String(c.address_comm_pct),
      brokerage_pct: c.brokerage_pct == null ? "" : String(c.brokerage_pct),
      // ── P11 IMOS header ──
      beneficiary: c.beneficiary || "",
      company_code: c.company_code || "",
      trade_area: c.trade_area || "",
      contract_form: c.contract_form || "",
      payment_terms: c.payment_terms || "",
      billing_period: c.billing_period || "",
      billing_schedule: c.billing_schedule || "",
      chtr_specialist: c.chtr_specialist || "",
      ic_company: c.ic_company || "",
      owner_comm_pct: c.owner_comm_pct == null ? "" : String(c.owner_comm_pct),
      remarks: c.remarks || "",
      notes_to_operations: c.notes_to_operations || "",
      duration_min_days: c.duration_min_days == null ? "" : String(c.duration_min_days),
      duration_max_days: c.duration_max_days == null ? "" : String(c.duration_max_days),
      duration_minus_days: c.duration_minus_days == null ? "" : String(c.duration_minus_days),
      duration_plus_days: c.duration_plus_days == null ? "" : String(c.duration_plus_days),
      el_redel_min: d(c.el_redel_min),
      el_redel_max: d(c.el_redel_max),
      duration_basis: c.duration_basis || "",
      use_local_time: c.use_local_time ? "1" : "0",
      intercompany: c.intercompany ? "1" : "0",
    });
  }, []);

  const reloadSummary = useCallback(async (explicitId?: string) => {
    const s = await apiGet(`/api/v1/tc/contracts/${explicitId ?? contract?.id ?? contractId}/hire-summary`);
    setSummary(s);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contractId, contract?.id]);

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const [c, v, p] = await Promise.all([
        apiGet(`/api/v1/tc/contracts/${contractId}`),
        apiGet("/api/v1/masterdata/vessels"),
        apiGet("/api/v1/masterdata/counterparties"),
      ]);
      setContract(c);
      toDraft(c);
      setVessels(v || []);
      setParties(p || []);
      await reloadSummary(c.id);
    } catch (ex) {
      setErr(msgOf(ex));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contractId]);

  useEffect(() => {
    load();
  }, [load]);

  const charterId = contract?.charter_id ?? null;
  // URL 可能是父租约 id（/charters/tc/{charter_id}）；子资源接口只认合同 id，统一用解析后的真实 id
  const cid = contract?.id ?? contractId;

  const loadTab = useCallback(
    async (which: TabId) => {
      setTabBusy(true);
      setErr("");
      try {
        if (which === "billing") {
          setBilling(await apiGet(`/api/v1/tc/contracts/${cid}/billing-schedule`));
        } else if (which === "profit_share") {
          const rows: PsRow[] = await apiGet(`/api/v1/tc/contracts/${cid}/profit-share`);
          setPsRows(rows.map((r) => ({ ...r, isNew: false })));
        } else if (which === "broker") {
          setBrokerRows(await apiGet(`/api/v1/tc/contracts/${cid}/broker-rules`));
        } else if (which === "lay_events") {
          setLayRows(await apiGet(`/api/v1/tc/contracts/${cid}/lay-events`));
        } else if (which === "pricing") {
          setPricingRows(await apiGet(`/api/v1/tc/contracts/${cid}/pricing-rows`));
        } else if (which === "other_items") {
          setOtherRows(await apiGet(`/api/v1/tc/contracts/${cid}/other-items`));
        } else if (which === "hire") {
          const [stR, sumR] = await Promise.allSettled([
            apiGet(`/api/v1/tc-contracts/${cid}/statements`),
            apiGet(`/api/v1/tc/contracts/${cid}/hire-summary`),
          ]);
          if (stR.status === "fulfilled") {
            const st = stR.value;
            setStatements(Array.isArray(st) ? st : []);
          } else {
            // 对账单取数失败 ≠ 没有对账单
            setStatements([]);
            setSubErr(msgOf(stR.reason));
          }
          if (sumR.status === "rejected") throw sumR.reason;
          const voyages = sumR.value;
          const vids: { id: string; voyage_no: string | null }[] = voyages?.voyages || [];
          const events: OffHireRow[] = [];
          const offHireFailures: unknown[] = [];
          await Promise.all(
            vids.map(async (v) => {
              try {
                const rows = await apiGet(`/api/v1/voyages/${v.id}/off-hire`);
                for (const r of rows || []) {
                  events.push({ ...r, voyage_no: v.voyage_no || v.id.slice(0, 8) });
                }
              } catch (ex) {
                // 单个航次没有 off-hire 记录可以跳过，但失败原因不能完全静默
                offHireFailures.push(ex);
              }
            }),
          );
          if (offHireFailures.length) setSubErr(msgOf(offHireFailures[0]));
          events.sort((a, b) => String(a.start_at).localeCompare(String(b.start_at)));
          setOffHire(events);
        } else if (which === "surveys") {
          if (charterId) {
            // 接口返回 { items: [...] } 信封（与 /scheduling 等一致），需解包
            const res = await apiGet(`/api/v1/charters/${charterId}/surveys`);
            setSurveys(Array.isArray(res) ? res : res?.items || []);
          }
        } else if (which === "children") {
          setChildren(await apiGet(`/api/v1/tc/contracts/${cid}/children`));
        }
      } catch (ex) {
        setErr(msgOf(ex));
      } finally {
        setTabBusy(false);
      }
    },
    [cid, charterId],
  );

  useEffect(() => {
    if (tab !== "contract" && contract) loadTab(tab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, contract]);

  async function saveContract() {
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        contract_style: draft.contract_style,
        hire_rate: Number(draft.hire_rate),
        hire_currency: draft.hire_currency,
        payment_frequency: draft.payment_frequency,
      };
      if (draft.delivery_port) payload.delivery_port = draft.delivery_port;
      if (draft.delivery_date) payload.delivery_date = draft.delivery_date;
      if (draft.redelivery_port) payload.redelivery_port = draft.redelivery_port;
      if (draft.redelivery_date) payload.redelivery_date = draft.redelivery_date;
      if (draft.cancel_date) payload.cancel_date = draft.cancel_date;
      if (draft.profit_share_pct !== "") payload.profit_share_pct = Number(draft.profit_share_pct);
      if (draft.profit_share_threshold !== "") payload.profit_share_threshold = Number(draft.profit_share_threshold);
      if (draft.address_comm_pct !== "") payload.address_comm_pct = Number(draft.address_comm_pct);
      if (draft.brokerage_pct !== "") payload.brokerage_pct = Number(draft.brokerage_pct);
      // ── P11 IMOS header ──
      const strFields = [
        "beneficiary", "company_code", "trade_area", "contract_form", "payment_terms",
        "billing_period", "billing_schedule", "chtr_specialist", "ic_company", "remarks",
        "notes_to_operations", "duration_basis",
      ] as const;
      strFields.forEach((k) => {
        if (draft[k]) payload[k] = draft[k];
      });
      const numFields = ["owner_comm_pct", "duration_min_days", "duration_max_days", "duration_minus_days", "duration_plus_days"] as const;
      numFields.forEach((k) => {
        if (draft[k] !== "") payload[k] = Number(draft[k]);
      });
      if (draft.el_redel_min) payload.el_redel_min = draft.el_redel_min;
      if (draft.el_redel_max) payload.el_redel_max = draft.el_redel_max;
      payload.use_local_time = draft.use_local_time === "1";
      payload.intercompany = draft.intercompany === "1";
      const updated = await apiPatch(`/api/v1/tc/contracts/${cid}`, payload);
      setContract(updated);
      toast.success(t("common.saved", "Saved"));
      await reloadSummary();
    } catch (ex: any) {
      toast.error(msgOf(ex));
    } finally {
      setSaving(false);
    }
  }

  async function removeContract() {
    setSaving(true);
    try {
      await apiDelete(`/api/v1/tc/contracts/${cid}`);
      toast.success(t("page.tc.deleted", "TC contract deleted"));
      router.push("/charters?type=tc");
    } catch (ex: any) {
      toast.error(msgOf(ex));
      setSaving(false);
    }
  }

  async function transitionTo(target: string) {
    try {
      const updated = await apiPost(`/api/v1/tc/contracts/${cid}/transition?target=${target}`);
      setContract(updated);
      toast.success(t("page.tc.transitioned", "Status → {s}", { s: updated.status }));
      await reloadSummary();
    } catch (ex) {
      toast.error(msgOf(ex));
    }
  }

  async function generateBilling() {
    setTabBusy(true);
    try {
      await apiPost(`/api/v1/tc/contracts/${cid}/billing-schedule/generate`, {});
      toast.success(t("page.tc.billing.generated", "Billing schedule generated"));
      await loadTab("billing");
      await reloadSummary();
    } catch (ex) {
      toast.error(msgOf(ex));
      setTabBusy(false);
    }
  }

  async function generateStatements() {
    setTabBusy(true);
    try {
      await apiPost(`/api/v1/tc-contracts/${cid}/generate-statements`, {});
      toast.success(t("page.tc.statements.generated", "Hire statements generated"));
      await loadTab("hire");
      await reloadSummary();
    } catch (ex) {
      toast.error(msgOf(ex));
      setTabBusy(false);
    }
  }

  async function saveProfitShare() {
    setTabBusy(true);
    try {
      const news = psRows.filter((r) => r.isNew && r.tier_from != null && r.share_pct != null);
      for (const r of news) {
        const body: Record<string, unknown> = {
          tier_from: Number(r.tier_from),
          share_pct: Number(r.share_pct),
          basis: r.basis || "tce",
        };
        if (r.tier_to != null) body.tier_to = Number(r.tier_to);
        await apiPost(`/api/v1/tc/contracts/${cid}/profit-share`, body);
      }
      toast.success(t("common.saved", "Saved"));
      await loadTab("profit_share");
      await reloadSummary();
    } catch (ex) {
      toast.error(msgOf(ex));
      setTabBusy(false);
    }
  }

  async function addBrokerRule() {
    try {
      await apiPost(`/api/v1/tc/contracts/${cid}/broker-rules`, {
        broker_party_id: brokerForm.broker_party_id,
        commission_type: brokerForm.commission_type,
        commission_pct: Number(brokerForm.commission_pct),
        applies_to: brokerForm.applies_to,
        payment_method: brokerForm.payment_method,
        m_method: Number(brokerForm.m_method),
      });
      setBrokerForm({ broker_party_id: "", commission_type: "brokerage", commission_pct: "", applies_to: "all", payment_method: "pay_directly", m_method: "0" });
      toast.success(t("common.saved", "Saved"));
      await loadTab("broker");
      await reloadSummary();
    } catch (ex) {
      toast.error(msgOf(ex));
    }
  }

  async function delBrokerRule(id: string) {
    try {
      await apiDelete(`/api/v1/tc/contracts/${cid}/broker-rules/${id}`);
      await loadTab("broker");
    } catch (ex) {
      toast.error(msgOf(ex));
    }
  }

  // ── P11: lay events (Delivery/Redelivery) ──
  async function addLayEvent() {
    try {
      await apiPost(`/api/v1/tc/contracts/${cid}/lay-events`, {
        kind: layForm.kind,
        port: layForm.port || null,
        est_gmt: layForm.est_gmt || null,
        proj_act_gmt: layForm.proj_act_gmt || null,
        remarks: layForm.remarks || null,
      });
      setLayForm({ kind: "delivery", port: "", est_gmt: "", proj_act_gmt: "", remarks: "" });
      toast.success(t("common.saved", "Saved"));
      await loadTab("lay_events");
    } catch (ex) {
      toast.error(msgOf(ex));
    }
  }

  async function delLayEvent(id: string) {
    try {
      await apiDelete(`/api/v1/tc/contracts/${cid}/lay-events/${id}`);
      await loadTab("lay_events");
    } catch (ex) {
      toast.error(msgOf(ex));
    }
  }

  // ── P11: pricing ladder ──
  async function addPricingRow() {
    try {
      await apiPost(`/api/v1/tc/contracts/${cid}/pricing-rows`, {
        hire_rate: Number(pricingForm.hire_rate),
        rate_type: pricingForm.rate_type,
        from_gmt: pricingForm.from_gmt || null,
        to_gmt: pricingForm.to_gmt || null,
        duration_days: pricingForm.duration_days === "" ? null : Number(pricingForm.duration_days),
        tcl_ins: pricingForm.tcl_ins === "" ? null : Number(pricingForm.tcl_ins),
        comments: pricingForm.comments || null,
      });
      setPricingForm({ hire_rate: "", rate_type: "per_day", from_gmt: "", to_gmt: "", duration_days: "", tcl_ins: "", comments: "" });
      toast.success(t("common.saved", "Saved"));
      await loadTab("pricing");
    } catch (ex) {
      toast.error(msgOf(ex));
    }
  }

  async function delPricingRow(id: string) {
    try {
      await apiDelete(`/api/v1/tc/contracts/${cid}/pricing-rows/${id}`);
      await loadTab("pricing");
    } catch (ex) {
      toast.error(msgOf(ex));
    }
  }

  // ── P11: other items (BALLA/CABLE/VICTU/…) ──
  async function addOtherItem() {
    try {
      await apiPost(`/api/v1/tc/contracts/${cid}/other-items`, {
        code: otherForm.code,
        description: otherForm.description || null,
        rate_type: otherForm.rate_type,
        rate: Number(otherForm.rate),
        comm: otherForm.comm,
      });
      setOtherForm({ code: "BALLA", description: "", rate_type: "lumpsum", rate: "", comm: true });
      toast.success(t("common.saved", "Saved"));
      await loadTab("other_items");
    } catch (ex) {
      toast.error(msgOf(ex));
    }
  }

  async function delOtherItem(id: string) {
    try {
      await apiDelete(`/api/v1/tc/contracts/${cid}/other-items/${id}`);
      await loadTab("other_items");
    } catch (ex) {
      toast.error(msgOf(ex));
    }
  }

  async function addSurvey() {
    if (!contract?.charter_id) return;
    try {
      await apiPost(`/api/v1/charters/${contract.charter_id}/surveys`, {
        kind: surveyForm.kind,
        surveyed_at: surveyForm.surveyed_at || new Date().toISOString(),
      });
      setSurveyForm({ kind: "on_hire", surveyed_at: "" });
      toast.success(t("common.saved", "Saved"));
      await loadTab("surveys");
    } catch (ex) {
      toast.error(msgOf(ex));
    }
  }

  async function addChild() {
    try {
      const body: Record<string, unknown> = {
        contract_type: childForm.contract_type,
        contract_style: childForm.contract_style,
        hire_rate: Number(childForm.hire_rate),
        hire_currency: childForm.hire_currency,
      };
      if (childForm.delivery_date) body.delivery_date = childForm.delivery_date;
      if (childForm.redelivery_date) body.redelivery_date = childForm.redelivery_date;
      await apiPost(`/api/v1/tc/contracts/${cid}/children`, body);
      setChildForm((f) => ({ ...f, hire_rate: "", delivery_date: "", redelivery_date: "" }));
      toast.success(t("page.tc.child.created", "Child TC created"));
      await loadTab("children");
    } catch (ex) {
      toast.error(msgOf(ex));
    }
  }

  const typeLabel = useMemo(() => {
    if (!contract) return "";
    if (contract.contract_style === "bareboat") return t("page.tc.type.bareboat", "Bareboat");
    return contract.contract_type === "tci" ? t("page.tc.type.tci", "TC In") : t("page.tc.type.tco", "TC Out");
  }, [contract, t]);

  const nameOf = (list: RefItem[], id: string | null) => (id ? list.find((x) => x.id === id)?.name || id.slice(0, 8) : "—");

  const psColumns: ColumnDef<PsRow>[] = useMemo(
    () => [
      {
        key: "tier_from",
        title: t("page.tc.ps.tier_from", "Tier from"),
        align: "right",
        width: 110,
        editor: { type: "number" },
        value: (r) => r.tier_from ?? "",
      },
      {
        key: "tier_to",
        title: t("page.tc.ps.tier_to", "Tier to"),
        align: "right",
        width: 110,
        editor: { type: "number" },
        value: (r) => r.tier_to ?? "",
      },
      {
        key: "share_pct",
        title: t("page.tc.ps.share_pct", "Share %"),
        align: "right",
        width: 100,
        agg: "avg",
        editor: { type: "number" },
        value: (r) => r.share_pct ?? "",
      },
      {
        key: "basis",
        title: t("page.tc.ps.basis", "Basis"),
        width: 110,
        editor: { type: "select", options: ["tce", "revenue", "profit"].map((b) => ({ value: b, label: b })) },
        value: (r) => r.basis,
      },
    ],
    [t],
  );

  const billingColumns: ColumnDef<BillingRow>[] = useMemo(
    () => [
      { key: "period_start", title: t("page.tc.col.period_start", "From"), width: 100, value: (r) => d(r.period_start) },
      { key: "period_end", title: t("page.tc.col.period_end", "To"), width: 100, value: (r) => d(r.period_end) },
      { key: "due_date", title: t("page.tc.col.due_date", "Due"), width: 100, value: (r) => d(r.due_date) },
      {
        key: "amount",
        title: t("page.tc.col.amount", "Amount"),
        align: "right",
        width: 120,
        agg: "sum",
        value: (r) => r.amount,
        render: (v) => <Num v={Number(v ?? 0)} digits={2} />,
      },
      {
        key: "status",
        title: t("common.status", "Status"),
        width: 90,
        value: (r) => r.status,
        render: (v) => <span className={`badge ${v === "paid" ? "badge-pass" : v === "overdue" ? "badge-fail" : "badge-info"}`}>{String(v)}</span>,
      },
      {
        key: "hire_statement_id",
        title: t("page.tc.col.statement", "Statement"),
        width: 110,
        value: (r) => r.hire_statement_id || "",
        render: (v) => (v ? String(v).slice(0, 8) : "—"),
      },
      {
        key: "invoice_id",
        title: t("page.tc.col.invoice", "Invoice"),
        width: 110,
        value: (r) => r.invoice_id || "",
        render: (v) => (v ? String(v).slice(0, 8) : "—"),
      },
    ],
    [t],
  );

  const statementColumns: ColumnDef<StatementRow>[] = useMemo(
    () => [
      { key: "statement_number", title: t("page.tc.col.statement_no", "No"), width: 110, sticky: true, value: (r) => r.statement_number },
      { key: "period_start", title: t("page.tc.col.period_start", "From"), width: 95, value: (r) => d(r.period_start) },
      { key: "period_end", title: t("page.tc.col.period_end", "To"), width: 95, value: (r) => d(r.period_end) },
      { key: "hire_days", title: t("page.tc.col.hire_days", "Hire days"), align: "right", width: 90, agg: "sum", value: (r) => r.hire_days, render: (v) => <Num v={Number(v ?? 0)} digits={2} /> },
      { key: "off_hire_days", title: t("page.tc.col.off_days", "Off-hire d"), align: "right", width: 95, agg: "sum", value: (r) => r.off_hire_days, render: (v) => <Num v={Number(v ?? 0)} digits={2} /> },
      {
        key: "gross_hire",
        title: t("page.tc.col.gross_hire", "Gross hire"),
        align: "right",
        width: 115,
        agg: "sum",
        value: (r) => r.gross_hire,
        render: (v) => <Num v={Number(v ?? 0)} digits={2} />,
      },
      {
        key: "off_hire_deduction",
        title: t("page.tc.col.off_deduction", "Off-hire ded."),
        align: "right",
        width: 115,
        agg: "sum",
        value: (r) => r.off_hire_deduction,
        render: (v) => <Num v={Number(v ?? 0)} digits={2} />,
      },
      {
        key: "net_hire",
        title: t("page.tc.col.net_hire", "Net hire"),
        align: "right",
        width: 115,
        agg: "sum",
        value: (r) => r.net_hire,
        render: (v) => (
          <strong>
            <Num v={Number(v ?? 0)} digits={2} />
          </strong>
        ),
      },
      { key: "status", title: t("common.status", "Status"), width: 85, value: (r) => r.status },
    ],
    [t],
  );

  const offHireColumns: ColumnDef<OffHireRow>[] = useMemo(
    () => [
      { key: "voyage_no", title: t("page.tc.col.voyage", "Voyage"), width: 100, sticky: true, value: (r) => r.voyage_no },
      { key: "start_at", title: t("page.tc.col.start_at", "Start"), width: 125, value: (r) => dt(r.start_at) },
      { key: "end_at", title: t("page.tc.col.end_at", "End"), width: 125, value: (r) => dt(r.end_at) },
      { key: "reason", title: t("page.tc.col.reason", "Reason"), width: 150, value: (r) => r.reason || "" },
      {
        key: "deducted_days",
        title: t("page.tc.col.deducted_days", "Days"),
        align: "right",
        width: 80,
        agg: "sum",
        value: (r) => r.deducted_days ?? 0,
        render: (v) => <Num v={Number(v ?? 0)} digits={2} />,
      },
      {
        key: "status",
        title: t("common.status", "Status"),
        width: 85,
        value: (r) => r.status,
        render: (v) => <span className={`badge ${v === "open" ? "badge-warn" : "badge-info"}`}>{String(v)}</span>,
      },
    ],
    [t],
  );

  const brokerColumns: ColumnDef<BrokerRow>[] = useMemo(
    () => [
      {
        key: "broker_party_id",
        title: t("page.tc.col.broker", "Broker"),
        width: 170,
        value: (r) => nameOf(parties, r.broker_party_id),
      },
      { key: "commission_type", title: t("page.tc.col.comm_type", "Type"), width: 110, value: (r) => r.commission_type },
      {
        key: "commission_pct",
        title: t("page.tc.col.comm_pct", "Comm %"),
        align: "right",
        width: 95,
        agg: "sum",
        value: (r) => r.commission_pct,
        render: (v) => <Num v={Number(v ?? 0)} digits={2} />,
      },
      { key: "applies_to", title: t("page.tc.col.applies_to", "Applies to"), width: 100, value: (r) => r.applies_to },
      // P11 IMOS：Payment Method / M / From-To GMT
      {
        key: "payment_method",
        title: t("page.tc.col.payment_method", "Payment method"),
        width: 140,
        value: (r) => r.payment_method || "pay_directly",
        render: (v) =>
          v === "deduct_from_hire"
            ? t("page.tc.pay.deduct_from_hire", "Deduct from hire")
            : t("page.tc.pay.pay_directly", "Pay directly"),
      },
      { key: "m_method", title: t("page.tc.col.m_method", "M"), width: 55, align: "right", value: (r) => r.m_method ?? 0 },
      { key: "from_gmt", title: t("page.tc.col.from_gmt", "From GMT"), width: 130, value: (r) => dt(r.from_gmt) },
      { key: "to_gmt", title: t("page.tc.col.to_gmt", "To GMT"), width: 130, value: (r) => dt(r.to_gmt) },
      { key: "remarks", title: t("page.tc.col.remarks", "Remarks"), minWidth: 120, value: (r) => r.remarks || "" },
      {
        key: "actions",
        title: "",
        width: 60,
        value: () => "",
        render: (_v, r) => (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={(e) => {
              e.stopPropagation();
              setConfirmRowDel({
                label: r.broker_party_id || r.id.slice(0, 8),
                action: () => void delBrokerRule(r.id),
              });
            }}
          >
            {t("common.delete", "Delete")}
          </button>
        ),
      },
    ],
    [t, parties],
  );

  // ── P11 grids: lay events / pricing ladder / other items ──
  const layColumns: ColumnDef<LayEventRow>[] = useMemo(
    () => [
      {
        key: "kind",
        title: t("page.tc.lay.kind", "Lay"),
        width: 100,
        value: (r) => r.kind,
        render: (v) =>
          v === "delivery" ? t("page.tc.lay.delivery", "Delivery") : t("page.tc.lay.redelivery", "Redelivery"),
      },
      { key: "port", title: t("page.tc.lay.port", "Port"), width: 150, value: (r) => r.port || "" },
      { key: "est_gmt", title: t("page.tc.lay.est_gmt", "Est GMT"), width: 150, value: (r) => dt(r.est_gmt) },
      { key: "proj_act_gmt", title: t("page.tc.lay.proj_act", "Proj/Act GMT"), width: 150, value: (r) => dt(r.proj_act_gmt) },
      {
        key: "difference_hours",
        title: t("page.tc.lay.difference", "Difference"),
        align: "right",
        width: 100,
        value: (r) => r.difference_hours,
        render: (v) => (v == null ? "—" : `${Number(v) > 0 ? "+" : ""}${Number(v).toFixed(2)} h`),
      },
      { key: "remarks", title: t("page.tc.col.remarks", "Remarks"), minWidth: 150, value: (r) => r.remarks || "" },
      {
        key: "actions",
        title: "",
        width: 60,
        value: () => "",
        render: (_v, r) => (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={(e) => {
              e.stopPropagation();
              setConfirmRowDel({
                label: r.port || r.kind || r.id.slice(0, 8),
                action: () => void delLayEvent(r.id),
              });
            }}
          >
            {t("common.delete", "Delete")}
          </button>
        ),
      },
    ],
    [t],
  );

  const pricingColumns: ColumnDef<PricingRow>[] = useMemo(
    () => [
      {
        key: "hire_rate",
        title: t("page.tc.col.hire_rate", "Hire rate"),
        align: "right",
        width: 110,
        agg: "avg",
        value: (r) => r.hire_rate,
        render: (v) => <Num v={Number(v ?? 0)} digits={2} />,
      },
      {
        key: "rate_type",
        title: t("page.tc.pricing.rate_type", "Rate type"),
        width: 110,
        value: (r) => r.rate_type,
        render: (v) =>
          v === "per_day"
            ? t("page.tc.pricing.per_day", "per day")
            : v === "lumpsum"
              ? t("page.tc.pricing.lumpsum", "lumpsum")
              : t("page.tc.pricing.per_30", "per 30 days"),
      },
      { key: "from_gmt", title: t("page.tc.col.from_gmt", "From GMT"), width: 150, value: (r) => dt(r.from_gmt) },
      { key: "to_gmt", title: t("page.tc.col.to_gmt", "To GMT"), width: 150, value: (r) => dt(r.to_gmt) },
      {
        key: "duration_days",
        title: t("page.tc.pricing.duration", "Duration (d)"),
        align: "right",
        width: 110,
        agg: "sum",
        value: (r) => r.duration_days,
        render: (v) => (v == null ? "—" : Number(v).toFixed(1)),
      },
      {
        key: "tcl_ins",
        title: t("page.tc.pricing.tcl_ins", "TCL Ins"),
        align: "right",
        width: 95,
        agg: "sum",
        value: (r) => r.tcl_ins,
        render: (v) => (v == null ? "—" : Number(v).toLocaleString()),
      },
      {
        key: "locked",
        title: t("page.tc.pricing.locked", "Locked"),
        width: 75,
        value: (r) => r.locked,
        render: (v) => (v ? t("common.yes", "Yes") : t("common.no", "No")),
      },
      { key: "comments", title: t("page.tc.col.remarks", "Comments"), minWidth: 130, value: (r) => r.comments || "" },
      {
        key: "actions",
        title: "",
        width: 60,
        value: () => "",
        render: (_v, r) => (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={(e) => {
              e.stopPropagation();
              setConfirmRowDel({
                label: r.rate_type || r.id.slice(0, 8),
                action: () => void delPricingRow(r.id),
              });
            }}
          >
            {t("common.delete", "Delete")}
          </button>
        ),
      },
    ],
    [t],
  );

  const otherColumns: ColumnDef<OtherItemRow>[] = useMemo(
    () => [
      {
        key: "code",
        title: t("page.tc.other.code", "Code"),
        width: 90,
        sticky: true,
        value: (r) => r.code,
        render: (v) => <strong>{String(v)}</strong>,
      },
      { key: "description", title: t("common.description", "Description"), minWidth: 180, value: (r) => r.description || "" },
      {
        key: "rate_type",
        title: t("page.tc.pricing.rate_type", "Rate type"),
        width: 110,
        value: (r) => r.rate_type,
      },
      {
        key: "rate",
        title: t("page.tc.other.rate", "Rate"),
        align: "right",
        width: 110,
        agg: "sum",
        value: (r) => r.rate,
        render: (v, r) => `${Number(v ?? 0).toLocaleString()} ${r.currency}`,
      },
      {
        key: "comm",
        title: t("page.tc.other.comm", "Comm"),
        width: 75,
        value: (r) => r.comm,
        render: (v) => (v ? t("common.yes", "Yes") : t("common.no", "No")),
      },
      {
        key: "actions",
        title: "",
        width: 60,
        value: () => "",
        render: (_v, r) => (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={(e) => {
              e.stopPropagation();
              setConfirmRowDel({
                label: r.code || r.id.slice(0, 8),
                action: () => void delOtherItem(r.id),
              });
            }}
          >
            {t("common.delete", "Delete")}
          </button>
        ),
      },
    ],
    [t],
  );

  const surveyColumns: ColumnDef<SurveyRow>[] = useMemo(
    () => [
      {
        key: "kind",
        title: t("page.tc.col.survey_kind", "Survey"),
        width: 120,
        value: (r) => r.kind,
        render: (v) => (v === "on_hire" ? t("page.tc.survey.on_hire", "On-hire") : t("page.tc.survey.off_hire", "Off-hire")),
      },
      { key: "surveyed_at", title: t("page.tc.col.surveyed_at", "Surveyed at"), width: 150, value: (r) => dt(r.surveyed_at) },
    ],
    [t],
  );

  const childColumns: ColumnDef<TcContract>[] = useMemo(
    () => [
      {
        key: "id",
        title: t("page.tc.col.child", "Child"),
        width: 110,
        sticky: true,
        value: (r) => r.id.slice(0, 8),
      },
      {
        key: "type",
        title: t("common.type", "Type"),
        width: 95,
        value: (r) => (r.contract_style === "bareboat" ? "Bareboat" : r.contract_type === "tci" ? "TC In" : "TC Out"),
      },
      { key: "vessel", title: t("page.estimates.vessel", "Vessel"), width: 130, value: (r) => nameOf(vessels, r.vessel_id) },
      {
        key: "counterparty",
        title: t("page.estimates.counterparty", "Counterparty"),
        width: 150,
        value: (r) => nameOf(parties, r.counterparty_id),
      },
      {
        key: "hire_rate",
        title: t("page.tc.col.hire_rate", "Hire rate"),
        align: "right",
        width: 110,
        agg: "sum",
        value: (r) => r.hire_rate,
        render: (v) => <Num v={Number(v ?? 0)} digits={2} />,
      },
      { key: "delivery_date", title: t("page.tc.col.delivery", "Delivery"), width: 100, value: (r) => d(r.delivery_date) },
      { key: "redelivery_date", title: t("page.tc.col.redelivery", "Redelivery"), width: 100, value: (r) => d(r.redelivery_date) },
      { key: "status", title: t("common.status", "Status"), width: 90, value: (r) => r.status },
    ],
    [t, vessels, parties],
  );

  const tabLabels: Record<TabId, string> = {
    contract: t("page.tc.tab.contract", "Contract"),
    lay_events: t("page.tc.tab.lay_events", "Delivery / Redel."),
    pricing: t("page.tc.tab.pricing", "Pricing Ladder"),
    hire: t("page.tc.tab.hire", "Hire & Off-hire"),
    billing: t("page.tc.tab.billing", "Billing Schedule"),
    profit_share: t("page.tc.tab.profit_share", "Profit Share"),
    broker: t("page.tc.tab.broker", "Broker Rules"),
    other_items: t("page.tc.tab.other_items", "Other Items"),
    surveys: t("page.tc.tab.surveys", "Surveys"),
    children: t("page.tc.tab.children", "Child TCs"),
  };

  return (
    <>
      <AppShell>
        {err ? <p className="flash-err">{err}</p> : null}
        {subErr ? (
          <p className="flash-err">
            {t("page.tc.sub_load_failed", "Some lists failed to load: {msg}", { msg: subErr })}
          </p>
        ) : null}
        {transitionErr ? (
          <p className="flash-err">
            {t("page.transitions.load_failed", "Workflow actions unavailable: {msg}", { msg: transitionErr })}
          </p>
        ) : null}

      {contract ? (
        <>
          <DetailHeader
            breadcrumb={[
              { label: t("page.tc.title", "Time charter"), href: "/charters?type=tc" },
              { label: contract.id ? `#${contract.id}` : `#${cid}` },
            ]}
            title={typeLabel}
            status={contract.status}
            entityType="time_charter"
            entityId={cid}
            subtitle={`${nameOf(vessels, contract.vessel_id)} · ${nameOf(parties, contract.counterparty_id)}`}
            actions={[
              ...nextStatuses.map((s) => ({
                key: `go-${s}`,
                label: t(`page.tc.action.${s}`, s.replace(/_/g, " ")),
                variant: s === "cancelled" ? ("danger" as const) : ("primary" as const),
                onClick: () => void transitionTo(s),
              })),
              {
                key: "back",
                label: t("common.back", "Back"),
                onClick: () => router.push("/charters?type=tc"),
              },
            ]}
          />
          <StatusLegend statuses={["draft", "active", "completed", "cancelled"]} />

          {summary ? (
            <div className="tc-kpis">
              <div className="tc-kpi">
                <span>{t("page.tc.kpi.billed", "Total billed")}</span>
                <strong>
                  {summary.total_billed.toLocaleString()} {summary.currency}
                </strong>
              </div>
              <div className="tc-kpi">
                <span>{t("page.tc.kpi.paid", "Total paid")}</span>
                <strong>
                  {summary.total_paid.toLocaleString()} {summary.currency}
                </strong>
              </div>
              <div className="tc-kpi">
                <span>{t("page.tc.kpi.outstanding", "Outstanding")}</span>
                <strong>
                  {summary.outstanding.toLocaleString()} {summary.currency}
                </strong>
              </div>
              <div className="tc-kpi">
                <span>{t("page.tc.kpi.statements", "Statements")}</span>
                <strong>{summary.statement_count}</strong>
              </div>
              <div className="tc-kpi">
                <span>{t("page.tc.kpi.voyages", "Voyages")}</span>
                <strong>{summary.voyage_count}</strong>
              </div>
              <div className="tc-kpi">
                <span>{t("page.tc.kpi.billing", "Billing total")}</span>
                <strong>
                  {summary.billing_total.toLocaleString()} {summary.currency}
                </strong>
              </div>
            </div>
          ) : null}

          <Tabs
            items={TABS.map((tb) => ({ key: tb, label: tabLabels[tb] }))}
            value={tab}
            onChange={(k) => setTab(k as TabId)}
            variant="line"
          />

          <div className="tc-tab-body">
            {tab === "contract" ? (
              <div className="tc-panel">
                <div className="tc-panel-head">
                  <h3>{t("page.tc.tab.contract", "Contract")}</h3>
                  <div className="quick-row">
                    <ValidateButton onValidate={validateTc} />
                    <button
                      type="button"
                      className="btn btn-primary"
                      onClick={saveContract}
                      disabled={saving || !isDraft}
                      title={isDraft ? undefined : t("page.tc.draft_only", "Only draft contracts can be edited")}
                    >
                      {t("common.save", "Save")}
                    </button>
                    <button
                      type="button"
                      className="btn btn-danger"
                      onClick={() => setConfirmDelete(true)}
                      disabled={saving || !isDraft || inUse}
                      title={
                        !isDraft
                          ? t("page.tc.draft_only_delete", "Only draft contracts can be deleted")
                          : inUse
                            ? t("page.tc.in_use", "Contract has hire statements or voyages and cannot be deleted")
                            : undefined
                      }
                    >
                      {t("common.delete", "Delete")}
                    </button>
                  </div>
                </div>
                <div className="tc-panel-body">
                  <FormPanel columns={3}>
                    <FormSection title={t("page.tc.terms.basic", "Terms")} dense>
                      <FieldRow label={t("page.tc.col.style", "Style")}>
                        <select
                          value={draft.contract_style || "time_charter"}
                          onChange={(e) => setDraft((f) => ({ ...f, contract_style: e.target.value }))}
                        >
                          <option value="time_charter">Time charter</option>
                          <option value="bareboat">Bareboat</option>
                        </select>
                      </FieldRow>
                      <FieldRow label={t("page.tc.col.hire_rate", "Hire rate")}>
                        <input
                          type="number"
                          step="any"
                          value={draft.hire_rate || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, hire_rate: e.target.value }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.terms.currency", "Currency")}>
                        <select
                          value={draft.hire_currency || "USD"}
                          onChange={(e) => setDraft((f) => ({ ...f, hire_currency: e.target.value }))}
                        >
                          {["USD", "EUR", "GBP", "CNY"].map((c) => (
                            <option key={c} value={c}>
                              {c}
                            </option>
                          ))}
                        </select>
                      </FieldRow>
                      <FieldRow label={t("page.tc.terms.pay_freq", "Payment")}>
                        <select
                          value={draft.payment_frequency || "monthly"}
                          onChange={(e) => setDraft((f) => ({ ...f, payment_frequency: e.target.value }))}
                        >
                          <option value="monthly">monthly</option>
                          <option value="semi_monthly">semi_monthly</option>
                        </select>
                      </FieldRow>
                    </FormSection>
                    <FormSection title={t("page.tc.terms.period", "Delivery / redelivery")} dense>
                      <FieldRow label={t("page.tc.col.delivery", "Delivery")}>
                        <DateInput
                          value={draft.delivery_date || ""}
                          onChange={(v) => setDraft((f) => ({ ...f, delivery_date: v }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.terms.delivery_port", "Delivery port")}>
                        <input
                          value={draft.delivery_port || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, delivery_port: e.target.value }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.col.redelivery", "Redelivery")}>
                        <DateInput
                          value={draft.redelivery_date || ""}
                          onChange={(v) => setDraft((f) => ({ ...f, redelivery_date: v }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.terms.redelivery_port", "Redelivery port")}>
                        <input
                          value={draft.redelivery_port || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, redelivery_port: e.target.value }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.terms.cancel_date", "Cancel date")}>
                        <DateInput
                          value={draft.cancel_date || ""}
                          onChange={(v) => setDraft((f) => ({ ...f, cancel_date: v }))}
                        />
                      </FieldRow>
                    </FormSection>
                    <FormSection title={t("page.tc.terms.share_comm", "Profit share & commission")} dense>
                      <FieldRow label={t("page.tc.terms.ps_threshold", "PS threshold")}>
                        <input
                          type="number"
                          step="any"
                          value={draft.profit_share_threshold || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, profit_share_threshold: e.target.value }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.terms.ps_pct", "PS %")}>
                        <input
                          type="number"
                          step="any"
                          value={draft.profit_share_pct || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, profit_share_pct: e.target.value }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.charters.address_comm", "Address comm %")}>
                        <input
                          type="number"
                          step="any"
                          value={draft.address_comm_pct || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, address_comm_pct: e.target.value }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.charters.brokerage", "Brokerage %")}>
                        <input
                          type="number"
                          step="any"
                          value={draft.brokerage_pct || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, brokerage_pct: e.target.value }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.col.owner_comm", "Owner comm %")}>
                        <input
                          type="number"
                          step="any"
                          value={draft.owner_comm_pct || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, owner_comm_pct: e.target.value }))}
                        />
                      </FieldRow>
                    </FormSection>
                    {/* P11 IMOS：Duration 块 — Min/Max/-Days/+Days/E/L Redel. */}
                    <FormSection title={t("page.tc.terms.duration", "Duration")} dense>
                      <FieldRow label={t("page.tc.duration.min", "Min (days)")}>
                        <input
                          type="number"
                          step="any"
                          value={draft.duration_min_days || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, duration_min_days: e.target.value }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.duration.max", "Max (days)")}>
                        <input
                          type="number"
                          step="any"
                          value={draft.duration_max_days || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, duration_max_days: e.target.value }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.duration.minus", "- Days")}>
                        <input
                          type="number"
                          step="any"
                          value={draft.duration_minus_days || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, duration_minus_days: e.target.value }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.duration.plus", "+ Days")}>
                        <input
                          type="number"
                          step="any"
                          value={draft.duration_plus_days || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, duration_plus_days: e.target.value }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.duration.el_min", "E redel.")}>
                        <DateInput
                          value={draft.el_redel_min || ""}
                          onChange={(v) => setDraft((f) => ({ ...f, el_redel_min: v }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.duration.el_max", "L redel.")}>
                        <DateInput
                          value={draft.el_redel_max || ""}
                          onChange={(v) => setDraft((f) => ({ ...f, el_redel_max: v }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.duration.basis", "Basis")}>
                        <input
                          value={draft.duration_basis || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, duration_basis: e.target.value }))}
                          placeholder="WEATHER WORKING…"
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.duration.local_time", "Use local time")}>
                        <select
                          value={draft.use_local_time || "0"}
                          onChange={(e) => setDraft((f) => ({ ...f, use_local_time: e.target.value }))}
                        >
                          <option value="0">{t("common.no", "No")}</option>
                          <option value="1">{t("common.yes", "Yes")}</option>
                        </select>
                      </FieldRow>
                    </FormSection>
                    {/* P11 IMOS：合同抬头其余字段 */}
                    <FormSection title={t("page.tc.terms.header_extra", "Contract header")} dense>
                      <FieldRow label={t("page.tc.header.beneficiary", "Beneficiary")}>
                        <input
                          value={draft.beneficiary || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, beneficiary: e.target.value }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.header.company_code", "Company code")}>
                        <input
                          value={draft.company_code || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, company_code: e.target.value }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.header.trade_area", "Trade area")}>
                        <input
                          value={draft.trade_area || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, trade_area: e.target.value }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.header.contract_form", "Contract form")}>
                        <input
                          value={draft.contract_form || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, contract_form: e.target.value }))}
                          placeholder="NYPE 2015…"
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.header.payment_terms", "Payment terms")}>
                        <input
                          value={draft.payment_terms || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, payment_terms: e.target.value }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.header.billing_period", "Billing period")}>
                        <input
                          value={draft.billing_period || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, billing_period: e.target.value }))}
                          placeholder="EVERY 15 DAYS…"
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.header.billing_schedule", "Billing schedule")}>
                        <input
                          value={draft.billing_schedule || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, billing_schedule: e.target.value }))}
                          placeholder="IN ADVANCE…"
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.header.chtr_specialist", "Chtr specialist")}>
                        <input
                          value={draft.chtr_specialist || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, chtr_specialist: e.target.value }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.header.ic_company", "IC company")}>
                        <input
                          value={draft.ic_company || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, ic_company: e.target.value }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.header.intercompany", "Intercompany")}>
                        <select
                          value={draft.intercompany || "0"}
                          onChange={(e) => setDraft((f) => ({ ...f, intercompany: e.target.value }))}
                        >
                          <option value="0">{t("common.no", "No")}</option>
                          <option value="1">{t("common.yes", "Yes")}</option>
                        </select>
                      </FieldRow>
                      <FieldRow label={t("page.tc.col.remarks", "Remarks")}>
                        <input
                          value={draft.remarks || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, remarks: e.target.value }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.header.notes_ops", "Notes to operations")}>
                        <input
                          value={draft.notes_to_operations || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, notes_to_operations: e.target.value }))}
                        />
                      </FieldRow>
                    </FormSection>
                  </FormPanel>
                </div>
              </div>
            ) : null}

            {/* P11：Delivery/Redelivery 表 — Est / Proj-Act GMT / Difference */}
            {tab === "lay_events" ? (
              <div className="tc-panel">
                <div className="tc-panel-head">
                  <h3>{t("page.tc.lay.title", "Delivery / Redelivery")}</h3>
                </div>
                <div className="tc-panel-body">
                  <DataGrid
                    columns={layColumns}
                    data={layRows}
                    rowKey={(r) => r.id}
                    loading={tabBusy}
                    storageKey="tc-lay-events"
                    emptyText={t("common.empty", "No records")}
                  />
                  <div className="quick-row mt-sm">
                    <select
                      aria-label={t("page.tc.lay.kind", "Lay")}
                      value={layForm.kind}
                      onChange={(e) => setLayForm((f) => ({ ...f, kind: e.target.value }))}
                    >
                      <option value="delivery">{t("page.tc.lay.delivery", "Delivery")}</option>
                      <option value="redelivery">{t("page.tc.lay.redelivery", "Redelivery")}</option>
                    </select>
                    <input
                      aria-label={t("page.tc.lay.port", "Port")}
                      placeholder={t("page.tc.lay.port", "Port")}
                      value={layForm.port}
                      onChange={(e) => setLayForm((f) => ({ ...f, port: e.target.value }))}
                    />
                    <label className="muted">
                      {t("page.tc.lay.est_gmt", "Est GMT")}
                      <input
                        type="datetime-local"
                        value={layForm.est_gmt}
                        onChange={(e) => setLayForm((f) => ({ ...f, est_gmt: e.target.value }))}
                      />
                    </label>
                    <label className="muted">
                      {t("page.tc.lay.proj_act", "Proj/Act GMT")}
                      <input
                        type="datetime-local"
                        value={layForm.proj_act_gmt}
                        onChange={(e) => setLayForm((f) => ({ ...f, proj_act_gmt: e.target.value }))}
                      />
                    </label>
                    <input
                      aria-label={t("page.tc.col.remarks", "Remarks")}
                      placeholder={t("page.tc.col.remarks", "Remarks")}
                      value={layForm.remarks}
                      onChange={(e) => setLayForm((f) => ({ ...f, remarks: e.target.value }))}
                    />
                    <button type="button" className="btn btn-primary" onClick={() => void addLayEvent()}>
                      {t("common.create", "Create")}
                    </button>
                  </div>
                </div>
              </div>
            ) : null}

            {/* P11：Pricing ladder — 多段租金 */}
            {tab === "pricing" ? (
              <div className="tc-panel">
                <div className="tc-panel-head">
                  <h3>{t("page.tc.pricing.title", "Pricing ladder")}</h3>
                </div>
                <div className="tc-panel-body">
                  <DataGrid
                    columns={pricingColumns}
                    data={pricingRows}
                    rowKey={(r) => r.id}
                    loading={tabBusy}
                    showFooter
                    storageKey="tc-pricing-ladder"
                    emptyText={t("common.empty", "No records")}
                  />
                  <div className="quick-row mt-sm">
                    <input
                      type="number"
                      step="any"
                      aria-label={t("page.tc.col.hire_rate", "Hire rate")}
                      placeholder={t("page.tc.col.hire_rate", "Hire rate")}
                      value={pricingForm.hire_rate}
                      onChange={(e) => setPricingForm((f) => ({ ...f, hire_rate: e.target.value }))}
                    />
                    <select
                      aria-label={t("page.tc.pricing.rate_type", "Rate type")}
                      value={pricingForm.rate_type}
                      onChange={(e) => setPricingForm((f) => ({ ...f, rate_type: e.target.value }))}
                    >
                      <option value="per_day">{t("page.tc.pricing.per_day", "per day")}</option>
                      <option value="lumpsum">{t("page.tc.pricing.lumpsum", "lumpsum")}</option>
                      <option value="per_30_days">{t("page.tc.pricing.per_30", "per 30 days")}</option>
                    </select>
                    <label className="muted">
                      {t("page.tc.col.from_gmt", "From GMT")}
                      <input
                        type="datetime-local"
                        value={pricingForm.from_gmt}
                        onChange={(e) => setPricingForm((f) => ({ ...f, from_gmt: e.target.value }))}
                      />
                    </label>
                    <label className="muted">
                      {t("page.tc.col.to_gmt", "To GMT")}
                      <input
                        type="datetime-local"
                        value={pricingForm.to_gmt}
                        onChange={(e) => setPricingForm((f) => ({ ...f, to_gmt: e.target.value }))}
                      />
                    </label>
                    <input
                      type="number"
                      step="any"
                      aria-label={t("page.tc.pricing.duration", "Duration (d)")}
                      placeholder={t("page.tc.pricing.duration", "Duration (d)")}
                      value={pricingForm.duration_days}
                      onChange={(e) => setPricingForm((f) => ({ ...f, duration_days: e.target.value }))}
                    />
                    <input
                      type="number"
                      step="any"
                      aria-label={t("page.tc.pricing.tcl_ins", "TCL Ins")}
                      placeholder={t("page.tc.pricing.tcl_ins", "TCL Ins")}
                      value={pricingForm.tcl_ins}
                      onChange={(e) => setPricingForm((f) => ({ ...f, tcl_ins: e.target.value }))}
                    />
                    <input
                      aria-label={t("page.tc.col.remarks", "Comments")}
                      placeholder={t("page.tc.col.remarks", "Comments")}
                      value={pricingForm.comments}
                      onChange={(e) => setPricingForm((f) => ({ ...f, comments: e.target.value }))}
                    />
                    <button type="button" className="btn btn-primary" onClick={() => void addPricingRow()}>
                      {t("common.create", "Create")}
                    </button>
                  </div>
                </div>
              </div>
            ) : null}

            {/* P11：Other items — BALLA/CABLE/VICTU/… */}
            {tab === "other_items" ? (
              <div className="tc-panel">
                <div className="tc-panel-head">
                  <h3>{t("page.tc.other.title", "Other items")}</h3>
                </div>
                <div className="tc-panel-body">
                  <DataGrid
                    columns={otherColumns}
                    data={otherRows}
                    rowKey={(r) => r.id}
                    loading={tabBusy}
                    showFooter
                    storageKey="tc-other-items"
                    emptyText={t("common.empty", "No records")}
                  />
                  <div className="quick-row mt-sm">
                    <select
                      aria-label={t("page.tc.other.code", "Code")}
                      value={otherForm.code}
                      onChange={(e) => setOtherForm((f) => ({ ...f, code: e.target.value }))}
                    >
                      {OTHER_ITEM_CODES.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                    <input
                      aria-label={t("common.description", "Description")}
                      placeholder={t("common.description", "Description")}
                      value={otherForm.description}
                      onChange={(e) => setOtherForm((f) => ({ ...f, description: e.target.value }))}
                    />
                    <select
                      aria-label={t("page.tc.pricing.rate_type", "Rate type")}
                      value={otherForm.rate_type}
                      onChange={(e) => setOtherForm((f) => ({ ...f, rate_type: e.target.value }))}
                    >
                      <option value="lumpsum">{t("page.tc.pricing.lumpsum", "lumpsum")}</option>
                      <option value="monthly">{t("page.tc.other.monthly", "monthly")}</option>
                      <option value="per_30_days">{t("page.tc.pricing.per_30", "per 30 days")}</option>
                      <option value="per_day">{t("page.tc.pricing.per_day", "per day")}</option>
                    </select>
                    <input
                      type="number"
                      step="any"
                      aria-label={t("page.tc.other.rate", "Rate")}
                      placeholder={t("page.tc.other.rate", "Rate")}
                      value={otherForm.rate}
                      onChange={(e) => setOtherForm((f) => ({ ...f, rate: e.target.value }))}
                    />
                    <label className="muted">
                      <input
                        type="checkbox"
                        checked={otherForm.comm}
                        onChange={(e) => setOtherForm((f) => ({ ...f, comm: e.target.checked }))}
                      />{" "}
                      {t("page.tc.other.comm", "Comm")}
                    </label>
                    <button type="button" className="btn btn-primary" onClick={() => void addOtherItem()}>
                      {t("common.create", "Create")}
                    </button>
                  </div>
                </div>
              </div>
            ) : null}

            {tab === "hire" ? (
              <div className="tc-split">
                <div className="tc-panel">
                  <div className="tc-panel-head">
                    <h3>{t("page.tc.statements.title", "Hire statements")}</h3>
                    <button type="button" className="btn btn-primary" onClick={generateStatements} disabled={tabBusy}>
                      {t("page.tc.statements.generate", "Generate")}
                    </button>
                  </div>
                  <div className="tc-panel-body">
                    <DataGrid
                      columns={statementColumns}
                      data={statements}
                      rowKey={(r) => r.id}
                      loading={tabBusy}
                      storageKey="tc-statements"
                      emptyText={t("common.empty", "No records")}
                    />
                  </div>
                </div>
                <div className="tc-panel">
                  <div className="tc-panel-head">
                    <h3>{t("page.tc.offhire.title", "Off-hire events")}</h3>
                  </div>
                  <div className="tc-panel-body">
                    <DataGrid
                      columns={offHireColumns}
                      data={offHire}
                      rowKey={(r) => r.id}
                      loading={tabBusy}
                      storageKey="tc-offhire"
                      emptyText={t("common.empty", "No records")}
                    />
                  </div>
                </div>
              </div>
            ) : null}

            {tab === "billing" ? (
              <div className="tc-panel">
                <div className="tc-panel-head">
                  <h3>{t("page.tc.tab.billing", "Billing Schedule")}</h3>
                  <button type="button" className="btn btn-primary" onClick={generateBilling} disabled={tabBusy}>
                    {t("page.tc.billing.generate", "Generate")}
                  </button>
                </div>
                <div className="tc-panel-body">
                  <DataGrid
                    columns={billingColumns}
                    data={billing}
                    rowKey={(r) => r.id}
                    loading={tabBusy}
                    storageKey="tc-billing"
                    emptyText={t("common.empty", "No records")}
                  />
                </div>
              </div>
            ) : null}

            {tab === "profit_share" ? (
              <div className="tc-panel">
                <div className="tc-panel-head">
                  <h3>{t("page.tc.tab.profit_share", "Profit Share")}</h3>
                  <div className="quick-row">
                    <button
                      type="button"
                      className="btn btn-ghost"
                      onClick={() =>
                        setPsRows((prev) => [
                          ...prev,
                          { id: `new-${Date.now()}`, tier_from: null, tier_to: null, share_pct: null, basis: "tce", isNew: true },
                        ])
                      }
                    >
                      {t("page.tc.ps.add_tier", "Add tier")}
                    </button>
                    <button type="button" className="btn btn-primary" onClick={saveProfitShare} disabled={tabBusy}>
                      {t("common.save", "Save")}
                    </button>
                  </div>
                </div>
                <div className="tc-panel-body">
                  <DataGrid
                    columns={psColumns}
                    data={psRows}
                    rowKey={(r) => r.id}
                    editable
                    loading={tabBusy}
                    storageKey="tc-profit-share"
                    emptyText={t("common.empty", "No records")}
                    onCellSave={(rowKey, colKey, value) =>
                      setPsRows((prev) =>
                        prev.map((r) => (r.id === rowKey ? { ...r, [colKey]: value === "" ? null : value } : r)),
                      )
                    }
                  />
                  <p className="muted" style={{ marginTop: 8 }}>
                    {t("page.tc.ps.hint", "Edit cells inline; new tiers are saved to the contract with Save.")}
                  </p>
                </div>
              </div>
            ) : null}

            {tab === "broker" ? (
              <div className="tc-panel">
                <div className="tc-panel-head">
                  <h3>{t("page.tc.tab.broker", "Broker Rules")}</h3>
                </div>
                <div className="tc-panel-body">
                  <div className="tc-inline-form">
                    <label>
                      {t("page.tc.col.broker", "Broker")}
                      <PartyPicker
                        value={brokerForm.broker_party_id}
                        onChange={(id) => setBrokerForm((f) => ({ ...f, broker_party_id: id }))}
                      />
                    </label>
                    <label>
                      {t("page.tc.col.comm_type", "Type")}
                      <select
                        value={brokerForm.commission_type}
                        onChange={(e) => setBrokerForm((f) => ({ ...f, commission_type: e.target.value }))}
                      >
                        <option value="brokerage">brokerage</option>
                        <option value="address">address</option>
                      </select>
                    </label>
                    <label>
                      {t("page.tc.col.comm_pct", "Comm %")}
                      <input
                        type="number"
                        step="any"
                        value={brokerForm.commission_pct}
                        onChange={(e) => setBrokerForm((f) => ({ ...f, commission_pct: e.target.value }))}
                      />
                    </label>
                    <label>
                      {t("page.tc.col.applies_to", "Applies to")}
                      <select
                        value={brokerForm.applies_to}
                        onChange={(e) => setBrokerForm((f) => ({ ...f, applies_to: e.target.value }))}
                      >
                        <option value="all">all</option>
                        <option value="hire">hire</option>
                        <option value="off_hire">off_hire</option>
                      </select>
                    </label>
                    <label>
                      {t("page.tc.col.payment_method", "Payment method")}
                      <select
                        value={brokerForm.payment_method}
                        onChange={(e) => setBrokerForm((f) => ({ ...f, payment_method: e.target.value }))}
                      >
                        <option value="pay_directly">{t("page.tc.pay.pay_directly", "Pay directly")}</option>
                        <option value="deduct_from_hire">{t("page.tc.pay.deduct_from_hire", "Deduct from hire")}</option>
                      </select>
                    </label>
                    <label>
                      {t("page.tc.col.m_method", "M")}
                      <input
                        type="number"
                        step="1"
                        value={brokerForm.m_method}
                        onChange={(e) => setBrokerForm((f) => ({ ...f, m_method: e.target.value }))}
                      />
                    </label>
                    <button type="button" className="btn btn-primary" onClick={addBrokerRule}>
                      {t("common.add", "Add")}
                    </button>
                  </div>
                  <DataGrid
                    columns={brokerColumns}
                    data={brokerRows}
                    rowKey={(r) => r.id}
                    loading={tabBusy}
                    storageKey="tc-broker"
                    emptyText={t("common.empty", "No records")}
                  />
                </div>
              </div>
            ) : null}

            {tab === "surveys" ? (
              <div className="tc-panel">
                <div className="tc-panel-head">
                  <h3>{t("page.tc.tab.surveys", "Surveys")}</h3>
                </div>
                <div className="tc-panel-body">
                  <div className="tc-inline-form">
                    <label>
                      {t("page.tc.col.survey_kind", "Survey")}
                      <select
                        value={surveyForm.kind}
                        onChange={(e) => setSurveyForm((f) => ({ ...f, kind: e.target.value }))}
                      >
                        <option value="on_hire">On-hire</option>
                        <option value="off_hire">Off-hire</option>
                      </select>
                    </label>
                    <label>
                      {t("page.tc.col.surveyed_at", "Surveyed at")}
                      <input
                        type="datetime-local"
                        value={surveyForm.surveyed_at}
                        onChange={(e) => setSurveyForm((f) => ({ ...f, surveyed_at: e.target.value }))}
                      />
                    </label>
                    <button type="button" className="btn btn-primary" onClick={addSurvey}>
                      {t("common.add", "Add")}
                    </button>
                  </div>
                  <DataGrid
                    columns={surveyColumns}
                    data={surveys}
                    rowKey={(r) => r.id}
                    loading={tabBusy}
                    storageKey="tc-surveys"
                    emptyText={t("common.empty", "No records")}
                  />
                </div>
              </div>
            ) : null}

            {tab === "children" ? (
              <div className="tc-panel">
                <div className="tc-panel-head">
                  <h3>{t("page.tc.tab.children", "Child TCs")}</h3>
                </div>
                <div className="tc-panel-body">
                  <div className="tc-inline-form">
                    <label>
                      {t("common.type", "Type")}
                      <select
                        value={childForm.contract_type}
                        onChange={(e) => setChildForm((f) => ({ ...f, contract_type: e.target.value }))}
                      >
                        <option value="tci">TC In</option>
                        <option value="tco">TC Out</option>
                      </select>
                    </label>
                    <label>
                      {t("page.tc.col.style", "Style")}
                      <select
                        value={childForm.contract_style}
                        onChange={(e) => setChildForm((f) => ({ ...f, contract_style: e.target.value }))}
                      >
                        <option value="time_charter">Time charter</option>
                        <option value="bareboat">Bareboat</option>
                      </select>
                    </label>
                    <label>
                      {t("page.tc.col.hire_rate", "Hire rate")}
                      <input
                        type="number"
                        step="any"
                        value={childForm.hire_rate}
                        onChange={(e) => setChildForm((f) => ({ ...f, hire_rate: e.target.value }))}
                      />
                    </label>
                    <label>
                      {t("page.tc.col.delivery", "Delivery")}
                      <DateInput
                        value={childForm.delivery_date}
                        onChange={(v) => setChildForm((f) => ({ ...f, delivery_date: v }))}
                      />
                    </label>
                    <label>
                      {t("page.tc.col.redelivery", "Redelivery")}
                      <DateInput
                        value={childForm.redelivery_date}
                        onChange={(v) => setChildForm((f) => ({ ...f, redelivery_date: v }))}
                      />
                    </label>
                    <button type="button" className="btn btn-primary" onClick={addChild}>
                      {t("common.add", "Add")}
                    </button>
                  </div>
                  <DataGrid
                    columns={childColumns}
                    data={children}
                    rowKey={(r) => r.id}
                    loading={tabBusy}
                    storageKey="tc-children"
                    emptyText={t("common.empty", "No records")}
                    onRowDoubleClick={(r) => router.push(`/charters/tc/${r.id}`)}
                  />
                </div>
              </div>
            ) : null}
          </div>
          {contract ? <RevisionsPanel entityType="time_charter" entityId={contract.id} /> : null}
        </>
      ) : loading ? (
        <p className="muted">{t("common.loading", "Loading…")}</p>
      ) : (
        <p className="flash-err">{t("common.not_found", "Not found")}</p>
      )}
      </AppShell>

      <ConfirmDialog
        open={confirmDelete}
        title={t("common.confirm", "Confirm")}
        message={t("common.confirm_delete", "Delete this record? It will move to the recycle bin and can be restored.")}
        danger
        confirmLabel={t("common.delete", "Delete")}
        onConfirm={() => {
          setConfirmDelete(false);
          void removeContract();
        }}
        onCancel={() => setConfirmDelete(false)}
      />

      <ConfirmDialog
        open={confirmRowDel !== null}
        title={t("common.confirm", "Confirm")}
        message={t("page.tc.confirm_delete_row", 'Delete the row "{label}"? This cannot be undone.', {
          label: confirmRowDel?.label ?? "",
        })}
        confirmLabel={t("common.delete", "Delete")}
        danger
        onConfirm={() => {
          const act = confirmRowDel?.action;
          setConfirmRowDel(null);
          act?.();
        }}
        onCancel={() => setConfirmRowDel(null)}
      />
    </>
  );
}
