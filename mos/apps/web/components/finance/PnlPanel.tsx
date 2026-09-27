"use client";

// 3.6 前端拆分试点：Dynamic P&L 面板（自取数，finance 页标签挂载）。

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const PNL_LINE_KEYS = ["revenue", "hire", "demurrage", "port_costs", "canal", "bunker", "commission", "emissions", "other"] as const;

type PnlRow = {
  voyage_id: string;
  voyage_no: string;
  status: string;
  estimated_revenue: number;
  estimated_cost: number;
  estimated_pnl: number;
  actual_revenue: number;
  actual_cost: number;
  actual_pnl: number;
  variance_pnl: number;
  estimated_tce?: number | null;
  lines?: Record<string, number>;
  lines_accrual?: Record<string, number>;
  accrual_net?: number;
};

function fmt(n: number | undefined | null) {
  if (n === undefined || n === null) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function PnlPanel() {
  const { t } = useI18n();
  const [pnl, setPnl] = useState<PnlRow[]>([]);
  const [basis, setBasis] = useState<"actual" | "accrual">("actual");
  const [selected, setSelected] = useState<string | null>(null);

  const load = useCallback(async (b: "actual" | "accrual") => {
    try {
      setPnl(await apiGet(`/api/v1/analytics/reports/voyage-pnl?basis=${b}`));
    } catch {
      setPnl([]);
    }
  }, []);

  useEffect(() => {
    load("actual").catch(() => undefined);
  }, [load]);

  return (
    <div className="panel">
      <div className="desk-toolbar" style={{ marginBottom: "0.75rem" }}>
        <h3 style={{ margin: 0 }}>{t("page.finance.pnl", "Dynamic P&L")}</h3>
        <Link href="/finance/pnl" className="btn btn-sm btn-ghost">4-Column View</Link>
        <button
          className={`btn btn-sm${basis === "actual" ? " btn-primary" : ""}`}
          type="button"
          onClick={() => {
            setBasis("actual");
            load("actual");
          }}
        >
          actual
        </button>
        <button
          className={`btn btn-sm${basis === "accrual" ? " btn-primary" : ""}`}
          type="button"
          onClick={() => {
            setBasis("accrual");
            load("accrual");
          }}
        >
          accrual
        </button>
        <button className="btn btn-sm btn-ghost" type="button" onClick={() => load(basis)}>
          {t("common.refresh", "刷新")}
        </button>
      </div>
      <table className="table">
        <thead>
          <tr>
            <th>{t("page.voyages.no", "No")}</th>
            <th>{t("common.status", "Status")}</th>
            <th>{t("page.finance.est_rev", "Est. revenue")}</th>
            <th>{t("page.finance.est_cost", "Est. cost")}</th>
            <th>{t("page.finance.est_pnl", "Est. P&L")}</th>
            <th>{t("page.finance.act_rev", "Actual revenue")}</th>
            <th>{t("page.finance.act_cost", "Actual cost")}</th>
            <th>{t("page.finance.act_pnl", "Actual P&L")}</th>
            {basis === "accrual" ? <th>{t("page.finance.accrual_net", "Accrual net")}</th> : null}
            <th>{t("page.finance.variance", "Variance")}</th>
            <th>TCE</th>
          </tr>
        </thead>
        <tbody>
          {pnl.map((r) => (
            <tr
              key={r.voyage_id}
              className={r.voyage_id === selected ? "selected" : ""}
              style={{ cursor: "pointer" }}
              onClick={() => setSelected(r.voyage_id === selected ? null : r.voyage_id)}
            >
              <td><Link href={`/finance/pnl/${r.voyage_id}`}>{r.voyage_no}</Link></td>
              <td>{r.status}</td>
              <td>{fmt(r.estimated_revenue)}</td>
              <td>{fmt(r.estimated_cost)}</td>
              <td>{fmt(r.estimated_pnl)}</td>
              <td>{fmt(r.actual_revenue)}</td>
              <td>{fmt(r.actual_cost)}</td>
              <td>{fmt(r.actual_pnl)}</td>
              {basis === "accrual" ? <td>{fmt(r.accrual_net ?? null)}</td> : null}
              <td>{fmt(r.variance_pnl)}</td>
              <td>{fmt(r.estimated_tce ?? null)}</td>
            </tr>
          ))}
          {!pnl.length ? (
            <tr>
              <td colSpan={basis === "accrual" ? 11 : 10} className="muted">
                {t("common.empty", "No records")}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
      {(() => {
        const sel = pnl.find((r) => r.voyage_id === selected);
        if (!sel || !sel.lines) return null;
        return (
          <div className="desk-section">
            <h3>
              {t("page.finance.pnl_lines", "行项分列")} · {sel.voyage_no}
            </h3>
            <table className="table">
              <thead>
                <tr>
                  <th>{t("page.finance.line", "Line")}</th>
                  <th>{basis === "accrual" ? t("page.finance.lines_merged", "Merged") : t("page.finance.lines_actual", "Actual")}</th>
                  {basis === "accrual" ? <th>{t("page.finance.lines_accrual", "Accrual")}</th> : null}
                </tr>
              </thead>
              <tbody>
                {PNL_LINE_KEYS.map((k) => (
                  <tr key={k}>
                    <td>{k}</td>
                    <td>{fmt(sel.lines?.[k] ?? 0)}</td>
                    {basis === "accrual" ? <td>{fmt(sel.lines_accrual?.[k] ?? 0)}</td> : null}
                  </tr>
                ))}
                {basis === "accrual" ? (
                  <tr>
                    <td>
                      <strong>{t("page.finance.accrual_net", "Accrual net")}</strong>
                    </td>
                    <td>
                      <strong>{fmt(sel.accrual_net ?? null)}</strong>
                    </td>
                    <td></td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        );
      })()}
    </div>
  );
}
