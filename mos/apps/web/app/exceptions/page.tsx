"use client";

import { Suspense } from "react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { PageHeader } from "@/components/PageHeader";
import { PageGuide } from "@/components/PageGuide";
import { SavedViews } from "@/components/SavedViews";
import { StatusLegend } from "@/components/StatusLegend";
import { Tabs, type TabItem } from "@/components/Tabs";
import { Toolbar } from "@/components/Toolbar";
import { StateView } from "@/components/StateView";
import { apiGet, type ExceptionItem, type ExceptionScan } from "@/lib/api";
import { formatDateInTz, parseUtc } from "@/lib/datetime";
import { downloadCsv } from "@/lib/csv";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";

type SeverityFilter = "all" | "critical" | "warning";

const KIND_FALLBACKS: Record<string, string> = {
  pnl_deterioration: "盈亏恶化",
  eta_delay: "ETA 延误",
  demurrage_open: "滞期未结",
  claim_timebar: "索赔时效",
  invoice_overdue: "发票逾期",
  cert_expired: "证书过期",
  cert_expiring: "证书临期",
  off_hire_open: "停租未关闭",
  tc_redelivery_due: "期租还船临期",
  sanctions_blocked: "制裁拦截",
  dq_issue: "数据质量问题",
};

function ExceptionsPageInner() {
  const { t, locale } = useI18n();
  const router = useRouter();
  const { query, setQuery } = useListQuery();
  const severity: SeverityFilter = query.severity === "critical" || query.severity === "warning" ? query.severity : "all";
  const kind = typeof query.kind === "string" && query.kind ? query.kind : "all";
  const [scan, setScan] = useState<ExceptionScan | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [scannedAt, setScannedAt] = useState<Date | null>(null);
  const [now, setNow] = useState(0);
  const rowCtx = useContextMenu<ExceptionItem>();

  function exportRows(selected: ExceptionItem[]) {
    downloadCsv(
      "exceptions",
      ["kind", "severity", "title", "detail", "value", "entity_type", "entity_id", "detected_at"],
      selected.map((r) => [r.kind, r.severity, r.title, r.detail, r.value, r.entity_type, r.entity_id, r.detected_at]),
    );
  }

  function rowMenuItems(target: ExceptionItem): ContextMenuItem[] {
    return [
      { key: "open", label: t("common.open", "Open"), onClick: () => target.href && router.push(target.href) },
      { key: "copy", label: t("common.copy_id", "Copy id"), onClick: () => void navigator.clipboard?.writeText(target.entity_id) },
      { key: "export", label: t("page.finance.export_selected", "Export selected"), onClick: () => exportRows([target]) },
    ];
  }

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setScan(await apiGet("/api/v1/exceptions/scan"));
      setScannedAt(new Date());
      setNow(Date.now());
    } catch (e: any) {
      setError(e?.message || t("common.failed", "Failed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    load();
  }, [load]);

  const kinds = useMemo(() => {
    const set = new Set<string>();
    for (const item of scan?.items || []) set.add(item.kind);
    return [...set].sort();
  }, [scan]);

  const items = useMemo(() => {
    return (scan?.items || []).filter(
      (item) => (severity === "all" || item.severity === severity) && (kind === "all" || item.kind === kind),
    );
  }, [scan, severity, kind]);

  function kindLabel(k: string) {
    return t(`page.exceptions.kind.${k}`, KIND_FALLBACKS[k] || k);
  }

  function relTime(iso: string) {
    const d = parseUtc(iso);
    if (!d) return "";
    const diff = (now || d.getTime()) - d.getTime();
    if (diff < 60_000) return t("notify.just_now", "Just now");
    if (diff < 3_600_000) return t("notify.minutes_ago", "{n} minutes ago", { n: Math.floor(diff / 60_000) });
    if (diff < 86_400_000) return t("notify.hours_ago", "{n} hours ago", { n: Math.floor(diff / 3_600_000) });
    return formatDateInTz(d, null, locale);
  }

  const summary = scan?.summary;

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.exceptions", "Exceptions") }]}
        title={t("page.exceptions.title", "Exception centre")}
        subtitle={`${t("page.exceptions.sub", "Cross-module business exceptions — click a row to jump to the handling page.")}${
          scannedAt
            ? ` · ${t("page.exceptions.scanned_at", "Scanned at {time}", {
                time: scannedAt.toLocaleTimeString(locale.startsWith("zh") ? "zh-CN" : "en-US"),
              })}`
            : ""
        }`}
        actions={
          <>
            <PageGuide pageKey="exceptions" />
            <SavedViews storageKey="exceptions_list" onApply={(q) => router.replace(`/exceptions${q}`)} />
          </>
        }
      />
      <Toolbar
        filterCount={(severity !== "all" ? 1 : 0) + (kind !== "all" ? 1 : 0)}
        onClearFilters={() => setQuery({ severity: null, kind: null })}
        right={
          <select
            className="input input-sm"
            value={kind}
            onChange={(e) => setQuery({ kind: e.target.value === "all" ? null : e.target.value })}
            aria-label={t("page.exceptions.kind_filter", "Kind")}
          >
            <option value="all">{t("page.exceptions.kind_all", "All kinds")}</option>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {kindLabel(k)}
              </option>
            ))}
          </select>
        }
      >
        <button type="button" className="btn btn-sm" onClick={load} disabled={loading} title={t("common.refresh", "Refresh")}>
          ↻
        </button>
      </Toolbar>

      <StateView loading={loading && !scan} error={error} empty={false} onRetry={load}>
        <div className="exc-summary">
          <span className="exc-badge critical">
            {t("page.exceptions.critical_n", "Critical {n}", { n: summary?.critical ?? 0 })}
          </span>
          <span className="exc-badge warning">
            {t("page.exceptions.warning_n", "Warning {n}", { n: summary?.warning ?? 0 })}
          </span>
          <span className="exc-badge total">{t("page.exceptions.total_n", "{n} total", { n: summary?.total ?? 0 })}</span>
        </div>

        <Tabs
          items={
            [
              { key: "all", label: t("page.exceptions.all", "All") },
              { key: "critical", label: t("page.exceptions.critical", "Critical") },
              { key: "warning", label: t("page.exceptions.warning", "Warning") },
            ] satisfies TabItem[]
          }
          value={severity}
          onChange={(k) => setQuery({ severity: k === "all" ? null : k, kind: kind === "all" ? null : kind })}
          variant="pill"
        />

        <StateView
          loading={false}
          empty={!items.length}
          emptyText={
            severity === "all" && kind === "all"
              ? t("page.exceptions.empty", "No exceptions detected. All clear.")
              : t("page.exceptions.empty_filtered", "No exceptions match the current filters")
          }
        >
          <StatusLegend statuses={["critical", "warning"]} />
          <div className="exc-list">
            {items.map((item: ExceptionItem, i) => (
              <button
                key={`${item.kind}-${item.entity_id}-${i}`}
                type="button"
                className={`exc-row ${item.severity}`}
                onClick={() => item.href && router.push(item.href)}
                onContextMenu={rowCtx.open(item)}
              >
                <span className="exc-row-bar" aria-hidden />
                <span className="exc-row-main">
                  <span className="exc-row-head">
                    <span className={`badge ${item.severity === "critical" ? "badge-fail" : "badge-warn"}`}>
                      {kindLabel(item.kind)}
                    </span>
                    <strong className="exc-row-title">{item.title}</strong>
                  </span>
                  {item.detail ? <small className="muted">{item.detail}</small> : null}
                  <small className="exc-row-time">{relTime(item.detected_at)}</small>
                </span>
                {item.value ? <span className={`exc-row-value ${item.severity}`}>{item.value}</span> : null}
              </button>
            ))}
          </div>
        </StateView>
      </StateView>

      <ContextMenu controller={rowCtx} items={rowMenuItems} />
    </AppShell>
  );
}

export default function ExceptionsPage() {
  return (
    <Suspense fallback={null}>
      <ExceptionsPageInner />
    </Suspense>
  );
}
