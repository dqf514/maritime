"use client";

// 统一列表工具栏 — IMOS 动词顺序：动作 · 筛选 · 视图 · 导出
// 直接替换页面里的 <div className="toolbar">，样式沿用 .toolbar。

import { ReactNode } from "react";
import { useI18n } from "@/lib/i18n";

type Props = {
  /** 左侧动作按钮（New / Delete / Refresh…），保持动词顺序 */
  children?: ReactNode;
  /** 右侧（筛选、SavedViews、导出、列选择），自动右对齐 */
  right?: ReactNode;
  /** 已生效的筛选条件数（橙色角标，IMOS 同款） */
  filterCount?: number;
  /** 清空筛选回调（传了才显示角标按钮） */
  onClearFilters?: () => void;
  className?: string;
};

export function Toolbar({ children, right, filterCount = 0, onClearFilters, className }: Props) {
  const { t } = useI18n();
  return (
    <div className={`toolbar${className ? ` ${className}` : ""}`}>
      {children ? <div className="toolbar-left">{children}</div> : null}
      {filterCount > 0 ? (
        <span
          className="toolbar-filter-count"
          role="status"
          title={t("toolbar.active_filters", "Active filters: {n}", { n: filterCount })}
        >
          {filterCount}
          {onClearFilters ? (
            <button type="button" className="toolbar-filter-clear" aria-label={t("toolbar.clear_filters", "Clear filters")} onClick={onClearFilters}>
              ✕
            </button>
          ) : null}
        </span>
      ) : null}
      {right ? <div className="toolbar-right">{right}</div> : null}
    </div>
  );
}
