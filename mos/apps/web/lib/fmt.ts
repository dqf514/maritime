// 3.6 共享金额/数值格式化 — IMOS 约定：显示 ≤6 位小数，hover 出全精度（后端存 15 位）
export function fmt(n: number | undefined | null, digits = 2): string {
  if (n === undefined || n === null) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

/** 显示精度 6 位（油耗/坐标/汇率等专业数值列） */
export function fmt6(n: number | undefined | null): string {
  return fmt(n, 6);
}

/** 完整精度字符串（hover tooltip 用） */
export function fmtFull(n: number | undefined | null): string {
  if (n === undefined || n === null) return "—";
  return String(n);
}

/** 金额：2 位小数 + 千分位 */
export function fmtMoney(n: number | undefined | null): string {
  return fmt(n, 2);
}
