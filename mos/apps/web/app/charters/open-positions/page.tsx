"use client";

// P11 IMOS Open Positions — TC In 还船机会 + 未成交 voyage fixture 汇总看板。
// 数据源：GET /api/v1/chartering/open-positions（kind = tc_open | voyage_fix）。

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { DateInput } from "@/components/DateInput";
import { PageHeader } from "@/components/PageHeader";
import { StateView } from "@/components/StateView";
import { Toolbar } from "@/components/Toolbar";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { apiGet } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";

type OpenRow = {
  kind: "tc_open" | "voyage_fix";
  id: string;
  tc_code?: string | null;
  fixture_no?: string | null;
  charter_no?: string | null;
  vessel_code?: string | null;
  vessel_name?: string | null;
  dwt?: number | null;
  vessel_type?: string | null;
  cubic_capacity?: number | null;
  company_code?: string | null;
  open_date: string | null;
  open_port?: string | null;
  laycan_from?: string | null;
  laycan_to?: string | null;
  hire_rate?: number | null;
  hire_currency?: string | null;
  cargo_qty?: number | null;
  freight_rate?: number | null;
  freight_basis?: string | null;
  trade_area?: string | null;
};

function OpenPositionsWorkspace() {
  const { t } = useI18n();
  const router = useRouter();
  const { query, setQuery } = useListQuery();
  const dateFrom = typeof query.date_from === "string" ? query.date_from : "";
  const dateTo = typeof query.date_to === "string" ? query.date_to : "";

  const [rows, setRows] = useState<OpenRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const qs = new URLSearchParams();
      if (dateFrom) qs.set("date_from", dateFrom);
      if (dateTo) qs.set("date_to", dateTo);
      const suffix = qs.toString() ? `?${qs.toString()}` : "";
      const res = await apiGet(`/api/v1/chartering/open-positions${suffix}`);
      setRows(Array.isArray(res) ? res : res?.items || []);
    } catch (ex) {
      setErr(msgOf(ex));
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo]);

  useEffect(() => {
    load();
  }, [load]);

  const columns = useMemo<ColumnDef<OpenRow>[]>(() => [
    {
      key: "kind",
      title: t("page.open_pos.kind", "Kind"),
      width: 110,
      value: (r) => r.kind,
      render: (v) =>
        v === "tc_open" ? t("page.open_pos.tc_open", "TC opening") : t("page.open_pos.voyage_fix", "Open fixture"),
    },
    {
      key: "ref",
      title: t("page.open_pos.ref", "TC Code / Fixture"),
      width: 150,
      sticky: true,
      value: (r) => r.tc_code || r.fixture_no || r.charter_no || "",
      render: (v) => (v ? <strong>{String(v)}</strong> : "—"),
    },
    {
      key: "vessel",
      title: t("page.estimates.vessel", "Vessel"),
      width: 170,
      value: (r) => r.vessel_name || "",
      render: (v, r) => (
        <>
          {v ? String(v) : "—"}
          {r.vessel_code ? <span className="muted"> {r.vessel_code}</span> : null}
        </>
      ),
    },
    {
      key: "dwt",
      title: t("page.tc.col.dwt", "DWT"),
      align: "right",
      width: 95,
      agg: "sum",
      value: (r) => r.dwt ?? null,
      render: (v) => (v == null ? "—" : Number(v).toLocaleString()),
    },
    { key: "vessel_type", title: t("common.type", "Type"), width: 120, value: (r) => r.vessel_type || "" },
    {
      key: "cubic_capacity",
      title: t("page.open_pos.cubic", "Cubic (ft³)"),
      align: "right",
      width: 110,
      value: (r) => r.cubic_capacity ?? null,
      render: (v) => (v == null ? "—" : Number(v).toLocaleString()),
    },
    {
      key: "open_date",
      title: t("page.open_pos.open_date", "Open date"),
      width: 110,
      value: (r) => r.open_date || "",
      render: (v) => (v ? String(v).slice(0, 10) : "—"),
    },
    {
      key: "open_port",
      title: t("page.open_pos.open_port", "Open port"),
      width: 140,
      value: (r) => r.open_port || "",
      render: (v) => (v == null || v === "" ? "—" : String(v)),
    },
    {
      key: "laycan",
      title: t("page.charters.laycan", "Laycan"),
      width: 170,
      value: (r) => (r.laycan_from || r.laycan_to ? `${r.laycan_from || "?"} → ${r.laycan_to || "?"}` : ""),
      render: (v) => (v == null || v === "" ? "—" : String(v)),
    },
    {
      key: "hire_rate",
      title: t("page.tc.col.hire_rate", "Hire rate"),
      align: "right",
      width: 120,
      value: (r) => r.hire_rate ?? null,
      render: (v, r) => (v == null ? "—" : `${Number(v).toLocaleString()} ${r.hire_currency || ""}`),
    },
    {
      key: "cargo_qty",
      title: t("page.estimates.cargo_qty", "Cargo qty"),
      align: "right",
      width: 105,
      agg: "sum",
      value: (r) => r.cargo_qty ?? null,
      render: (v) => (v == null ? "—" : Number(v).toLocaleString()),
    },
    {
      key: "freight_rate",
      title: t("page.estimates.freight_rate", "Freight rate"),
      align: "right",
      width: 115,
      value: (r) => r.freight_rate ?? null,
      render: (v, r) => (v == null ? "—" : `${Number(v).toLocaleString()} ${r.freight_basis ? ` (${r.freight_basis})` : ""}`),
    },
    { key: "company_code", title: t("page.tc.header.company_code", "Company"), width: 100, value: (r) => r.company_code || "" },
    { key: "trade_area", title: t("page.tc.header.trade_area", "Trade area"), width: 110, value: (r) => r.trade_area || "" },
  ], [t]);

  return (
    <AppShell>
      <PageHeader
        title={t("page.open_pos.title", "Open Positions")}
        subtitle={t("page.open_pos.sub", "TC In redelivery openings & unfixed voyage fixtures — click a row to open the record.")}
      />

      <Toolbar>
        <label className="muted">
          {t("page.open_pos.date_from", "From")}
          <DateInput value={dateFrom} onChange={(v) => setQuery({ date_from: v || null })} />
        </label>
        <label className="muted">
          {t("page.open_pos.date_to", "To")}
          <DateInput value={dateTo} onChange={(v) => setQuery({ date_to: v || null })} />
        </label>
        <button type="button" className="btn" onClick={() => load()}>
          {t("common.refresh", "Refresh")}
        </button>
        <span className="muted">
          {t("page.open_pos.count", "{n} open position(s)", { n: rows.length })}
        </span>
      </Toolbar>

      <div className="panel">
        <StateView
          loading={loading}
          error={err}
          empty={!loading && !err && rows.length === 0}
          emptyText={t("page.open_pos.empty", "No open positions — active TC In contracts and unfixed voyage fixtures appear here.")}
          onRetry={load}
        >
          <DataGrid<OpenRow>
            columns={columns}
            data={rows}
            rowKey={(r) => `${r.kind}-${r.id}`}
            loading={loading}
            showFooter
            storageKey="open_positions_grid"
            emptyText={t("common.empty", "No records")}
            onRowClick={(r) => {
              if (r.kind === "tc_open") router.push(`/charters/tc/${r.id}`);
              else router.push(`/charters/${r.id}`);
            }}
            onRowOpen={(r) => {
              if (r.kind === "tc_open") router.push(`/charters/tc/${r.id}`);
              else router.push(`/charters/${r.id}`);
            }}
          />
        </StateView>
      </div>
    </AppShell>
  );
}

// Next 16: useSearchParams（useListQuery）须位于 Suspense 边界内
export default function Page() {
  return (
    <Suspense fallback={null}>
      <OpenPositionsWorkspace />
    </Suspense>
  );
}
