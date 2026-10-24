"use client";

// U-DISTANCES 航线距离表（IMOS Data Center > Distances 对齐）。
// 全局航海参照数据（port_distances 无 tenant_id），故列表与写入都不做租户过滤。

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { RefreshButton } from "@/components/RefreshButton";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageHeader } from "@/components/PageHeader";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { ExportButton } from "@/components/ExportButton";
import { RecordModal } from "@/components/RecordModal";
import { SavedViews } from "@/components/SavedViews";
import { StateView } from "@/components/StateView";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";
import { useListQuery } from "@/lib/useListQuery";

type Distance = {
  id: string;
  from_port_unlocode: string;
  to_port_unlocode: string;
  distance_nm: number;
  route_type: string;
  canal_transit?: string | null;
  canal_toll?: number | string | null;
  transit_days?: number | string | null;
  notes?: string | null;
  source?: string | null;
};

const emptyRow = {
  from_port_unlocode: "",
  to_port_unlocode: "",
  distance_nm: "",
  route_type: "standard",
  canal_transit: "",
  canal_toll: "",
  transit_days: "",
  notes: "",
};

const ROUTE_TYPES = ["standard", "canal", "cape"] as const;

function numIn(v: string): number | null {
  return v === "" || v === null || v === undefined ? null : Number(v);
}
function numOut(v: number | string | null | undefined): string {
  return v === null || v === undefined || v === "" ? "" : String(v);
}

