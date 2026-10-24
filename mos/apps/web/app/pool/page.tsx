"use client";

import { FormEvent, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { RefreshButton } from "@/components/RefreshButton";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { Num } from "@/components/Num";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { SavedViews } from "@/components/SavedViews";
import { StateView } from "@/components/StateView";
import { StatusLegend } from "@/components/StatusLegend";
import { Toolbar } from "@/components/Toolbar";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { useListHotkeys } from "@/components/useListHotkeys";
import { apiDelete, apiGet, apiPost } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { msgOf, handled } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { toFiniteNumber } from "@/lib/numbers";
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
  // 主列表（池期 / 船只）取数状态：失败必须走 StateView 错误态（P1-4）。
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState("");
  // 参考数据取数失败的可见提示（P1-4）
  const [refWarn, setRefWarn] = useState("");
  // 破坏性操作二次确认：结算池期 / 离池（P1-8）。
  const [confirm, setConfirm] = useState<{
    title: string;
    message: string;
    confirmLabel: string;
    action: () => void;
  } | null>(null);
  // 新建入口统一走 RecordModal（列表页禁止内联新建表单）——
  // 面板只留「标题 + 打开弹窗」按钮，表单字段进弹窗，列表不再被表单包住。
  const [addVesselOpen, setAddVesselOpen] = useState(false);
  const [periodOpen, setPeriodOpen] = useState(false);
  const [savingVessel, setSavingVessel] = useState(false);
  const [savingPeriod, setSavingPeriod] = useState(false);

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
      { key: "leave", label: t("page.pool.leave", "Leave"), onClick: () => askLeavePool(target.id, target.vessel_id) },
    ];
  }

  function periodMenuItems(target: Pool["periods"][number]): ContextMenuItem[] {
    return [
      { key: "copy", label: t("common.copy_id", "Copy id"), onClick: () => void navigator.clipboard?.writeText(target.id) },
      { key: "export", label: t("page.finance.export_selected", "Export selected"), onClick: () => exportPeriods([target]) },
      ...(target.status !== "settled"
        ? [
            {
              key: "settle",
              label: t("page.pool.settle", "Settle"),
              onClick: () => askSettle(target.id, target.label),
            } as ContextMenuItem,
          ]
        : []),
    ];
  }

  const load = useCallback(async () => {
    setLoading(true);
    setLoadErr("");
    try {
      const [p, v] = await Promise.all([
        apiGet("/api/v1/pools"),
        // 参考数据（船名表）失败不让整页报错，但要可见（P1-4）。
        apiGet("/api/v1/masterdata/vessels").catch(() => {
          setRefWarn(t("page.pool.vessels_fail", "Could not load the vessel master data — names may show as IDs."));
          return [];
        }),
      ]);
      setPools(p);
      setVessels(v);
      if (!selected && p[0]?.id) setSelected(p[0].id);
    } catch (e) {
      setPools([]);
      setLoadErr(msgOf(e, t("common.failed", "Failed")));
      throw e;
    } finally {
      setLoading(false);
    }
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
      toast.error(msgOf(ex));
    } finally {
      setSavingPool(false);
    }
  }

  async function addVessel(e: FormEvent) {
    e.preventDefault();
    setErr("");
    if (!selected || !vesselId) return;
    // P1-24：Points 是权重，填 0 就是 0（合法）；垃圾输入必须报错，不能静默变成 1。
    const pointsNum = toFiniteNumber(points);
    if (pointsNum === null || pointsNum < 0) {
      const msg = t("page.pool.err_points", {
        en: "Points must be a number of 0 or more.",
        zh: "Points 必须是不小于 0 的数字。",
      });
      setErr(msg);
      toast.error(msg);
      return;
    }
    setSavingVessel(true);
    try {
      await apiPost(`/api/v1/pools/${selected}/vessels?vessel_id=${vesselId}&points=${pointsNum}`);
      toast.success(t("page.pool.vessel_ok", "Vessel added to pool"));
      setAddVesselOpen(false);
      await load();
    } catch (ex: any) {
      const code = ex?.detail?.code || ex?.code;
      let msg: string;
      if (code === "VESSEL_ALREADY_IN_POOL") {
        msg = t("page.pool.already_in", "Vessel is already in this pool");
      } else if (code === "VESSEL_IN_OTHER_POOL") {
        msg = t("page.pool.in_other", "Vessel is already in pool {name}. Leave it before joining.", {
          name: ex?.detail?.pool_name || "",
        });
      } else {
        msg = msgOf(ex);
      }
      setErr(msg);
      // 弹窗遮住页面级错误条 —— 同时用 toast 报一次，错误必须在视线内。
      toast.error(msg);
    } finally {
      setSavingVessel(false);
    }
  }

  const removeVessel = useCallback(async (membershipId: string) => {
    if (!selected) return;
    setErr("");
    try {
      await apiDelete(`/api/v1/pools/${selected}/vessels/${membershipId}`);
      toast.success(t("page.pool.left", "Left the pool"));
      await load();
    } catch (ex: any) {
      setErr(msgOf(ex));
    }
  }, [selected, t, toast, load]);

  const settle = useCallback(async (periodId: string) => {
    setErr("");
    try {
      await apiPost(`/api/v1/pools/periods/${periodId}/settle`);
      toast.success(t("page.pool.settled", "Period settled"));
      await load();
    } catch (ex: any) {
      setErr(msgOf(ex));
    }
  }, [t, toast, load]);

  /** 离池是破坏性操作 —— 走二次确认并指名船只（P1-8）。 */
  const askLeavePool = useCallback((membershipId: string, vesselId: string) => {
    const name = vessels.find((x) => x.id === vesselId)?.name || vesselId.slice(0, 8);
    setConfirm({
      title: t("page.pool.leave", "Leave"),
      message: t("page.pool.leave_confirm", 'Remove vessel "{name}" from this pool?', { name }),
      confirmLabel: t("page.pool.leave", "Leave"),
      action: () => void removeVessel(membershipId),
    });
  }, [vessels, t, removeVessel]);

  /** 结算池期不可撤销 —— 二次确认并指名结算期（P1-8）。 */
  const askSettle = useCallback((periodId: string, label: string) => {
    setConfirm({
      title: t("page.pool.settle", "Settle"),
      message: t(
        "page.pool.settle_confirm",
        'Settle period "{label}"? The distribution becomes final and cannot be changed.',
        { label },
      ),
      confirmLabel: t("page.pool.settle", "Settle"),
      action: () => void settle(periodId),
    });
  }, [t, settle]);

  async function createPeriod(e: FormEvent) {
    e.preventDefault();
    setErr("");
    if (!selected) return;
    // P1-24：垃圾输入不能静默变 0 —— 非法值直接报错并中止提交（0 本身合法）。
    const rawTotal = totalResult.trim();
    const totalNum = rawTotal === "" ? 0 : Number(rawTotal);
    if (!Number.isFinite(totalNum)) {
      const msg = t("page.pool.err_total_result", "Enter a valid number for the pool result");
      setErr(msg);
      toast.error(msg);
      return;
    }
    setSavingPeriod(true);
    try {
      await apiPost(
        `/api/v1/pools/${selected}/periods?label=${encodeURIComponent(periodLabel)}&total_pool_result=${totalNum}`,
      );
      toast.success(t("page.pool.period_ok", "Period distribution generated"));
      setPeriodOpen(false);
      await load();
    } catch (ex: any) {
      const msg = msgOf(ex);
      setErr(msg);
      toast.error(msg);
    } finally {
      setSavingPeriod(false);
    }
  }

  const vesselColumns = useMemo<ColumnDef<Pool["vessels"][number]>[]>(
    () => [
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
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => askLeavePool(r.id, r.vessel_id)}>
            {t("page.pool.leave", "Leave")}
          </button>
        ),
      },
    ],
    [t, vessels, askLeavePool],
  );

  const periodColumns = useMemo<ColumnDef<Pool["periods"][number]>[]>(
    () => [
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
        minWidth: 220,
        value: (r) => JSON.stringify(r.distribution),
        // 分配结果是 {vessel_id: 金额} + _fees —— 直接吐 JSON 没法看，
        // 按船名 + 金额逐行列出（用户看到的是船，不是 UUID）。
        render: (v) => {
          let dist: Record<string, unknown> = {};
          try {
            dist = (typeof v === "string" ? JSON.parse(v) : (v as Record<string, unknown>)) || {};
          } catch {
            return <code>{String(v)}</code>;
          }
          const fees = (dist._fees ?? {}) as Record<string, number>;
          const shares = Object.entries(dist).filter(([k]) => k !== "_fees");
          if (!shares.length) return <span className="muted">{t("common.none", "None")}</span>;
          return (
            <div className="pool-dist">
              {shares.map(([vid, amount]) => (
                <div key={vid} className="pool-dist-row">
                  <span>{vessels.find((x) => x.id === vid)?.name ?? vid.slice(0, 8)}</span>
                  <span>
                    <Num v={Number(amount)} digits={2} />
                  </span>
                </div>
              ))}
              {fees.total != null ? (
                <div className="pool-dist-row muted">
                  <span>{t("page.pool.fees", "Fees")}</span>
                  <span>
                    <Num v={Number(fees.total)} digits={2} />
                  </span>
                </div>
              ) : null}
            </div>
          );
        },
      },
      {
        key: "_actions",
        title: "",
        width: 90,
        align: "right",
        render: (_v, r) =>
          r.status !== "settled" ? (
            <button type="button" className="btn btn-sm" onClick={() => askSettle(r.id, r.label)}>
              {t("page.pool.settle", "Settle")}
            </button>
          ) : null,
      },
    ],
    [t, vessels, askSettle],
  );

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
        <RefreshButton label={t("common.refresh", "Refresh")} className="btn btn-sm" onClick={() => load().catch(() => setErr(t("common.failed", "Failed")))} />
      </Toolbar>
      {err ? <p className="flash-err">{err}</p> : null}
      {refWarn ? <p className="flash-err">{refWarn}</p> : null}

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

      <StateView
        loading={loading}
        error={loadErr || undefined}
        empty={!loadErr && !current}
        emptyText={t("page.pool.no_pool", "No pooling group yet — create one to get started.")}
        onRetry={() => load().catch(handled)}
      >
      {current ? (
        <>
          <div className="panel" style={{ marginTop: "1rem" }}>
            <div className="panel-header">
              <span>{t("page.pool.vessels_title", "Vessels in pool")}</span>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => setAddVesselOpen(true)}
                disabled={!availableVessels.length}
              >
                {t("page.pool.add_vessel", "Add vessel")}
              </button>
            </div>
            <div className="panel-body">
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
          </div>

          <div className="panel" style={{ marginTop: "1rem" }}>
            <div className="panel-header">
              <span>{t("page.pool.period", "Settlement period")}</span>
              <button type="button" className="btn btn-primary btn-sm" onClick={() => setPeriodOpen(true)}>
                {t("page.pool.new_period", "New settlement period")}
              </button>
            </div>
            <div className="panel-body">
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
          </div>
        </>
      ) : null}
      </StateView>

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

      <RecordModal
        open={addVesselOpen}
        title={t("page.pool.add_vessel_title", "Add vessel to pool")}
        onClose={() => setAddVesselOpen(false)}
        onSave={addVessel}
        canDelete={false}
        saving={savingVessel}
        size="md"
      >
        <div className="form-grid">
          <label className="field">
            <span>{t("page.estimates.vessel", "Vessel")}</span>
            <select
              className="input"
              value={vesselId}
              onChange={(e) => setVesselId(e.target.value)}
              disabled={!availableVessels.length}
            >
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
          <label className="field">
            <span>{t("page.pool.points", "Points")}</span>
            <input className="input" value={points} onChange={(e) => setPoints(e.target.value)} />
          </label>
        </div>
      </RecordModal>

      <RecordModal
        open={periodOpen}
        title={t("page.pool.new_period", "New settlement period")}
        onClose={() => setPeriodOpen(false)}
        onSave={createPeriod}
        canDelete={false}
        saving={savingPeriod}
        size="md"
      >
        <div className="form-grid">
          <label className="field">
            <span>{t("page.pool.label", "Label")}</span>
            <input className="input" value={periodLabel} onChange={(e) => setPeriodLabel(e.target.value)} />
          </label>
          <label className="field">
            <span>{t("page.pool.total", "Pool total result")}</span>
            <input className="input" value={totalResult} onChange={(e) => setTotalResult(e.target.value)} />
          </label>
        </div>
      </RecordModal>

      <ContextMenu controller={vesselCtx} items={vesselMenuItems} />
      <ContextMenu controller={periodCtx} items={periodMenuItems} />

      <ConfirmDialog
        open={Boolean(confirm)}
        title={confirm?.title || ""}
        message={confirm?.message || ""}
        confirmLabel={confirm?.confirmLabel}
        danger
        onConfirm={() => {
          const fn = confirm?.action;
          setConfirm(null);
          fn?.();
        }}
        onCancel={() => setConfirm(null)}
      />
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
