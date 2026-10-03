"use client";

// 密集面板（Phase 2）：标题条 + 可选折叠 + 右侧动作。

import { ReactNode, useState } from "react";

export type PanelProps = {
  title: ReactNode;
  collapsible?: boolean;
  defaultCollapsed?: boolean;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  /** 面板体去掉内边距（表格类内容贴边） */
  flush?: boolean;
};

export function Panel({ title, collapsible, defaultCollapsed = false, actions, children, className = "", flush }: PanelProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);

  return (
    <section className={`ws-panel${collapsed ? " collapsed" : ""}${className ? ` ${className}` : ""}`}>
      <div className="ws-panel-head">
        {collapsible ? (
          <button
            type="button"
            className="ws-panel-toggle"
            aria-expanded={!collapsed}
            aria-label={collapsed ? "Expand" : "Collapse"}
            onClick={() => setCollapsed((v) => !v)}
          >
            <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden>
              <path fill="currentColor" d="M2.2 4.1 6 7.9l3.8-3.8 1 1L6 9.9 1.2 5.1z" />
            </svg>
          </button>
        ) : null}
        <h3 className="ws-panel-title">{title}</h3>
        {actions ? <div className="ws-panel-actions">{actions}</div> : null}
      </div>
      <div className={`ws-panel-body${flush ? " ws-panel-flush" : ""}`}>{children}</div>
    </section>
  );
}
