// 显示层 HTML → 纯文本兜底（正则版，零依赖）。
//
// 后端入库前已统一 html_to_text（apps/api/app/services/html_to_text.py），
// 这里只防御历史数据 / 外部数据源漏网的 HTML —— 解析字段值、正文预览
// 过一遍再展示，避免把 <span style=...> 直接渲染给用户看。

const BLOCK_RE =
  /<\/?(?:p|div|br|tr|li|h[1-6]|table|blockquote|pre|section|article|header|footer|hr)\b[^>]*>/gi;
const STYLE_RE = /<style[\s\S]*?<\/style>/gi;
const SCRIPT_RE = /<script[\s\S]*?<\/script>/gi;
const TAG_RE = /<[^>]+>/g;
const ENTITY_RE = /&(amp|lt|gt|quot|apos|nbsp|#\d+|#x[0-9a-f]+);/gi;

const ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
};

function decodeEntities(s: string): string {
  return s.replace(ENTITY_RE, (m, code: string) => {
    if (code.startsWith("#x") || code.startsWith("#X")) {
      const n = parseInt(code.slice(2), 16);
      return Number.isFinite(n) ? String.fromCodePoint(n) : m;
    }
    if (code.startsWith("#")) {
      const n = parseInt(code.slice(1), 10);
      return Number.isFinite(n) ? String.fromCodePoint(n) : m;
    }
    return ENTITIES[code] ?? m;
  });
}

/** HTML 片段 → 纯文本；纯文本幂等返回。空/非字符串返回 ""。 */
export function htmlToText(input: unknown): string {
  if (input == null) return "";
  let s = String(input);
  if (!s) return "";
  // 双重转义：&lt;span&gt; 先还原成 <span> 再走标签剥离
  if (/&lt;\/?[a-z]/i.test(s)) s = decodeEntities(s);
  if (!/<[a-z]/i.test(s)) return s.replace(/[ \t]+$/gm, "").trim();
  s = s.replace(STYLE_RE, "").replace(SCRIPT_RE, "");
  s = s.replace(BLOCK_RE, "\n");
  s = s.replace(TAG_RE, "");
  s = decodeEntities(s);
  return s
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]+$/gm, "")
    .trim();
}

/** 截取前 n 个字符的纯文本预览（列渲染用）。 */
export function textPreview(input: unknown, n = 160): string {
  const s = htmlToText(input);
  return s.length > n ? `${s.slice(0, n)}…` : s;
}
