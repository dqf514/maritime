"use client";

// Report templates gallery + 我的报表 + 调度计划
// Section 1: 模板卡片画廊（按类别分组）— Run / Customize
// Section 2: 我的报表 — Run / Edit / Export / Schedule
// Section 3: 调度计划 — 频率 / 收件人 / 状态 + 新增/编辑

import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { FormPanel, FormSection, FieldRow } from "@/components/form/FormPanel";
import { NavIcon } from "@/components/NavIcon";
import { apiGet, apiPost, apiPatch, apiDelete } from "@/lib/api";
import { useI18n, type TFallback } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type Report = {
  id: string;
  report_name: string;
  report_type: string;
  data_source: string;
  is_system: boolean;
  description: string | null;
  created_at?: string | null;
};

type ReportResult = {
  columns: { key: string; label: string; format?: string; width?: number }[];
  rows: Record<string, unknown>[];
  total_rows: number;
  error?: string;
};

type Schedule = {
  id: string;
  report_id: string;
  schedule_type: string;
  cron_expression: string | null;
  recipients: string[] | null;
  output_format: string;
  is_active: boolean;
  last_run_at: string | null;
};

type CatKey = "commercial" | "laytime" | "finance" | "operations" | "emissions";

type Tpl = {
  key: string;
  cat: CatKey;
  name: TFallback;
  desc: TFallback;
  report_type?: string;
};

const CATEGORIES: { key: CatKey; label: TFallback; icon: string }[] = [
  { key: "commercial", label: { en: "Commercial", zh: "商务" }, icon: "estimates" },
  { key: "laytime", label: { en: "Laytime & Claims", zh: "装卸时间与索赔" }, icon: "ops" },
  { key: "finance", label: { en: "Finance", zh: "财务" }, icon: "finance" },
  { key: "operations", label: { en: "Operations", zh: "运营" }, icon: "ship" },
  { key: "emissions", label: { en: "Emissions", zh: "排放" }, icon: "emissions" },
];

