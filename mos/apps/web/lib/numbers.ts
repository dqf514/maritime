// 数值输入的统一解析规则（前端数值正确性 · 审计 P1-24）。
//
// 问题背景：
//   `Number(x) || 0` / `Number(x) || 1` 会把「用户输入的 0」静默改写成 0/1，
//   把「空输入」和「非法输入（NaN）」统统降级成一个看起来合法的数字；
//   `value === null || value === "" ? 0 : Number(value)` 在垃圾输入时产出 NaN，
//   带着 NaN 发给后端就是「静默地说谎」。
//
// 这里的统一约定：
//   - 用户输入的 0 必须原样保留为 0；
//   - 非法输入（NaN / Infinity / 非数字）返回 null —— 由调用方给出**可见的**校验提示，
//     绝不静默替换成别的数字；
//   - 1 起始的序号：0 是非法值（不是「缺省成 1」），返回 null 交由调用方报错。

/** 解析输入为有限数值；空串 / null / undefined / 非法值返回 null。 */
export function toFiniteNumber(v: unknown): number | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "boolean") return null;
  if (typeof v === "string") {
    const s = v.trim();
    if (s === "") return null;
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/**
 * 解析为 ≥ 1 的整数（1 起始的序号，如航次挂靠序号）。
 * 0 与负数是**非法**值，返回 null（不是静默补 1）。
 */
export function toPositiveInt(v: unknown): number | null {
  const n = toFiniteNumber(v);
  if (n === null) return null;
  if (!Number.isInteger(n)) return null;
  return n >= 1 ? n : null;
}

/** 解析为 ≥ 0 的整数（0 合法 —— 例如 sort_order）。 */
export function toNonNegativeInt(v: unknown): number | null {
  const n = toFiniteNumber(v);
  if (n === null) return null;
  if (!Number.isInteger(n)) return null;
  return n >= 0 ? n : null;
}

/**
 * 解析 URL 查询串里的页码（1 起始）。
 * `?page=abc` / `?page=0` / `?page=-3` / `?page=1.5` 一律回落到第 1 页，
 * 绝不产出 NaN（原 `Math.max(1, Number(query.page) || 1)` 在 `?page=abc` 时
 * 会先算成 NaN 再被 `|| 1` 兜住，语义正确但依赖隐式 falsy 转换）。
 */
export function toPageNumber(v: unknown): number {
  const n = toFiniteNumber(v);
  if (n === null || !Number.isInteger(n) || n < 1) return 1;
  return n;
}

/**
 * 本位币金额预览 = 金额 × 汇率。
 *
 * 汇率留空按 1 处理（这是「未指定汇率」的正常含义）；汇率是垃圾输入 / 0 / 负数时
 * 返回 null —— **不显示预览**，绝不静默替换成 1（那会让用户看到一个假的换算结果）。
 */
export function baseAmountPreview(amountRaw: unknown, fxRaw: unknown): number | null {
  const amount = toFiniteNumber(amountRaw);
  if (amount === null) return null;
  const fxText = typeof fxRaw === "string" ? fxRaw.trim() : fxRaw;
  if (fxText === "" || fxText === null || fxText === undefined) return amount;
  const fx = toFiniteNumber(fxText);
  if (fx === null || fx <= 0) return null;
  return amount * fx;
}

/**
 * 数组最大值的 O(n) 版本 —— 取代 `Math.max(...arr)`。
 * `Math.max(...arr)` 在超大数组上会因参数个数超限抛 RangeError（栈溢出）。
 * 空数组返回 `fallback`。
 */export function maxOf<T>(items: readonly T[], pick: (item: T) => number, fallback = 0): number {
  let out = fallback;
  for (const item of items) {
    const v = pick(item);
    if (Number.isFinite(v) && v > out) out = v;
  }
  return out;
}

/** 数组最小值的 O(n) 版本。空数组返回 `fallback`。 */
export function minOf<T>(items: readonly T[], pick: (item: T) => number, fallback = 0): number {
  let out = fallback;
  let seen = false;
  for (const item of items) {
    const v = pick(item);
    if (!Number.isFinite(v)) continue;
    if (!seen || v < out) {
      out = v;
      seen = true;
    }
  }
  return out;
}
