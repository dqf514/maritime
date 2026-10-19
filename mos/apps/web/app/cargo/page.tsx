"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { Num } from "@/components/Num";
import { PageHeader } from "@/components/PageHeader";
import { SavedViews } from "@/components/SavedViews";
import { StatusLegend } from "@/components/StatusLegend";
import { Tabs, type TabItem } from "@/components/Tabs";
import { Toolbar } from "@/components/Toolbar";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { StateView } from "@/components/StateView";
import { apiList } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
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

// 与后端 CARGO_TRANSITIONS 一致：open → booked → nominated → fixed → completed | cancelled
const STATUS_OPTIONS = ["open", "booked", "nominated", "fixed", "completed", "cancelled"] as const;

function CargoBookWorkspace() {
  const { t } = useI18n();
  const router = useRouter();
  const { query, setQuery } = useListQuery();
  const statusFilter = typeof query.status === "string" ? query.status : "";

  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState("");
  const [rows, setRows] = useState<CargoBookRow[]>([]);
  const rowCtx = useContextMenu<CargoBookRow>();

  function exportRows(selected: CargoBookRow[]) {
    downloadCsv(
      "cargo-book",
      ["id", "cargo_ref", "status", "cargo_type", "cargo_qty", "load_port", "discharge_port", "vessel_name", "laycan_from", "laycan_to", "etd", "eta", "counterparty"],
      selected.map((r) => [
        r.id,
        r.cargo_ref,
        r.status,
        r.cargo_type,
        r.cargo_qty,
        r.load_port,
        r.discharge_port,
        r.vessel_name ?? "",
        r.laycan_from ?? "",
        r.laycan_to ?? "",
        r.etd ?? "",
        r.eta ?? "",
        r.counterparty ?? "",
      ]),
    );
  }

  function rowMenuItems(target: CargoBookRow): ContextMenuItem[] {
    return [
      {
        key: "open",
        label: t("common.open", "Open"),
        onClick: () => {
          if (target.voyage_id) router.push(`/operations/voyages/${target.voyage_id}/workspace`);
          else if (target.charter_id) router.push(`/charters/${target.charter_id}`);
        },
      },
      { key: "copy", label: t("common.copy_id", "Copy id"), onClick: () => void navigator.clipboard?.writeText(target.id) },
      { key: "export", label: t("page.finance.export_selected", "Export selected"), onClick: () => exportRows([target]) },
    ];
  }

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
          const cls = s === "completed" ? "badge-pass"
            : s === "cancelled" ? "badge-fail"
            : s === "fixed" || s === "nominated" ? "badge-info"
            : "badge-warn";
          return <span className={`badge ${cls}`}>{s}</span>;
        },
      },
      { key: "cargo_type", title: t("page.cargo.type", "Cargo"), width: 90, sortable: true },
      {
        key: "cargo_qty", title: t("page.cargo.qty", "Qty (mt)"), width: 100, align: "right", sortable: true, agg: "sum",
        value: (r) => r.cargo_qty, render: (v) => <Num v={v as number} digits={2} />,
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

  const tabs = useMemo<TabItem[]>(() => {
    const items: TabItem[] = [
      { key: "", label: t("common.all", "All"), badge: rows.length },
    ];
    for (const s of STATUS_OPTIONS) {
      const c = statusCounts.get(s) ?? 0;
      if (c > 0) items.push({ key: s, label: s.replace("_", " "), badge: c });
    }
    return items;
  }, [rows.length, statusCounts, t]);

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.cargo-book", "Cargo Book") }]}
        title={t("page.cargo.title", "Cargo Book")}
        subtitle={t("page.cargo.sub", "All cargo allocations, shipments and delivery status.")}
        actions={
          <SavedViews storageKey="cargo_list" onApply={(q) => router.replace(`/cargo${q}`)} />
        }
      />
      <Toolbar
        filterCount={statusFilter ? 1 : 0}
        onClearFilters={() => setStatus("")}
        right={<span className="hint">{t("page.cargo.count", "{n} rows", { n: rows.length })}</span>}
      >
        <button type="button" className="btn btn-sm" onClick={load} title={t("common.refresh", "Refresh")}>
          ↻
        </button>
      </Toolbar>

      <Tabs items={tabs} value={statusFilter} onChange={setStatus} variant="pill" />

      <StatusLegend statuses={[...STATUS_OPTIONS]} />

      <StateView loading={loading} error={loadErr} empty={!loading && !loadErr && rows.length === 0} onRetry={load}>
        <div className="trading-grid-wrap">
          <DataGrid<CargoBookRow>
            columns={cols}
            data={rows}
            rowKey={(r) => r.id}
            onRowClick={(r) => {
              if (r.voyage_id) router.push(`/operations/voyages/${r.voyage_id}/workspace`);
            }}
            onRowContextMenu={(row, _i, e) => rowCtx.open(row)(e)}
            storageKey="cargo_book"
            emptyText={t("common.empty", "No records")}
          />
        </div>
      </StateView>

      <ContextMenu controller={rowCtx} items={rowMenuItems} />
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
