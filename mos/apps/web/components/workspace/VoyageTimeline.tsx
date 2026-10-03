"use client";

// 航次时间轴（Phase 2）：港口挂靠 + SOF/正午事件，映射到水平时间轴。
// 纯 CSS 条带（绝对定位百分比），随容器横向滚动。

import { useMemo, useState } from "react";

export type TimelinePortCall = {
  seq: number;
  port_name: string;
  eta?: string | null;
  etd?: string | null;
  ata?: string | null;
  atd?: string | null;
  purpose?: string | null;
};

export type TimelineEvent = {
  type: string;
  at: string;
  label: string;
};

export type VoyageTimelineProps = {
  portCalls: TimelinePortCall[];
  events: TimelineEvent[];
  /** 时间轴宽度（px），默认按天数自适应，最小 720 */
  width?: number;
};

function ts(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d.getTime();
}

function fmtDay(t: number) {
  const d = new Date(t);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

function fmtFull(t: number) {
  const d = new Date(t);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const DAY = 86400000;

export function VoyageTimeline({ portCalls, events, width }: VoyageTimelineProps) {
  const [now] = useState(() => Date.now());
  const model = useMemo(() => {
    const times: number[] = [];
    for (const pc of portCalls) {
      for (const v of [pc.eta, pc.etd, pc.ata, pc.atd]) {
        const t = ts(v);
        if (t !== null) times.push(t);
      }
    }
    for (const ev of events) {
      const t = ts(ev.at);
      if (t !== null) times.push(t);
    }
    if (!times.length) return null;

    const min = Math.min(...times);
    const max = Math.max(...times);
    const pad = Math.max((max - min) * 0.04, DAY * 0.5);
    const t0 = min - pad;
    const t1 = max + pad;
    const span = t1 - t0;
    const pct = (t: number) => ((t - t0) / span) * 100;

    // 日期刻度：按跨度选日/周粒度
    const days = span / DAY;
    const stepDays = days <= 14 ? 1 : days <= 60 ? 7 : 14;
    const ticks: number[] = [];
    const first = new Date(t0);
    first.setHours(0, 0, 0, 0);
    for (let t = first.getTime(); t <= t1; t += stepDays * DAY) {
      if (t >= t0) ticks.push(t);
    }

    return {
      t0,
      t1,
      pct,
      ticks,
      showToday: now >= t0 && now <= t1,
      now,
      width: Math.max(width ?? 0, days * 34, 720),
      ports: portCalls.map((pc, i) => {
        const arrive = ts(pc.ata) ?? ts(pc.eta);
        const depart = ts(pc.atd) ?? ts(pc.etd);
        return {
          seq: pc.seq,
          name: pc.port_name,
          purpose: pc.purpose || "",
          arrive,
          depart,
          x: arrive !== null ? pct(arrive) : depart !== null ? pct(depart) : 50,
          delayed: ts(pc.ata) !== null && ts(pc.eta) !== null && (ts(pc.ata) as number) > (ts(pc.eta) as number),
          side: i % 2 === 0 ? "above" : "below",
        };
      }),
      evs: events.map((ev) => {
        const t = ts(ev.at);
        return {
          type: ev.type,
          label: ev.label,
          at: t,
          x: t !== null ? pct(t) : 50,
          alt: ev.type.toLowerCase().includes("noon") || ev.type.toLowerCase().includes("sof"),
        };
      }),
    };
  }, [portCalls, events, width, now]);

  if (!model) {
    return <p className="muted">{""}</p>;
  }

  return (
    <div className="ws-timeline">
      <div className="ws-timeline-track" style={{ width: model.width }}>
        <div className="ws-timeline-axis" />
        {model.ticks.map((t) => (
          <div key={t}>
            <div className="ws-tl-tick" style={{ left: `${model.pct(t)}%` }} />
            <div className="ws-tl-tick-label" style={{ left: `${model.pct(t)}%` }}>
              {fmtDay(t)}
            </div>
          </div>
        ))}
        {model.showToday ? (
          <div className="ws-tl-today" style={{ left: `${model.pct(model.now)}%` }}>
            <span>now</span>
          </div>
        ) : null}
        {model.ports.map((p, i) => (
          <div key={`${p.seq}-${i}`}>
            <div
              className={`ws-tl-port ${p.purpose === "load" ? "port-load" : p.purpose === "disch" ? "port-disch" : "port-pass"}`}
              style={{ left: `${p.x}%` }}
              title={p.arrive ? fmtFull(p.arrive) : p.name}
            />
            <div className={`ws-tl-port-label ${p.side}`} style={{ left: `${p.x}%` }}>
              {p.seq}. {p.name}
              <small>
                {p.arrive ? fmtDay(p.arrive) : "—"}
                {p.delayed ? " ⚠" : ""}
              </small>
            </div>
          </div>
        ))}
        {model.evs.map((ev, i) => (
          <div key={`${ev.type}-${i}`}>
            <div className="ws-tl-event" style={{ left: `${ev.x}%` }} title={`${ev.type} ${ev.at ? fmtFull(ev.at) : ""}`} />
            <div className={`ws-tl-event-label${ev.alt ? " alt" : ""}`} style={{ left: `${ev.x}%` }}>
              {ev.label}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
