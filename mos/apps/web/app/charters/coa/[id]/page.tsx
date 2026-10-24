"use client";

// Phase 6 — COA Manager workspace：合同条款 / 分单执行 / 运力分摊 / 关联航次 / 燃油中性盈亏。

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
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
import { ValidateButton, type ValidateIssue } from "@/components/ValidateButton";
import { useStateActions, useTransitionTable } from "@/components/useTransitions";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type CoaContract = {
  id: string;
  coa_no: string;
  charter_id: string;
  total_qty: number;
  qty_unit: string;
  period_from: string;
  period_to: string;
  rate_basis: string;
  rate: number;
  currency: string;
  cargo_spec: string | null;
  bill_by: string | null;
  tolerance_pct: number | null;
  overage_pct: number | null;
  status: string;
};

type LiftingRow = {
  id: string;
  charter_id: string;
  period_label: string;
  planned_qty: number | null;
  actual_qty: number | null;
  status: string;
  voyage_id: string | null;
  laycan_from: string | null;
  laycan_to: string | null;
};

type ItineraryRow = {
  seq: number;
  load_port_id: string | null;
  disch_port_id: string | null;
  qty: number;
  allocated_qty: number;
  remaining_qty: number;
};

type AllocationSummary = {
  coa_contract_id: string;
  coa_no: string;
  total_qty: number;
  qty_unit: string;
  planned_qty: number;
  allocated_qty: number;
  remaining_qty: number;
  unplanned_qty: number;
  itineraries: ItineraryRow[];
};

type PnlResult = {
  coa_contract_id: string;
  coa_no: string;
  rate_basis: string;
  rate: number;
  currency: string;
  completed_liftings: number;
  completed_qty: number;
  voyage_count: number;
  revenue: number;
  fuel_cost: number;
  other_cost: number;
  pnl_fuel_neutral: number;
  pnl_gross: number;
};

type RefItem = { id: string; name: string };

type PnlLine = { key: string; label: string; amount: number; total?: boolean };

type ScoreMatch = {
  cargo_id: string | null;
  cargo_no: string | null;
  score: number;
  within_tolerance: boolean;
};

type ScoreLeg = {
  itinerary_id: string | null;
  seq: number;
  load_port_id: string | null;
  disch_port_id: string | null;
  qty: number | null;
  matches: ScoreMatch[];
};

type ScoreResult = {
  contract_id: string;
  bill_by: string | null;
  tolerance_pct: number | null;
  overage_pct: number | null;
  items: ScoreLeg[];
};

const TABS = ["contract", "liftings", "allocation", "voyages", "pnl"] as const;
type TabId = (typeof TABS)[number];

function asArray<T>(raw: unknown): T[] {
  if (Array.isArray(raw)) return raw as T[];
  if (raw && typeof raw === "object") {
    const o = raw as Record<string, unknown>;
    if (Array.isArray(o.items)) return o.items as T[];
    if (Array.isArray(o.itineraries)) return o.itineraries as T[];
    if (Array.isArray(o.results)) return o.results as T[];
  }
  return [];
}

function d(v: unknown): string {
  return v == null ? "" : String(v).slice(0, 10);
}
function dt(v: unknown): string {
  return v == null ? "" : String(v).slice(0, 16).replace("T", " ");
}

