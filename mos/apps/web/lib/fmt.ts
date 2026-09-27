// 3.6 共享金额/数值格式化
export function fmt(n: number | undefined | null): string {
  if (n === undefined || n === null) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}
