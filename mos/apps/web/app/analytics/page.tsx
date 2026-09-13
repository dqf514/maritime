"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function AnalyticsPage() {
  const { t } = useI18n();
  const [tce, setTce] = useState<Array<{ title: string; tce: number | null }>>([]);
  const [pnl, setPnl] = useState<Array<{ voyage_id: string; voyage_no?: string; revenue: number; actual_pnl?: number; variance_pnl?: number }>>([]);
  const [aging, setAging] = useState<Array<{ invoice_no: string; open_amount: number }>>([]);
  const [warn, setWarn] = useState("");

  useEffect(() => {
    const notes: string[] = [];
    apiGet("/api/v1/analytics/reports/tce")
      .then(setTce)
      .catch(() => {
        setTce([]);
        notes.push("TCE");
      });
    apiGet("/api/v1/analytics/reports/voyage-pnl")
      .then(setPnl)
      .catch(() => {
        setPnl([]);
        notes.push("P&L");
      });
    apiGet("/api/v1/finance/aging")
      .then(setAging)
      .catch(() => {
        setAging([]);
        notes.push("Aging");
      });
    const timer = setTimeout(() => {
      if (notes.length) setWarn(t("page.analytics.partial", "Some reports unavailable: {list}", { list: notes.join(", ") }));
    }, 800);
    return () => clearTimeout(timer);
  }, [t]);

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("page.analytics.title", "Analytics")}</h1>
      <p style={{ color: "var(--muted)" }}>{t("page.analytics.sub", "TCE, voyage P&L and AR aging.")}</p>
      {warn ? <p className="muted">{warn}</p> : null}
      <div className="card-grid">
        <div className="card">
          <h3>TCE</h3>
          <ul>
            {tce.map((r, i) => (
              <li key={i}>
                {r.title}: {r.tce ?? "—"}
              </li>
            ))}
            {!tce.length ? <li className="muted">{t("common.no_data", "No data")}</li> : null}
          </ul>
        </div>
        <div className="card">
          <h3>{t("page.analytics.revenue", "Voyage revenue")}</h3>
          <ul>
            {pnl.map((r, i) => (
              <li key={i}>
                {r.voyage_no || r.voyage_id.slice(0, 8)}: {r.revenue}
                {r.actual_pnl != null ? ` · P&L ${r.actual_pnl}` : ""}
                {r.variance_pnl != null ? ` · Δ ${r.variance_pnl}` : ""}
              </li>
            ))}
            {!pnl.length ? <li className="muted">{t("common.no_data", "No data")}</li> : null}
          </ul>
        </div>
        <div className="card">
          <h3>{t("page.analytics.aging", "AR aging")}</h3>
          <ul>
            {aging.map((r, i) => (
              <li key={i}>
                {r.invoice_no}: {r.open_amount}
              </li>
            ))}
            {!aging.length ? <li className="muted">{t("common.no_data", "No data")}</li> : null}
          </ul>
        </div>
      </div>
    </AppShell>
  );
}
