"use client";

// 工作台外壳（Phase 2）：固定头 + 可滚动面板区。
// 供航次工作台等“单据工作台”页复用。头部内容由页面用 PageHeader 传入，
// 保证与全站页头一致（本组件只负责布局，不自行画标题）。

import { ReactNode } from "react";

export type WorkspaceShellProps = {
  /** 固定头部内容 — 统一传 <PageHeader … /> */
  header: ReactNode;
  children: ReactNode;
};

export function WorkspaceShell({ header, children }: WorkspaceShellProps) {
  return (
    <div className="ws-shell">
      <header className="ws-header">{header}</header>
      <div className="ws-body">{children}</div>
    </div>
  );
}