function DistancesPage() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const { query, setQuery } = useListQuery();
  const q = query.q ?? "";
  const routeType = query.route_type ?? "";

  const [rows, setRows] = useState<Distance[]>([]);
  const [open, setOpen] = useState<Distance | null>(null);
  const [creating, setCreating] = useState(false);
  const [edit, setEdit] = useState({ ...emptyRow });
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [listErr, setListErr] = useState("");
  // P1-28：后端 /distances/list 硬上限 2000 条且无 offset —— 截断必须对用户可见
  const [truncated, setTruncated] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<{ run: () => void; name: string } | null>(null);

  async function load() {
    setLoading(true);
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (routeType) params.set("route_type", routeType);
    params.set("limit", "2000");
    try {
      const d = await apiGet(`/api/v1/distances/list?${params.toString()}`);
      const arr = Array.isArray(d) ? (d as Distance[]) : [];
      setRows(arr);
      setTruncated(arr.length >= 2000);
      setListErr("");
    } catch (ex) {
      // 列表取数失败必须走错误态，不能静默变成「No records」
      setRows([]);
      setTruncated(false);
      setListErr(msgOf(ex));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [q, routeType]);

  function openCreate() {
    setEdit({ ...emptyRow });
    setOpen(null);
    setCreating(true);
  }

  useListHotkeys(openCreate);

  function closeModal() {
    setOpen(null);
    setCreating(false);
  }

  function openRow(r: Distance) {
    setCreating(false);
    setOpen(r);
    setEdit({
      from_port_unlocode: r.from_port_unlocode,
      to_port_unlocode: r.to_port_unlocode,
      distance_nm: numOut(r.distance_nm),
      route_type: r.route_type || "standard",
      canal_transit: r.canal_transit || "",
      canal_toll: numOut(r.canal_toll),
      transit_days: numOut(r.transit_days),
      notes: r.notes || "",
    });
  }

  function payload() {
    return {
      from_port_unlocode: edit.from_port_unlocode.trim().toUpperCase(),
      to_port_unlocode: edit.to_port_unlocode.trim().toUpperCase(),
      distance_nm: Number(edit.distance_nm),
      route_type: edit.route_type,
      canal_transit: edit.canal_transit || null,
      canal_toll: numIn(edit.canal_toll),
      transit_days: numIn(edit.transit_days),
      notes: edit.notes || null,
    };
  }

  function validate(): string | null {
    if (!edit.from_port_unlocode.trim() || !edit.to_port_unlocode.trim())
      return t("page.distances.err_ports", "Both ports are required");
    if (edit.from_port_unlocode.trim().toUpperCase() === edit.to_port_unlocode.trim().toUpperCase())
      return t("page.distances.err_same", "From and To must differ");
    if (edit.distance_nm === "" || Number.isNaN(Number(edit.distance_nm)) || Number(edit.distance_nm) <= 0)
      return t("page.distances.err_distance", "Distance must be a positive number");
    // 其余数值字段：非法输入必须中止提交（不能静默变成 NaN/null）
    for (const [raw, label] of [
      [edit.transit_days, t("page.distances.transit_days", "Transit (days)")],
      [edit.canal_toll, t("page.distances.toll", "Canal toll")],
    ] as Array<[string, string]>) {
      if (raw.trim() === "") continue;
      const n = Number(raw);
      if (!Number.isFinite(n) || n < 0)
        return t("page.distances.err_numeric", "{field} must be a non-negative number", { field: label });
    }
    return null;
  }

  async function save() {
    const err = validate();
    if (err) {
      toast.error(err);
      return;
    }
    setSaving(true);
    try {
      if (creating || !open) {
        // POST /distances 是 upsert：同一对港口重复提交即更新
        await apiPost("/api/v1/distances", payload());
        toast.success(t("page.distances.created", "Distance saved"));
      } else {
        await apiPatch(`/api/v1/distances/${open.id}`, payload());
        toast.success(t("common.saved", "Saved"));
      }
      closeModal();
      await load();
    } catch (ex) {
      toast.error(msgOf(ex, t("common.failed", "Failed")));
    } finally {
      setSaving(false);
    }
  }

  async function removeById(id: string) {
    setSaving(true);
    try {
      await apiDelete(`/api/v1/distances/${id}`);
      toast.success(t("common.deleted", "Deleted"));
      closeModal();
      await load();
    } catch (ex) {
      toast.error(msgOf(ex, t("common.failed", "Failed")));
    } finally {
      setSaving(false);
    }
  }

  const columns = useMemo<ColumnDef<Distance>[]>(() => [
    {
      key: "from_port_unlocode",
      title: t("page.distances.from", "From"),
      width: 110,
      value: (r) => r.from_port_unlocode,
    },
    {
      key: "to_port_unlocode",
      title: t("page.distances.to", "To"),
      width: 110,
      value: (r) => r.to_port_unlocode,
    },
    {
      key: "distance_nm",
      title: t("page.distances.distance", "Distance (NM)"),
      width: 130,
      align: "right",
      value: (r) => r.distance_nm,
      render: (_v, r) => String(r.distance_nm),
    },
    {
      key: "route_type",
      title: t("page.distances.route_type", "Route"),
      width: 110,
      value: (r) => r.route_type,
      render: (_v, r) => t(`page.distances.type_${r.route_type}`, r.route_type),
    },
    {
      key: "canal_transit",
      title: t("page.distances.canal", "Canal"),
      width: 130,
      value: (r) => r.canal_transit || "",
      render: (_v, r) => r.canal_transit || "—",
    },
    {
      key: "transit_days",
      title: t("page.distances.transit_days", "Transit (days)"),
      width: 125,
      align: "right",
      value: (r) => (r.transit_days ?? null) as number | string | null,
      render: (_v, r) =>
        r.transit_days === null || r.transit_days === undefined || r.transit_days === "" ? "—" : String(r.transit_days),
    },
    {
      key: "canal_toll",
      title: t("page.distances.toll", "Canal toll"),
      width: 125,
      align: "right",
      value: (r) => (r.canal_toll ?? null) as number | string | null,
      render: (_v, r) =>
        r.canal_toll === null || r.canal_toll === undefined || r.canal_toll === "" ? "—" : String(r.canal_toll),
    },
    { key: "notes", title: t("common.notes", "Notes"), minWidth: 150, value: (r) => r.notes || "", render: (_v, r) => r.notes || "—" },
    { key: "source", title: t("page.distances.source", "Source"), width: 120, value: (r) => r.source || "", render: (_v, r) => r.source || "—" },
    {
      key: "actions",
      title: "",
      width: 90,
      align: "right",
      render: (_v, r) => (
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={(e) => {
            e.stopPropagation();
            openRow(r);
          }}
        >
          {t("common.edit", "Edit")}
        </button>
      ),
    },
  ], [t]);

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.master", "Master data") }]}
        title={t("page.distances.title", "Distances")}
        subtitle={t("page.distances.sub", "Port-to-port nautical distances (UN/LOCODE). Click a row to edit.")}
        actions={
          <>
            <ExportButton entity="distances" />
            <Link href="/settings/recycle" className="btn btn-ghost">
              {t("nav.recycle", "Recycle bin")}
            </Link>
          </>
        }
      />
      <Toolbar
        filterCount={(q ? 1 : 0) + (routeType ? 1 : 0)}
        onClearFilters={() => setQuery({ q: null, route_type: null }, { resetPage: true })}
        right={
          <>
            <input
              className="input input-sm"
              type="search"
              value={q}
              onChange={(e) => setQuery({ q: e.target.value || null }, { resetPage: true })}
              placeholder={t("page.distances.search", "Search UN/LOCODE…")}
              aria-label={t("common.search", "Search")}
            />
            <select
              className="input input-sm"
              value={routeType}
              onChange={(e) => setQuery({ route_type: e.target.value || null }, { resetPage: true })}
              aria-label={t("page.distances.route_type", "Route")}
            >
              <option value="">{t("page.distances.all_routes", "All routes")}</option>
              {ROUTE_TYPES.map((rt) => (
                <option key={rt} value={rt}>
                  {t(`page.distances.type_${rt}`, rt)}
                </option>
              ))}
            </select>
            <SavedViews storageKey="md_distances" onApply={(qs) => router.replace(`${pathname}${qs}`)} />
          </>
        }
      >
        <button type="button" className="btn btn-primary" onClick={openCreate}>
          {t("page.distances.add", "New distance")}
        </button>
        <RefreshButton label={t("common.refresh", "Refresh")} className="btn btn-sm" onClick={() => void load()} />
      </Toolbar>

      <div className="panel">
        <StateView
          loading={loading}
          error={listErr || undefined}
          empty={!rows.length}
          emptyText={t("common.empty", "No records")}
          onRetry={() => void load()}
        >
          <DataGrid<Distance>
            columns={columns}
            data={rows}
            rowKey={(r) => r.id}
            onRowClick={(r) => openRow(r)}
            storageKey="masterdata_distances_grid"
            emptyText={t("common.empty", "No records")}
          />
        </StateView>
        {/* P1-28：列表总数必须可见 */}
        {!listErr && rows.length ? (
          <p className="muted">{t("list.count_total", "{n} records", { n: rows.length })}</p>
        ) : null}
        {truncated ? (
          <p className="muted">
            {t("page.distances.truncated", "Showing the first 2000 records — narrow the search to see the rest.")}
          </p>
        ) : null}
      </div>

      <RecordModal
        open={creating || Boolean(open)}
        title={creating ? t("page.distances.add", "New distance") : t("page.distances.edit", "Edit distance")}
        onClose={closeModal}
        onSave={save}
        saving={saving}
      >
        <label>
          {t("page.distances.from", "From")}
          <input
            value={edit.from_port_unlocode}
            onChange={(e) => setEdit({ ...edit, from_port_unlocode: e.target.value })}
            maxLength={8}
            required
          />
        </label>
        <label>
          {t("page.distances.to", "To")}
          <input
            value={edit.to_port_unlocode}
            onChange={(e) => setEdit({ ...edit, to_port_unlocode: e.target.value })}
            maxLength={8}
            required
          />
        </label>
        <label>
          {t("page.distances.distance", "Distance (NM)")}
          <input
            type="number"
            step="0.1"
            min="0"
            value={edit.distance_nm}
            onChange={(e) => setEdit({ ...edit, distance_nm: e.target.value })}
            required
          />
        </label>
        <label>
          {t("page.distances.route_type", "Route")}
          <select value={edit.route_type} onChange={(e) => setEdit({ ...edit, route_type: e.target.value })}>
            {ROUTE_TYPES.map((rt) => (
              <option key={rt} value={rt}>
                {t(`page.distances.type_${rt}`, rt)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("page.distances.canal", "Canal")}
          <input
            value={edit.canal_transit}
            onChange={(e) => setEdit({ ...edit, canal_transit: e.target.value })}
            placeholder={t("page.distances.canal_ph", "Suez / Panama")}
          />
        </label>
        <label>
          {t("page.distances.transit_days", "Transit (days)")}
          <input
            type="number"
            step="0.1"
            min="0"
            value={edit.transit_days}
            onChange={(e) => setEdit({ ...edit, transit_days: e.target.value })}
          />
        </label>
        <label>
          {t("page.distances.toll", "Canal toll")}
          <input
            type="number"
            step="0.01"
            min="0"
            value={edit.canal_toll}
            onChange={(e) => setEdit({ ...edit, canal_toll: e.target.value })}
          />
        </label>
        <label>
          {t("common.notes", "Notes")}
          <input value={edit.notes} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} />
        </label>

        {/* P1-8：删除航线距离是不可逆动作 —— 走指名对象的二次确认。 */}
        {open ? (
          <div className="desk-toolbar">
            <button
              type="button"
              className="btn btn-danger btn-sm"
              disabled={saving}
              onClick={() =>
                setPendingDelete({
                  run: () => void removeById(open.id),
                  name: `${open.from_port_unlocode} → ${open.to_port_unlocode}`,
                })
              }
            >
              {t("common.delete", "Delete")}
            </button>
          </div>
        ) : null}
      </RecordModal>

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title={t("common.confirm", "Confirm")}
        message={t("common.confirm_delete_named", 'Delete "{name}"?', { name: pendingDelete?.name ?? "" })}
        danger
        confirmLabel={t("common.delete", "Delete")}
        onConfirm={() => {
          const fn = pendingDelete;
          setPendingDelete(null);
          fn?.run();
        }}
        onCancel={() => setPendingDelete(null)}
      />
    </AppShell>
  );
}

// Next 16: useSearchParams（useListQuery）须位于 Suspense 边界内
export default function Page() {
  return (
    <Suspense fallback={null}>
      <DistancesPage />
    </Suspense>
  );
}
