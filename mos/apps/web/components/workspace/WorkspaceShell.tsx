"use client";

// 工作台外壳（Phase 2）：固定头 + 可滚动面板区。
// 供航次工作台等“单据工作台”页复用。头部内容由页面用 PageHeader 传入，
// 保证与全站页头一致（本组件只负责布局，不自行画标题）。

import { ReactNode } from "react";

export type WorkspaceShellProps = {
  /** 固定头部内容 — 统一传 <PageHeader … /> */
  header: ReactNode;
  children: ReactNode;
  /** 可折叠右侧栏（Revisions / Tasks & Alerts 等 IMOS 侧板） */
  sidebar?: ReactNode;
  sidebarOpen?: boolean;
  onToggleSidebar?: () => void;
};

export function WorkspaceShell({ header, children, sidebar, sidebarOpen = true, onToggleSidebar }: WorkspaceShellProps) {
  return (
    <div className={`ws-shell${sidebar ? " has-sidebar" : ""}${sidebar && sidebarOpen ? " sidebar-open" : ""}`}>
      <header className="ws-header">{header}</header>
      <div className="ws-body">
        <div className="ws-main">{children}</div>
        {sidebar ? (
          <aside className="ws-sidebar" aria-label="Side panels">
            <div className="ws-sidebar-head">
              <button type="button" className="btn btn-sm" onClick={onToggleSidebar} aria-expanded={sidebarOpen}>
                {sidebarOpen ? "▸" : "◂"}
              </button>
            </div>
            {sidebarOpen ? <div className="ws-sidebar-body">{sidebar}</div> : null}
          </aside>
        ) : null}
      </div>
    </div>
  );
}
