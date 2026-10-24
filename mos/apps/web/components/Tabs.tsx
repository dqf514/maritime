"use client";

// 全站统一 Tab 组件 — 替代 6 套散装实现（desk-tabs / page-tabs / trading-tabs /
// ai-tabs / tc-coa 自造 / 手写 role="tab"）。所有页面必须使用本组件。
//
// 变体：
//   line （默认）：底边下划线式 — 详情页/工作区
//   pill          ：药丸式 — 页内分段
//
// 布局：外层 `.ui-tabs` 是**纵向**容器 —— tab 条（`.ui-tabs-bar`，横排：
// list 在左、可选 right 插槽在右）在上，`panels` 渲染的面板在下。
// 历史缺陷：`panels` 曾直接塞进 tab 条的横排 flex 里，导致航次工作台的
// 面板被排到 tab 条**右侧**（tab 扎堆在左半边、内容区下方大片空白）。
//
// 无障碍：tab 按钮用 role="tab" + aria-selected；**只有当页面真的提供了
// 对应的面板 id 时才写 aria-controls** —— 指向不存在的 id 比不写更糟
// （审计项：aria-controls 指向不存在的 id）。
// 页面要么用 `panels` 让本组件渲染面板，要么自己渲染面板并把真实 id 传给
// `panelIdPrefix`。

import { ReactNode, useCallback, useId, useRef } from "react";

export type TabItem = {
  key: string;
  label: ReactNode;
  /** 右上角计数徽标。字符串/数字走默认徽标样式；ReactNode 原样渲染（自带样式）。 */
  badge?: ReactNode;
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
  /**
   * 面板容器 id 前缀。传入后 tab 按钮的 aria-controls 指向
   * `${panelIdPrefix}-${key}-panel`（页面需自行渲染同名 id 的面板容器）。
   */
  panelIdPrefix?: string;
  /** 由本组件直接渲染的面板（key → 内容）。传了它就不必再传 panelIdPrefix。 */
  panels?: Record<string, ReactNode>;
  /** 面板容器的额外 class（用于沿用宿主页面的面板样式）。 */
  panelClassName?: string;
  className?: string;
  "aria-label"?: string;
};

export function Tabs({
  items,
  value,
  onChange,
  variant = "line",
  size = "sm",
  right,
  panelIdPrefix,
  panels,
  panelClassName,
  className,
  ...rest
}: Props) {
  const baseId = useId();
  const listRef = useRef<HTMLDivElement>(null);
  const prefix = panelIdPrefix ?? (panels ? baseId : undefined);
  const panelId = (key: string) => `${prefix}-${key}-panel`;
  const tabId = (key: string) => `${baseId}-${key}`;

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
      {/* tab 条：横排容器（list 在左、right 插槽在右）。面板必须放在它**外面** ——
          历史缺陷是面板和 list 同处一个横排 flex，导致内容被排到 tab 右侧。 */}
      <div className="ui-tabs-bar">
        <div className="ui-tabs-list" role="tablist" ref={listRef} onKeyDown={onKeyDown}>
          {items.map((it) => {
            const active = it.key === value;
            return (
              <button
                key={it.key}
                type="button"
                role="tab"
                id={tabId(it.key)}
                data-tab-key={it.key}
                aria-selected={active}
                aria-controls={prefix ? panelId(it.key) : undefined}
                tabIndex={active ? 0 : -1}
                disabled={it.disabled}
                title={it.title}
                className={`ui-tab${active ? " active" : ""}`}
                onClick={() => onChange(it.key)}
              >
                <span className="ui-tab-label">{it.label}</span>
                {it.badge != null && it.badge !== "" ? (
                  typeof it.badge === "string" || typeof it.badge === "number" ? (
                    <span className="ui-tab-badge">{it.badge}</span>
                  ) : (
                    it.badge
                  )
                ) : null}
              </button>
            );
          })}
        </div>
        {right ? <div className="ui-tabs-right">{right}</div> : null}
      </div>
      {panels && prefix
        ? items.map((it) => (
            <TabPanel
              key={it.key}
              id={panelId(it.key)}
              ariaLabelledBy={tabId(it.key)}
              active={it.key === value}
              className={panelClassName}
            >
              {panels[it.key]}
            </TabPanel>
          ))
        : null}
    </div>
  );
}

/** Tab 内容面板：负责 id 关联与无障碍属性（简单场景可不用，直接条件渲染） */
export function TabPanel({
  tabKey,
  active,
  children,
  className,
  id,
  ariaLabelledBy,
}: {
  tabKey?: string;
  active: boolean;
  children: ReactNode;
  className?: string;
  id?: string;
  ariaLabelledBy?: string;
}) {
  if (!active) return null;
  return (
    <div
      role="tabpanel"
      id={id}
      aria-labelledby={ariaLabelledBy}
      data-tab-panel={tabKey}
      className={className}
      tabIndex={0}
    >
      {children}
    </div>
  );
}
