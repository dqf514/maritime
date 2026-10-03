"use client";

// 排程条（Phase 3）：可拖动/可缩放的时间块（ScheduleBlock）。
// 拖动 = 平移窗口；左右手柄 = 调整起止；点击（未拖动）= 打开关联单据。

import { useCallback, useRef, useState } from "react";
import { DAY_MS, GanttBlock, snapHour, toMs, ZOOM_PX_PER_DAY } from "./types";

export type GanttBarProps = {
  block: GanttBlock;
  x: number;
  width: number;
  pxPerDay?: number;
  onMove?: (block: GanttBlock, start: string, end: string) => void;
  onResize?: (block: GanttBlock, start: string, end: string) => void;
  onClick?: (block: GanttBlock) => void;
};

type DragState = {
  mode: "move" | "start" | "end";
  originX: number;
  startMs: number;
  endMs: number;
};

export function GanttBar({ block, x, width, pxPerDay = ZOOM_PX_PER_DAY.week, onMove, onResize, onClick }: GanttBarProps) {
  const [drag, setDrag] = useState<DragState | null>(null);
  const [preview, setPreview] = useState<{ x: number; width: number } | null>(null);
  const movedRef = useRef(false);

  const pxToMs = useCallback((px: number) => (px / pxPerDay) * DAY_MS, [pxPerDay]);

  const beginDrag = useCallback(
    (e: React.PointerEvent, mode: DragState["mode"]) => {
      if (!onMove && !onResize) return;
      e.preventDefault();
      e.stopPropagation();
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      movedRef.current = false;
      setDrag({
        mode,
        originX: e.clientX,
        startMs: toMs(block.start),
        endMs: toMs(block.end),
      });
      setPreview({ x, width });
    },
    [block.start, block.end, onMove, onResize, x, width],
  );

  const handleMove = useCallback(
    (e: React.PointerEvent) => {
      if (!drag) return;
      const dx = e.clientX - drag.originX;
      if (Math.abs(dx) > 2) movedRef.current = true;
      const deltaMs = snapHour(pxToMs(dx));

      if (drag.mode === "move") {
        const start = snapHour(drag.startMs + deltaMs);
        const dur = drag.endMs - drag.startMs;
        setPreview({
          x: x + dx,
          width,
        });
        (e.currentTarget as HTMLElement).dataset.pendingStart = String(start);
        (e.currentTarget as HTMLElement).dataset.pendingEnd = String(start + dur);
      } else if (drag.mode === "start") {
        const start = snapHour(Math.min(drag.startMs + deltaMs, drag.endMs - 3600000));
        setPreview({
          x: x + ((start - drag.startMs) / DAY_MS) * pxPerDay,
          width: Math.max(6, width - ((start - drag.startMs) / DAY_MS) * pxPerDay),
        });
        (e.currentTarget as HTMLElement).dataset.pendingStart = String(start);
        (e.currentTarget as HTMLElement).dataset.pendingEnd = String(drag.endMs);
      } else {
        const end = snapHour(Math.max(drag.endMs + deltaMs, drag.startMs + 3600000));
        setPreview({
          x,
          width: Math.max(6, width + ((end - drag.endMs) / DAY_MS) * pxPerDay),
        });
        (e.currentTarget as HTMLElement).dataset.pendingStart = String(drag.startMs);
        (e.currentTarget as HTMLElement).dataset.pendingEnd = String(end);
      }
    },
    [drag, pxToMs, x, width, pxPerDay],
  );

  const endDrag = useCallback(
    (e: React.PointerEvent) => {
      if (!drag) return;
      const el = e.currentTarget as HTMLElement;
      const pendingStart = el.dataset.pendingStart;
      const pendingEnd = el.dataset.pendingEnd;
      delete el.dataset.pendingStart;
      delete el.dataset.pendingEnd;

      const wasMoved = movedRef.current;
      setDrag(null);
      setPreview(null);

      if (!wasMoved || pendingStart === undefined || pendingEnd === undefined) return;
      const start = new Date(Number(pendingStart)).toISOString();
      const end = new Date(Number(pendingEnd)).toISOString();
      if (drag.mode === "move") onMove?.(block, start, end);
      else onResize?.(block, start, end);
    },
    [drag, block, onMove, onResize],
  );

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      if (movedRef.current) return;
      onClick?.(block);
    },
    [block, onClick],
  );

  const left = preview ? preview.x : x;
  const w = preview ? preview.width : width;
  const cls = [
    "gantt-bar",
    `block-${block.block_type || "voyage"}`,
    block.hard_conflict ? "hard_conflict" : "",
    drag ? "dragging" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      className={cls}
      style={{ left, width: Math.max(6, w) }}
      title={`${block.label}\n${block.start} → ${block.end}`}
      onClick={handleClick}
      onPointerDown={(e) => beginDrag(e, "move")}
      onPointerMove={handleMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
    >
      {onResize ? (
        <>
          <span className="gantt-bar-handle left" onPointerDown={(e) => beginDrag(e, "start")} />
          <span className="gantt-bar-handle right" onPointerDown={(e) => beginDrag(e, "end")} />
        </>
      ) : null}
      <span className="gantt-bar-label">{block.label}</span>
    </div>
  );
}
