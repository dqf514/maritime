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
];

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
