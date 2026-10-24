"use client";

// 刷新按钮 — 全站统一的「↻」图标按钮。
//
// 之前 ↻ 在 37 处各写一遍：没有 aria-label（读屏只念「↻」）、文案不本地化、
// 样式类各不相同。统一到本组件后：图标本身 aria-hidden，按钮有可读的
// aria-label（读屏念「Refresh / 刷新」），颜色/尺寸一致。

import { useI18n } from "@/lib/i18n";

type Props = {
  onClick: () => void;
  /** 无障碍名与 tooltip 文案（默认 common.refresh） */
  label?: string;
  className?: string;
  disabled?: boolean;
};

export function RefreshButton({ onClick, label, className = "btn btn-sm", disabled }: Props) {
  const { t } = useI18n();
  const text = label ?? t("common.refresh", "Refresh");
  return (
    <button
      type="button"
      className={className}
      onClick={onClick}
      disabled={disabled}
      aria-label={text}
      title={text}
    >
      <span aria-hidden="true">↻</span>
    </button>
  );
}
