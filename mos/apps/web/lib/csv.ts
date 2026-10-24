// U6 批量导出：客户端 CSV 下载（选中行 → CSV 文件）。

/** 解析 CSV 文本为二维数组（支持引号转义 / CRLF / BOM，跳过空行）。 */
export function parseCsv(text: string): string[][] {
  const src = text.replace(/^\uFEFF/, "");
  const rows: string[][] = [];
  let row: string[] = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (inQuotes) {
      if (ch === '"') {
        if (src[i + 1] === '"') {
          cur += '"';
          i++;
        } else inQuotes = false;
      } else cur += ch;
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      row.push(cur);
      cur = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && src[i + 1] === "\n") i++;
      row.push(cur);
      cur = "";
      rows.push(row);
      row = [];
    } else cur += ch;
  }
  if (cur !== "" || row.length) {
    row.push(cur);
    rows.push(row);
  }
  return rows.filter((r) => r.some((c) => c.trim() !== ""));
}

/** CSV 公式注入防护（IMOS 同款）：= + @ \t \r 开头，或"非纯数字的 -"开头 → 加撇号 */
function guardFormula(s: string): string {
  if (/^[=+@\t\r]/.test(s)) return `'${s}`;
  if (s.startsWith("-") && !/^-\d+(\.\d+)?$/.test(s)) return `'${s}`;
  return s;
}

type DownloadCsvOpts = {
  /** \u7A7A\u8868\u5B88\u536B\uFF1A\u7B5B\u9009\u540E 0 \u884C\u65F6\u7684\u786E\u8BA4\u6587\u6848\uFF08\u5DF2\u7FFB\u8BD1\uFF09\uFF1B\u53D6\u6D88\u5219\u4E0D\u5BFC\u51FA\uFF08D6\uFF1A\u5BFC\u51FA\u4E0E\u7B5B\u9009\u5F3A\u7ED1\u5B9A\uFF09 */
  emptyGuard?: string;
};

/** D6\uFF1A\u6587\u4EF6\u540D\u9644\u5E26\u65F6\u95F4\u6233\uFF08\u5B9E\u4F53_YYYYMMDD-HHMM.csv\uFF09\uFF0C\u4FBF\u4E8E\u8FFD\u6EAF\u5BFC\u51FA\u65F6\u70B9 */
function stampFilename(filename: string): string {
  const base = filename.endsWith(".csv") ? filename.slice(0, -4) : filename;
  if (/\d{8}[-_]?\d{4}/.test(base)) return `${base}.csv`; // \u8C03\u7528\u65B9\u5DF2\u5E26\u65F6\u95F4\u6233
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  const stamp = `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}`;
  return `${base}_${stamp}.csv`;
}

export function downloadCsv(
  filename: string,
  headers: string[],
  rows: (string | number | null | undefined)[][],
  opts?: DownloadCsvOpts,
) {
  if (!rows.length && opts?.emptyGuard && !window.confirm(opts.emptyGuard)) return;
  const lines = [headers.map(escCell).join(","), ...rows.map((r) => r.map(escCell).join(","))];
  saveCsvFile(filename, lines.join("\n"));
}

/**
 * \u4E0B\u8F7D\u300C\u5DF2\u7ECF\u662F CSV \u6587\u672C\u300D\u7684\u5185\u5BB9\uFF08\u540E\u7AEF\u5BFC\u51FA\u7684\u62A5\u8868\u7B49\uFF09\u3002
 *
 * \u76F4\u63A5 Blob \u539F\u59CB\u6587\u672C\u4F1A\u6F0F\u6389\u4E24\u4EF6\u4E8B\uFF1ABOM\uFF08Excel \u91CC\u4E2D\u6587\u8868\u5934\u4E71\u7801\uFF09\u4E0E\u516C\u5F0F\u6CE8\u5165\u9632\u62A4
 * \uFF08\u8239\u540D/\u5BF9\u624B\u65B9\u540D\u4EE5 `=`/`+`/`-` \u5F00\u5934\u65F6 Excel \u4F1A\u5F53\u516C\u5F0F\u6267\u884C\uFF09\u3002
 * \u8FD9\u91CC\u5148\u89E3\u6790\u6210\u683C\u5B50\uFF0C\u518D\u8D70\u4E0E downloadCsv \u76F8\u540C\u7684\u9632\u62A4\u4E0E BOM \u51FA\u53E3\u3002
 */
export function downloadCsvText(filename: string, csvText: string) {
  const rows = parseCsv(csvText ?? "");
  if (!rows.length) {
    saveCsvFile(filename, "");
    return;
  }
  downloadCsv(filename, rows[0], rows.slice(1));
}

/** \u5355\u683C\u8F6C\u4E49 + \u516C\u5F0F\u6CE8\u5165\u9632\u62A4\u3002 */
function escCell(v: string | number | null | undefined): string {
  const s = guardFormula(v === null || v === undefined ? "" : String(v));
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** \u843D\u76D8\uFF08\u5E26 BOM\uFF0C\u4FDD\u8BC1 Excel \u6B63\u786E\u8BC6\u522B UTF-8 \u4E2D\u6587\u8868\u5934\uFF09\u3002 */
function saveCsvFile(filename: string, text: string) {
  const blob = new Blob(["\uFEFF" + text], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = stampFilename(filename);
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
