"use client";

// 标签面板组（Phase 2）：航次详情选用标签式布局，本组件为通用 tab strip。
// 受控（activeId + onChange）或非受控均可。

import { ReactNode, useState } from "react";

export type PanelTab = {
  id: string;
  label: ReactNode;
  content: ReactNode;
};

export type PanelTabsProps = {
  tabs: PanelTab[];
  activeId?: string;
  onChange?: (id: string) => void;
};

export function PanelTabs({ tabs, activeId, onChange }: PanelTabsProps) {
  const [inner, setInner] = useState(tabs[0]?.id ?? "");
  const active = activeId ?? inner;

  function select(id: string) {
    if (activeId === undefined) setInner(id);
    onChange?.(id);
  }

  const current = tabs.find((x) => x.id === active) ?? tabs[0];

  return (
    <div className="ws-tabs-wrap">
      <div className="ws-tabs" role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={tab.id === current?.id}
            className={`ws-tab${tab.id === current?.id ? " active" : ""}`}
            onClick={() => select(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {current ? (
        <div className="ws-tab-body" role="tabpanel">
          {current.content}
        </div>
      ) : null}
    </div>
  );
}
