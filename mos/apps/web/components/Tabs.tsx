"use client";

// 全站统一 Tab 组件 — 替代 6 套散装实现（desk-tabs / page-tabs / trading-tabs /
// ai-tabs / tc-coa 自造 / 手写 role="tab"）。所有页面必须使用本组件。
//
// 变体：
//   line （默认）：底边下划线式 — 详情页/工作区
//   pill          ：药丸式 — 页内分段

import { ReactNode, useCallback, useId, useRef } from "react";

export type TabItem = {
  key: string;
  label: ReactNode;
  /** 右上角计数徽标 */
  badge?: number | string;
  disabled?: boolean;
  title?: string;
};

type Props = {
  items: TabItem[];
  value: string;
  onChange: (key: string) => void;
  variant?: "line" | "pill";
  /** 尺寸：sm（默认，22px 密度） / md */
  size?: "sm" | "md";
  /** 右侧附加内容（如工具按钮），与 tab 条同行 */
  right?: ReactNode;
  className?: string;
  "aria-label"?: string;
};

export function Tabs({ items, value, onChange, variant = "line", size = "sm", right, className, ...rest }: Props) {
  const baseId = useId();
  const listRef = useRef<HTMLDivElement>(null);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      const enabled = items.filter((i) => !i.disabled);
      const idx = enabled.findIndex((i) => i.key === value);
      let next = -1;
      if (e.key === "ArrowRight") next = (idx + 1) % enabled.length;
      else if (e.key === "ArrowLeft") next = (idx - 1 + enabled.length) % enabled.length;
      else if (e.key === "Home") next = 0;
      else if (e.key === "End") next = enabled.length - 1;
      if (next >= 0) {
        e.preventDefault();
        const key = enabled[next].key;
        onChange(key);
        requestAnimationFrame(() => {
          listRef.current?.querySelector<HTMLElement>(`[data-tab-key="${CSS.escape(key)}"]`)?.focus();
        });
      }
    },
    [items, value, onChange],
  );

  return (
    <div className={`ui-tabs ui-tabs--${variant} ui-tabs--${size}${className ? ` ${className}` : ""}`} {...rest}>
      <div className="ui-tabs-list" role="tablist" ref={listRef} onKeyDown={onKeyDown}>
        {items.map((it) => {
          const active = it.key === value;
          return (
            <button
              key={it.key}
              type="button"
              role="tab"
              id={`${baseId}-${it.key}`}
              data-tab-key={it.key}
              aria-selected={active}
              aria-controls={`${baseId}-${it.key}-panel`}
              tabIndex={active ? 0 : -1}
              disabled={it.disabled}
              title={it.title}
              className={`ui-tab${active ? " active" : ""}`}
              onClick={() => onChange(it.key)}
            >
              <span className="ui-tab-label">{it.label}</span>
              {it.badge != null && it.badge !== "" ? <span className="ui-tab-badge">{it.badge}</span> : null}
            </button>
          );
        })}
      </div>
      {right ? <div className="ui-tabs-right">{right}</div> : null}
    </div>
  );
}

/** Tab 内容面板：负责 id 关联与无障碍属性（简单场景可不用，直接条件渲染） */
export function TabPanel({ tabKey, active, children, className }: { tabKey: string; active: boolean; children: ReactNode; className?: string }) {
  if (!active) return null;
  return (
    <div role="tabpanel" data-tab-panel={tabKey} className={className} tabIndex={0}>
      {children}
    </div>
  );
}
