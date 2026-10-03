"use client";

// 集中排程（Phase 3）：船舶/货盘/泊位三视图 Gantt + 空档船期面板。
// 数据源：/api/v1/scheduling/{blocks,open-positions,cargo-book,berth-windows}

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { DateInput } from "@/components/DateInput";
import { PageHeader } from "@/components/PageHeader";
import { StateView } from "@/components/StateView";
import { useToast } from "@/components/ToastProvider";
import { GanttBoard } from "@/components/gantt/GanttBoard";
import {
  DAY_MS,
  GanttBlock,
  GanttLaneData,
  GanttView,
  GanttZoom,
  startOfDay,
  toMs,
} from "@/components/gantt/types";
import { Panel } from "@/components/workspace/Panel";
import { WorkspaceShell } from "@/components/workspace/WorkspaceShell";
import { apiGet, apiPost, type Page } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

// —— API row shapes ——

type ScheduleBlockRow = {
  id: string;
  vessel_id: string;
  block_type: string;
  title: string;
  start_at: string | null;
  end_at: string | null;
  voyage_id: string | null;
  hard_conflict: boolean;
  meta?: Record<string, unknown> | null;
};

type VesselRow = { id: string; name: string; imo?: string | null };

type CargoRow = {
  id: string;
  cargo_no: string | null;
  commodity: string | null;
  qty: number | null;
  qty_unit: string | null;
  status: string | null;
  laycan_from: string | null;
  laycan_to: string | null;
  voyage_id: string | null;
  charter_id: string | null;
};

type BerthRow = {
  id: string;
  port_id: string | null;
  berth_name: string | null;
  start_at: string | null;
  end_at: string | null;
  voyage_id: string | null;
  status: string | null;
};

type OpenPositionRow = {
  vessel_id: string;
  vessel_name: string;
  imo: string | null;
  gaps: { start: string; end: string | null; days: number | null }[];
  open_days: number;
};

