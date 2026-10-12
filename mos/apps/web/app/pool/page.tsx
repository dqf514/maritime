"use client";

import { FormEvent, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { Num } from "@/components/Num";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { SavedViews } from "@/components/SavedViews";
import { StatusLegend } from "@/components/StatusLegend";
import { Toolbar } from "@/components/Toolbar";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { useListHotkeys } from "@/components/useListHotkeys";
import { apiDelete, apiGet, apiPost } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";
import { useToast } from "@/components/ToastProvider";

type Pool = {
  id: string;
  name: string;
  vessel_count: number;
  vessels: { id: string; vessel_id: string; points: number }[];
  periods: { id: string; label: string; total_pool_result: number; status: string; distribution: Record<string, number> }[];
};
type Vessel = { id: string; name: string };

function PoolPageInner() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const { query, setQuery } = useListQuery();
  const [pools, setPools] = useState<Pool[]>([]);
  const [vessels, setVessels] = useState<Vessel[]>([]);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [savingPool, setSavingPool] = useState(false);
  const selected = typeof query.pool === "string" ? query.pool : "";
  const setSelected = (id: string) => setQuery({ pool: id || null });
  const [vesselId, setVesselId] = useState("");
  const [points, setPoints] = useState("1");
  const [periodLabel, setPeriodLabel] = useState("2026-Q3");
  const [totalResult, setTotalResult] = useState("1000000");
  const [err, setErr] = useState("");

  useListHotkeys(() => {
    setName("");
    setCreating(true);
  });

  const vesselCtx = useContextMenu<Pool["vessels"][number]>();
  const periodCtx = useContextMenu<Pool["periods"][number]>();

  function exportVessels(selected: Pool["vessels"][number][]) {
    downloadCsv(
      "pool-vessels",
      ["id", "vessel_id", "vessel_name", "points"],
      selected.map((r) => [r.id, r.vessel_id, vessels.find((x) => x.id === r.vessel_id)?.name || r.vessel_id, r.points]),
    );
  }

  function exportPeriods(selected: Pool["periods"][number][]) {
    downloadCsv(
      "pool-periods",
      ["id", "label", "total_pool_result", "status", "distribution"],
      selected.map((r) => [r.id, r.label, r.total_pool_result, r.status, JSON.stringify(r.distribution)]),
    );
  }

  function vesselMenuItems(target: Pool["vessels"][number]): ContextMenuItem[] {
    return [
      { key: "copy", label: t("common.copy_id", "Copy id"), onClick: () => void navigator.clipboard?.writeText(target.id) },
      { key: "export", label: t("page.finance.export_selected", "Export selected"), onClick: () => exportVessels([target]) },
      { key: "div", divider: true, label: "" },
      { key: "leave", label: t("page.pool.leave", "Leave"), onClick: () => removeVessel(target.id) },
    ];
  }

  function periodMenuItems(target: Pool["periods"][number]): ContextMenuItem[] {
    return [
      { key: "copy", label: t("common.copy_id", "Copy id"), onClick: () => void navigator.clipboard?.writeText(target.id) },
      { key: "export", label: t("page.finance.export_selected", "Export selected"), onClick: () => exportPeriods([target]) },
      ...(target.status !== "settled"
        ? [{ key: "settle", label: t("page.pool.settle", "Settle"), onClick: () => settle(target.id) } as ContextMenuItem]
        : []),
    ];
  }

  const load = useCallback(async () => {
    const [p, v] = await Promise.all([apiGet("/api/v1/pools"), apiGet("/api/v1/masterdata/vessels").catch(() => [])]);
    setPools(p);
    setVessels(v);
    if (!selected && p[0]?.id) setSelected(p[0].id);
  }, [selected, setSelected]);

  useEffect(() => {
    load().catch(() => setErr(t("common.failed", "Failed")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const current = pools.find((p) => p.id === selected) || null;

  const activeVesselIds = useMemo(() => {
    const ids = new Set<string>();
    for (const p of pools) {
      for (const m of p.vessels) ids.add(m.vessel_id);
    }
    return ids;
  }, [pools]);

  const availableVessels = useMemo(() => {
    return vessels.filter((v) => !activeVesselIds.has(v.id));
  }, [vessels, activeVesselIds]);

  useEffect(() => {
    if (!availableVessels.length) {
      setVesselId("");
      return;
    }
    if (!availableVessels.some((v) => v.id === vesselId)) {
      setVesselId(availableVessels[0].id);
    }
  }, [availableVessels, vesselId]);

  async function createPool(e: FormEvent) {
    e.preventDefault();
    setSavingPool(true);
    try {
      const res = await apiPost(`/api/v1/pools?name=${encodeURIComponent(name)}`);
      toast.success(t("page.pool.created", "Pool created"));
      setName("");
      setCreating(false);
      await load();
      setSelected(res.id);
    } catch (ex: any) {
      toast.error(String(ex?.detail?.message || ex?.message || ex));
    } finally {
      setSavingPool(false);
    }
  }

  async function addVessel(e: FormEvent) {
    e.preventDefault();
    setErr("");
    toast.success("");
    if (!selected || !vesselId) return;
    try {
      await apiPost(`/api/v1/pools/${selected}/vessels?vessel_id=${vesselId}&points=${Number(points) || 1}`);
      toast.success(t("page.pool.vessel_ok", "Vessel added to pool"));
      await load();
    } catch (ex: any) {
      const code = ex?.detail?.code || ex?.code;
      if (code === "VESSEL_ALREADY_IN_POOL") {
        setErr(t("page.pool.already_in", "Vessel is already in this pool"));
      } else if (code === "VESSEL_IN_OTHER_POOL") {
        setErr(
          t("page.pool.in_other", "Vessel is already in pool {name}. Leave it before joining.", {
            name: ex?.detail?.pool_name || "",
          }),
        );
      } else {
        setErr(String(ex?.detail?.message || ex?.message || ex));
      }
    }
  }

  async function removeVessel(membershipId: string) {
    if (!selected) return;
    setErr("");
    try {
      await apiDelete(`/api/v1/pools/${selected}/vessels/${membershipId}`);
      toast.success(t("page.pool.left", "Left the pool"));
      await load();
    } catch (ex: any) {
      setErr(String(ex?.detail?.message || ex?.message || ex));
    }
  }

  async function createPeriod(e: FormEvent) {
    e.preventDefault();
    setErr("");
    if (!selected) return;
    try {
      await apiPost(
        `/api/v1/pools/${selected}/periods?label=${encodeURIComponent(periodLabel)}&total_pool_result=${Number(totalResult) || 0}`,
      );
      toast.success(t("page.pool.period_ok", "Period distribution generated"));
      await load();
    } catch (ex: any) {
      setErr(String(ex?.detail?.message || ex?.message || ex));
    }
  }

  async function settle(periodId: string) {
    setErr("");
    try {
      await apiPost(`/api/v1/pools/periods/${periodId}/settle`);
      toast.success(t("page.pool.settled", "Period settled"));
      await load();
    } catch (ex: any) {
      setErr(String(ex?.detail?.message || ex?.message || ex));
    }
  }

  const vesselColumns: ColumnDef<Pool["vessels"][number]>[] = [
    {
      key: "vessel_name",
      title: t("page.pool.vessel", "Vessel"),
      minWidth: 160,
      value: (r) => vessels.find((x) => x.id === r.vessel_id)?.name || r.vessel_id.slice(0, 8),
    },
    {
      key: "points",
      title: t("page.pool.points", "Points"),
      width: 90,
      align: "right",
      value: (r) => r.points,
      render: (v) => <Num v={v as number} digits={2} />,
    },
    {
      key: "_actions",
      title: "",
      width: 90,
      align: "right",
      render: (_v, r) => (
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => removeVessel(r.id)}>
          {t("page.pool.leave", "Leave")}
        </button>
      ),
    },
  ];

  const periodColumns: ColumnDef<Pool["periods"][number]>[] = [
    { key: "label", title: t("page.pool.label", "Label"), minWidth: 120, value: (r) => r.label },
    {
      key: "total_pool_result",
      title: t("page.pool.total", "Pool total result"),
      width: 130,
      align: "right",
      value: (r) => r.total_pool_result,
      render: (v) => <Num v={v as number} digits={2} />,
    },
    { key: "status", title: t("common.status", "Status"), width: 100, value: (r) => r.status },
    {
      key: "distribution",
      title: t("page.pool.distribution", "Distribution"),
      minWidth: 180,
      value: (r) => JSON.stringify(r.distribution),
      render: (v) => <code style={{ fontSize: "0.75rem" }}>{String(v)}</code>,
    },
    {
      key: "_actions",
      title: "",
      width: 90,
      align: "right",
      render: (_v, r) =>
        r.status !== "settled" ? (
          <button type="button" className="btn btn-sm" onClick={() => settle(r.id)}>
            {t("page.pool.settle", "Settle")}
          </button>
        ) : null,
    },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.pool", "Pooling") }]}
        title={t("page.pool.title", "Pooling")}
        subtitle={t("page.pool.sub", "Pool vessels, period results and points-based distribution.")}
        actions={<SavedViews storageKey="pool_list" onApply={(q) => router.replace(`/pool${q}`)} />}
      />
      <StatusLegend statuses={["open", "calculating", "settled"]} />
      <Toolbar>
        <button type="button" className="btn btn-primary btn-sm" onClick={() => setCreating(true)}>
          {t("page.pool.create", "Create pool")}
        </button>
        <button type="button" className="btn btn-sm" onClick={() => load().catch(() => setErr(t("common.failed", "Failed")))} title={t("common.refresh", "Refresh")}>
          ↻
        </button>
      </Toolbar>
      {err ? <p className="flash-err">{err}</p> : null}

      <div className="panel" style={{ marginTop: "1rem" }}>
        <label>
          {t("page.pool.select", "Current pool")}
          <select value={selected} onChange={(e) => setSelected(e.target.value)}>
            {pools.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({p.vessel_count})
              </option>
            ))}
          </select>
        </label>
      </div>

      {current ? (
        <>
          <form className="panel" style={{ marginTop: "1rem" }} onSubmit={addVessel}>
            <h3 style={{ marginTop: 0 }}>{t("page.pool.add_vessel", "Add vessel")}</h3>
            <div className="form-grid">
              <label>
                {t("page.estimates.vessel", "Vessel")}
                <select value={vesselId} onChange={(e) => setVesselId(e.target.value)} disabled={!availableVessels.length}>
                  {!availableVessels.length ? (
                    <option value="">{t("page.pool.no_available", "No vessels available (all already in pools)")}</option>
                  ) : (
                    availableVessels.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.name}
                      </option>
                    ))
                  )}
                </select>
              </label>
              <label>
                {t("page.pool.points", "Points")}
                <input value={points} onChange={(e) => setPoints(e.target.value)} />
              </label>
            </div>
            <button className="btn btn-primary" type="submit" disabled={!availableVessels.length || !vesselId}>
              {t("common.add", "Add")}
            </button>
            <div style={{ marginTop: "1rem" }}>
              <DataGrid<Pool["vessels"][number]>
                columns={vesselColumns}
                data={current.vessels}
                rowKey={(r) => r.id}
                onRowContextMenu={(row, _i, e) => vesselCtx.open(row)(e)}
                storageKey="pool_vessels_grid"
                showFooter={false}
                emptyText={t("common.none", "None")}
              />
            </div>
          </form>

          <form className="panel" style={{ marginTop: "1rem" }} onSubmit={createPeriod}>
            <h3 style={{ marginTop: 0 }}>{t("page.pool.period", "Settlement period")}</h3>
            <div className="form-grid">
              <label>
                {t("page.pool.label", "Label")}
                <input value={periodLabel} onChange={(e) => setPeriodLabel(e.target.value)} />
              </label>
              <label>
                {t("page.pool.total", "Pool total result")}
                <input value={totalResult} onChange={(e) => setTotalResult(e.target.value)} />
              </label>
            </div>
            <button className="btn btn-primary" type="submit">
              {t("page.pool.distribute", "Calculate distribution")}
            </button>
            <div style={{ marginTop: "1rem" }}>
              <DataGrid<Pool["periods"][number]>
                columns={periodColumns}
                data={current.periods}
                rowKey={(r) => r.id}
                onRowContextMenu={(row, _i, e) => periodCtx.open(row)(e)}
                storageKey="pool_periods_grid"
                showFooter={false}
                emptyText={t("common.none", "None")}
              />
            </div>
          </form>
        </>
      ) : null}

      <RecordModal
        open={creating}
        title={t("page.pool.create_title", "New pool")}
        onClose={() => setCreating(false)}
        onSave={createPool}
        canDelete={false}
        saving={savingPool}
        size="md"
      >
        <div className="form-grid">
          <label className="field">
            <span>{t("common.name", "Name")}</span>
            <input className="input" value={name} required onChange={(e) => setName(e.target.value)} />
          </label>
        </div>
      </RecordModal>

      <ContextMenu controller={vesselCtx} items={vesselMenuItems} />
      <ContextMenu controller={periodCtx} items={periodMenuItems} />
    </AppShell>
  );
}

export default function PoolPage() {
  return (
    <Suspense fallback={null}>
      <PoolPageInner />
    </Suspense>
  );
}
