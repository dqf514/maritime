"use client";

// B3 状态色图例条：列表页头部/工具栏下的成套状态说明（IMOS 状态语言）。
// 用法：<StatusLegend statuses={["draft", "issued", "paid", "void"]} />

import { useI18n } from "@/lib/i18n";
import { StatusBadge } from "@/components/StatusBadge";

export function StatusLegend({ statuses, className }: { statuses: string[]; className?: string }) {
  const { t } = useI18n();
  if (!statuses.length) return null;
  return (
    <div className={`status-legend${className ? ` ${className}` : ""}`} role="note" aria-label={t("legend.status", "Status legend")}>
      <span className="status-legend-title">{t("legend.status", "Status")}</span>
      {statuses.map((s) => (
        <StatusBadge
          key={s}
          status={s}
          label={t(`status.${s}`, s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()))}
        />
      ))}
    </div>
  );
}
