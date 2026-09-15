"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { StateView } from "@/components/StateView";
import { apiGet, type ExceptionItem, type ExceptionScan } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

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

export default function ExceptionsPage() {
  const { t, locale } = useI18n();
  const router = useRouter();
  const [scan, setScan] = useState<ExceptionScan | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [severity, setSeverity] = useState<SeverityFilter>("all");
  const [kind, setKind] = useState("all");
  const [scannedAt, setScannedAt] = useState<Date | null>(null);
  const [now, setNow] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setScan(await apiGet("/api/v1/exceptions/scan"));
      setScannedAt(new Date());
      setNow(Date.now());
    } catch (e: any) {
      setError(e?.message || t("common.failed", "加载失败"));
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
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    const diff = (now || d.getTime()) - d.getTime();
    if (diff < 60_000) return t("notify.just_now", "刚刚");
    if (diff < 3_600_000) return t("notify.minutes_ago", "{n} 分钟前", { n: Math.floor(diff / 60_000) });
    if (diff < 86_400_000) return t("notify.hours_ago", "{n} 小时前", { n: Math.floor(diff / 3_600_000) });
    return d.toLocaleDateString(locale.startsWith("zh") ? "zh-CN" : "en-US", { month: "2-digit", day: "2-digit" });
  }

  const summary = scan?.summary;

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.exceptions.title", "异常管理中心")}</h1>
          <p className="page-sub">
            {t("page.exceptions.sub", "跨模块业务异常扫描，点击条目直达处理页面。")}
            {scannedAt
              ? ` · ${t("page.exceptions.scanned_at", "扫描于 {time}", {
                  time: scannedAt.toLocaleTimeString(locale.startsWith("zh") ? "zh-CN" : "en-US"),
                })}`
              : ""}
          </p>
        </div>
        <button type="button" className="btn btn-ghost" onClick={load} disabled={loading}>
          {t("page.exceptions.refresh", "刷新")}
        </button>
      </div>

      <StateView loading={loading && !scan} error={error} empty={false} onRetry={load}>
        <div className="exc-summary">
          <span className="exc-badge critical">
            {t("page.exceptions.critical_n", "严重 {n}", { n: summary?.critical ?? 0 })}
          </span>
          <span className="exc-badge warning">
            {t("page.exceptions.warning_n", "提醒 {n}", { n: summary?.warning ?? 0 })}
          </span>
          <span className="exc-badge total">{t("page.exceptions.total_n", "共 {n} 项", { n: summary?.total ?? 0 })}</span>
        </div>

        <div className="page-tabs" role="tablist">
          {(["all", "critical", "warning"] as SeverityFilter[]).map((s) => (
            <button
              key={s}
              type="button"
              role="tab"
              aria-selected={severity === s}
              className={`page-tab ${severity === s ? "active" : ""}`}
              onClick={() => setSeverity(s)}
            >
              {s === "all"
                ? t("page.exceptions.all", "全部")
                : s === "critical"
                  ? t("page.exceptions.critical", "严重")
                  : t("page.exceptions.warning", "提醒")}
            </button>
          ))}
          <select
            className="exc-kind-select"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            aria-label={t("page.exceptions.kind_filter", "异常类型")}
          >
            <option value="all">{t("page.exceptions.kind_all", "全部类型")}</option>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {kindLabel(k)}
              </option>
            ))}
          </select>
        </div>

        <StateView
          loading={false}
          empty={!items.length}
          emptyText={
            severity === "all" && kind === "all"
              ? t("page.exceptions.empty", "未发现异常，业务运行正常")
              : t("page.exceptions.empty_filtered", "当前筛选条件下没有异常")
          }
        >
          <div className="exc-list">
            {items.map((item: ExceptionItem, i) => (
              <button
                key={`${item.kind}-${item.entity_id}-${i}`}
                type="button"
                className={`exc-row ${item.severity}`}
                onClick={() => item.href && router.push(item.href)}
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
    </AppShell>
  );
}
