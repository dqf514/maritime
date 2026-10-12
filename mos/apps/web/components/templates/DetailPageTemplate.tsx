"use client";

// 详情页模板：DetailHeader（状态+动作）+ 卡片区 + Tabs 关联区 + 可折叠侧栏。
// 核心合同/航次用整页 Workspace；其余实体详情统一用本模板。

import { ReactNode } from "react";
import { DetailHeader, DetailAction } from "@/components/DetailHeader";
import { Tabs, TabItem } from "@/components/Tabs";
import { StatusTone } from "@/components/StatusBadge";
import { BreadcrumbItem } from "@/components/Breadcrumb";

type Props = {
  title: ReactNode;
  status?: string;
  statusTone?: StatusTone;
  subtitle?: ReactNode;
  breadcrumb?: BreadcrumbItem[];
  headerActions?: DetailAction[];
  badges?: ReactNode;
  /** 字段卡片区（CardGroup 列表） */
  children: ReactNode;
  /** 关联区 tabs（有才渲染 tab 条） */
  tabs?: TabItem[];
  activeTab?: string;
  onTabChange?: (key: string) => void;
  /** tab 区右侧动作 */
  tabRight?: ReactNode;
  /** tab 面板内容（与 activeTab 对应） */
  tabPanels?: ReactNode;
  /** 右侧栏（Revisions / Tasks & Alerts） */
  sidebar?: ReactNode;
  sidebarOpen?: boolean;
  onToggleSidebar?: () => void;
  className?: string;
};

export function DetailPageTemplate({
  title,
  status,
  statusTone,
  subtitle,
  breadcrumb,
  headerActions,
  badges,
  children,
  tabs,
  activeTab,
  onTabChange,
  tabRight,
  tabPanels,
  sidebar,
  sidebarOpen = false,
  onToggleSidebar,
  className,
}: Props) {
  return (
    <div className={`page-detail${sidebar && sidebarOpen ? " has-sidebar" : ""}${className ? ` ${className}` : ""}`}>
      <div className="page-detail-main">
        <DetailHeader
          title={title}
          status={status}
          statusTone={statusTone}
          subtitle={subtitle}
          breadcrumb={breadcrumb}
          actions={headerActions}
          badges={badges}
        />
        <div className="page-detail-cards">{children}</div>
        {tabs?.length ? (
          <div className="page-detail-tabs">
            <Tabs items={tabs} value={activeTab ?? tabs[0]?.key ?? ""} onChange={(k) => onTabChange?.(k)} right={tabRight} />
            <div className="page-detail-panels">{tabPanels}</div>
          </div>
        ) : null}
      </div>
      {sidebar ? (
        <aside className={`page-detail-sidebar${sidebarOpen ? " open" : ""}`} aria-label="Side panels">
          <div className="page-detail-sidebar-head">
            <button type="button" className="btn btn-sm" onClick={onToggleSidebar} aria-expanded={sidebarOpen}>
              {sidebarOpen ? "▸" : "◂"}
            </button>
          </div>
          {sidebarOpen ? <div className="page-detail-sidebar-body">{sidebar}</div> : null}
        </aside>
      ) : null}
    </div>
  );
}
