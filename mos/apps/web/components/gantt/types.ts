// Gantt 共享类型与时间工具（Phase 3）

import { parseUtc } from "@/lib/datetime";

export type GanttBlock = {
  id: string;
  block_type: string;
  /** ISO 时间 */
  start: string;
  end: string;
  label: string;
  hard_conflict?: boolean;
  voyage_id?: string | null;
  meta?: Record<string, unknown>;
};

export type GanttLaneData = {
  id: string;
  label: string;
  /** 副标题（如 IMO / 泊位号） */
  sublabel?: string;
  blocks: GanttBlock[];
};

export type GanttView = "vessel" | "cargo" | "berth";
export type GanttZoom = "day" | "week" | "month";

export const DAY_MS = 86400000;
export const HOUR_MS = 3600000;

export const ZOOM_PX_PER_DAY: Record<GanttZoom, number> = {
  day: 96,
  week: 26,
  month: 9,
};

export function toMs(iso: string | number | Date): number {
  if (typeof iso === "number") return iso;
  // 后端 ISO 串无偏移量即 UTC（parseUtc 补 Z），避免按浏览器本地时区解析导致整体偏移。
  const d = parseUtc(iso);
  return d ? d.getTime() : 0;
}

export function toIso(ms: number): string {
  return new Date(ms).toISOString();
}

/** 起始日 00:00（本地时区） */
export function startOfDay(ms: number): number {
  const d = new Date(ms);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

export function endOfDay(ms: number): number {
  return startOfDay(ms) + DAY_MS - 1;
}

export function snapHour(ms: number): number {
  return Math.round(ms / HOUR_MS) * HOUR_MS;
}

export function fmtDayLabel(ms: number): string {
  const d = new Date(ms);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function fmtMonthLabel(ms: number): string {
  const d = new Date(ms);
  return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, "0")}`;
}