const TEMPLATES: Tpl[] = [
  // —— Commercial ——
  {
    key: "voyage_pnl",
    cat: "commercial",
    name: { en: "Voyage P&L", zh: "航次损益" },
    desc: {
      en: "Voyage profit & loss with estimate vs actual comparison.",
      zh: "航次损益，预估与实际对比。",
    },
    report_type: "voyage_pnl",
  },
  {
    key: "tce_analysis",
    cat: "commercial",
    name: { en: "TCE Analysis", zh: "TCE 分析" },
    desc: {
      en: "Time charter equivalent earnings by voyage and vessel.",
      zh: "按航次与船舶的等效期租收益分析。",
    },
    report_type: "tce_analysis",
  },
  {
    key: "estimate_vs_actual",
    cat: "commercial",
    name: { en: "Estimate vs Actual", zh: "预估与实际对比" },
    desc: {
      en: "Variance of revenue, bunker, port cost and TCE against the fixture estimate.",
      zh: "收入、燃油、港口费与 TCE 相对估价的差异。",
    },
  },
  {
    key: "fixture_recap",
    cat: "commercial",
    name: { en: "Fixture Recap", zh: "成交回顾" },
    desc: {
      en: "Fixture summary recap — main terms, parties and laycan.",
      zh: "成交要点回顾——主要条款、各方与受载期。",
    },
  },
  {
    key: "sof_statement",
    cat: "commercial",
    name: { en: "SOF Statement", zh: "装卸事实记录" },
    desc: {
      en: "Statement of facts timeline per port call with laytime implications.",
      zh: "各港口靠泊的装卸事实时间线及装卸时间影响。",
    },
  },
  // —— Laytime & Claims ——
  {
    key: "laytime_statement",
    cat: "laytime",
    name: { en: "Laytime Statement", zh: "装卸时间计算书" },
    desc: {
      en: "Laytime computation with allowed time, used time and deductions.",
      zh: "装卸时间计算：可用时间、已用时间与扣减。",
    },
  },
  {
    key: "demurrage_report",
    cat: "laytime",
    name: { en: "Demurrage Report", zh: "滞期费报告" },
    desc: {
      en: "Demurrage and despatch accruals per voyage with claim status.",
      zh: "按航次的滞期/速遣费计提与索赔状态。",
    },
  },
  {
    key: "claims_summary",
    cat: "laytime",
    name: { en: "Claims Summary", zh: "索赔汇总" },
    desc: {
      en: "Open and settled claims by counterparty, type and time bar.",
      zh: "按对手方、类型与时效的未结/已结索赔汇总。",
    },
  },
  // —— Finance ——
  {
    key: "trial_balance",
    cat: "finance",
    name: { en: "Trial Balance", zh: "试算平衡表" },
    desc: {
      en: "GL account balances for a period with debit/credit totals.",
      zh: "期间内总账科目余额与借贷合计。",
    },
  },
  {
    key: "commission_report",
    cat: "finance",
    name: { en: "Commission Report", zh: "佣金报告" },
    desc: {
      en: "Commission accruals and payments by broker and fixture.",
      zh: "按经纪人与成交的佣金计提与支付。",
    },
  },
  {
    key: "statement_of_account",
    cat: "finance",
    name: { en: "Statement of Account", zh: "对账单" },
    desc: {
      en: "Counterparty statement — invoices, payments and running balance.",
      zh: "对手方对账单——发票、收付款与滚动余额。",
    },
  },
  {
    key: "age_days",
    cat: "finance",
    name: { en: "Age Days", zh: "账龄分析" },
    desc: {
      en: "Receivable/payable aging analysis with aging buckets.",
      zh: "应收/应付账龄分析与账龄区间。",
    },
    report_type: "age_days",
  },
  {
    key: "port_cost_breakdown",
    cat: "finance",
    name: { en: "Port Cost Breakdown", zh: "港口费明细" },
    desc: {
      en: "Port disbursement breakdown by cost item and port.",
      zh: "按费用科目与港口的使费明细。",
    },
  },
  {
    key: "credit_exposure",
    cat: "finance",
    name: { en: "Credit Exposure", zh: "信用敞口" },
    desc: {
      en: "Outstanding exposure and credit limits by counterparty.",
      zh: "按对手方的未结敞口与信用额度。",
    },
    report_type: "counterparty",
  },
  // —— Operations ——
  {
    key: "fleet_performance",
    cat: "operations",
    name: { en: "Fleet Performance", zh: "船队业绩" },
    desc: {
      en: "Fleet-wide operational and commercial performance summary.",
      zh: "全船队运营与商业业绩汇总。",
    },
    report_type: "fleet_performance",
  },
  {
    key: "noon_report_summary",
    cat: "operations",
    name: { en: "Noon Report Summary", zh: "午报汇总" },
    desc: {
      en: "Daily noon positions, speed, consumption and weather.",
      zh: "每日午间船位、航速、油耗与天气汇总。",
    },
  },
  {
    key: "bunker_reconciliation",
    cat: "operations",
    name: { en: "Bunker Reconciliation", zh: "燃油对账" },
    desc: {
      en: "Bunker consumption vs ROB reconciliation by vessel and voyage.",
      zh: "按船舶与航次的油耗与 ROB 对账。",
    },
    report_type: "bunker",
  },
  {
    key: "vessel_utilization",
    cat: "operations",
    name: { en: "Vessel Utilization", zh: "船舶利用率" },
    desc: {
      en: "Trading days, off-hire and utilization percentage per vessel.",
      zh: "各船营运天、停租与利用率百分比。",
    },
  },
  {
    key: "port_details",
    cat: "operations",
    name: { en: "Port Details", zh: "港口明细" },
    desc: {
      en: "Port call statistics, stay duration and costs.",
      zh: "靠泊统计、在港时间与费用。",
    },
    report_type: "port_details",
  },
  // —— Emissions ——
  {
    key: "mrv_voyage",
    cat: "emissions",
    name: { en: "MRV Voyage", zh: "MRV 航次" },
    desc: {
      en: "EU MRV voyage emissions data with cargo and distance.",
      zh: "EU MRV 航次排放数据，含货量与距离。",
    },
  },
  {
    key: "eu_ets_cost",
    cat: "emissions",
    name: { en: "EU ETS Cost", zh: "EU ETS 成本" },
    desc: {
      en: "EU ETS allowance cost allocation per voyage and charter party.",
      zh: "按航次与租约的 EU ETS 配额成本分摊。",
    },
  },
  {
    key: "cii_annual",
    cat: "emissions",
    name: { en: "CII Annual", zh: "CII 年度" },
    desc: {
      en: "Annual CII rating, AER trend and reduction pathway.",
      zh: "年度 CII 评级、AER 趋势与减排路径。",
    },
  },
  {
    key: "cargo_emissions",
    cat: "emissions",
    name: { en: "Cargo Emissions", zh: "货物排放" },
    desc: {
      en: "CO2 emissions per cargo unit for compliance reporting.",
      zh: "单位货物 CO2 排放，用于合规报告。",
    },
    report_type: "emissions",
  },
];

