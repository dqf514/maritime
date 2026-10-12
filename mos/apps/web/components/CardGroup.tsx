"use client";

// 详情页卡片分组（IMOS Card Group）：组头 + 折叠 + 错误/警告指示点。
// 详情页字段必须按业务分组包裹在 CardGroup 内，禁止裸堆表单。

import { ReactNode, useState } from "react";

type Props = {
  title: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  /** 组内校验错误数（红点 + 计数） */
  errors?: number;
  /** 组内警告数（黄点 + 计数） */
  warnings?: number;
  /** 组头右侧（链接、开关等） */
  right?: ReactNode;
  className?: string;
};

export function CardGroup({ title, children, defaultOpen = true, errors = 0, warnings = 0, right, className }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const hasIssue = errors > 0 || warnings > 0;
  return (
    <section className={`card-group${open ? " open" : ""}${className ? ` ${className}` : ""}`}>
      <div className="card-group-head">
        <button
          type="button"
          className="card-group-toggle"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          <span className={`card-group-caret${open ? " open" : ""}`} aria-hidden>
            ▸
          </span>
          <span className="card-group-title">{title}</span>
          {errors > 0 ? <span className="card-group-err" title={`${errors} error(s)`}>{errors}</span> : null}
          {warnings > 0 ? <span className="card-group-warn" title={`${warnings} warning(s)`}>{warnings}</span> : null}
        </button>
        {right ? <div className="card-group-right">{right}</div> : null}
        {hasIssue && !open ? <span className="card-group-issue-dot" aria-hidden /> : null}
      </div>
      {open ? <div className="card-group-body">{children}</div> : null}
    </section>
  );
}