export default function CoaWorkspacePage() {
  const { t } = useI18n();
  const toast = useToast();
  const params = useParams<{ id: string }>();
  const coaId = params.id;

  const [contract, setContract] = useState<CoaContract | null>(null);
  const [allocation, setAllocation] = useState<AllocationSummary | null>(null);
  const [pnl, setPnl] = useState<PnlResult | null>(null);
  const [liftings, setLiftings] = useState<LiftingRow[]>([]);
  const [ports, setPorts] = useState<RefItem[]>([]);
  const [err, setErr] = useState("");
  /** 参考数据（港口）加载失败 */
  const [refErr, setRefErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<TabId>("contract");
  const [tabBusy, setTabBusy] = useState(false);

  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [score, setScore] = useState<ScoreResult | null>(null);
  const [scoreBusy, setScoreBusy] = useState(false);

  // 状态机动作可见性：只渲染当前状态可执行的转移（coa_contract 表）
  // 转移表取数失败时不能静默地「没有可用动作」
  const { error: transitionErr } = useTransitionTable();
  const nextStatuses = useStateActions("coa_contract", contract?.status);

  const toDraft = useCallback((c: CoaContract) => {
    setDraft({
      total_qty: String(c.total_qty ?? ""),
      qty_unit: c.qty_unit || "mt",
      period_from: d(c.period_from),
      period_to: d(c.period_to),
      rate_basis: c.rate_basis || "per_voyage",
      rate: String(c.rate ?? ""),
      currency: c.currency || "USD",
      cargo_spec: c.cargo_spec || "",
      bill_by: c.bill_by || "",
      tolerance_pct: c.tolerance_pct == null ? "" : String(c.tolerance_pct),
      overage_pct: c.overage_pct == null ? "" : String(c.overage_pct),
    });
  }, []);

  function validateCoa(): ValidateIssue[] {
    const issues: ValidateIssue[] = [];
    const qty = Number(draft.total_qty);
    if (draft.total_qty === "" || !Number.isFinite(qty) || qty <= 0) {
      issues.push({ level: "error", message: t("validate.coa.no_qty", "Total quantity must be greater than zero") });
    }
    if (draft.period_from && draft.period_to && draft.period_from > draft.period_to) {
      issues.push({ level: "error", message: t("validate.coa.period", "Period from is after period to") });
    }
    const rate = Number(draft.rate);
    if (draft.rate === "" || !Number.isFinite(rate) || rate < 0) {
      issues.push({ level: "error", message: t("validate.coa.rate", "Rate is required and must not be negative") });
    }
    const tol = Number(draft.tolerance_pct);
    if (draft.tolerance_pct !== "" && (!Number.isFinite(tol) || tol < 0 || tol > 50)) {
      issues.push({ level: "error", message: t("validate.coa.tolerance", "Tolerance must be between 0 and 50") });
    }
    const over = Number(draft.overage_pct);
    if (draft.overage_pct !== "" && (!Number.isFinite(over) || over < 0 || over > 100)) {
      issues.push({ level: "error", message: t("validate.coa.overage", "Overage must be between 0 and 100") });
    }
    return issues;
  }

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const c = await apiGet(`/api/v1/coa/contracts/${coaId}`);
      setContract(c);
      toDraft(c);
      apiGet("/api/v1/masterdata/ports/options")
        .then((p) => {
          setPorts(p || []);
          setRefErr(null);
        })
        // 参考数据取数失败 ≠ 没有港口选项：局部提示
        .catch((ex) => setRefErr(msgOf(ex)));
    } catch (ex) {
      setErr(msgOf(ex));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [coaId]);

  useEffect(() => {
    load();
  }, [load]);

  const charterId = contract?.charter_id ?? null;

  const loadTab = useCallback(
    async (which: TabId) => {
      setTabBusy(true);
      setErr("");
      try {
        if (which === "allocation") {
          setAllocation(await apiGet(`/api/v1/coa/${coaId}/allocation`));
        } else if (which === "pnl") {
          setPnl(await apiGet(`/api/v1/coa/${coaId}/pnl`));
        } else if (which === "liftings" || which === "voyages") {
          if (charterId) {
            setLiftings(asArray<LiftingRow>(await apiGet(`/api/v1/charters/${charterId}/liftings`)));
          }
        }
      } catch (ex) {
        setErr(msgOf(ex));
      } finally {
        setTabBusy(false);
      }
    },
    [coaId, charterId],
  );

  useEffect(() => {
    if (tab !== "contract" && contract) loadTab(tab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, contract]);

  async function saveContract() {
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        total_qty: Number(draft.total_qty),
        qty_unit: draft.qty_unit,
        period_from: draft.period_from,
        period_to: draft.period_to,
        rate_basis: draft.rate_basis,
        rate: Number(draft.rate),
        currency: draft.currency,
      };
      if (draft.cargo_spec) payload.cargo_spec = draft.cargo_spec;
      // C1-P1 cargo CP terms (null clears)
      payload.bill_by = draft.bill_by || null;
      payload.tolerance_pct = draft.tolerance_pct === "" ? null : Number(draft.tolerance_pct);
      payload.overage_pct = draft.overage_pct === "" ? null : Number(draft.overage_pct);
      const updated = await apiPatch(`/api/v1/coa/contracts/${coaId}`, payload);
      setContract(updated);
      toast.success(t("common.saved", "Saved"));
    } catch (ex: any) {
      if (ex?.status === 422) {
        toast.error(ex?.message || t("page.coa.cp_terms_invalid", "Cargo CP terms invalid — check bill by / tolerance / overage"));
      } else {
        toast.error(msgOf(ex));
      }
    } finally {
      setSaving(false);
    }
  }

  async function transitionTo(target: string) {
    try {
      const res = await apiPost(`/api/v1/coa/contracts/${coaId}/transition?target=${encodeURIComponent(target)}`);
      setContract((c) => (c ? { ...c, status: res.status || target } : c));
      toast.success(t("page.coa.transitioned", "Status → {s}", { s: res.status || target }));
    } catch (ex: any) {
      toast.error(msgOf(ex));
    }
  }

  async function loadScore() {
    setScoreBusy(true);
    try {
      const res: ScoreResult = await apiGet(`/api/v1/coa/contracts/${coaId}/score`);
      setScore(res);
    } catch (ex: any) {
      toast.error(msgOf(ex));
    } finally {
      setScoreBusy(false);
    }
  }

  const portName = (id: string | null) => (id ? ports.find((p) => p.id === id)?.name || id.slice(0, 8) : "—");

  const liftingColumns: ColumnDef<LiftingRow>[] = useMemo(
    () => [
      { key: "period_label", title: t("page.coa.col.period_label", "Period"), width: 110, sticky: true, value: (r) => r.period_label },
      {
        key: "planned_qty",
        title: t("page.coa.col.planned_qty", "Planned qty"),
        align: "right",
        width: 115,
        agg: "sum",
        value: (r) => r.planned_qty ?? 0,
        render: (v) => <Num v={Number(v ?? 0)} digits={2} />,
      },
      {
        key: "actual_qty",
        title: t("page.coa.col.actual_qty", "Actual qty"),
        align: "right",
        width: 115,
        agg: "sum",
        value: (r) => r.actual_qty ?? 0,
        render: (v) => <Num v={Number(v ?? 0)} digits={2} />,
      },
      {
        key: "status",
        title: t("common.status", "Status"),
        width: 100,
        value: (r) => r.status,
        render: (v) => (
          <span className={`badge ${v === "completed" ? "badge-pass" : v === "withdrawn" ? "badge-fail" : "badge-info"}`}>
            {String(v)}
          </span>
        ),
      },
      {
        key: "voyage_id",
        title: t("page.coa.col.voyage", "Voyage"),
        width: 110,
        value: (r) => r.voyage_id || "",
        render: (v) => (v ? String(v).slice(0, 8) : "—"),
      },
      { key: "laycan_from", title: t("page.coa.col.laycan_from", "Laycan from"), width: 130, value: (r) => dt(r.laycan_from) },
      { key: "laycan_to", title: t("page.coa.col.laycan_to", "Laycan to"), width: 130, value: (r) => dt(r.laycan_to) },
    ],
    [t],
  );

  const itineraryColumns: ColumnDef<ItineraryRow>[] = useMemo(
    () => [
      { key: "seq", title: "#", width: 50, align: "right", value: (r) => r.seq },
      { key: "load_port_id", title: t("page.coa.col.load_port", "Load"), width: 130, value: (r) => portName(r.load_port_id) },
      { key: "disch_port_id", title: t("page.coa.col.disch_port", "Disch"), width: 130, value: (r) => portName(r.disch_port_id) },
      {
        key: "qty",
        title: t("page.coa.col.qty", "Planned"),
        align: "right",
        width: 115,
        agg: "sum",
        value: (r) => r.qty,
        render: (v) => <Num v={Number(v ?? 0)} digits={2} />,
      },
      {
        key: "allocated_qty",
        title: t("page.coa.col.allocated_qty", "Allocated"),
        align: "right",
        width: 115,
        agg: "sum",
        value: (r) => r.allocated_qty,
        render: (v) => <Num v={Number(v ?? 0)} digits={2} />,
      },
      {
        key: "remaining_qty",
        title: t("page.coa.col.remaining_qty", "Remaining"),
        align: "right",
        width: 115,
        agg: "sum",
        value: (r) => r.remaining_qty,
        render: (v) => <Num v={Number(v ?? 0)} digits={2} />,
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, ports],
  );

  const linkedVoyages = useMemo(
    () => liftings.filter((l) => l.voyage_id).map((l) => ({ key: `${l.id}`, lifting: l })),
    [liftings],
  );

  const voyageColumns: ColumnDef<{ key: string; lifting: LiftingRow }>[] = useMemo(
    () => [
      {
        key: "period_label",
        title: t("page.coa.col.period_label", "Period"),
        width: 110,
        sticky: true,
        value: (r) => r.lifting.period_label,
      },
      {
        key: "voyage_id",
        title: t("page.coa.col.voyage", "Voyage"),
        width: 220,
        value: (r) => r.lifting.voyage_id || "",
        render: (v) =>
          v ? (
            <Link href={`/operations/voyages/${v}/workspace`}>{String(v)}</Link>
          ) : (
            "—"
          ),
      },
      {
        key: "status",
        title: t("common.status", "Status"),
        width: 100,
        value: (r) => r.lifting.status,
      },
      {
        key: "qty",
        title: t("page.coa.col.actual_qty", "Actual qty"),
        align: "right",
        width: 115,
        agg: "sum",
        value: (r) => r.lifting.actual_qty ?? r.lifting.planned_qty ?? 0,
        render: (v) => <Num v={Number(v ?? 0)} digits={2} />,
      },
    ],
    [t],
  );

  const pnlLineColumns: ColumnDef<PnlLine>[] = useMemo(
    () => [
      {
        key: "label",
        title: t("page.coa.pnl.line", "Line"),
        value: (r) => r.label,
        render: (v, r) => (r.total ? <strong>{String(v)}</strong> : String(v)),
      },
      {
        key: "amount",
        title: pnl?.currency || "USD",
        align: "right",
        value: (r) => r.amount,
        render: (v, r) =>
          r.total ? (
            <strong>
              <Num v={Number(v)} digits={2} />
            </strong>
          ) : (
            <Num v={Number(v)} digits={2} />
          ),
      },
    ],
    [t, pnl?.currency],
  );

  const pnlLines: PnlLine[] = useMemo(() => {
    if (!pnl) return [];
    return [
      { key: "revenue", label: t("page.coa.pnl.revenue", "Revenue"), amount: pnl.revenue },
      { key: "fuel_cost", label: t("page.coa.pnl.fuel_cost", "Fuel cost"), amount: -pnl.fuel_cost },
      { key: "other_cost", label: t("page.coa.pnl.other_cost", "Other cost"), amount: -pnl.other_cost },
      { key: "gross", label: t("page.coa.pnl.gross", "P&L gross"), amount: pnl.pnl_gross, total: true },
      { key: "fuel_neutral", label: t("page.coa.pnl.fuel_neutral", "P&L fuel-neutral"), amount: pnl.pnl_fuel_neutral, total: true },
    ];
  }, [pnl, t]);

  const scoreMatchColumns: ColumnDef<ScoreMatch>[] = useMemo(
    () => [
      {
        key: "cargo_no",
        title: t("page.coa.score_cargo", "Cargo"),
        minWidth: 140,
        value: (r) => r.cargo_no || r.cargo_id || "",
      },
      {
        key: "score",
        title: t("page.coa.score_value", "Score"),
        width: 100,
        align: "right",
        value: (r) => r.score,
        render: (v) => <Num v={Number(v ?? 0)} digits={1} />,
      },
      {
        key: "within_tolerance",
        title: t("page.coa.score_tolerance", "In tolerance"),
        width: 110,
        value: (r) => r.within_tolerance,
        render: (v) =>
          v ? (
            <span className="badge badge-pass">{t("common.yes", "Yes")}</span>
          ) : (
            <span className="badge badge-warn">{t("common.no", "No")}</span>
          ),
      },
    ],
    [t],
  );

  const tabLabels: Record<TabId, string> = {
    contract: t("page.coa.tab.contract", "Contract"),
    liftings: t("page.coa.tab.liftings", "Lifting Schedule"),
    allocation: t("page.coa.tab.allocation", "Itinerary Allocation"),
    voyages: t("page.coa.tab.voyages", "Linked Voyages"),
    pnl: t("page.coa.tab.pnl", "P&L"),
  };

  const allocPct =
    allocation && allocation.total_qty > 0
      ? Math.min(100, Math.max(0, (allocation.allocated_qty / allocation.total_qty) * 100))
      : 0;

  return (
    <AppShell>
      {err ? <p className="flash-err">{err}</p> : null}
      {refErr ? (
        <p className="flash-err">
          {t("page.coa.ref_load_failed", "Reference data failed to load: {msg}", { msg: refErr })}
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
              { label: t("page.coa.title", "COA"), href: "/charters?type=coa" },
              { label: contract.coa_no ? `#${contract.coa_no}` : `#${coaId}` },
            ]}
            title={contract.coa_no}
            status={contract.status}
            entityType="coa_contract"
            entityId={coaId}
            subtitle={`${contract.rate_basis} · ${contract.rate.toLocaleString()} ${contract.currency} · ${contract.total_qty.toLocaleString()} ${contract.qty_unit}`}
            actions={[
              ...nextStatuses.map((s) => ({
                key: `go-${s}`,
                label: t(`page.coa.action.${s}`, s.replace(/_/g, " ")),
                variant: s === "cancelled" ? ("danger" as const) : ("primary" as const),
                onClick: () => void transitionTo(s),
              })),
              {
                key: "back",
                label: t("common.back", "Back"),
                onClick: () => window.location.href = "/charters?type=coa",
              },
            ]}
          />
          <StatusLegend statuses={["draft", "active", "completed", "cancelled"]} />

          {allocation ? (
            <div className="coa-kpis">
              <div className="coa-kpi">
                <span>{t("page.coa.kpi.total_qty", "Contracted")}</span>
                <strong>
                  {allocation.total_qty.toLocaleString()} {allocation.qty_unit}
                </strong>
              </div>
              <div className="coa-kpi">
                <span>{t("page.coa.kpi.planned", "Planned")}</span>
                <strong>
                  {allocation.planned_qty.toLocaleString()} {allocation.qty_unit}
                </strong>
              </div>
              <div className="coa-kpi">
                <span>{t("page.coa.kpi.allocated", "Allocated")}</span>
                <strong>
                  {allocation.allocated_qty.toLocaleString()} {allocation.qty_unit}
                </strong>
              </div>
              <div className="coa-kpi">
                <span>{t("page.coa.kpi.remaining", "Remaining")}</span>
                <strong>
                  {allocation.remaining_qty.toLocaleString()} {allocation.qty_unit}
                </strong>
              </div>
              <div className="coa-kpi">
                <span>{t("page.coa.kpi.unplanned", "Unplanned")}</span>
                <strong>
                  {allocation.unplanned_qty.toLocaleString()} {allocation.qty_unit}
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

          <div className="coa-tab-body">
            {tab === "contract" ? (
              <div className="coa-panel">
                <div className="coa-panel-head">
                  <h3>{t("page.coa.tab.contract", "Contract")}</h3>
                  <div className="quick-row">
                    <ValidateButton onValidate={validateCoa} />
                    <button type="button" className="btn btn-primary" onClick={saveContract} disabled={saving}>
                      {t("common.save", "Save")}
                    </button>
                  </div>
                </div>
                <div className="coa-panel-body">
                  <FormPanel columns={3}>
                    <FormSection title={t("page.coa.terms.quantity", "Quantity & period")} dense>
                      <FieldRow label={t("page.coa.col.total_qty", "Total qty")}>
                        <input
                          type="number"
                          step="any"
                          value={draft.total_qty || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, total_qty: e.target.value }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.coa.terms.qty_unit", "Unit")}>
                        <select
                          value={draft.qty_unit || "mt"}
                          onChange={(e) => setDraft((f) => ({ ...f, qty_unit: e.target.value }))}
                        >
                          <option value="mt">mt</option>
                          <option value="bbl">bbl</option>
                        </select>
                      </FieldRow>
                      <FieldRow label={t("page.coa.col.period_from", "Period from")}>
                        <DateInput
                          value={draft.period_from || ""}
                          onChange={(v) => setDraft((f) => ({ ...f, period_from: v }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.coa.col.period_to", "Period to")}>
                        <DateInput
                          value={draft.period_to || ""}
                          onChange={(v) => setDraft((f) => ({ ...f, period_to: v }))}
                        />
                      </FieldRow>
                    </FormSection>
                    <FormSection title={t("page.coa.terms.rate", "Rate")} dense>
                      <FieldRow label={t("page.coa.col.rate_basis", "Rate basis")}>
                        <select
                          value={draft.rate_basis || "per_voyage"}
                          onChange={(e) => setDraft((f) => ({ ...f, rate_basis: e.target.value }))}
                        >
                          <option value="per_voyage">per_voyage</option>
                          <option value="per_mt">per_mt</option>
                          <option value="lumpsum">lumpsum</option>
                        </select>
                      </FieldRow>
                      <FieldRow label={t("page.coa.col.rate", "Rate")}>
                        <input
                          type="number"
                          step="any"
                          value={draft.rate || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, rate: e.target.value }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.tc.terms.currency", "Currency")}>
                        <select
                          value={draft.currency || "USD"}
                          onChange={(e) => setDraft((f) => ({ ...f, currency: e.target.value }))}
                        >
                          {["USD", "EUR", "GBP", "CNY"].map((c) => (
                            <option key={c} value={c}>
                              {c}
                            </option>
                          ))}
                        </select>
                      </FieldRow>
                    </FormSection>
                    <FormSection title={t("page.coa.terms.cargo", "Cargo")} dense>
                      <FieldRow label={t("page.coa.terms.cargo_spec", "Cargo spec")} span={3}>
                        <textarea
                          value={draft.cargo_spec || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, cargo_spec: e.target.value }))}
                          rows={3}
                        />
                      </FieldRow>
                      {/* C1-P1 货物 CP 条款：计费量基准 / MOL 公差 / 超量加价 */}
                      <FieldRow label={t("page.coa.terms.bill_by", "Bill by")}>
                        <select
                          value={draft.bill_by || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, bill_by: e.target.value }))}
                        >
                          <option value="">—</option>
                          <option value="weight">weight</option>
                          <option value="measure">measure</option>
                          <option value="volume">volume</option>
                        </select>
                      </FieldRow>
                      <FieldRow label={t("page.coa.terms.tolerance_pct", "Tolerance % (0–50)")}>
                        <input
                          type="number"
                          step="any"
                          min={0}
                          max={50}
                          value={draft.tolerance_pct || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, tolerance_pct: e.target.value }))}
                        />
                      </FieldRow>
                      <FieldRow label={t("page.coa.terms.overage_pct", "Overage % (0–100)")}>
                        <input
                          type="number"
                          step="any"
                          min={0}
                          max={100}
                          value={draft.overage_pct || ""}
                          onChange={(e) => setDraft((f) => ({ ...f, overage_pct: e.target.value }))}
                        />
                      </FieldRow>
                    </FormSection>
                  </FormPanel>
                </div>
              </div>
            ) : null}

            {tab === "liftings" ? (
              <div className="coa-panel">
                <div className="coa-panel-head">
                  <h3>{t("page.coa.tab.liftings", "Lifting Schedule")}</h3>
                </div>
                <div className="coa-panel-body">
                  <DataGrid
                    columns={liftingColumns}
                    data={liftings}
                    rowKey={(r) => r.id}
                    loading={tabBusy}
                    storageKey="coa-liftings"
                    emptyText={t("common.empty", "No records")}
                  />
                </div>
              </div>
            ) : null}

            {tab === "allocation" ? (
              <div className="coa-panel">
                <div className="coa-panel-head">
                  <h3>{t("page.coa.tab.allocation", "Itinerary Allocation")}</h3>
                  <div className="quick-row">
                    {allocation ? (
                      <span className="muted">
                        {t("page.coa.alloc.ratio", "Allocated {pct} of contracted", { pct: `${allocPct.toFixed(1)}%` })}
                      </span>
                    ) : null}
                    <button type="button" className="btn btn-sm" onClick={() => void loadScore()} disabled={scoreBusy}>
                      {scoreBusy ? t("common.loading", "Loading…") : t("page.coa.score_match", "Score match")}
                    </button>
                  </div>
                </div>
                <div className="coa-panel-body">
                  {allocation ? (
                    <>
                      <div className="coa-alloc-bar" aria-hidden>
                        <div className="alloc-done" style={{ width: `${allocPct}%` }} />
                        <div className="alloc-open" style={{ width: `${100 - allocPct}%` }} />
                      </div>
                      <DataGrid
                        columns={itineraryColumns}
                        data={allocation.itineraries || []}
                        rowKey={(r) => String(r.seq)}
                        loading={tabBusy}
                        storageKey="coa-allocation"
                        emptyText={t("common.empty", "No records")}
                      />
                    </>
                  ) : (
                    <p className="muted">{t("common.loading", "Loading…")}</p>
                  )}
                  {score ? (
                    <div className="desk-section">
                      <h3>{t("page.coa.score_title", "Cargo × leg score (0–100)")}</h3>
                      {score.items.length === 0 ? (
                        <p className="muted">{t("page.coa.score_empty", "No itinerary legs to score")}</p>
                      ) : (
                        score.items.map((leg) => (
                          <div key={leg.itinerary_id || leg.seq} className="desk-section">
                            <p className="muted">
                              {t("page.coa.score_leg", "Leg {seq}", { seq: leg.seq })} · {portName(leg.load_port_id)} → {portName(leg.disch_port_id)}
                              {leg.qty != null ? ` · ${leg.qty.toLocaleString()}` : ""}
                            </p>
                            {leg.matches.length === 0 ? (
                              <p className="muted">{t("page.coa.score_no_match", "No matching cargoes")}</p>
                            ) : (
                              <DataGrid<ScoreMatch>
                                columns={scoreMatchColumns}
                                data={leg.matches}
                                rowKey={(r, i) => `${leg.seq}-${r.cargo_id || i}`}
                                storageKey="coa-score-matches"
                                showFooter={false}
                                showColumnMenu={false}
                                emptyText={t("common.empty", "No records")}
                              />
                            )}
                          </div>
                        ))
                      )}
                    </div>
                  ) : null}
                </div>
              </div>
            ) : null}

            {tab === "voyages" ? (
              <div className="coa-panel">
                <div className="coa-panel-head">
                  <h3>{t("page.coa.tab.voyages", "Linked Voyages")}</h3>
                </div>
                <div className="coa-panel-body">
                  <DataGrid
                    columns={voyageColumns}
                    data={linkedVoyages}
                    rowKey={(r) => r.key}
                    loading={tabBusy}
                    storageKey="coa-voyages"
                    emptyText={t("common.empty", "No records")}
                  />
                </div>
              </div>
            ) : null}

            {tab === "pnl" ? (
              <div className="coa-panel">
                <div className="coa-panel-head">
                  <h3>{t("page.coa.tab.pnl", "Fuel-neutral P&L")}</h3>
                  {pnl ? (
                    <span className="muted">
                      {pnl.rate_basis} · {pnl.rate.toLocaleString()} {pnl.currency}
                    </span>
                  ) : null}
                </div>
                <div className="coa-panel-body">
                  {pnl ? (
                    <>
                      <div className="coa-kpis">
                        <div className="coa-kpi">
                          <span>{t("page.coa.pnl.revenue", "Revenue")}</span>
                          <strong>{pnl.revenue.toLocaleString()}</strong>
                        </div>
                        <div className="coa-kpi">
                          <span>{t("page.coa.pnl.fuel_cost", "Fuel cost")}</span>
                          <strong>{pnl.fuel_cost.toLocaleString()}</strong>
                        </div>
                        <div className="coa-kpi">
                          <span>{t("page.coa.pnl.other_cost", "Other cost")}</span>
                          <strong>{pnl.other_cost.toLocaleString()}</strong>
                        </div>
                        <div className={`coa-kpi ${pnl.pnl_fuel_neutral >= 0 ? "coa-kpi-pos" : "coa-kpi-neg"}`}>
                          <span>{t("page.coa.pnl.fuel_neutral", "P&L fuel-neutral")}</span>
                          <strong>{pnl.pnl_fuel_neutral.toLocaleString()}</strong>
                        </div>
                        <div className={`coa-kpi ${pnl.pnl_gross >= 0 ? "coa-kpi-pos" : "coa-kpi-neg"}`}>
                          <span>{t("page.coa.pnl.gross", "P&L gross")}</span>
                          <strong>{pnl.pnl_gross.toLocaleString()}</strong>
                        </div>
                        <div className="coa-kpi">
                          <span>{t("page.coa.pnl.completed", "Completed liftings")}</span>
                          <strong>
                            {pnl.completed_liftings} / {pnl.completed_qty.toLocaleString()} {contract.qty_unit}
                          </strong>
                        </div>
                        <div className="coa-kpi">
                          <span>{t("page.coa.pnl.voyage_count", "Voyages")}</span>
                          <strong>{pnl.voyage_count}</strong>
                        </div>
                      </div>
                      <DataGrid<PnlLine>
                        columns={pnlLineColumns}
                        data={pnlLines}
                        rowKey={(r) => r.key}
                        storageKey="coa_pnl_lines"
                        showFooter={false}
                        showColumnMenu={false}
                        emptyText={t("common.empty", "No records")}
                      />
                      <p className="muted" style={{ marginTop: 10 }}>
                        {t(
                          "page.coa.pnl.hint",
                          "Fuel-neutral P&L strips bunker price effects: revenue − non-fuel costs. Gross P&L deducts fuel cost as well.",
                        )}
                      </p>
                    </>
                  ) : (
                    <p className="muted">{t("common.loading", "Loading…")}</p>
                  )}
                </div>
              </div>
            ) : null}
          </div>
          {contract ? <RevisionsPanel entityType="coa_contract" entityId={contract.id} /> : null}
        </>
      ) : loading ? (
        <p className="muted">{t("common.loading", "Loading…")}</p>
      ) : (
        <p className="flash-err">{t("common.not_found", "Not found")}</p>
      )}
    </AppShell>
  );
}
