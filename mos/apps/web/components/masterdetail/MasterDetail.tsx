"use client";

// 主从布局壳（IMOS 式）—— 左窄导航 + 右详情，全高、各栏独立滚动。
//
// 为什么是「详情页自带左栏」而不是「列表页就地展开」：
//   * URL 保持干净可深链（/cargo/abc），前进/后退/收藏/外发链接都对；
//   * 详情页自带兄弟清单上下文，用户点另一条即可切换，不必回到列表；
//   * 列表页保持整页表格（列全、可排序可导出），不牺牲既有信息密度。
//
// 布局挂载点：必须是 .content 的直接子元素 —— styles/masterdetail.css 用
// .content:has(> .master-detail) 把内容区改成不滚动的列容器。

import { ReactNode } from "react";

export type MasterDetailProps = {
  /** 左栏内容，通常是 <DetailRail … /> */
  rail: ReactNode;
  /** 详情区固定头部（不随内容滚动），通常是 <DetailHeader … /> */
  header?: ReactNode;
  /** 详情区滚动内容 */
  children: ReactNode;
  /** 追加到 .master-detail 的 class */
  className?: string;
  /**
   * 不加 .md-detail-body 滚动容器 —— 子元素自带全高布局时用
   * （航次工作台的 WorkspaceShell 自带固定头 + 自己的滚动区）。
   */
  raw?: boolean;
};

export function MasterDetail({ rail, header, children, className, raw }: MasterDetailProps) {
  return (
    <div className={className ? `master-detail ${className}` : "master-detail"}>
      {rail}
      <section className="md-detail">
        {header ? <div className="md-detail-head">{header}</div> : null}
        {raw ? children : <div className="md-detail-body">{children}</div>}
      </section>
    </div>
  );
}
