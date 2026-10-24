"use client";

// 标签面板组（Phase 2）：航次详情选用标签式布局，本组件为通用 tab strip。
// 受控（activeId + onChange）或非受控均可。
//
// 实现说明：本组件**委托**给全站唯一的 Tabs 组件（components/Tabs.tsx）——
// 之前这里是第二套手写的 role="tablist"，没有方向键 / Home / End 导航，
// 也没有 aria-controls ↔ 面板 id 的关联。现在只保留本组件自己的数据形状
// （id / label / content / badge），交互与无障碍全部由 Tabs 负责。

import { ReactNode, useMemo, useState } from "react";

import { Tabs } from "@/components/Tabs";

export type PanelTab = {
  id: string;
  label: ReactNode;
  content: ReactNode;
  /** 数字上标（如未读数）；渲染在 label 右侧 */
  badge?: ReactNode;
};

export type PanelTabsProps = {
  tabs: PanelTab[];
  activeId?: string;
  onChange?: (id: string) => void;
};

export function PanelTabs({ tabs, activeId, onChange }: PanelTabsProps) {
  const [inner, setInner] = useState(tabs[0]?.id ?? "");
  const active = activeId ?? inner;

  const items = useMemo(
    () => tabs.map((tab) => ({ key: tab.id, label: tab.label, badge: tab.badge })),
    [tabs],
  );
  const panels = useMemo(() => {
    const out: Record<string, ReactNode> = {};
    for (const tab of tabs) out[tab.id] = tab.content;
    return out;
  }, [tabs]);

  function select(id: string) {
    if (activeId === undefined) setInner(id);
    onChange?.(id);
  }

  return (
    <div className="ws-tabs-wrap">
      <Tabs
        items={items}
        value={active}
        onChange={select}
        variant="line"
        panels={panels}
        panelClassName="ws-tab-body"
      />
    </div>
  );
}