function toDateInput(ms: number): string {
  const d = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function dayStartFromInput(v: string, fallback: number): number {
  if (!v) return fallback;
  const t = new Date(`${v}T00:00:00`).getTime();
  return Number.isNaN(t) ? fallback : t;
}

async function fetchRows<T>(path: string): Promise<T[]> {
  try {
    const data = await apiGet(path);
    if (Array.isArray(data)) return data as T[];
    const page = data as Page<T> | { items?: T[] };
    if (page && Array.isArray((page as { items?: T[] }).items)) return (page as { items: T[] }).items;
    return [];
  } catch {
    return [];
  }
}

export default function SchedulePage() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();

  const [view, setView] = useState<GanttView>("vessel");
  const [zoom, setZoom] = useState<GanttZoom>("week");
  const [todayMs] = useState(() => Date.now());
  const [rangeFrom, setRangeFrom] = useState(() => toDateInput(startOfDay(Date.now()) - 7 * DAY_MS));
  const [rangeTo, setRangeTo] = useState(() => toDateInput(startOfDay(Date.now()) + 45 * DAY_MS));

  const [blocks, setBlocks] = useState<ScheduleBlockRow[]>([]);
  const [vessels, setVessels] = useState<VesselRow[]>([]);
  const [cargos, setCargos] = useState<CargoRow[]>([]);
  const [berths, setBerths] = useState<BerthRow[]>([]);
  const [positions, setPositions] = useState<OpenPositionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const rangeStart = useMemo(() => dayStartFromInput(rangeFrom, startOfDay(todayMs) - 7 * DAY_MS), [rangeFrom, todayMs]);
  const rangeEnd = useMemo(() => dayStartFromInput(rangeTo, startOfDay(todayMs) + 45 * DAY_MS) + DAY_MS - 1, [rangeTo, todayMs]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const qs = `date_from=${encodeURIComponent(new Date(rangeStart).toISOString())}&date_to=${encodeURIComponent(
        new Date(rangeEnd).toISOString(),
      )}`;
      const [b, v, c, bw, pos] = await Promise.all([
        fetchRows<ScheduleBlockRow>(`/api/v1/scheduling/blocks?${qs}&limit=500`),
        fetchRows<VesselRow>("/api/v1/vessels"),
        fetchRows<CargoRow>("/api/v1/scheduling/cargo-book"),
        fetchRows<BerthRow>("/api/v1/scheduling/berth-windows"),
        fetchRows<OpenPositionRow>(`/api/v1/scheduling/open-positions?${qs}`),
      ]);
      setBlocks(b);
      setVessels(v);
      setCargos(c);
      setBerths(bw);
      setPositions(pos);
    } catch (e: any) {
      setError(e?.message || t("common.failed", "加载失败"));
    } finally {
      setLoading(false);
    }
  }, [rangeStart, rangeEnd, t]);

  useEffect(() => {
    load();
  }, [load]);

  // —— lanes per view ——

  const lanes: GanttLaneData[] = useMemo(() => {
    if (view === "cargo") {
      return cargos
        .filter((c) => c.laycan_from && c.laycan_to)
        .map((c) => ({
          id: c.id,
          label: c.cargo_no || c.commodity || c.id.slice(0, 8),
          sublabel: [c.commodity, c.qty ? `${c.qty} ${c.qty_unit || ""}` : null, c.status].filter(Boolean).join(" · "),
          blocks: [
            {
              id: `cargo-${c.id}`,
              block_type: "cargo",
              start: c.laycan_from as string,
              end: c.laycan_to as string,
              label: t("sched.laycan", "Laycan"),
              voyage_id: c.voyage_id,
              meta: { charter_id: c.charter_id, cargo_id: c.id },
            },
          ],
        }));
    }

    if (view === "berth") {
      const byBerth = new Map<string, GanttLaneData>();
      for (const b of berths) {
        if (!b.start_at || !b.end_at) continue;
        const key = b.berth_name || b.port_id || b.id;
        let lane = byBerth.get(key);
        if (!lane) {
          lane = { id: key, label: b.berth_name || key.slice(0, 8), sublabel: undefined, blocks: [] };
          byBerth.set(key, lane);
        }
        lane.blocks.push({
          id: b.id,
          block_type: "berth",
          start: b.start_at,
          end: b.end_at,
          label: b.status || t("sched.berth_window", "泊位窗口"),
          voyage_id: b.voyage_id,
          meta: { port_id: b.port_id },
        });
      }
      return [...byBerth.values()];
    }

    // vessel view: lane per vessel, blocks from schedule
    const vesselNames = new Map(vessels.map((v) => [v.id, v]));
    const byVessel = new Map<string, GanttLaneData>();
    for (const v of vessels) {
      byVessel.set(v.id, {
        id: v.id,
        label: v.name,
        sublabel: v.imo || undefined,
        blocks: [],
      });
    }
    for (const b of blocks) {
      let lane = byVessel.get(b.vessel_id);
      if (!lane) {
        lane = {
          id: b.vessel_id,
          label: vesselNames.get(b.vessel_id)?.name || b.vessel_id.slice(0, 8),
          blocks: [],
        };
        byVessel.set(b.vessel_id, lane);
      }
      if (!b.start_at || !b.end_at) continue;
      lane.blocks.push({
        id: b.id,
        block_type: b.block_type || "voyage",
        start: b.start_at,
        end: b.end_at,
        label: b.title,
        hard_conflict: b.hard_conflict,
        voyage_id: b.voyage_id,
        meta: b.meta || undefined,
      });
    }
    return [...byVessel.values()].filter((l) => l.blocks.length > 0 || vessels.some((v) => v.id === l.id));
  }, [view, cargos, berths, blocks, vessels, t]);

  // —— block move / resize ——

  const persistWindow = useCallback(
    async (block: GanttBlock, start: string, end: string, mode: "move" | "resize") => {
      // cargo/berth blocks are derived rows — not movable via schedule API
      if (block.block_type === "cargo" || block.block_type === "berth") return;
      try {
        await apiPost(`/api/v1/scheduling/blocks/${block.id}/${mode}`, { start_at: start, end_at: end });
        await load();
      } catch (e: any) {
        const msg =
          e?.detail?.code === "SCHEDULE_CONFLICT"
            ? t("sched.conflict", "与其他排程块冲突，已拒绝")
            : e?.message || t("common.failed", "保存失败");
        toast.error(msg);
        await load();
      }
    },
    [load, toast, t],
  );

  const onBlockMove = useCallback((block: GanttBlock, start: string, end: string) => persistWindow(block, start, end, "move"), [persistWindow]);
  const onBlockResize = useCallback((block: GanttBlock, start: string, end: string) => persistWindow(block, start, end, "resize"), [persistWindow]);

  const onBlockClick = useCallback(
    (block: GanttBlock) => {
      const voyageId = block.voyage_id || (block.meta?.voyage_id as string | undefined) || null;
      const charterId = (block.meta?.charter_id as string | undefined) || null;
      if (voyageId) {
        router.push(`/operations/voyages/${voyageId}/workspace`);
      } else if (charterId) {
        router.push(`/charters/${charterId}`);
      } else if (block.block_type === "cargo") {
        router.push("/operations/cargo-book");
      }
    },
    [router],
  );

  return (
    <AppShell>
      <WorkspaceShell
        header={
          <PageHeader
            left={
              <div className="ws-crumb">
                <span className="muted">{t("sched.crumb", "运营 · 排程")}</span>
              </div>
            }
            title={t("sched.title", "集中排程")}
            subtitle={t("sched.sub", "船舶 / 货盘 / 泊位统一时间轴，拖动块可调整窗口")}
            actions={
              <button type="button" className="btn btn-ghost btn-sm" onClick={load}>
                {t("common.refresh", "刷新")}
              </button>
            }
          />
        }
      >
        <div className="sched-controls">
          <div className="sched-seg" role="group" aria-label={t("sched.view", "视图")}>
            <button type="button" className={view === "vessel" ? "active" : ""} onClick={() => setView("vessel")}>
              {t("sched.view_vessel", "船舶排程")}
            </button>
            <button type="button" className={view === "cargo" ? "active" : ""} onClick={() => setView("cargo")}>
              {t("sched.view_cargo", "货盘簿")}
            </button>
            <button type="button" className={view === "berth" ? "active" : ""} onClick={() => setView("berth")}>
              {t("sched.view_berth", "泊位排程")}
            </button>
          </div>
          <div className="sched-range">
            <label>
              {t("sched.from", "从")}
              <DateInput value={rangeFrom} onChange={setRangeFrom} />
            </label>
            <label>
              {t("sched.to", "到")}
              <DateInput value={rangeTo} onChange={setRangeTo} />
            </label>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => {
                setRangeFrom(toDateInput(startOfDay(Date.now()) - 7 * DAY_MS));
                setRangeTo(toDateInput(startOfDay(Date.now()) + 45 * DAY_MS));
              }}
            >
              {t("sched.reset_range", "重置")}
            </button>
          </div>
        </div>

        <div className="sched-layout">
          <div>
            <StateView loading={loading && !lanes.length} error={error} empty={false} onRetry={load}>
              <GanttBoard
                lanes={lanes}
                view={view}
                rangeStart={rangeStart}
                rangeEnd={rangeEnd}
                zoom={zoom}
                onZoomChange={setZoom}
                onBlockMove={onBlockMove}
                onBlockResize={onBlockResize}
                onBlockClick={onBlockClick}
                emptyText={t("sched.empty_lanes", "当前范围没有排程块")}
              />
            </StateView>
          </div>

          <Panel title={t("sched.open_positions", "空档船期")} collapsible>
            {loading && !positions.length ? (
              <p className="muted">{t("common.loading", "加载中…")}</p>
            ) : positions.length ? (
              <ul className="gantt-pos-list">
                {positions.map((p) => (
                  <li key={p.vessel_id}>
                    <strong>{p.vessel_name}</strong>
                    {p.imo ? <span className="muted"> · {p.imo}</span> : null}
                    <div className="muted" style={{ fontSize: 11 }}>
                      {t("sched.open_days", "可用 {n} 天", { n: p.open_days })}
                    </div>
                    <div>
                      {p.gaps.map((g, i) => (
                        <span className="gantt-pos-gap" key={`${p.vessel_id}-${i}`}>
                          {toDateInput(toMs(g.start))}
                          {g.end ? ` → ${toDateInput(toMs(g.end))}` : " → …"}
                          {g.days != null ? ` (${g.days}d)` : ""}
                        </span>
                      ))}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">{t("sched.no_positions", "暂无空档")}</p>
            )}
          </Panel>
        </div>
      </WorkspaceShell>
    </AppShell>
  );
}
