"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageGuide } from "@/components/PageGuide";
import { StateView } from "@/components/StateView";
import { apiGet, type VoyageOverview } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

function fmtDate(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fmtMoney(n: number | null | undefined, currency: string, locale: string) {
  if (n === null || n === undefined) return "—";
  const text = n.toLocaleString(locale.startsWith("zh") ? "zh-CN" : "en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
  return currency ? `${currency} ${text}` : text;
}

function varianceClass(n: number | null | undefined) {
  if (n === null || n === undefined || n === 0) return "";
  return n < 0 ? "neg" : "pos";
}

export default function VoyageOverviewPage() {
  const { t, locale } = useI18n();
  const params = useParams();
  const id = String(params.id || "");
  const [data, setData] = useState<VoyageOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError("");
    try {
      setData(await apiGet(`/api/v1/voyages/${id}/overview`));
    } catch (e: any) {
      setError(e?.message || t("common.failed", "加载失败"));
    } finally {
      setLoading(false);
    }
  }, [id, t]);

  useEffect(() => {
    load();
  }, [load]);

  const voyage = data?.voyage;
  const pnl = data?.pnl;
  const currency = pnl?.currency || "USD";
  const title = voyage?.voyage_no || voyage?.vessel_name || id.slice(0, 8);

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <p style={{ margin: "0 0 0.2rem" }}>
            <Link href="/operations/voyages" className="muted" style={{ fontSize: "0.85rem" }}>
              ← {t("page.voyage.back", "返回航次列表")}
            </Link>
          </p>
          <h1 style={{ margin: 0, display: "flex", alignItems: "center", gap: "0.6rem", flexWrap: "wrap" }}>
            {t("page.voyage.title", "航次 360")}
            <span>{title}</span>
            {voyage ? <span className="pill">{voyage.status}</span> : null}
          </h1>
          <p className="page-sub">
            {voyage?.vessel_name
              ? t("page.voyage.sub_vessel", "船舶 {vessel}", { vessel: voyage.vessel_name })
              : t("page.voyage.sub", "航次全生命周期与盈亏归因")}
            {data?.charter?.charter_no ? ` · ${data.charter.charter_no}` : ""}
            {data?.charter?.counterparty_name ? ` · ${data.charter.counterparty_name}` : ""}
          </p>
        </div>
        <PageGuide pageKey="voyage_detail" />
      </div>

      <StateView loading={loading && !data} error={error} empty={false} onRetry={load}>
        {data?.lifecycle?.length ? (
          <div className="panel lc-panel">
            <ol className="lc-stepper">
              {data.lifecycle.map((step, i) => {
                const label = locale.startsWith("zh") ? step.label.zh || step.label.en : step.label.en;
                const inner = (
                  <>
                    <span className="lc-dot" aria-hidden>
                      {step.state === "done" ? (
                        <svg viewBox="0 0 12 12" width="11" height="11">
                          <path fill="currentColor" d="M4.4 9 1.6 6.2l1-1 1.8 1.8L9.3 2.1l1 1z" />
                        </svg>
                      ) : (
                        i + 1
                      )}
                    </span>
                    <span className="lc-text">
                      <strong>{label}</strong>
                      {step.detail ? <small>{step.detail}</small> : null}
                    </span>
                  </>
                );
                return (
                  <li key={step.key} className={`lc-step ${step.state}`}>
                    {i > 0 ? <span className={`lc-conn ${step.state === "todo" ? "todo" : "done"}`} aria-hidden /> : null}
                    {step.href ? (
                      <Link href={step.href} className="lc-step-link">
                        {inner}
                      </Link>
                    ) : (
                      <span className="lc-step-link">{inner}</span>
                    )}
                  </li>
                );
              })}
            </ol>
          </div>
        ) : null}

        {pnl ? (
          <div className="panel">
            <h3 style={{ marginTop: 0 }}>{t("page.voyage.pnl_title", "P&L 归因")}</h3>
            <div className="desk-results pnl-summary">
              <div className="kv-box">
                <span>{t("page.voyage.pnl_estimated", "预估盈亏")}</span>
                <strong>{fmtMoney(pnl.estimated_pnl, currency, locale)}</strong>
              </div>
              <div className="kv-box">
                <span>{t("page.voyage.pnl_actual", "实际盈亏")}</span>
                <strong>{fmtMoney(pnl.actual_pnl, currency, locale)}</strong>
              </div>
              <div className="kv-box">
                <span>{t("page.voyage.pnl_variance", "差异")}</span>
                <strong className={varianceClass(pnl.variance_pnl)}>{fmtMoney(pnl.variance_pnl, currency, locale)}</strong>
              </div>
            </div>
            <table className="table" style={{ marginTop: "0.75rem" }}>
              <thead>
                <tr>
                  <th>{t("page.voyage.pnl_category", "费用类别")}</th>
                  <th className="num">{t("page.voyage.pnl_estimated_col", "预估")}</th>
                  <th className="num">{t("page.voyage.pnl_actual_col", "实际")}</th>
                  <th className="num">{t("page.voyage.pnl_variance_col", "差异")}</th>
                </tr>
              </thead>
              <tbody>
                {(pnl.lines || []).map((line) => (
                  <tr key={line.key}>
                    <td>{t(`page.voyage.pnl.${line.key}`, line.key)}</td>
                    <td className="num">{fmtMoney(line.estimated, currency, locale)}</td>
                    <td className="num">{fmtMoney(line.actual, currency, locale)}</td>
                    <td className={`num ${varianceClass(line.variance)}`}>{fmtMoney(line.variance, currency, locale)}</td>
                  </tr>
                ))}
                {!pnl.lines?.length ? (
                  <tr>
                    <td colSpan={4} className="muted">
                      {t("common.no_data", "No data")}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        ) : null}

        <div className="voy360-grid">
          <div className="panel" style={{ marginTop: 0 }}>
            <div className="desk-card-head">
              <h3 style={{ margin: 0 }}>{t("page.voyage.port_calls", "港口动态")}</h3>
              <span className="muted" style={{ fontSize: "0.8rem" }}>
                {t("page.voyage.noon_count", "正午报 {n} 份", { n: data?.noon_reports_count ?? 0 })}
              </span>
            </div>
            <table className="table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>{t("page.voyage.port", "港口")}</th>
                  <th>ETA</th>
                  <th>ATA</th>
                  <th>ETD</th>
                  <th>ATD</th>
                </tr>
              </thead>
              <tbody>
                {(data?.port_calls || []).map((pc, i) => {
                  const eta = pc.eta ? new Date(pc.eta).getTime() : null;
                  const ata = pc.ata ? new Date(pc.ata).getTime() : null;
                  const delayed = eta !== null && ata !== null && ata > eta;
                  return (
                    <tr key={pc.id || i}>
                      <td>{pc.seq ?? i + 1}</td>
                      <td>{pc.port_name || pc.port_id?.slice(0, 8) || "—"}</td>
                      <td>{fmtDate(pc.eta)}</td>
                      <td className={delayed ? "neg" : ""}>
                        {fmtDate(pc.ata)}
                        {delayed ? (
                          <span className="badge badge-fail" style={{ marginLeft: "0.35rem" }}>
                            {t("page.voyage.delayed", "延误")}
                          </span>
                        ) : null}
                      </td>
                      <td>{fmtDate(pc.etd)}</td>
                      <td>{fmtDate(pc.atd)}</td>
                    </tr>
                  );
                })}
                {!data?.port_calls?.length ? (
                  <tr>
                    <td colSpan={6} className="muted">
                      {t("common.empty", "No records")}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>

          <div className="panel" style={{ marginTop: 0 }}>
            <div className="desk-card-head">
              <h3 style={{ margin: 0 }}>{t("page.voyage.finance", "财务")}</h3>
              <Link href="/finance" className="btn btn-ghost btn-sm">
                {t("page.voyage.goto_finance", "前往财务")}
              </Link>
            </div>

            <h4 className="voy360-fin-title">{t("page.voyage.laytime", "滞期/速遣")}</h4>
            <table className="table">
              <tbody>
                {(data?.laytime || []).map((lt) => (
                  <tr key={lt.id}>
                    <td>{lt.result_type || "—"}</td>
                    <td>{lt.status}</td>
                    <td className="num">{fmtMoney(lt.amount, lt.currency || currency, locale)}</td>
                  </tr>
                ))}
                {!data?.laytime?.length ? (
                  <tr>
                    <td className="muted">{t("common.no_data", "No data")}</td>
                  </tr>
                ) : null}
              </tbody>
            </table>

            <h4 className="voy360-fin-title">{t("page.voyage.claims", "索赔")}</h4>
            <table className="table">
              <tbody>
                {(data?.claims || []).map((c) => (
                  <tr key={c.id}>
                    <td>{c.claim_no || c.id.slice(0, 8)}</td>
                    <td>{c.status || "—"}</td>
                    <td className="num">{fmtMoney(c.amount, c.currency || currency, locale)}</td>
                  </tr>
                ))}
                {!data?.claims?.length ? (
                  <tr>
                    <td className="muted">{t("common.no_data", "No data")}</td>
                  </tr>
                ) : null}
              </tbody>
            </table>

            <h4 className="voy360-fin-title">{t("page.voyage.invoices", "发票")}</h4>
            <table className="table">
              <tbody>
                {(data?.invoices || []).map((inv) => (
                  <tr key={inv.id}>
                    <td>{inv.invoice_no || inv.id.slice(0, 8)}</td>
                    <td>{inv.status || "—"}</td>
                    <td className="num">{fmtMoney(inv.amount, inv.currency || currency, locale)}</td>
                  </tr>
                ))}
                {!data?.invoices?.length ? (
                  <tr>
                    <td className="muted">{t("common.no_data", "No data")}</td>
                  </tr>
                ) : null}
              </tbody>
            </table>

            <h4 className="voy360-fin-title">{t("page.voyage.off_hire", "停租")}</h4>
            <table className="table">
              <tbody>
                {(data?.off_hire || []).map((oh) => (
                  <tr key={oh.id}>
                    <td>{fmtDate(oh.start_at)}</td>
                    <td>{oh.end_at ? fmtDate(oh.end_at) : t("page.voyage.oh_open", "进行中")}</td>
                    <td className="num">
                      {oh.deducted_days != null
                        ? t("page.voyage.oh_days", "{n} 天", { n: oh.deducted_days })
                        : oh.reason || "—"}
                    </td>
                  </tr>
                ))}
                {!data?.off_hire?.length ? (
                  <tr>
                    <td className="muted">{t("common.no_data", "No data")}</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </div>
      </StateView>
    </AppShell>
  );
}
