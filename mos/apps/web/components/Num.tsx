"use client";

// 数值单元格：显示 ≤6 位，hover 出全精度 tooltip（IMOS D5 约定）。
// 用法：render: (v) => <Num v={v as number} digits={2} />

import { fmt, fmtFull } from "@/lib/fmt";

export function Num({ v, digits = 6, className }: { v: number | undefined | null; digits?: number; className?: string }) {
  if (v === undefined || v === null) return <span className={className}>—</span>;
  const full = fmtFull(v);
  const shown = fmt(v, digits);
  return (
    <span className={className} title={full !== shown ? full : undefined} style={{ fontVariantNumeric: "tabular-nums" }}>
      {shown}
    </span>
  );
}
