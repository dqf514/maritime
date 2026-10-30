"use client";

// U2/U4 单据详情：laytime 计算书（可深链 + 打印/PDF + 对账）。

import { msgOf } from "@/lib/errors";
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { RecordAttribution } from "@/components/RecordAttribution";
import { Num } from "@/components/Num";
import { AttachmentsPanel } from "@/components/AttachmentsPanel";
import { RevisionsPanel } from "@/components/RevisionsPanel";
import { SkeletonCard } from "@/components/Skeleton";
import { StateView } from "@/components/StateView";
import { PrintDoc } from "@/components/PrintDoc";
import { LaytimeDemurragePanel } from "@/components/finance/LaytimeDemurragePanel";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { formatDateTimeShort } from "@/lib/datetime";

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
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState("");
  const [sectionErr, setSectionErr] = useState<{ mail?: string }>({});
  const [cmprJson, setCmprJson] = useState("");
  const [mailOpts, setMailOpts] = useState<{ message_id: string; subject: string; parsed: unknown }[]>([]);
  const [cmpr, setCmpr] = useState<CompareResult | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet(`/api/v1/laytimes/${id}/export`);
      setSt(data);
      setLoadErr("");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    refresh().catch((ex) => {
      if (ex?.status === 404) setNotFound(true);
      else setLoadErr(msgOf(ex));
    });
    // D12 对账直连：拉取已解析的 laytime 邮件供一键导入（失败不拖垮整页，但要可见）
    apiGet("/api/v1/email-intelligence/laytime-parsed")
      .then((r: { items: { message_id: string; subject: string; parsed: unknown }[] }) => setMailOpts(r.items || []))
      .catch((ex) => {
        setMailOpts([]);
        setSectionErr((prev) => ({ ...prev, mail: msgOf(ex) }));
      });
  }, [refresh]);

  /** 重新加载（错误态重试） */
  function reload() {
    setLoadErr("");
    setNotFound(false);
    refresh().catch((ex) => {
      if (ex?.status === 404) setNotFound(true);
      else setLoadErr(msgOf(ex));
    });
  }

  async function runCompare() {
    if (!st) return;
    setBusy(true);
    setErr("");
    try {
      const their = JSON.parse(cmprJson);
      setCmpr(await apiPost("/api/v1/laytimes/compare", { my: st, their }));
    } catch (ex) {
      const msg =
        ex instanceof SyntaxError
          ? t("page.finance.lt_compare_bad", "对手方 JSON 解析失败或对账请求出错")
          : msgOf(ex);
      setErr(msg);
      setCmpr(null);
    } finally {
      setBusy(false);
    }
  }

  const fmtTs = (v: unknown) => formatDateTimeShort(v as string | null);

  const eventCols = useMemo<ColumnDef<StatementEventRow>[]>(
    () => [
      { key: "start", title: t("common.start", "开始"), width: 130, value: (r) => r.start ?? "", render: (v) => fmtTs(v) },
      { key: "end", title: t("common.end", "结束"), width: 130, value: (r) => r.end ?? "", render: (v) => fmtTs(v) },
      {
        key: "kind",
        title: t("common.kind", "类型"),
        value: (r) => r.kind,
        render: (_v, r) =>
          `${r.kind}${r.caller_excluded ? ` (${t("page.finance.ev_excluded", "剔除")})` : ""}`,
      },
      {
        key: "gross_hours",
        title: t("page.finance.ev_gross", "挂钟(h)"),
        align: "right",
        value: (r) => r.gross_hours,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      {
        key: "term_excluded_hours",
        title: t("page.finance.ev_excl", "除外(h)"),
        align: "right",
        value: (r) => r.term_excluded_hours,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      {
        key: "counted_hours",
        title: t("page.finance.ev_counted", "计费(h)"),
        align: "right",
        value: (r) => r.counted_hours,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      {
        key: "cumulative_hours",
        title: t("page.finance.ev_cum", "累计(h)"),
        align: "right",
        value: (r) => r.cumulative_hours,
        render: (v) => <Num v={v as number} digits={2} />,
      },
    ],
    [t],
  );

  type DiffRow = { id: string; label: string; mine: unknown; theirs: unknown; delta: number | null };
  const diffRows: DiffRow[] = useMemo(() => {
    if (!cmpr || cmpr.match) return [];
    return [
      ...cmpr.field_diffs.map((d) => ({
        id: `f-${d.field}`,
        label: d.field,
        mine: d.mine,
        theirs: d.theirs,
        delta: d.delta,
      })),
      ...cmpr.event_diffs.map((d) => ({
        id: `e-${d.start}-${d.end}`,
        label: `${fmtTs(d.start)} ~ ${fmtTs(d.end)} (${d.issue})`,
        mine: d.mine,
        theirs: d.theirs,
        delta: d.delta,
      })),
    ];
  }, [cmpr]);

  const diffCols = useMemo<ColumnDef<DiffRow>[]>(
    () => [
      { key: "label", title: t("page.finance.lt_cmp_field", "口径/事件") },
      {
        key: "mine",
        title: t("page.finance.lt_cmp_mine", "我方"),
        value: (r) => r.mine ?? "",
        render: (v) => String(v ?? "—"),
      },
      {
        key: "theirs",
        title: t("page.finance.lt_cmp_theirs", "对方"),
        value: (r) => r.theirs ?? "",
        render: (v) => String(v ?? "—"),
      },
      {
        key: "delta",
        title: t("page.finance.lt_cmp_delta", "差额"),
        align: "right",
        value: (r) => r.delta ?? "",
        render: (v) => (v !== "" && v != null ? <Num v={v as number} digits={2} /> : "—"),
      },
    ],
    [t],
  );

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
    <AppShell>
      <PageHeader
        breadcrumb={[
          { label: t("nav.finance", "Finance"), href: "/finance?tab=laytime" },
          { label: st?.id ? `#${st.id.slice(0, 8)}` : `#${id.slice(0, 8)}` },
        ]}
        title={
          <>
            {t("page.finance.lt_statement", "Laytime 计算书")} {st ? <span className="badge badge-warn">{st.status}</span> : null}
          </>
        }
        subtitle={
          st ? (
            <>
              {`${st.format || "LAYTIME_STATEMENT_v1"}${st.terms ? ` · ${st.terms}` : ""}`} ·{" "}
              <RecordAttribution entityType="laytime" entityId={id} />
            </>
          ) : (
            "…"
          )
        }
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
      {loadErr ? (
        <p className="state-view-text state-view-error">
          {t("page.finance.load_failed", "数据加载失败：{msg}", { msg: loadErr })}
        </p>
      ) : null}
      {sectionErr.mail ? (
        <p className="state-view-text state-view-error">
          {t("page.finance.laytime_mail_failed", "已解析的滞期费邮件加载失败：{msg}", { msg: sectionErr.mail })}
        </p>
      ) : null}

      {!st ? (
        // P1-5：loading / error / content 三态互斥 —— 错误不被骨架屏吞掉
        <StateView
          loading={loading}
          error={loadErr || undefined}
          empty={!loading && !loadErr}
          emptyText={t("common.empty", "No records")}
          onRetry={reload}
        >
          <SkeletonCard />
        </StateView>
      ) : (
        <PrintDoc
          title={t("page.finance.lt_statement", "LAYTIME STATEMENT")}
          no={st.id?.slice(0, 8)}
          meta={st.terms || undefined}
          entityType="laytime_statement"
          entityId={st.id || id}
        >
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
                <strong>{st.result_type ? t(`status.${st.result_type}`, st.result_type.replace(/_/g, " ")) : "—"}</strong>
              </div>
            </div>
          </div>

          {st.events?.length ? (
            <div className="panel">
              <h3 style={{ marginTop: 0 }}>{t("page.finance.lt_events", "事件明细")}</h3>
              <DataGrid<StatementEventRow>
                columns={eventCols}
                data={st.events}
                rowKey={(r, i) => `${r.start ?? ""}-${r.end ?? ""}-${i}`}
                storageKey="laytime_events_grid"
                showFooter={false}
                emptyText={t("common.empty", "No records")}
              />
            </div>
          ) : null}

          <LaytimeDemurragePanel laytimeId={st.id || id} />

          <div className="panel no-print">
            <h3 style={{ marginTop: 0 }}>{t("page.finance.lt_compare", "对账（粘贴对手方计算书 JSON）")}</h3>
            <textarea
              style={{ width: "100%", minHeight: 72, fontFamily: "monospace", fontSize: 12 }}
              value={cmprJson}
              onChange={(e) => setCmprJson(e.target.value)}
              aria-label={t("page.finance.lt_compare_json", "Counterparty calculation JSON")}
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
              <div style={{ marginTop: "0.5rem" }}>
                <DataGrid<DiffRow>
                  columns={diffCols}
                  data={diffRows}
                  rowKey={(r) => r.id}
                  storageKey="laytime_compare_grid"
                  showFooter={false}
                  emptyText={t("common.empty", "No records")}
                />
              </div>
            ) : null}
          </div>
        </PrintDoc>
      )}

      {id ? <AttachmentsPanel entityType="laytime" entityId={id} /> : null}
      {id ? <RevisionsPanel entityType="laytime" entityId={id} /> : null}
    </AppShell>
  );
}
