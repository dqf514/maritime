"use client";

// 航次收尾面板：清单逐项 ok/缺失 + Actual vs Estimate TCE + 深链。
// 数据源 GET /voyages/{id}/closing-check（services/voyage_close.py）。

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";

type ClosingItem = {
  key: string;
  ok: boolean;
  label: string;
  detail: string;
  severity: "warn" | "info";
  href?: string | null;
  task_title?: string | null;
  assign_role?: string | null;
};

type TceSummary = {
  estimate_tce: number | null;
  actual_tce: number | null;
  variance: number | null;
  days: number | null;
  actual_revenue: number | null;
  actual_cost: number | null;
};

type ClosingCheck = {
  ready: boolean;
  items: ClosingItem[];
  tce: TceSummary;
  missing: string[];
};

function fmtMoney(v: number | null | undefined, locale: string): string {
  if (v === null || v === undefined) return "—";
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(v);
}

export function ClosingPanel({ voyageId }: { voyageId: string }) {
  const { t, locale } = useI18n();
  const [check, setCheck] = useState<ClosingCheck | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    apiGet(`/api/v1/voyages/${voyageId}/closing-check`)
      .then((data: ClosingCheck) => setCheck(data))
      .catch((err: unknown) => setError(msgOf(err)))
      .finally(() => setLoading(false));
  }, [voyageId]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !check) return <p className="muted">{t("ws.closing_loading", "Loading closing checklist…")}</p>;
  if (error) return <p className="form-error">{error}</p>;
  if (!check) return null;

  const tce = check.tce || ({} as TceSummary);
  const missing = check.items.filter((i) => !i.ok && i.severity === "warn");
  const info = check.items.filter((i) => i.severity === "info");

  return (
    <div className="closing-panel">
      <div className={`closing-status ${check.ready ? "closing-ready" : "closing-blocked"}`}>
        <strong>
          {check.ready
            ? t("ws.closing_ready", "Ready to close — checklist complete")
            : t("ws.closing_blocked", "Closeout blocked — follow-up tasks auto-assigned")}
        </strong>
        <button type="button" className="btn btn-ghost btn-sm" onClick={load}>
          {t("common.refresh", "Refresh")}
        </button>
      </div>

      <div className="closing-tce">
        <span>{t("ws.closing_tce", "Actual vs Estimate TCE")}</span>
        <div className="closing-tce-grid">
          <div>
            <em>{t("ws.closing_est_tce", "Estimate TCE")}</em>
            <strong>{fmtMoney(tce.estimate_tce, locale)}</strong>
          </div>
          <div>
            <em>{t("ws.closing_act_tce", "Actual TCE")}</em>
            <strong>{fmtMoney(tce.actual_tce, locale)}</strong>
          </div>
          <div>
            <em>{t("ws.closing_variance", "Variance")}</em>
            <strong className={tce.variance != null && tce.variance < 0 ? "closing-neg" : undefined}>
              {fmtMoney(tce.variance, locale)}
            </strong>
          </div>
          <div>
            <em>{t("ws.closing_days", "Voyage days")}</em>
            <strong>{tce.days != null ? tce.days : "—"}</strong>
          </div>
        </div>
      </div>

      {missing.length > 0 ? (
        <p className="field-hint">
          {t("ws.closing_missing_hint", "Missing items below generate system follow-up tasks on voyage completion.")}
        </p>
      ) : null}

      <ul className="closing-list">
        {check.items
          .filter((i) => i.severity === "warn")
          .map((item) => (
            <li key={item.key} className={item.ok ? "closing-ok" : "closing-missing"}>
              <span className="closing-mark" aria-hidden>
                {item.ok ? "✓" : "!"}
              </span>
              <div>
                <strong>{item.label}</strong>
                <p className="muted">{item.detail}</p>
                {!item.ok && item.href ? (
                  <Link href={item.href}>{t("ws.closing_goto", "Go fix →")}</Link>
                ) : null}
              </div>
            </li>
          ))}
      </ul>

      {info.length > 0 ? (
        <details className="closing-info">
          <summary>{t("ws.closing_info", "Informational items")}</summary>
          <ul className="closing-list">
            {info.map((item) => (
              <li key={item.key} className={item.ok ? "closing-ok" : "closing-missing"}>
                <span className="closing-mark" aria-hidden>
                  {item.ok ? "✓" : "·"}
                </span>
                <div>
                  <strong>{item.label}</strong>
                  <p className="muted">{item.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
