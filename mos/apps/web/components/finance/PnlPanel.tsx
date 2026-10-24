"use client";

// 3.6 前端拆分试点：Dynamic P&L 面板（自取数，finance 页标签挂载）。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { Num } from "@/components/Num";
import { StateView } from "@/components/StateView";
import { apiGet } from "@/lib/api";
import { msgOf, handled } from "@/lib/errors";
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
  // P1-4：取数失败 → 三态错误（不能静默变成「No records」）
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  // P1-32：请求序号 —— actual/accrual 两个 in-flight 请求可能乱序返回，
  // 过期响应必须丢弃，否则会用旧数据覆盖新数据。
  const reqSeq = useRef(0);

  const load = useCallback(async (b: "actual" | "accrual") => {
    const seq = ++reqSeq.current;
    setLoading(true);
    setErr(null);
    try {
      const data = await apiGet(`/api/v1/analytics/reports/voyage-pnl?basis=${b}`);
      if (seq !== reqSeq.current) return; // 过期响应，丢弃
      setPnl(Array.isArray(data) ? data : []);
    } catch (ex) {
      if (seq !== reqSeq.current) return;
      setPnl([]);
      setErr(msgOf(ex));
    } finally {
      if (seq === reqSeq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    load("actual").catch(handled);
  }, [load]);

  const listCols = useMemo<ColumnDef<PnlRow>[]>(
    () => [
      {
        key: "voyage_no",
        title: t("page.voyages.no", "No"),
        width: 110,
        sticky: true,
        value: (r) => r.voyage_no,
        render: (v, r) => <Link href={`/finance/pnl/${r.voyage_id}`}>{String(v)}</Link>,
      },
      { key: "status", title: t("common.status", "Status"), width: 100 },
      {
        key: "estimated_revenue",
        title: t("page.finance.est_rev", "Est. revenue"),
        align: "right",
        value: (r) => r.estimated_revenue,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      {
        key: "estimated_cost",
        title: t("page.finance.est_cost", "Est. cost"),
        align: "right",
        value: (r) => r.estimated_cost,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      {
        key: "estimated_pnl",
        title: t("page.finance.est_pnl", "Est. P&L"),
        align: "right",
        value: (r) => r.estimated_pnl,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      {
        key: "actual_revenue",
        title: t("page.finance.act_rev", "Actual revenue"),
        align: "right",
        value: (r) => r.actual_revenue,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      {
        key: "actual_cost",
        title: t("page.finance.act_cost", "Actual cost"),
        align: "right",
        value: (r) => r.actual_cost,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      {
        key: "actual_pnl",
        title: t("page.finance.act_pnl", "Actual P&L"),
        align: "right",
        value: (r) => r.actual_pnl,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      ...(basis === "accrual"
        ? [
            {
              key: "accrual_net",
              title: t("page.finance.accrual_net", "Accrual net"),
              align: "right" as const,
              value: (r: PnlRow) => r.accrual_net ?? null,
              render: (v: unknown) => <Num v={v as number | null} digits={2} />,
            },
          ]
        : []),
      {
        key: "variance_pnl",
        title: t("page.finance.variance", "Variance"),
        align: "right",
        value: (r) => r.variance_pnl,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      {
        key: "estimated_tce",
        title: "TCE",
        align: "right",
        value: (r) => r.estimated_tce ?? null,
        render: (v) => fmt(v as number | null),
      },
    ],
    [t, basis],
  );

  const sel = pnl.find((r) => r.voyage_id === selected);

  type LineRow = { id: string; label: string; merged: number; accrual: number | null };

  const lineRows = useMemo<LineRow[]>(() => {
    if (!sel?.lines) return [];
    const rows: LineRow[] = PNL_LINE_KEYS.map((k) => ({
      id: k,
      label: k,
      merged: sel.lines?.[k] ?? 0,
      accrual: sel.lines_accrual?.[k] ?? 0,
    }));
    if (basis === "accrual") {
      rows.push({
        id: "accrual_net",
        label: t("page.finance.accrual_net", "Accrual net"),
        merged: sel.accrual_net ?? 0,
        accrual: null,
      });
    }
    return rows;
  }, [sel, basis, t]);

  const lineCols = useMemo<ColumnDef<LineRow>[]>(
    () => [
      {
        key: "label",
        title: t("page.finance.line", "Line"),
        value: (r) => r.label,
        render: (v, r) => (r.id === "accrual_net" ? <strong>{String(v)}</strong> : String(v)),
      },
      {
        key: "merged",
        title: basis === "accrual" ? t("page.finance.lines_merged", "Merged") : t("page.finance.lines_actual", "Actual"),
        align: "right",
        value: (r) => r.merged,
        render: (v, r) => {
          const text = <Num v={v as number} digits={2} />;
          return r.id === "accrual_net" ? <strong>{text}</strong> : text;
        },
      },
      ...(basis === "accrual"
        ? [
            {
              key: "accrual",
              title: t("page.finance.lines_accrual", "Accrual"),
              align: "right" as const,
              value: (r: LineRow) => r.accrual,
              render: (v: unknown) => (v == null ? "" : <Num v={v as number} digits={2} />),
            },
          ]
        : []),
    ],
    [t, basis],
  );

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
      <StateView
        loading={loading}
        error={err ?? undefined}
        empty={!pnl.length}
        emptyText={t("common.empty", "No records")}
        onRetry={() => load(basis)}
      >
        <DataGrid<PnlRow>
          columns={listCols}
          data={pnl}
          rowKey={(r) => r.voyage_id}
          onRowClick={(r) => setSelected(r.voyage_id === selected ? null : r.voyage_id)}
          storageKey="finance_pnl_panel_grid"
          showFooter={false}
          emptyText={t("common.empty", "No records")}
        />
      </StateView>
      {sel && sel.lines ? (
        <div className="desk-section">
          <h3>
            {t("page.finance.pnl_lines", "行项分列")} · {sel.voyage_no}
          </h3>
          <DataGrid<LineRow>
            columns={lineCols}
            data={lineRows}
            rowKey={(r) => r.id}
            storageKey="finance_pnl_panel_lines_grid"
            showFooter={false}
            emptyText={t("common.empty", "No records")}
          />
        </div>
      ) : null}
    </div>
  );
}
