"use client";

// 统一页头 — 标题、副标题、快捷链接、操作按钮严格一致
// 所有页面必须使用此组件，不得自行写 <h1> / page-header div
// 原面包屑槽位（与主标题重复的本页标题）已改为「收藏快捷链接」区域；
// breadcrumb prop 仍接受但不再渲染（保留以兼容存量调用与收藏标题提取）。

import { ReactNode } from "react";
import { BreadcrumbItem } from "@/components/Breadcrumb";
import { FavoriteBar, FavoriteButton } from "@/components/FavoriteBar";

type Props = {
  /** 页面主标题（必填，可含状态徽标等行内元素） */
  title: ReactNode;
  /** 副标题 / 描述（可选） */
  subtitle?: ReactNode;
  /** 右侧操作按钮区（可选） */
  actions?: ReactNode;
  /** 自定义左侧内容（可选） */
  left?: ReactNode;
  /** 面包屑（详情页必传；列表页传导航根即可）— 现仅用于收藏标题提取 */
  breadcrumb?: BreadcrumbItem[];
};

function titleText(title: ReactNode, breadcrumb?: BreadcrumbItem[]): string {
  if (typeof title === "string") return title;
  return breadcrumb?.length ? breadcrumb[breadcrumb.length - 1].label : "";
}

export function PageHeader({ title, subtitle, actions, left, breadcrumb }: Props) {
  return (
    <div className="page-header">
      <div className="page-header-left">
        {left}
        <FavoriteBar />
        <h1 className="page-header-title">{title}</h1>
        {subtitle ? <p className="page-header-sub">{subtitle}</p> : null}
      </div>
      <div className="page-header-actions">
        {actions}
        <FavoriteButton title={titleText(title, breadcrumb)} />
      </div>
    </div>
  );
}
