"use client";

// 统一分页顶栏 — 标题、副标题、操作按钮严格一致
// 所有页面必须使用此组件，不得自行写 <h1> / page-header div

import { ReactNode } from "react";

type Props = {
  /** 页面主标题（必填，可含状态徽标等行内元素） */
  title: ReactNode;
  /** 副标题 / 描述（可选） */
  subtitle?: ReactNode;
  /** 右侧操作按钮区（可选） */
  actions?: ReactNode;
  /** 自定义左侧内容（面包屑等，可选） */
  left?: ReactNode;
};

export function PageHeader({ title, subtitle, actions, left }: Props) {
  return (
    <div className="page-header">
      <div className="page-header-left">
        {left}
        <h1 className="page-header-title">{title}</h1>
        {subtitle ? <p className="page-header-sub">{subtitle}</p> : null}
      </div>
      {actions ? <div className="page-header-actions">{actions}</div> : null}
    </div>
  );
}
