// D2 时区策略：存储统一 UTC（ISO），展示按港口/租户本地时区；Intl 原生 DST 感知。
// 未给 tz 时按 UTC 展示（避免浏览器时区差异导致同屏不一致）。

/** 按时区格式化时间；无效输入原样返回，无效 tz 回退 UTC。 */
export function formatInTz(
  value: string | number | Date | null | undefined,
  tz?: string | null,
  opts?: Intl.DateTimeFormatOptions,
): string {
  if (value == null || value === "") return "—";
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
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
    return new Intl.DateTimeFormat(undefined, base).format(d);
  } catch {
    return d.toISOString().slice(0, 16).replace("T", " ");
  }
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
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  const local = formatInTz(d, tz);
  const label = tzShort(tz);
  return `${local}${label ? ` (${label})` : ""} · ${d.toISOString()}`;
}
