"use client";

// 排程看板（Phase 3）：泳道 + 时间轴 + 缩放控制。
// 布局：单滚动容器，左列 sticky 对齐（无 JS 滚动同步）。

import { useCallback, useMemo, useRef, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { GanttLane } from "./GanttLane";
import { TimeAxis } from "./TimeAxis";
import {
  DAY_MS,
  GanttBlock,
  GanttLaneData,
  GanttView,
  GanttZoom,
  startOfDay,
  ZOOM_PX_PER_DAY,
} from "./types";

export type GanttBoardProps = {
  lanes: GanttLaneData[];
  view: GanttView;
  rangeStart: number;
  rangeEnd: number;
  zoom?: GanttZoom;
  onZoomChange?: (zoom: GanttZoom) => void;
  onBlockMove?: (block: GanttBlock, start: string, end: string) => void | Promise<void>;
  onBlockResize?: (block: GanttBlock, start: string, end: string) => void | Promise<void>;
  onBlockClick?: (block: GanttBlock) => void;
  emptyText?: string;
  labelWidth?: number;
};

const ZOOMS: GanttZoom[] = ["day", "week", "month"];

export function GanttBoard({
  lanes,
  view,
  rangeStart,
  rangeEnd,
  zoom: zoomProp,
  onZoomChange,
  onBlockMove,
  onBlockResize,
  onBlockClick,
  emptyText,
  labelWidth,
}: GanttBoardProps) {
  const [innerZoom, setInnerZoom] = useState<GanttZoom>("week");
  const { t } = useI18n();
  const zoom = zoomProp ?? innerZoom;
  const ppd = ZOOM_PX_PER_DAY[zoom];
  const s = startOfDay(rangeStart);
  const days = Math.max(1, Math.ceil((rangeEnd - s) / DAY_MS));
  const width = days * ppd;

  const setZoom = useCallback(
    (z: GanttZoom) => {
      if (zoomProp === undefined) setInnerZoom(z);
      onZoomChange?.(z);
    },
    [zoomProp, onZoomChange],
  );

  const viewLabel = useMemo(() => {
    if (view === "cargo") return t("gantt.view_cargo", "Cargo");
    if (view === "berth") return t("gantt.view_berth", "Berth");
    return t("gantt.view_vessel", "Vessel");
  }, [view, t]);

  // —— 键盘路径（无障碍）——
  // 排程条本身已经可聚焦（role=button + tabIndex=0），Enter/Space 打开单据，
  // ←/→ 前后平移一天（见 GanttBar）。这里补上「在排程条之间移动焦点」的路径：
  //   ↑ / ↓   —— 上一条 / 下一条排程条（按看板顺序：泳道自上而下、条自左而右）
  //   Home / End —— 当前泳道的第一条 / 最后一条
  // 这样键盘用户不必逐个 Tab 穿过整个看板。
  const boardRef = useRef<HTMLDivElement>(null);

  const focusBar = useCallback((mode: "prev" | "next" | "first" | "last") => {
    const board = boardRef.current;
    if (!board) return;
    const all = Array.from(board.querySelectorAll<HTMLElement>(".gantt-bar"));
    if (!all.length) return;
    const active = document.activeElement as HTMLElement | null;
    const cur = active ? all.indexOf(active) : -1;

    if (mode === "first" || mode === "last") {
      // Home / End 限定在当前泳道内
      const lane = active?.closest(".gantt-row");
      const inLane = lane
        ? Array.from(lane.querySelectorAll<HTMLElement>(".gantt-bar"))
        : all;
      if (!inLane.length) return;
      inLane[mode === "first" ? 0 : inLane.length - 1].focus();
      return;
    }

    const next = mode === "next" ? cur + 1 : cur - 1;
    if (next < 0 || next >= all.length) {
      // 到边界时停在原处（不静默跳到别的泳道）
      if (cur >= 0) all[cur].focus();
      return;
    }
    all[next].focus();
  }, []);

  const onBoardKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      const target = e.target as HTMLElement | null;
      if (!target?.classList.contains("gantt-bar")) return;
      if (e.key === "ArrowUp") {
        e.preventDefault();
        focusBar("prev");
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        focusBar("next");
      } else if (e.key === "Home") {
        e.preventDefault();
        focusBar("first");
      } else if (e.key === "End") {
        e.preventDefault();
        focusBar("last");
      }
    },
    [focusBar],
  );

  return (
    <div
      className="gantt-board"
      ref={boardRef}
      onKeyDown={onBoardKeyDown}
      style={labelWidth ? ({ ["--gantt-label-w" as string]: `${labelWidth}px` } as React.CSSProperties) : undefined}
    >
      <div className="gantt-board-toolbar">
        <h3 className="gantt-board-title">{viewLabel}</h3>
        <div className="gantt-zoom" role="group" aria-label={t("gantt.zoom_group", { en: "Zoom", zh: "缩放" })}>
          {ZOOMS.map((z) => (
            <button key={z} type="button" className={z === zoom ? "active" : ""} onClick={() => setZoom(z)}>
              {z === "day" ? t("gantt.zoom_day", "Day") : z === "week" ? t("gantt.zoom_week", "Week") : t("gantt.zoom_month", "Month")}
            </button>
          ))}
        </div>
        <span className="muted">
          {new Date(s).toISOString().slice(0, 10)} → {new Date(rangeEnd).toISOString().slice(0, 10)}
        </span>
      </div>

      {!lanes.length ? (
        <div className="state-view">
          <span className="state-view-text muted">{emptyText || t("common.no_data", "No records")}</span>
        </div>
      ) : (
        <div className="gantt-board-grid">
          <div className="gantt-row">
            <div className="gantt-row-label" style={{ position: "sticky", left: 0, zIndex: 6, background: "#f2f7f9", height: 30, borderRight: "1px solid var(--border)" }} />
            <div className="gantt-row-time" style={{ width }}>
              <TimeAxis rangeStart={s} rangeEnd={rangeEnd} zoom={zoom} pxPerDay={ppd} />
            </div>
          </div>
          {lanes.map((lane) => (
            <div className="gantt-row" key={`${view}-${lane.id}`}>
              <div className="gantt-row-label">
                <div className="gantt-lane-label">
                  <strong title={lane.label}>{lane.label}</strong>
                  {lane.sublabel ? <span className="gantt-lane-sub">{lane.sublabel}</span> : null}
                </div>
              </div>
              <div className="gantt-row-time">
                <GanttLane
                  lane={lane}
                  rangeStart={s}
                  rangeEnd={rangeEnd}
                  zoom={zoom}
                  pxPerDay={ppd}
                  onBlockMove={onBlockMove}
                  onBlockResize={onBlockResize}
                  onBlockClick={onBlockClick}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
