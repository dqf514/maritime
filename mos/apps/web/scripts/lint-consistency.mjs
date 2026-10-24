#!/usr/bin/env node
/**
 * 一致性 lint（MariOS 改造计划 A7）— 防回退的"宪法"。
 *
 * 规则基于 MARIOS_IMOS_REFORM_PLAN.md 第 2 节量化指标。存量违规记录在
 * scripts/consistency-baseline.json（豁免基线），新代码只许减少、不许增加：
 *   current > baseline  →  exit 1（回退）
 *   current < baseline  →  提示更新基线（收紧）
 *
 * 用法：node scripts/lint-consistency.mjs [--update]
 */

import { readFileSync, writeFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(fileURLToPath(new URL(".", import.meta.url)), "..");
const BASELINE_PATH = join(ROOT, "scripts", "consistency-baseline.json");
const UPDATE = process.argv.includes("--update");

const RULES = [
  {
    id: "toast-success-on-failure",
    desc: "失败场景禁止 toast.success（应用 toast.error/warning）",
    // 语句内同时出现 toast.success 与失败语义
    test: (src) => {
      let n = 0;
      const stmts = src.split(/;|\n/);
      for (const s of stmts) {
        if (!/toast\.success/.test(s)) continue;
        if (/fail|error|invalid|denied|cannot|unable|失败|错误/i.test(s)) n++;
      }
      return n;
    },
  },
  {
    id: "raw-h1",
    desc: "页面必须用 PageHeader 组件（禁止裸 <h1>；login/help/落地页豁免）",
    test: (src, file) => {
      if (!/page\.tsx$/.test(file)) return 0;
      if (/^app\/(login|help)\//.test(file) || file === "app/page.tsx") return 0;
      if (src.includes("PageHeader")) return 0;
      return (src.match(/<h1[\s>]/g) || []).length;
    },
  },
  {
    id: "legacy-tab-families",
    desc: "禁止旧 tab 实现（desk-tabs/page-tabs/trading-tabs/ai-tabs/手写 role=tab）",
    test: (src, file) => {
      if (!/\.tsx$/.test(file)) return 0;
      if (file === "components/Tabs.tsx" || file === "components/workspace/PanelTabs.tsx") return 0; // 许可实现
      let n = 0;
      for (const re of [/desk-tabs/g, /page-tabs/g, /trading-tabs/g, /ai-tabs/g, /role="tab"/g]) {
        n += (src.match(re) || []).length;
      }
      return n;
    },
  },
  {
    id: "data-table",
    desc: "禁止 .data-table（统一 DataGrid / .table）",
    test: (src) => (src.match(/data-table/g) || []).length,
  },
  {
    id: "inline-create-form",
    desc: "列表页禁止内联新建表单（统一 RecordModal / 整页）",
    test: (src, file) => {
      if (!/page\.tsx$/.test(file)) return 0;
      if (/\[.+\]/.test(file)) return 0; // 详情路由整页编辑表单合法（A6 只针对列表页）
      // 只统计「挂在列表上的新建表单」：<form> 内部包着 DataGrid / <table>。
      // 整页设置表单（admin/i18n、admin/security）不含列表，不算违规；
      // 弹窗里的表单由 RecordModal 自己的 <form> 承担，天然不在列表页里。
      let hits = 0;
      const re = /<form\b/g;
      let m;
      while ((m = re.exec(src))) {
        const end = src.indexOf("</form>", m.index);
        const body = src.slice(m.index, end < 0 ? src.length : end);
        if (/DataGrid|<table/i.test(body)) hits += 1;
      }
      return hits;
    },
  },
  {
    id: "inline-style",
    desc: "内联样式 style={{（存量基线，新文件应为 0）",
    test: (src) => (src.match(/style=\{\{/g) || []).length,
  },
  {
    id: "raw-toolbar-div",
    desc: "工具栏用 <Toolbar> 组件（禁止裸 div.toolbar）",
    test: (src, file) => {
      if (!/page\.tsx$/.test(file)) return 0;
      if (src.includes("Toolbar")) return 0;
      return (src.match(/className="toolbar"/g) || []).length;
    },
  },
  {
    id: "raw-blob-download",
    desc: "CSV 导出统一走 lib/csv（禁止在 app/ 内自造 new Blob 下载）",
    // 自造 Blob 会漏掉 BOM（Excel 中文表头乱码）与公式注入防护（= + - 开头被当公式执行）。
    test: (src, file) => {
      if (!/^app\//.test(file)) return 0;
      return (src.match(/new Blob\(/g) || []).length;
    },
  },
  {
    id: "raw-string-err",
    desc: "错误文案统一走 msgOf（禁止把 String(err) 直接展示给用户）",
    // String(err) 展示出来的是 "[object Object]" / 堆栈片段 —— 用户看不懂，
    // 也可能把内部路径、SQL 片段泄露出去。lib/errors.ts 的 msgOf 会按状态码
    // 翻成双语人话。注释里的举例不算违规。
    test: (src) => {
      const code = src
        .split("\n")
        .filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l))
        .join("\n");
      return (code.match(/\bString\(err\)/g) || []).length;
    },
  },
  {
    id: "silent-catch",
    desc: "禁止 catch(() => …) 吞错（错误已在别处处理必须写 .catch(handled)）",
    // 审计 P1-4：`catch(() => [])` / `catch(() => undefined)` 分不清
    //   (a) 错误已经在函数内部 setErr/toast 过，外层只是防 unhandled rejection；
    //   (b) 错误被真的吞掉 —— 界面上还是一片"暂无数据"。
    // (b) 是病灶。现在 (a) 必须写成 `.catch(handled)`（显式标记，来自 lib/errors），
    // 就地报错必须写 `.catch((ex) => toast.error(msgOf(ex)))`。
    // 注释里的示例不算违规。
    //
    // 判据（只抓"**静默吞错**"，不误伤正常写法）：
    //   * 处理器**不接参数**（`catch(() => …)`）—— 接了参数却不用，那才是
    //     真的在无视错误；
    //   * 且处理器的结果**没有任何错误信号**：
    //       - 表达式体：返回 `undefined` / `null` / `[]` / `{}` 这类"空值"
    //         （取数失败 → 当成"没有数据"，界面显示"暂无记录"，用户不知道
    //          刚才那次取数失败了 —— 这正是 P1-4 的病灶）；
    //       - 块体：只把某个列表置空（`setRows([])` / `setItems(null)`），
    //         却没有 `toast.error` / `setErr` / `set*Warn` 之类的提示。
    // 豁免：
    //   * `res.json().catch(() => ({}))` —— 解析"可能不是 JSON 的响应体"
    //     是通用写法，不是吞错；
    //   * `.catch(handled)` —— 显式声明"错误已在别处处理"（lib/errors.ts）。
    test: (src) => countSilentCatches(src),
  },
  {
    id: "icon-button-aria-label",
    desc: "纯图标按钮必须有 aria-label（屏幕阅读器读不出图标）",
    // 判据：<button> 标签本身没有 aria-label / aria-labelledby，且去掉内部标签后
    // 剩下的可见文字要么为空（纯图标），要么**全部是非字母数字符号**（↻ ← → × ☰ ☑
    // 等字形）—— 屏幕阅读器只能读出 "left arrow" / "nothing"，等于没有名字。
    // aria-labelledby 也算数（指向可见文字）。
    test: (src) => {
      const code = stripComments(src);
      let n = 0;
      const re = /<button\b/g;
      let m;
      while ((m = re.exec(code))) {
        const openEnd = endOfOpenTag(code, m.index);
        if (openEnd < 0) continue;
        const tag = code.slice(m.index, openEnd);
        if (/aria-label|aria-labelledby/.test(tag)) continue;
        if (/\/>$/.test(tag)) continue; // 自闭合按钮没有内容
        const end = code.indexOf("</button>", openEnd);
        // 只看标签**之后**的内容（属性里的 onClick={...} 不是可见文字）
        const inner = end < 0 ? "" : code.slice(openEnd, end);
        const text = inner.replace(/<[^>]*>/g, "").replace(/\s+/g, "").trim();
        if (!text) {
          n += 1;
          continue;
        }
        // 全部字符都不是字母/数字 → 纯符号字形（图标、箭头、CJK、emoji）也算未命名
        if ([...text].every((ch) => !/[A-Za-z0-9]/.test(ch))) n += 1;
      }
      return n;
    },
  },
];

/** 去掉注释（保留字符串字面量内容），避免把文档注释里的示例当成真实按钮。 */function stripComments(src) {
  let out = "";
  let i = 0;
  const n = src.length;
  while (i < n) {
    const c = src[i];
    if (c === '"' || c === "'" || c === "`") {
      const q = c;
      out += c;
      i += 1;
      while (i < n) {
        if (src[i] === "\\") {
          out += src[i] + (src[i + 1] ?? "");
          i += 2;
          continue;
        }
        out += src[i];
        if (src[i] === q) {
          i += 1;
          break;
        }
        i += 1;
      }
      continue;
    }
    if (c === "/" && src[i + 1] === "*") {
      const end = src.indexOf("*/", i + 2);
      i = end < 0 ? n : end + 2;
      out += " ";
      continue;
    }
    if (c === "/" && src[i + 1] === "/") {
      const end = src.indexOf("\n", i);
      i = end < 0 ? n : end;
      out += " ";
      continue;
    }
    out += c;
    i += 1;
  }
  return out;
}

/** 返回 `<button ...>` 开标签的结束下标（不含），能正确跳过属性里的 `=>` 与字符串。 */
function endOfOpenTag(src, start) {
  let quote = null;
  let depth = 0;
  for (let j = start; j < src.length; j++) {
    const c = src[j];
    if (quote) {
      if (c === "\\") {
        j += 1;
        continue;
      }
      if (c === quote) quote = null;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") {
      quote = c;
      continue;
    }
    if (c === "{") {
      depth += 1;
      continue;
    }
    if (c === "}") {
      depth -= 1;
      continue;
    }
    if (c === ">" && depth === 0) return j + 1;
  }
  return -1;
}

/**
 * 数"静默吞错"的 catch：处理器不接参数，且结果里没有任何错误信号。
 * 详见 RULES 里 `silent-catch` 的说明。
 */
function countSilentCatches(src) {
  const code = stripComments(src);
  let n = 0;
  const re = /\.catch\s*\(/g;
  let m;
  while ((m = re.exec(code))) {
    const openEnd = m.index + m[0].length;
    // 取出 handler 参数（到与之匹配的右括号）
    let depth = 1;
    let i = openEnd;
    let quote = null;
    for (; i < code.length; i++) {
      const c = code[i];
      if (quote) {
        if (c === "\\") {
          i++;
          continue;
        }
        if (c === quote) quote = null;
        continue;
      }
      if (c === '"' || c === "'" || c === "`") {
        quote = c;
        continue;
      }
      if (c === "(") depth++;
      else if (c === ")") {
        depth--;
        if (depth === 0) break;
      }
    }
    const handler = code.slice(openEnd, i);
    // 只看"不接参数"的箭头处理器
    const hm = handler.match(/^\s*(?:async\s*)?\(\s*\)\s*=>/);
    if (!hm) continue;
    // 豁免：res.json().catch(...) —— 解析"可能不是 JSON 的响应体"是通用写法
    const before = code.slice(Math.max(0, m.index - 24), m.index);
    if (/\.json\s*\(\s*\)\s*$/.test(before)) continue;
    const body = handler.slice(hm[0].length).trim();
    // 错误信号：toast / setErr / set*Error / set*Warn …
    const hasErrorSignal = /toast\.|console\.warn|set[A-Za-z0-9_]*(?:Err|Error|Warn|Warning)\s*\(/.test(body);
    if (body.startsWith("{")) {
      // 块体：只把列表置空、却没有提示 → 吞错
      const silentEmpty = /set[A-Za-z0-9_]*\(\s*(?:\[\]|null|undefined)\s*\)/.test(body);
      if (silentEmpty && !hasErrorSignal) n += 1;
      continue;
    }
    // 表达式体：返回"空值" → 取数失败被当成"没有数据"
    if (hasErrorSignal) continue;
    if (/^(?:undefined|null|\[\]|\(\{\}\)|\{\})(?:\s+as\s+[\w<>\[\]\s.,]+)?$/.test(body)) n += 1;
  }
  return n;
}

function walk(dir, out = []) {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const e of entries) {
    const p = join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === "node_modules" || e.name === ".next") continue;
      walk(p, out);
    } else if (/\.tsx?$/.test(e.name)) {
      out.push(p);
    }
  }
  return out;
}

const files = [...walk(join(ROOT, "app")), ...walk(join(ROOT, "components")), ...walk(join(ROOT, "lib"))];

const counts = {};
for (const r of RULES) counts[r.id] = 0;
for (const f of files) {
  const src = readFileSync(f, "utf8");
  const rel = relative(ROOT, f).replaceAll("\\", "/");
  for (const r of RULES) counts[r.id] += r.test(src, rel);
}

let baseline = {};
let hadBaseline = false;
try {
  baseline = JSON.parse(readFileSync(BASELINE_PATH, "utf8"));
  hadBaseline = true;
} catch {
  baseline = {};
}

let failed = false;
const lines = [];
for (const r of RULES) {
  const base = baseline[r.id] ?? 0;
  const cur = counts[r.id];
  const mark = cur > base ? "FAIL" : cur < base ? "tighten" : "ok";
  if (cur > base) failed = true;
  lines.push(`  [${mark.padEnd(7)}] ${r.id.padEnd(26)} ${String(cur).padStart(4)} (baseline ${base}) — ${r.desc}`);
}

lines.push("");
lines.push(failed ? "❌ 一致性 lint 未通过：新代码引入了回退项（见 FAIL）。" : "✅ 一致性 lint 通过（存量仅受基线约束，只减不增）。");

// 基线不存在时（首次引导）允许 --update 直接以当前存量建基线；
// 已有基线时 --update 仍只许收紧（cur > base 视为回退，拒绝覆盖）。
if (UPDATE && (!failed || !hadBaseline)) {
  writeFileSync(BASELINE_PATH, JSON.stringify(counts, null, 2) + "\n", "utf8");
  lines.push(hadBaseline ? "📌 基线已收紧到当前值。" : "📌 基线已初始化为当前存量。");
  failed = false;
} else if (failed && !UPDATE) {
  lines.push("   修复违规；确认为不可消除的存量后用 --update 初始化/收紧基线（已有基线时只允许比旧基线更小）。");
}

console.log(lines.join("\n"));
process.exit(failed ? 1 : 0);
