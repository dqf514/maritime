"use client";

// 列表页模板：PageHeader + Toolbar + 内容区。
// 新列表页必须从本模板起步；存量列表页迁移后由一致性 lint 锁定。

import { ReactNode } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Toolbar } from "@/components/Toolbar";
import { BreadcrumbItem } from "@/components/Breadcrumb";

type Props = {
  title: ReactNode;
  subtitle?: ReactNode;
  breadcrumb?: BreadcrumbItem[];
  headerActions?: ReactNode;
  /** 工具栏左侧动作（New/Refresh…） */
  toolbar?: ReactNode;
  /** 工具栏右侧（筛选/SavedViews/导出/列选择） */
  toolbarRight?: ReactNode;
  filterCount?: number;
  onClearFilters?: () => void;
  /** 表格上方的 tab 条（如状态分段） */
  children: ReactNode;
  /** 状态栏文字（如 "128 records · page 1/7"） */
  footer?: ReactNode;
  className?: string;
};

export function ListPageTemplate({
  title,
  subtitle,
  breadcrumb,
  headerActions,
  toolbar,
  toolbarRight,
  filterCount,
  onClearFilters,
  children,
  footer,
  className,
}: Props) {
  return (
    <div className={`page-list${className ? ` ${className}` : ""}`}>
      <PageHeader title={title} subtitle={subtitle} breadcrumb={breadcrumb} actions={headerActions} />
      {toolbar != null || toolbarRight != null ? (
        <Toolbar right={toolbarRight} filterCount={filterCount} onClearFilters={onClearFilters}>
          {toolbar}
        </Toolbar>
      ) : null}
      <div className="page-list-body">{children}</div>
      {footer ? <div className="page-list-footer">{footer}</div> : null}
    </div>
  );
}