const SCHEDULE_TYPES = ["on_demand", "daily", "weekly", "monthly"];
const OUTPUT_FORMATS = ["excel", "csv", "pdf"];

function shortTs(v: string | null | undefined): string {
  if (!v) return "—";
  return v.slice(0, 16).replace("T", " ");
}

export default function ReportsPage() {
  const { t } = useI18n();
  const toast = useToast();

  const [reports, setReports] = useState<Report[]>([]);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [loading, setLoading] = useState(true);

  const [catFilter, setCatFilter] = useState<CatKey | "all">("all");
  const [result, setResult] = useState<(ReportResult & { title: string }) | null>(null);
  const [runningKey, setRunningKey] = useState<string | null>(null);

  // schedule modal
  const [schedOpen, setSchedOpen] = useState(false);
  const [schedEditing, setSchedEditing] = useState<Schedule | null>(null);
  const [schedReport, setSchedReport] = useState("");
  const [schedType, setSchedType] = useState("daily");
  const [schedCron, setSchedCron] = useState("");
  const [schedRecipients, setSchedRecipients] = useState("");
  const [schedFormat, setSchedFormat] = useState("excel");
  const [schedActive, setSchedActive] = useState(true);
  const [schedSaving, setSchedSaving] = useState(false);
  const [confirmDelSched, setConfirmDelSched] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet("/api/v1/reports");
      setReports(Array.isArray(data) ? data : []);
    } catch {
      setReports([]);
    }
    try {
      const data = await apiGet("/api/v1/reports/schedules/list");
      setSchedules(Array.isArray(data) ? data : []);
    } catch {
      setSchedules([]);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  // ————————————— run / export —————————————

  async function executeReport(rep: Report, runKey: string) {
    setRunningKey(runKey);
    setResult({ title: rep.report_name, columns: [], rows: [], total_rows: 0 });
    try {
      const res = await apiPost(`/api/v1/reports/${rep.id}/execute`, {});
      setResult({ title: rep.report_name, ...res });
    } catch (err) {
      setResult({
        title: rep.report_name,
        columns: [],
        rows: [],
        total_rows: 0,
        error: err instanceof Error ? err.message : String(err),
      });
    }
    setRunningKey(null);
    if (typeof document !== "undefined") {
      document.getElementById("rg-result")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  async function runTemplate(tpl: Tpl) {
    if (!tpl.report_type) {
      toast.info(
        t("rg.tpl.build_first", {
          en: "This template has no preset engine yet — open Customize to build it.",
          zh: "该模板尚无预置引擎——请通过“自定义”构建。",
        }),
      );
      return;
    }
    let rep = reports.find((r) => r.report_type === tpl.report_type);
    if (!rep) {
      try {
        await apiGet("/api/v1/reports/system/seed");
        toast.info(t("rg.seeded", { en: "System reports seeded", zh: "系统报表已初始化" }));
      } catch {
        /* seeding is best-effort */
      }
      await loadAll();
      rep = reports.find((r) => r.report_type === tpl.report_type);
    }
    if (!rep) {
      toast.info(
        t("rg.tpl.build_first", {
          en: "This template has no preset engine yet — open Customize to build it.",
          zh: "该模板尚无预置引擎——请通过“自定义”构建。",
        }),
      );
      return;
    }
    await executeReport(rep, `tpl:${tpl.key}`);
  }

  async function exportCsv(rep: Report) {
    try {
      const res = await apiGet(`/api/v1/reports/${rep.id}/export/csv`);
      const blob = new Blob([res.csv], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${rep.report_name.replace(/\s+/g, "_")}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success(t("rg.exported", { en: "CSV exported", zh: "CSV 已导出" }));
    } catch {
      toast.error(t("rg.export_fail", { en: "Export failed", zh: "导出失败" }));
    }
  }

  // ————————————— schedule modal —————————————

  function openSchedule(rep?: Report) {
    setSchedEditing(null);
    setSchedReport(rep?.id ?? reports[0]?.id ?? "");
    setSchedType("daily");
    setSchedCron("");
    setSchedRecipients("");
    setSchedFormat("excel");
    setSchedActive(true);
    setSchedOpen(true);
  }

  function openScheduleEdit(s: Schedule) {
    setSchedEditing(s);
    setSchedReport(s.report_id);
    setSchedType(s.schedule_type);
    setSchedCron(s.cron_expression ?? "");
    setSchedRecipients((s.recipients ?? []).join(", "));
    setSchedFormat(s.output_format || "excel");
    setSchedActive(!!s.is_active);
    setSchedOpen(true);
  }

  async function saveSchedule(e: FormEvent) {
    e.preventDefault();
    if (!schedReport && !schedEditing) {
      toast.error(t("rg.sched.need_report", { en: "Select a report first", zh: "请先选择报表" }));
      return;
    }
    const recipients = schedRecipients
      .split(/[,\s;]+/)
      .map((x) => x.trim())
      .filter(Boolean);
    setSchedSaving(true);
    try {
      if (schedEditing) {
        await apiPatch(`/api/v1/reports/schedules/${schedEditing.id}`, {
          schedule_type: schedType,
          cron_expression: schedCron.trim() || null,
          recipients,
          output_format: schedFormat,
          is_active: schedActive,
        });
      } else {
        await apiPost("/api/v1/reports/schedules", {
          report_id: schedReport,
          schedule_type: schedType,
          cron_expression: schedCron.trim() || null,
          recipients,
          output_format: schedFormat,
          is_active: schedActive,
        });
      }
      toast.success(t("rg.sched.saved", { en: "Schedule saved", zh: "调度已保存" }));
      setSchedOpen(false);
      await loadAll();
    } catch (err) {
      toast.error(
        t("rg.sched.save_fail", { en: "Save failed: {msg}", zh: "保存失败：{msg}" }, {
          msg: err instanceof Error ? err.message : String(err),
        }),
      );
    }
    setSchedSaving(false);
  }

  async function deleteSchedule(id: string) {
    try {
      await apiDelete(`/api/v1/reports/schedules/${id}`);
      toast.success(t("rg.sched.deleted", { en: "Schedule deleted", zh: "调度已删除" }));
      await loadAll();
    } catch {
      toast.error(t("rg.sched.delete_fail", { en: "Delete failed", zh: "删除失败" }));
    }
  }

  // ————————————— columns —————————————

  const reportNameOf = useCallback(
    (id: string) => reports.find((r) => r.id === id)?.report_name ?? id.slice(0, 8),
    [reports],
  );

  const myReportCols: ColumnDef<Report>[] = useMemo(
    () => [
      {
        key: "report_name",
        title: t("rg.col.name", "Report name"),
        width: 220,
        sticky: true,
        value: (r) => r.report_name,
        render: (v, r) => (
          <span>
            {String(v)}
            {r.is_system ? <span className="rg-card-tag">{t("rg.system", "system")}</span> : null}
          </span>
        ),
      },
      { key: "report_type", title: t("common.type", "Type"), width: 130, value: (r) => r.report_type },
      { key: "data_source", title: t("rg.col.source", "Source"), width: 90, value: (r) => r.data_source },
      {
        key: "created_at",
        title: t("common.created", "Created"),
        width: 130,
        value: (r) => r.created_at ?? "",
        render: (v) => shortTs(v as string),
      },
      {
        key: "_act",
        title: t("common.actions", "Actions"),
        width: 240,
        value: (r) => r.id,
        render: (_v, r) => (
          <span className="rg-actions">
            <button type="button" onClick={(e) => { e.stopPropagation(); executeReport(r, `rep:${r.id}`); }}>
              {runningKey === `rep:${r.id}` ? "…" : t("common.run", "Run")}
            </button>
            <Link href="/analytics/reports/builder" className="btn btn-sm btn-ghost" onClick={(e) => e.stopPropagation()}>
              {t("common.edit", "Edit")}
            </Link>
            <button type="button" onClick={(e) => { e.stopPropagation(); exportCsv(r); }}>
              {t("common.export", "Export")}
            </button>
            <button type="button" onClick={(e) => { e.stopPropagation(); openSchedule(r); }}>
              {t("rg.schedule", "Schedule")}
            </button>
          </span>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, runningKey, reports],
  );

  const scheduleCols: ColumnDef<Schedule & { report_name: string }>[] = useMemo(
    () => [
      {
        key: "report_name",
        title: t("rg.col.report", "Report"),
        width: 200,
        sticky: true,
        value: (r) => r.report_name,
      },
      {
        key: "schedule_type",
        title: t("rg.col.frequency", "Frequency"),
        width: 110,
        value: (r) => r.schedule_type,
        render: (v) => String(v ?? "—"),
      },
      {
        key: "cron_expression",
        title: t("rg.col.next_run", "Next run"),
        width: 140,
        value: (r) => r.cron_expression ?? "",
        render: (v, r) => (r.is_active ? (v ? String(v) : t("rg.per_schedule", "per schedule")) : "—"),
      },
      {
        key: "recipients",
        title: t("rg.col.recipients", "Recipients"),
        width: 220,
        value: (r) => (r.recipients ?? []).join(", "),
        render: (v) => (v ? String(v) : "—"),
      },
      {
        key: "output_format",
        title: t("rg.col.format", "Format"),
        width: 80,
        value: (r) => r.output_format,
      },
      {
        key: "is_active",
        title: t("common.status", "Status"),
        width: 90,
        value: (r) => r.is_active,
        render: (v, r) => (
          <span className={`rg-pill ${v ? "on" : "off"}`}>
            {v ? t("rg.active", "Active") : t("rg.paused", "Paused")}
          </span>
        ),
      },
      {
        key: "last_run_at",
        title: t("rg.col.last_run", "Last run"),
        width: 130,
        value: (r) => r.last_run_at ?? "",
        render: (v) => shortTs(v as string),
      },
      {
        key: "_act",
        title: t("common.actions", "Actions"),
        width: 130,
        value: (r) => r.id,
        render: (_v, r) => (
          <span className="rg-actions">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                openScheduleEdit(r);
              }}
            >
              {t("common.edit", "Edit")}
            </button>
            <button
              type="button"
              className="danger"
              onClick={(e) => {
                e.stopPropagation();
                setConfirmDelSched(r.id);
              }}
            >
              {t("common.delete", "Delete")}
            </button>
          </span>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t],
  );

  const scheduleRows = useMemo(
    () => schedules.map((s) => ({ ...s, report_name: reportNameOf(s.report_id) })),
    [schedules, reportNameOf],
  );

  const resultCols: ColumnDef<Record<string, unknown>>[] = useMemo(
    () =>
      (result?.columns ?? []).map((c) => ({
        key: c.key,
        title: c.label,
        width: c.width || 140,
        align: c.format === "currency" || c.format === "number" ? ("right" as const) : undefined,
        value: (r: Record<string, unknown>) => r[c.key],
        render: (v: unknown) => {
          if (v === null || v === undefined) return "";
          if (c.format === "currency")
            return Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
          if (c.format === "number") return Number(v).toLocaleString();
          return String(v);
        },
      })),
    [result],
  );

  // ————————————— render —————————————

  const visibleCats = CATEGORIES.filter((c) => catFilter === "all" || c.key === catFilter);

  return (
    <AppShell>
      <PageHeader
        title={t("page.reports.title", { en: "Reports", zh: "报表中心" })}
        subtitle={t("page.reports.sub", {
          en: "Template gallery, custom reports and scheduled delivery.",
          zh: "模板画廊、自定义报表与定时发送。",
        })}
      />
      <div className="rg-wrap">
        {/* ——————— Section 1: Template gallery ——————— */}
        <section className="rg-section">
          <div className="rg-section-head">
            <div>
              <h2>{t("rg.gallery", { en: "Report templates", zh: "报表模板" })}</h2>
              <span className="sub">
                {t("rg.gallery_sub", {
                  en: "Pick a template to run it now, or customize it in the report designer.",
                  zh: "选择模板立即运行，或在报表设计器中自定义。",
                })}
              </span>
            </div>
            <div className="rg-filter">
              <button
                type="button"
                className={catFilter === "all" ? "active" : ""}
                onClick={() => setCatFilter("all")}
              >
                {t("common.all", "All")}
              </button>
              {CATEGORIES.map((c) => (
                <button
                  key={c.key}
                  type="button"
                  className={catFilter === c.key ? "active" : ""}
                  onClick={() => setCatFilter(c.key)}
                >
                  {t(`rg.cat.${c.key}`, c.label)}
                </button>
              ))}
            </div>
          </div>

          {visibleCats.map((cat) => {
            const items = TEMPLATES.filter((x) => x.cat === cat.key);
            return (
              <div className="rg-cat" key={cat.key}>
                <div className="rg-cat-head">
                  <NavIcon id={cat.icon} size={14} />
                  {t(`rg.cat.${cat.key}`, cat.label)}
                  <span className="count">({items.length})</span>
                </div>
                <div className="rg-grid">
                  {items.map((tpl) => (
                    <article className="rg-card" key={tpl.key}>
                      <div className="rg-card-top">
                        <span className="rg-card-icon">
                          <NavIcon id={cat.icon} size={15} />
                        </span>
                        <h3 className="rg-card-name">
                          {t(`rg.tpl.${tpl.key}`, tpl.name)}
                          {tpl.report_type ? (
                            <span className="rg-card-tag">{t("rg.preset", "preset")}</span>
                          ) : null}
                        </h3>
                      </div>
                      <p className="rg-card-desc">{t(`rg.tpld.${tpl.key}`, tpl.desc)}</p>
                      <div className="rg-card-actions">
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          disabled={runningKey === `tpl:${tpl.key}`}
                          onClick={() => runTemplate(tpl)}
                        >
                          {runningKey === `tpl:${tpl.key}` ? "…" : t("common.run", "Run")}
                        </button>
                        <Link href="/analytics/reports/builder" className="btn btn-sm btn-ghost">
                          {t("rg.customize", "Customize")}
                        </Link>
                      </div>
                    </article>
                  ))}
                </div>
              </div>
            );
          })}
        </section>

        {/* ——————— Run result ——————— */}
        {result && (
          <section className="rg-result" id="rg-result">
            <div className="rg-result-head">
              <h3>
                {result.title}
                <span className="meta">{t("rg.rows", { en: "{n} rows", zh: "{n} 行" }, { n: String(result.total_rows) })}</span>
              </h3>
              <div style={{ display: "flex", gap: 8 }}>
                <Link href="/analytics/reports/builder" className="btn btn-sm btn-ghost">
                  {t("rg.customize", "Customize")}
                </Link>
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => setResult(null)}>
                  {t("common.close", "Close")}
                </button>
              </div>
            </div>
            {result.error && (
              <div className="rg-empty" style={{ color: "var(--danger)" }}>
                {result.error}
              </div>
            )}
            {!result.error && result.columns.length > 0 && (
              <DataGrid<Record<string, unknown>>
                columns={resultCols}
                data={result.rows}
                rowKey={(_r, i) => `row-${i}`}
                emptyText={t("rg.no_data", "No data for this report run.")}
                showFooter
                storageKey="rg_result"
              />
            )}
            {!result.error && result.columns.length === 0 && (
              <div className="rg-empty">{t("rg.no_data", "No data for this report run.")}</div>
            )}
          </section>
        )}

        {/* ——————— Section 2: My reports ——————— */}
        <section className="rg-section">
          <div className="rg-section-head">
            <div>
              <h2>{t("rg.my_reports", { en: "My reports", zh: "我的报表" })}</h2>
              <span className="sub">
                {t("rg.my_reports_sub", {
                  en: "Saved report definitions — run, edit, export or schedule them.",
                  zh: "已保存的报表定义——可运行、编辑、导出或排程。",
                })}
              </span>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                type="button"
                className="btn btn-sm"
                onClick={async () => {
                  try {
                    const res = await apiGet("/api/v1/reports/system/seed");
                    toast.success(res.message || t("rg.seeded", { en: "System reports seeded", zh: "系统报表已初始化" }));
                  } catch {
                    toast.error(t("rg.seed_fail", { en: "Seed failed", zh: "初始化失败" }));
                  }
                  await loadAll();
                }}
              >
                {t("rg.seed_system", "Seed system")}
              </button>
              <Link href="/analytics/reports/builder" className="btn btn-primary btn-sm">
                {t("rg.new_report", { en: "New report", zh: "新建报表" })}
              </Link>
            </div>
          </div>
          <DataGrid<Report>
            columns={myReportCols}
            data={reports}
            rowKey={(r) => r.id}
            loading={loading}
            emptyText={t(
              "rg.my_empty",
              "No reports yet — seed the system set or create one in the designer.",
            )}
            onRowDoubleClick={(r) => executeReport(r, `rep:${r.id}`)}
            showFooter={false}
            storageKey="rg_my_reports"
          />
        </section>

        {/* ——————— Section 3: Schedules ——————— */}
        <section className="rg-section">
          <div className="rg-section-head">
            <div>
              <h2>{t("rg.schedules", { en: "Schedules", zh: "调度计划" })}</h2>
              <span className="sub">
                {t("rg.schedules_sub", {
                  en: "Recurring report delivery to recipients by email.",
                  zh: "按频率向收件人邮件发送报表。",
                })}
              </span>
            </div>
            <button type="button" className="btn btn-primary btn-sm" onClick={() => openSchedule()}>
              {t("rg.add_schedule", { en: "Add schedule", zh: "新增调度" })}
            </button>
          </div>
          <DataGrid<Schedule & { report_name: string }>
            columns={scheduleCols}
            data={scheduleRows}
            rowKey={(r) => r.id}
            loading={loading}
            emptyText={t("rg.sched_empty", "No report schedules yet.")}
            onRowDoubleClick={(r) => openScheduleEdit(r)}
            showFooter={false}
            storageKey="rg_schedules"
          />
        </section>
      </div>

      {/* ——————— Schedule modal ——————— */}
      <RecordModal
        open={schedOpen}
        title={
          schedEditing
            ? t("rg.sched.edit_title", { en: "Edit schedule", zh: "编辑调度" })
            : t("rg.sched.new_title", { en: "New schedule", zh: "新增调度" })
        }
        onClose={() => setSchedOpen(false)}
        onSave={saveSchedule}
        onDelete={schedEditing ? () => deleteSchedule(schedEditing.id) : undefined}
        canDelete={!!schedEditing}
        saving={schedSaving}
        size="lg"
      >
        <FormPanel columns={2}>
          <FormSection title={t("rg.sched.section", { en: "Delivery", zh: "发送设置" })} dense>
            <FieldRow label={t("rg.col.report", "Report")} span={2}>
              <select
                value={schedReport}
                onChange={(e) => setSchedReport(e.target.value)}
                disabled={!!schedEditing}
              >
                {reports.length === 0 && <option value="">{t("rg.no_reports", "No reports")}</option>}
                {reports.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.report_name}
                  </option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label={t("rg.col.frequency", "Frequency")}>
              <select value={schedType} onChange={(e) => setSchedType(e.target.value)}>
                {SCHEDULE_TYPES.map((x) => (
                  <option key={x} value={x}>
                    {x}
                  </option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label={t("rg.col.next_run", "Next run")}>
              <input
                type="text"
                value={schedCron}
                onChange={(e) => setSchedCron(e.target.value)}
                placeholder="0 8 * * *"
              />
            </FieldRow>
          </FormSection>
          <FormSection title={t("rg.sched.section_out", { en: "Output", zh: "输出" })} dense>
            <FieldRow label={t("rg.col.recipients", "Recipients")} span={2}>
              <input
                type="text"
                value={schedRecipients}
                onChange={(e) => setSchedRecipients(e.target.value)}
                placeholder="ops@example.com, cfo@example.com"
              />
            </FieldRow>
            <FieldRow label={t("rg.col.format", "Format")}>
              <select value={schedFormat} onChange={(e) => setSchedFormat(e.target.value)}>
                {OUTPUT_FORMATS.map((x) => (
                  <option key={x} value={x}>
                    {x}
                  </option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label={t("rg.active", "Active")}>
              <input
                type="checkbox"
                checked={schedActive}
                onChange={(e) => setSchedActive(e.target.checked)}
                style={{ width: "auto", height: "auto" }}
              />
            </FieldRow>
          </FormSection>
        </FormPanel>
      </RecordModal>

      <ConfirmDialog
        open={confirmDelSched !== null}
        title={t("common.confirm", "Confirm")}
        message={t("rg.sched.confirm_delete", {
          en: "Delete this schedule? Delivery will stop immediately.",
          zh: "确认删除该调度？发送将立即停止。",
        })}
        danger
        onConfirm={() => {
          if (confirmDelSched) deleteSchedule(confirmDelSched);
          setConfirmDelSched(null);
        }}
        onCancel={() => setConfirmDelSched(null)}
      />
    </AppShell>
  );
}
