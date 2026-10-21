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

export function StatusLegend({ statuses, className }: { statuses: string[]; className?: string }) {
  const { t } = useI18n();
  if (!statuses.length) return null;
  return (
    <div className={`status-legend${className ? ` ${className}` : ""}`} role="note" aria-label={t("legend.status", "Status legend")}>
      <span className="status-legend-title">{t("legend.status", "Status")}</span>
      {statuses.map((s) => {
        const full = t(`status.${s}`, s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()));
        return <StatusBadge key={s} status={s} label={abbrev(s)} title={full} />;
      })}
    </div>
  );
}
