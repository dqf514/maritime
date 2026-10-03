"use client";

// 泳道（Phase 3）：船舶/货盘/泊位一行，带时间网格背景 + 排程条。

import { GanttBar } from "./GanttBar";
import { DAY_MS, GanttBlock, GanttLaneData, GanttZoom, startOfDay, ZOOM_PX_PER_DAY } from "./types";

export type GanttLaneProps = {
  lane: GanttLaneData;
  rangeStart: number;
  rangeEnd: number;
  zoom: GanttZoom;
  pxPerDay?: number;
  onBlockMove?: (block: GanttBlock, start: string, end: string) => void;
  onBlockResize?: (block: GanttBlock, start: string, end: string) => void;
  onBlockClick?: (block: GanttBlock) => void;
};

function ts(iso: string): number {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? 0 : d.getTime();
}

export function GanttLane({
  lane,
  rangeStart,
  rangeEnd,
  zoom,
  pxPerDay,
  onBlockMove,
  onBlockResize,
  onBlockClick,
}: GanttLaneProps) {
  const ppd = pxPerDay ?? ZOOM_PX_PER_DAY[zoom];
  const s = startOfDay(rangeStart);
  const days = Math.max(1, Math.ceil((rangeEnd - s) / DAY_MS));
  const width = days * ppd;

  const gridlines: { x: number; cls: string }[] = [];
  const weekends: { x: number; w: number }[] = [];
  const cursor = new Date(s);
  cursor.setHours(0, 0, 0, 0);
  for (let i = 0; i <= days; i++) {
    const x = i * ppd;
    const dow = cursor.getDay();
    const dom = cursor.getDate();
    if (dow === 0 || dow === 6) weekends.push({ x, w: ppd });
    gridlines.push({ x, cls: dom === 1 ? "month" : dow === 1 ? "week" : "" });
    cursor.setDate(cursor.getDate() + 1);
  }

  return (
    <div className="gantt-lane" style={{ width }}>
      <div className="gantt-lane-grid">
        {weekends.map((w, i) => (
          <div key={`we-${i}`} className="gantt-weekend" style={{ left: w.x, width: w.w }} />
        ))}
        {gridlines.map((g, i) => (
          <div key={`g-${i}`} className={`gantt-gridline ${g.cls}`} style={{ left: g.x }} />
        ))}
      </div>
      <div className="gantt-lane-blocks">
        {lane.blocks.map((block) => {
          const bStart = ts(block.start);
          const bEnd = ts(block.end);
          const x = ((bStart - s) / DAY_MS) * ppd;
          const widthPx = Math.max(6, ((bEnd - bStart) / DAY_MS) * ppd);
          return (
            <GanttBar
              key={block.id}
              block={block}
              x={x}
              width={widthPx}
              pxPerDay={ppd}
              onMove={onBlockMove}
              onResize={onBlockResize}
              onClick={onBlockClick}
            />
          );
        })}
      </div>
    </div>
  );
}
