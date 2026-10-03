"use client";

// Phase 5 — TC Manager workspace：合同条款 / Hire & Off-hire / 账单计划 / 利润分成 /
// 经纪规则 / 交还船检验 / 子合同。行详情页 /charters/tc/{id}。

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { FormPanel, FormSection, FieldRow } from "@/components/form/FormPanel";
import { DateInput } from "@/components/DateInput";
import { PageHeader } from "@/components/PageHeader";
import { PartyPicker } from "@/components/DataPicker";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
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
};

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
  "hire",
  "billing",
  "profit_share",
  "broker",
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
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<TabId>("contract");

  // Contract edit form
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  // Tab data
  const [billing, setBilling] = useState<BillingRow[]>([]);
  const [psRows, setPsRows] = useState<PsRow[]>([]);
  const [brokerRows, setBrokerRows] = useState<BrokerRow[]>([]);
  const [statements, setStatements] = useState<StatementRow[]>([]);
  const [offHire, setOffHire] = useState<OffHireRow[]>([]);
  const [surveys, setSurveys] = useState<SurveyRow[]>([]);
  const [children, setChildren] = useState<TcContract[]>([]);
  const [tabBusy, setTabBusy] = useState(false);

  // Inline add forms
  const [brokerForm, setBrokerForm] = useState({ broker_party_id: "", commission_type: "brokerage", commission_pct: "", applies_to: "all" });
  const [surveyForm, setSurveyForm] = useState({ kind: "on_hire", surveyed_at: "" });
  const [childForm, setChildForm] = useState({ contract_type: "tci", contract_style: "time_charter", hire_rate: "", hire_currency: "USD", delivery_date: "", redelivery_date: "" });

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
    });
  }, []);

  const reloadSummary = useCallback(async () => {
    const s = await apiGet(`/api/v1/tc/contracts/${contractId}/hire-summary`);
    setSummary(s);
  }, [contractId]);

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
      await reloadSummary();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contractId]);

  useEffect(() => {
    load();
  }, [load]);

  const charterId = contract?.charter_id ?? null;

  const loadTab = useCallback(
    async (which: TabId) => {
      setTabBusy(true);
      setErr("");
      try {
        if (which === "billing") {
          setBilling(await apiGet(`/api/v1/tc/contracts/${contractId}/billing-schedule`));
        } else if (which === "profit_share") {
          const rows: PsRow[] = await apiGet(`/api/v1/tc/contracts/${contractId}/profit-share`);
          setPsRows(rows.map((r) => ({ ...r, isNew: false })));
        } else if (which === "broker") {
          setBrokerRows(await apiGet(`/api/v1/tc/contracts/${contractId}/broker-rules`));
        } else if (which === "hire") {
          const [st, voyages] = await Promise.all([
            apiGet(`/api/v1/tc-contracts/${contractId}/statements`).catch(() => []),
            apiGet(`/api/v1/tc/contracts/${contractId}/hire-summary`),
          ]);
          setStatements(Array.isArray(st) ? st : []);
          const vids: { id: string; voyage_no: string | null }[] = voyages?.voyages || [];
          const events: OffHireRow[] = [];
          await Promise.all(
            vids.map(async (v) => {
              try {
                const rows = await apiGet(`/api/v1/voyages/${v.id}/off-hire`);
                for (const r of rows || []) {
                  events.push({ ...r, voyage_no: v.voyage_no || v.id.slice(0, 8) });
                }
              } catch {
                // voyage without off-hire feed — skip
              }
            }),
          );
          events.sort((a, b) => String(a.start_at).localeCompare(String(b.start_at)));
          setOffHire(events);
        } else if (which === "surveys") {
          if (charterId) {
            setSurveys(await apiGet(`/api/v1/charters/${charterId}/surveys`));
          }
        } else if (which === "children") {
          setChildren(await apiGet(`/api/v1/tc/contracts/${contractId}/children`));
        }
      } catch (ex) {
        setErr(String(ex));
      } finally {
        setTabBusy(false);
      }
    },
    [contractId, charterId],
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
      const updated = await apiPatch(`/api/v1/tc/contracts/${contractId}`, payload);
      setContract(updated);
      toast.success(t("common.saved", "Saved"));
      await reloadSummary();
    } catch (ex) {
      toast.error(String(ex));
    } finally {
      setSaving(false);
    }
  }

  async function transitionTo(target: string) {
    try {
      const updated = await apiPost(`/api/v1/tc/contracts/${contractId}/transition?target=${target}`);
      setContract(updated);
      toast.success(t("page.tc.transitioned", "Status → {s}", { s: updated.status }));
      await reloadSummary();
    } catch (ex) {
      toast.error(String(ex));
    }
  }

  async function generateBilling() {
    setTabBusy(true);
    try {
      await apiPost(`/api/v1/tc/contracts/${contractId}/billing-schedule/generate`, {});
      toast.success(t("page.tc.billing.generated", "Billing schedule generated"));
      await loadTab("billing");
      await reloadSummary();
    } catch (ex) {
      toast.error(String(ex));
      setTabBusy(false);
    }
  }

  async function generateStatements() {
    setTabBusy(true);
    try {
      await apiPost(`/api/v1/tc-contracts/${contractId}/generate-statements`, {});
      toast.success(t("page.tc.statements.generated", "Hire statements generated"));
      await loadTab("hire");
      await reloadSummary();
    } catch (ex) {
      toast.error(String(ex));
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
        await apiPost(`/api/v1/tc/contracts/${contractId}/profit-share`, body);
      }
      toast.success(t("common.saved", "Saved"));
      await loadTab("profit_share");
      await reloadSummary();
    } catch (ex) {
      toast.error(String(ex));
      setTabBusy(false);
    }
  }

  async function addBrokerRule() {
    try {
      await apiPost(`/api/v1/tc/contracts/${contractId}/broker-rules`, {
        broker_party_id: brokerForm.broker_party_id,
        commission_type: brokerForm.commission_type,
        commission_pct: Number(brokerForm.commission_pct),
        applies_to: brokerForm.applies_to,
      });
      setBrokerForm({ broker_party_id: "", commission_type: "brokerage", commission_pct: "", applies_to: "all" });
      toast.success(t("common.saved", "Saved"));
      await loadTab("broker");
      await reloadSummary();
    } catch (ex) {
      toast.error(String(ex));
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
      toast.error(String(ex));
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
      await apiPost(`/api/v1/tc/contracts/${contractId}/children`, body);
      setChildForm((f) => ({ ...f, hire_rate: "", delivery_date: "", redelivery_date: "" }));
      toast.success(t("page.tc.child.created", "Child TC created"));
      await loadTab("children");
    } catch (ex) {
      toast.error(String(ex));
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
        render: (v) => Number(v ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
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
      { key: "hire_days", title: t("page.tc.col.hire_days", "Hire days"), align: "right", width: 90, agg: "sum", value: (r) => r.hire_days },
      { key: "off_hire_days", title: t("page.tc.col.off_days", "Off-hire d"), align: "right", width: 95, agg: "sum", value: (r) => r.off_hire_days },
      {
        key: "gross_hire",
        title: t("page.tc.col.gross_hire", "Gross hire"),
        align: "right",
        width: 115,
        agg: "sum",
        value: (r) => r.gross_hire,
        render: (v) => Number(v ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
      },
      {
        key: "off_hire_deduction",
        title: t("page.tc.col.off_deduction", "Off-hire ded."),
        align: "right",
        width: 115,
        agg: "sum",
        value: (r) => r.off_hire_deduction,
        render: (v) => Number(v ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
      },
      {
        key: "net_hire",
        title: t("page.tc.col.net_hire", "Net hire"),
        align: "right",
        width: 115,
        agg: "sum",
        value: (r) => r.net_hire,
        render: (v) => <strong>{Number(v ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>,
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
      },
      { key: "applies_to", title: t("page.tc.col.applies_to", "Applies to"), width: 100, value: (r) => r.applies_to },
    ],
    [t, parties],
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
      },
      { key: "delivery_date", title: t("page.tc.col.delivery", "Delivery"), width: 100, value: (r) => d(r.delivery_date) },
      { key: "redelivery_date", title: t("page.tc.col.redelivery", "Redelivery"), width: 100, value: (r) => d(r.redelivery_date) },
      { key: "status", title: t("common.status", "Status"), width: 90, value: (r) => r.status },
    ],
    [t, vessels, parties],
  );

  const tabLabels: Record<TabId, string> = {
    contract: t("page.tc.tab.contract", "Contract"),
    hire: t("page.tc.tab.hire", "Hire & Off-hire"),
    billing: t("page.tc.tab.billing", "Billing Schedule"),
    profit_share: t("page.tc.tab.profit_share", "Profit Share"),
    broker: t("page.tc.tab.broker", "Broker Rules"),
    surveys: t("page.tc.tab.surveys", "Surveys"),
    children: t("page.tc.tab.children", "Child TCs"),
  };

  return (
    <AppShell
      breadcrumbs={[
        { label: t("page.tc.title", "Time Charter"), href: "/charters/tc" },
        { label: typeLabel || t("page.tc.workspace", "TC Manager") },
      ]}
    >
      {err ? <p className="flash-err">{err}</p> : null}

      {contract ? (
        <>
          <PageHeader
            title={
              <>
                {typeLabel}
                <span className={`badge tc-status-${contract.status}`}>{contract.status}</span>
              </>
            }
            subtitle={`${nameOf(vessels, contract.vessel_id)} · ${nameOf(parties, contract.counterparty_id)}`}
            actions={
              <>
                {contract.status === "draft" ? (
                  <>
                    <button type="button" className="btn btn-primary" onClick={() => transitionTo("active")}>
                      {t("page.tc.action.activate", "Activate")}
                    </button>
                    <button type="button" className="btn btn-ghost" onClick={() => transitionTo("cancelled")}>
                      {t("page.tc.action.cancel", "Cancel")}
                    </button>
                  </>
                ) : null}
                {contract.status === "active" ? (
                  <>
                    <button type="button" className="btn btn-primary" onClick={() => transitionTo("completed")}>
                      {t("page.tc.action.complete", "Complete")}
                    </button>
                    <button type="button" className="btn btn-ghost" onClick={() => transitionTo("cancelled")}>
                      {t("page.tc.action.cancel", "Cancel")}
                    </button>
                  </>
                ) : null}
                <Link href="/charters/tc" className="btn btn-ghost">
                  {t("common.back", "Back")}
                </Link>
              </>
            }
          />

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

          <div className="desk-tabs">
            {TABS.map((tb) => (
              <button
                key={tb}
                type="button"
                className={`desk-tab${tab === tb ? " active" : ""}`}
                onClick={() => setTab(tb)}
              >
                {tabLabels[tb]}
              </button>
            ))}
          </div>

          <div className="tc-tab-body">
            {tab === "contract" ? (
              <div className="tc-panel">
                <div className="tc-panel-head">
                  <h3>{t("page.tc.tab.contract", "Contract")}</h3>
                  <button type="button" className="btn btn-primary" onClick={saveContract} disabled={saving}>
                    {t("common.save", "Save")}
                  </button>
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
                    </FormSection>
                  </FormPanel>
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
        </>
      ) : loading ? (
        <p className="muted">{t("common.loading", "Loading…")}</p>
      ) : (
        <p className="flash-err">{t("common.not_found", "Not found")}</p>
      )}
    </AppShell>
  );
}
