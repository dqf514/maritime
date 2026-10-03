// Excel 兼容的 TSV 剪贴板工具
// Excel 复制 → 网格粘贴 → 网格复制 → Excel 粘贴，往返无损

export function parseTSV(text: string): string[][] {
  return text
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .split("\n")
    .filter((line, i, arr) => !(i === arr.length - 1 && line === ""))
    .map((line) => line.split("\t"));
}

export function serializeTSV(matrix: string[][]): string {
  return matrix.map((row) => row.join("\t")).join("\n");
}

/** 从单元格矩阵复制到剪贴板 */
export async function copyToClipboard(matrix: string[][]): Promise<void> {
  const text = serializeTSV(matrix);
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // fallback: execCommand
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
  }
}

/** 从剪贴板读取 */
export async function readFromClipboard(): Promise<string[][]> {
  try {
    const text = await navigator.clipboard.readText();
    return parseTSV(text);
  } catch {
    return [];
  }
}

/** 类型强制转换 — 粘贴时将字符串转为目标类型 */
export function coerceValue(raw: string, targetType: string | undefined): unknown {
  if (raw === "") return null;
  if (targetType === "number") {
    const n = Number(raw.replace(/,/g, ""));
    return isNaN(n) ? raw : n;
  }
  if (targetType === "checkbox") {
    return raw.toLowerCase() === "true" || raw === "1" || raw.toLowerCase() === "yes";
  }
  return raw;
}

/** 填充序列 — 智能识别数字递增/日期递增/复制 */
export function fillSeries(source: unknown[], count: number, type?: string): unknown[] {
  if (source.length === 0) return Array(count).fill(null);
  if (source.length === 1) return Array(count).fill(source[0]);

  // 数字序列
  if (type === "number" && source.length >= 2) {
    const nums = source.map(Number);
    if (nums.every((n) => !isNaN(n))) {
      const step = nums[nums.length - 1] - nums[nums.length - 2];
      return Array.from({ length: count }, (_, i) => nums[nums.length - 1] + step * (i + 1));
    }
  }

  // 日期序列
  if (type === "date" && source.length >= 2) {
    const d1 = new Date(source[0] as string).getTime();
    const d2 = new Date(source[1] as string).getTime();
    if (!isNaN(d1) && !isNaN(d2)) {
      const step = d2 - d1;
      return Array.from({ length: count }, (_, i) => {
        const d = new Date(d2 + step * (i + 1));
        return d.toISOString().slice(0, 10);
      });
    }
  }

  // 循环复制
  return Array.from({ length: count }, (_, i) => source[i % source.length]);
}
