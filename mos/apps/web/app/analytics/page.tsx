"use client";

import { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { StateView } from "@/components/StateView";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function AnalyticsPage() {
  const { t } = useI18n();
  const [tce, setTce] = useState<Array<{ title: string; tce: number | null }>>([]);
  const [pnl, setPnl] = useState<Array<{ voyage_id: string; voyage_no?: string; revenue: number; actual_pnl?: number; variance_pnl?: number }>>([]);
  const [aging, setAging] = useState<Array<{ invoice_no: string; open_amount: number }>>([]);
  const [warn, setWarn] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setWarn("");
    const [tceR, pnlR, agingR] = await Promise.allSettled([
      apiGet("/api/v1/analytics/reports/tce"),
      apiGet("/api/v1/analytics/reports/voyage-pnl"),
      apiGet("/api/v1/finance/aging"),
    ]);
    const notes: string[] = [];
    if (tceR.status === "fulfilled") setTce(tceR.value);
    else {
      setTce([]);
      notes.push("TCE");
    }
    if (pnlR.status === "fulfilled") setPnl(pnlR.value);
    else {
      setPnl([]);
      notes.push("P&L");
    }
    if (agingR.status === "fulfilled") setAging(agingR.value);
    else {
      setAging([]);
      notes.push("Aging");
    }
    if (notes.length) setWarn(t("page.analytics.partial", "Some reports unavailable: {list}", { list: notes.join(", ") }));
    setLoading(false);
  }, [t]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("page.analytics.title", "Analytics")}</h1>
      <p style={{ color: "var(--muted)" }}>{t("page.analytics.sub", "TCE, voyage P&L and AR aging.")}</p>
      {warn && (tce.length || pnl.length || aging.length) ? <p className="muted">{warn}</p> : null}
      <StateView
        loading={loading}
        error={!tce.length && !pnl.length && !aging.length && warn ? warn : ""}
        empty={!tce.length && !pnl.length && !aging.length}
        emptyText={t("common.no_data", "No data")}
        onRetry={load}
      >
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
      </StateView>
    </AppShell>
  );
}

