"use client";

// 时间轴（Phase 3）：日/周/月三级缩放刻度 + 今日标记。
// 由 GanttBoard 渲染在时间列顶部，宽度 = rangeDays * pxPerDay。

import { useMemo, useState } from "react";
import { DAY_MS, fmtDayLabel, fmtMonthLabel, GanttZoom, startOfDay, ZOOM_PX_PER_DAY } from "./types";

export type TimeAxisProps = {
  rangeStart: number;
  rangeEnd: number;
  zoom: GanttZoom;
  pxPerDay?: number;
};

type Tick = { x: number; label: string; major: boolean; monthStart: boolean };

function tickKey(t: Tick) {
  return `${t.x}-${t.label}`;
}

export function TimeAxis({ rangeStart, rangeEnd, zoom, pxPerDay }: TimeAxisProps) {
  const [now] = useState(() => Date.now());
  const ppd = pxPerDay ?? ZOOM_PX_PER_DAY[zoom];

  const { ticks, width, todayX } = useMemo(() => {
    const s = startOfDay(rangeStart);
    const e = rangeEnd;
    const days = Math.max(1, Math.ceil((e - s) / DAY_MS));
    const w = days * ppd;
    const out: Tick[] = [];

    const cursor = new Date(s);
    cursor.setHours(0, 0, 0, 0);
    for (let i = 0; i <= days; i++) {
      const t = cursor.getTime();
      const x = ((t - s) / DAY_MS) * ppd;
      const dow = cursor.getDay();
      const dom = cursor.getDate();

      if (zoom === "day") {
        out.push({ x, label: fmtDayLabel(t), major: dow === 1 || dom === 1, monthStart: dom === 1 });
      } else if (zoom === "week") {
        if (dow === 1 || i === 0) out.push({ x, label: fmtDayLabel(t), major: true, monthStart: dom === 1 });
      } else {
        if (dom === 1 || i === 0) out.push({ x, label: fmtMonthLabel(t), major: true, monthStart: dom === 1 });
      }
      cursor.setDate(cursor.getDate() + 1);
    }

    return {
      ticks: out,
      width: w,
      todayX: now >= s && now <= e ? ((now - s) / DAY_MS) * ppd : null,
    };
  }, [rangeStart, rangeEnd, zoom, ppd, now]);

  return (
    <div className="gantt-axis">
      <div className="gantt-axis-canvas" style={{ width }}>
        {ticks.map((t) => (
          <div
            key={tickKey(t)}
            className={`gantt-axis-tick${t.major ? " major" : ""}${t.monthStart ? " month-start" : ""}`}
            style={{ left: t.x }}
          >
            {t.label}
          </div>
        ))}
        {todayX !== null ? (
          <div className="gantt-today-line" style={{ left: todayX }}>
            <span>▶</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
