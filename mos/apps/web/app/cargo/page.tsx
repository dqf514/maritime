"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { StateView } from "@/components/StateView";
import { apiGet, apiList } from "@/lib/api";
import { fmt } from "@/lib/fmt";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";

type CargoBookRow = {
  id: string;
  cargo_ref: string;
  charter_id: string | null;
  voyage_id: string | null;
  vessel_name: string | null;
  cargo_type: string;
  cargo_qty: number;
  load_port: string;
  discharge_port: string;
  laycan_from: string | null;
  laycan_to: string | null;
  etd: string | null;
  eta: string | null;
  status: string;
  counterparty: string | null;
};

const STATUS_OPTIONS = ["booked", "loading", "loaded", "in_transit", "discharged", "completed", "cancelled"] as const;

function CargoBookWorkspace() {
  const { t } = useI18n();
  const { query, setQuery } = useListQuery();
  const statusFilter = typeof query.status === "string" ? query.status : "";

  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState("");
  const [rows, setRows] = useState<CargoBookRow[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadErr("");
    try {
      const params: Record<string, string | number> = { limit: 200 };
      if (statusFilter) params.status = statusFilter;
      const page = await apiList<CargoBookRow>("/api/v1/cargo-book", params);
      setRows(
        page.items.map((r) => ({
          id: String(r.id),
          cargo_ref: String(r.cargo_ref ?? ""),
          charter_id: r.charter_id ? String(r.charter_id) : null,
          voyage_id: r.voyage_id ? String(r.voyage_id) : null,
          vessel_name: r.vessel_name ? String(r.vessel_name) : null,
          cargo_type: String(r.cargo_type ?? ""),
          cargo_qty: Number(r.cargo_qty ?? 0),
          load_port: String(r.load_port ?? ""),
          discharge_port: String(r.discharge_port ?? ""),
          laycan_from: r.laycan_from ? String(r.laycan_from).slice(0, 10) : null,
          laycan_to: r.laycan_to ? String(r.laycan_to).slice(0, 10) : null,
          etd: r.etd ? String(r.etd).slice(0, 10) : null,
          eta: r.eta ? String(r.eta).slice(0, 10) : null,
          status: String(r.status ?? "booked"),
          counterparty: r.counterparty ? String(r.counterparty) : null,
        })),
      );
    } catch (ex) {
      setLoadErr(String(ex));
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  const setStatus = (s: string) => setQuery({ status: s || null });

  const statusCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of rows) m.set(r.status, (m.get(r.status) ?? 0) + 1);
    return m;
  }, [rows]);

  const cols = useMemo<ColumnDef<CargoBookRow>[]>(
    () => [
      { key: "cargo_ref", title: t("page.cargo.ref", "Cargo ref"), width: 110, sortable: true, sticky: true },
      {
        key: "status", title: t("common.status", "Status"), width: 100, sortable: true,
        render: (v) => {
          const s = String(v ?? "");
          const cls = s === "completed" || s === "discharged" ? "badge-pass"
            : s === "cancelled" ? "badge-fail"
            : s === "in_transit" || s === "loaded" ? "badge-info"
            : "badge-warn";
          return <span className={`badge ${cls}`}>{s}</span>;
        },
      },
      { key: "cargo_type", title: t("page.cargo.type", "Cargo"), width: 90, sortable: true },
      {
        key: "cargo_qty", title: t("page.cargo.qty", "Qty (mt)"), width: 100, align: "right", sortable: true, agg: "sum",
        value: (r) => r.cargo_qty, render: (v) => fmt(Number(v)),
      },
      { key: "load_port", title: t("page.cargo.load_port", "Load port"), width: 110, sortable: true },
      { key: "discharge_port", title: t("page.cargo.disch_port", "Disch port"), width: 110, sortable: true },
      { key: "vessel_name", title: t("page.cargo.vessel", "Vessel"), width: 120, value: (r) => r.vessel_name ?? "" },
      {
        key: "laycan", title: t("page.cargo.laycan", "Laycan"), width: 160,
        value: (r) => (r.laycan_from && r.laycan_to ? `${r.laycan_from} → ${r.laycan_to}` : r.laycan_from ?? ""),
        render: (_v, r) => (r.laycan_from && r.laycan_to ? `${r.laycan_from} → ${r.laycan_to}` : r.laycan_from ?? "—"),
      },
      { key: "etd", title: t("page.cargo.etd", "ETD"), width: 90, value: (r) => r.etd ?? "" },
      { key: "eta", title: t("page.cargo.eta", "ETA"), width: 90, value: (r) => r.eta ?? "" },
      { key: "counterparty", title: t("page.cargo.counterparty", "CP"), width: 120, value: (r) => r.counterparty ?? "" },
    ],
    [t],
  );

  const tabs = useMemo(() => {
    const items: Array<{ id: string; label: string; count: number }> = [
      { id: "", label: t("common.all", "All"), count: rows.length },
    ];
    for (const s of STATUS_OPTIONS) {
      const c = statusCounts.get(s) ?? 0;
      if (c > 0) items.push({ id: s, label: s.replace("_", " "), count: c });
    }
    return items;
  }, [rows.length, statusCounts, t]);

  return (
    <AppShell>
      <PageHeader
        title={t("page.cargo.title", "Cargo Book")}
        subtitle={t("page.cargo.sub", "All cargo allocations, shipments and delivery status.")}
        actions={
          <button type="button" className="btn btn-sm" onClick={load}>
            {t("common.refresh", "Refresh")}
          </button>
        }
      />

      <div className="trading-tabs">
        {tabs.map((tb) => (
          <button
            key={tb.id}
            type="button"
            className={`trading-tab${statusFilter === tb.id ? " active" : ""}`}
            onClick={() => setStatus(tb.id)}
          >
            {tb.label} ({tb.count})
          </button>
        ))}
      </div>

      <StateView loading={loading} error={loadErr} empty={!loading && !loadErr && rows.length === 0} onRetry={load}>
        <div className="trading-grid-wrap">
          <DataGrid<CargoBookRow>
            columns={cols}
            data={rows}
            rowKey={(r) => r.id}
            storageKey="cargo_book"
            emptyText={t("common.empty", "No records")}
          />
        </div>
      </StateView>
    </AppShell>
  );
}

export default function CargoBookPage() {
  return (
    <Suspense fallback={null}>
      <CargoBookWorkspace />
    </Suspense>
  );
}
