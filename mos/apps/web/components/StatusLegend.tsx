"use client";

// B3 状态色图例条：列表页头部/工具栏下的成套状态说明（IMOS 状态语言）。
// 用法：<StatusLegend statuses={["draft", "issued", "paid", "void"]} />

import { useI18n } from "@/lib/i18n";
import { StatusBadge } from "@/components/StatusBadge";

/** 图例短标：多词取首字母缩写（in_progress → IP），长单词截前 4 字母（calculated → CALC）；完整文案走 title hint */
function abbrev(s: string): string {
  const parts = s.replace(/_/g, " ").trim().split(/\s+/);
  if (parts.length > 1) return parts.map((w) => w[0]).join("").toUpperCase();
  return (s.length <= 5 ? s : s.slice(0, 4)).toUpperCase();
}

export function StatusLegend({
  statuses,
  labels,
  className,
}: {
  statuses: string[];
  /** 覆盖文案（图例与列里的说法要一致 —— 例如制裁状态用「审查中」而不是通用的「待审核」） */
  labels?: Record<string, string>;
  className?: string;
}) {
  const { t } = useI18n();
  if (!statuses.length) return null;
  return (
    <div className={`status-legend${className ? ` ${className}` : ""}`} role="note" aria-label={t("legend.status", "Status legend")}>
      <span className="status-legend-title">{t("legend.status", "Status")}</span>
      {statuses.map((s) => {
        // 优先用页面给的文案；否则用 status.* 的译文；再否则退回原始码的人话写法。
        const raw = t(`status.${s}`);
        const text = labels?.[s] ?? (raw !== `status.${s}` ? raw : null);
        const full = text ?? s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
        return <StatusBadge key={s} status={s} label={abbrev(text ?? s)} title={full} />;
      })}
    </div>
  );
}
