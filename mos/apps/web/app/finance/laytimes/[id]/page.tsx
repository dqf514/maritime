"use client";

// U2/U4 单据详情：laytime 计算书（可深链 + 打印/PDF + 对账）。

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { SkeletonCard } from "@/components/Skeleton";
import { PrintDoc } from "@/components/PrintDoc";
import { LaytimeDemurragePanel } from "@/components/finance/LaytimeDemurragePanel";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type StatementEventRow = {
  start: string;
  end: string;
  kind: string;
  caller_excluded: boolean;
  gross_hours: number;
  term_excluded_hours: number;
  counted_hours: number;
  cumulative_hours: number;
  note?: string;
};
type LaytimeStatement = {
  id: string;
  status: string;
  format?: string;
  terms?: string;
  allowed_hours?: number;
  used_hours?: number;
  excluded_hours?: number;
  balance_hours?: number;
  result_type?: string;
  amount?: number;
  currency?: string;
  events?: StatementEventRow[];
};

type CompareResult = {
  match: boolean;
  field_diffs: { field: string; mine: unknown; theirs: unknown; delta: number | null }[];
  event_diffs: { start: string; end: string; mine: unknown; theirs: unknown; delta: number | null; issue: string }[];
};

function fmt(n: number | undefined | null) {
  if (n === undefined || n === null) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export default function LaytimeDetailPage() {
  const { t } = useI18n();
  const params = useParams<{ id: string }>();
  const id = params.id;

  const [st, setSt] = useState<LaytimeStatement | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [err, setErr] = useState("");
  const [cmprJson, setCmprJson] = useState("");
  const [mailOpts, setMailOpts] = useState<{ message_id: string; subject: string; parsed: unknown }[]>([]);
  const [cmpr, setCmpr] = useState<CompareResult | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const data = await apiGet(`/api/v1/laytimes/${id}/export`);
    setSt(data);
  }, [id]);

  useEffect(() => {
    refresh().catch((ex) => {
      if (ex?.status === 404) setNotFound(true);
      else setErr(String(ex));
    });
    // D12 对账直连：拉取已解析的 laytime 邮件供一键导入
    apiGet("/api/v1/email-intelligence/laytime-parsed")
      .then((r: { items: { message_id: string; subject: string; parsed: unknown }[] }) => setMailOpts(r.items || []))
      .catch(() => setMailOpts([]));
  }, [refresh]);

  async function runCompare() {
    if (!st) return;
    setBusy(true);
    setErr("");
    try {
      const their = JSON.parse(cmprJson);
      setCmpr(await apiPost("/api/v1/laytimes/compare", { my: st, their }));
    } catch {
      setErr(t("page.finance.lt_compare_bad", "对手方 JSON 解析失败或对账请求出错"));
      setCmpr(null);
    } finally {
      setBusy(false);
    }
  }

  if (notFound) {
    return (
      <AppShell>
        <div className="panel">
          <p>{t("common.not_found", "Not found")}</p>
          <Link href="/finance?tab=laytime" className="btn">
            {t("common.back", "返回")}
          </Link>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell
      breadcrumbs={[
        { label: t("page.finance.title", "Finance / laytime / P&L"), href: "/finance" },
        { label: t("page.finance.lt_statement", "Laytime 计算书") },
      ]}
    >
      <PageHeader
        title={
          <>
            {t("page.finance.lt_statement", "Laytime 计算书")} {st ? <span className="badge badge-warn">{st.status}</span> : null}
          </>
        }
        subtitle={st ? `${st.format || "LAYTIME_STATEMENT_v1"}${st.terms ? ` · ${st.terms}` : ""}` : "…"}
        actions={
          <>
            <Link href="/finance?tab=laytime" className="btn btn-ghost">
              {t("common.back", "返回")}
            </Link>
            <button className="btn btn-sm" type="button" onClick={() => window.print()}>
              {t("common.print", "打印 / PDF")}
            </button>
          </>
        }
      />

      {err ? <p className="err-text">{err}</p> : null}

      {!st ? (
        <SkeletonCard />
      ) : (
        <PrintDoc title={t("page.finance.lt_statement", "LAYTIME STATEMENT")} no={st.id?.slice(0, 8)} meta={st.terms || undefined}>
          <div className="panel">
            <div className="desk-results">
              <div className="kv-box">
                <span>{t("page.finance.allowed_hours", "Allowed hours")}</span>
                <strong>{fmt(st.allowed_hours)}</strong>
              </div>
              <div className="kv-box">
                <span>{t("page.finance.used_hours", "Used hours")}</span>
                <strong>{fmt(st.used_hours)}</strong>
              </div>
              <div className="kv-box">
                <span>{t("page.finance.excluded_hours", "Excluded hours")}</span>
                <strong>{fmt(st.excluded_hours)}</strong>
              </div>
              <div className="kv-box">
                <span>{t("page.finance.balance_hours", "Balance hours")}</span>
                <strong>{fmt(st.balance_hours)}</strong>
              </div>
              <div className="kv-box">
                <span>{t("common.amount", "Amount")}</span>
                <strong>
                  {fmt(st.amount)} {st.currency || "USD"}
                </strong>
              </div>
              <div className="kv-box">
                <span>{t("common.result", "Result")}</span>
                <strong>{st.result_type || "—"}</strong>
              </div>
            </div>
          </div>

          {st.events?.length ? (
            <div className="panel">
              <h3 style={{ marginTop: 0 }}>{t("page.finance.lt_events", "事件明细")}</h3>
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("common.start", "开始")}</th>
                    <th>{t("common.end", "结束")}</th>
                    <th>{t("common.kind", "类型")}</th>
                    <th>{t("page.finance.ev_gross", "挂钟(h)")}</th>
                    <th>{t("page.finance.ev_excl", "除外(h)")}</th>
                    <th>{t("page.finance.ev_counted", "计费(h)")}</th>
                    <th>{t("page.finance.ev_cum", "累计(h)")}</th>
                  </tr>
                </thead>
                <tbody>
                  {st.events.map((ev, i) => (
                    <tr key={i}>
                      <td>{ev.start?.replace("T", " ").slice(0, 16)}</td>
                      <td>{ev.end?.replace("T", " ").slice(0, 16)}</td>
                      <td>
                        {ev.kind}
                        {ev.caller_excluded ? ` (${t("page.finance.ev_excluded", "剔除")})` : ""}
                      </td>
                      <td>{fmt(ev.gross_hours)}</td>
                      <td>{fmt(ev.term_excluded_hours)}</td>
                      <td>{fmt(ev.counted_hours)}</td>
                      <td>{fmt(ev.cumulative_hours)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          <LaytimeDemurragePanel laytimeId={st.id || id} />

          <div className="panel no-print">
            <h3 style={{ marginTop: 0 }}>{t("page.finance.lt_compare", "对账（粘贴对手方计算书 JSON）")}</h3>
            <textarea
              style={{ width: "100%", minHeight: 72, fontFamily: "monospace", fontSize: 12 }}
              value={cmprJson}
              onChange={(e) => setCmprJson(e.target.value)}
              placeholder='{"allowed_hours": 72, "used_hours": 84, "amount": 12000, "events": [...]}'
            />
            <div className="desk-toolbar" style={{ margin: "0.5rem 0 0" }}>
              <button className="btn btn-sm" type="button" disabled={busy} onClick={runCompare}>
                {t("page.finance.lt_compare_run", "开始对账")}
              </button>
              {cmpr ? (
                <span className={cmpr.match ? "ok-text" : "err-text"}>
                  {cmpr.match ? t("page.finance.lt_compare_match", "双方一致") : t("page.finance.lt_compare_diff", "存在差异")}
                </span>
              ) : null}
            </div>
            {cmpr && !cmpr.match ? (
              <table className="table" style={{ marginTop: "0.5rem" }}>
                <thead>
                  <tr>
                    <th>{t("page.finance.lt_cmp_field", "口径/事件")}</th>
                    <th>{t("page.finance.lt_cmp_mine", "我方")}</th>
                    <th>{t("page.finance.lt_cmp_theirs", "对方")}</th>
                    <th>{t("page.finance.lt_cmp_delta", "差额")}</th>
                  </tr>
                </thead>
                <tbody>
                  {cmpr.field_diffs.map((d) => (
                    <tr key={`f-${d.field}`}>
                      <td>{d.field}</td>
                      <td>{String(d.mine ?? "—")}</td>
                      <td>{String(d.theirs ?? "—")}</td>
                      <td>{d.delta != null ? fmt(d.delta) : "—"}</td>
                    </tr>
                  ))}
                  {cmpr.event_diffs.map((d) => (
                    <tr key={`e-${d.start}-${d.end}`}>
                      <td>
                        {d.start.replace("T", " ").slice(0, 16)} ~ {d.end.replace("T", " ").slice(0, 16)} ({d.issue})
                      </td>
                      <td>{String(d.mine ?? "—")}</td>
                      <td>{String(d.theirs ?? "—")}</td>
                      <td>{d.delta != null ? fmt(d.delta) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
          </div>
        </PrintDoc>
      )}
    </AppShell>
  );
}
