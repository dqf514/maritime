"use client";

// 排程看板（Phase 3）：泳道 + 时间轴 + 缩放控制。
// 布局：单滚动容器，左列 sticky 对齐（无 JS 滚动同步）。

import { useCallback, useMemo, useState } from "react";
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
    if (view === "cargo") return t("gantt.view_cargo", "货盘");
    if (view === "berth") return t("gantt.view_berth", "泊位");
    return t("gantt.view_vessel", "船舶");
  }, [view, t]);

  return (
    <div className="gantt-board" style={labelWidth ? ({ ["--gantt-label-w" as string]: `${labelWidth}px` } as React.CSSProperties) : undefined}>
      <div className="gantt-board-toolbar">
        <h3 className="gantt-board-title">{viewLabel}</h3>
        <div className="gantt-zoom" role="group" aria-label="zoom">
          {ZOOMS.map((z) => (
            <button key={z} type="button" className={z === zoom ? "active" : ""} onClick={() => setZoom(z)}>
              {z === "day" ? t("gantt.zoom_day", "日") : z === "week" ? t("gantt.zoom_week", "周") : t("gantt.zoom_month", "月")}
            </button>
          ))}
        </div>
        <span className="muted">
          {new Date(s).toISOString().slice(0, 10)} → {new Date(rangeEnd).toISOString().slice(0, 10)}
        </span>
      </div>

      {!lanes.length ? (
        <div className="state-view">
          <span className="state-view-text muted">{emptyText || "No records"}</span>
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
