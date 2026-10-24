// D2 时区策略：存储统一 UTC（ISO），展示按港口/租户本地时区；Intl 原生 DST 感知。
// 未给 tz 时按 UTC 展示（避免浏览器时区差异导致同屏不一致）。

/**
 * 解析后端时间戳。
 *
 * 平台约定（后端写库与 API 序列化均以 UTC 为准）：**不带时区偏移的 ISO 串即 UTC**。
 * JS 原生 `new Date("2026-10-24T03:00:00")` 会按浏览器本地时区解析，导致同一时刻
 * 在不同时区的客户端上显示相差一个 UTC 偏移（本项目历史缺陷：相差 8 小时）。
 * 这里统一补 `Z` 后再解析，使「naive = UTC」成为真正的全局不变量。
 */
export function parseUtc(
  value: string | number | Date | null | undefined,
): Date | null {
  if (value === null || value === undefined || value === "") return null;
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  if (typeof value === "number") {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  let s = String(value).trim();
  if (!s) return null;
  // "2026-10-24 03:00:00" → "2026-10-24T03:00:00"（SQLite/PG 常见分隔符）
  s = s.replace(/^(\d{4}-\d{2}-\d{2})\s+/, "$1T");
  // 无偏移量 → 视作 UTC
  if (!/(?:Z|[+-]\d{2}:?\d{2})$/i.test(s)) s += "Z";
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** 按时区格式化时间；无效输入原样返回，无效 tz 回退 UTC。 */
export function formatInTz(
  value: string | number | Date | null | undefined,
  tz?: string | null,
  opts?: Intl.DateTimeFormatOptions,
  locale?: string | null,
): string {
  if (value == null || value === "") return "—";
  const d = parseUtc(value);
  if (!d) return String(value);
  const base: Intl.DateTimeFormatOptions = {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    ...(opts ?? {}),
    timeZone: tz || "UTC",
  };
  try {
    return new Intl.DateTimeFormat(locale || undefined, base).format(d);
  } catch {
    return d.toISOString().slice(0, 16).replace("T", " ");
  }
}

/**
 * 仅日期部分（MM-DD / 年月日），按时区与语言格式化。
 * 需要去掉年份时传 `withYear=false`，或用 `formatInTz(..., { year: undefined })`。
 */
export function formatDateInTz(
  value: string | number | Date | null | undefined,
  tz?: string | null,
  locale?: string | null,
  withYear = false,
): string {
  if (value == null || value === "") return "—";
  const d = parseUtc(value);
  if (!d) return String(value);
  const base: Intl.DateTimeFormatOptions = withYear
    ? { year: "numeric", month: "2-digit", day: "2-digit", timeZone: tz || "UTC" }
    : { month: "2-digit", day: "2-digit", timeZone: tz || "UTC" };
  try {
    return new Intl.DateTimeFormat(locale || undefined, base).format(d);
  } catch {
    return d.toISOString().slice(0, 10);
  }
}

/**
 * UTC 日序号（floor 到 UTC 00:00 的天数）。
 *
 * 用于「逾期 N 天 / 今天到期」这类按自然日比较的场景：后端存的 naive 串是 UTC，
 * 因此日界也必须按 UTC 切，否则浏览器在非 UTC 时区会把跨日的时刻算错一天。
 */
export function utcDayNumber(
  value: string | number | Date | null | undefined,
): number | null {
  const d = parseUtc(value);
  if (!d) return null;
  const day = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
  return Math.floor(day / 86_400_000);
}

/** 与「今天」相差的自然日数（UTC 日界）：正数=未来，0=今天，负数=已过期。 */
export function utcDayDiff(
  value: string | number | Date | null | undefined,
  now: Date = new Date(),
): number | null {
  const d = utcDayNumber(value);
  if (d === null) return null;
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return d - Math.floor(today / 86_400_000);
}

/**
 * ISO → datetime-local 输入值（UTC 墙钟，YYYY-MM-DDTHH:mm）。
 *
 * 全站 datetime 输入框统一用 **UTC 墙钟**：后端存的是 UTC naive 串，
 * 输入框也显示同一串，用户改完回传即可原样落库；用浏览器本地时区解释会
 * 在保存时整体偏移一个 UTC 偏移（非 UTC 时区用户必踩）。
 */
export function toUtcInput(
  value: string | number | Date | null | undefined,
): string {
  const d = parseUtc(value);
  if (!d) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

/**
 * datetime-local 输入值（UTC 墙钟）→ 后端 ISO 串。
 * 无效输入返回 null；空串返回 null。
 */
export function fromUtcInput(
  value: string | null | undefined,
): string | null {
  if (!value) return null;
  const d = parseUtc(value);
  return d ? d.toISOString() : null;
}

/** UTC 墙钟短串："YYYY-MM-DD HH:MM"（表格窄列用）。 */
export function formatUtcShort(
  value: string | number | Date | null | undefined,
  withSeconds = false,
): string {
  const d = parseUtc(value);
  if (!d) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  const base = `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
  return withSeconds ? `${base}:${pad(d.getUTCSeconds())}` : base;
}

/** 时区短标签："GMT+8" / "GMT-5"；无效/缺失返回原值或 ""。 */
export function tzShort(tz?: string | null): string {
  if (!tz) return "";
  try {
    const parts = new Intl.DateTimeFormat("en", {
      timeZone: tz,
      timeZoneName: "shortOffset",
    }).formatToParts(new Date());
    return parts.find((p) => p.type === "timeZoneName")?.value ?? tz;
  } catch {
    return tz;
  }
}

/** hover 全精度时间戳（D1）：本地化显示 + 时区标签 + 原始 ISO。 */
export function fullTimestamp(value: string | number | Date | null | undefined, tz?: string | null): string {
  if (value == null || value === "") return "";
  const d = parseUtc(value);
  if (!d) return String(value);
  const local = formatInTz(d, tz);
  const label = tzShort(tz);
  return `${local}${label ? ` (${label})` : ""} · ${d.toISOString()}`;
}
