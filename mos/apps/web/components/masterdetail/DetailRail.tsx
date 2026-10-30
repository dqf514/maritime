"use client";

// 详情页左窄导航（IMOS 式清单收窄）。
//
// 每条记录一张卡：粗体标题 + 1~2 行副信息（类型 · 国家 / 状态 · 到期日）。
// 当前记录高亮 + 左侧色条；键盘 ↑↓/Home/End 在条目间移动，Enter 原生跳转；
// 选中项自动滚入可视区。
//
// 注意：卡片必须 prefetch={false} —— 一屏几十个 <Link> 会被 Next 预取，
// 进视口就打出几十个 RSC 请求。

import Link from "next/link";
import { KeyboardEvent, useEffect, useRef } from "react";

export type RailItem = {
  id: string;
  /** 粗体标题行 */
  title: string;
  /** 1~2 行次要信息 */
  meta?: string[];
  /** 目标详情路由 */
  href: string;
};

export type DetailRailProps = {
  items: RailItem[];
  /** 当前打开的记录 id */
  activeId?: string | null;
  /** 栏标题（如 "Voyages · 128"） */
  title?: string;
  /** 「← 返回列表」链接（带列表的筛选状态） */
  backHref?: string;
  backLabel?: string;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  emptyText?: string;
  /** 追加到 .md-rail 的 class */
  className?: string;
};

export function DetailRail({
  items,
  activeId,
  title,
  backHref,
  backLabel = "Back to list",
  loading,
  error,
  onRetry,
  emptyText = "No records",
  className,
}: DetailRailProps) {
  const listRef = useRef<HTMLUListElement>(null);

  // 选中项滚入可视区（左栏独立滚动容器）
  useEffect(() => {
    const active = listRef.current?.querySelector('[aria-current="page"]');
    active?.scrollIntoView({ block: "nearest" });
  }, [activeId, items.length]);

  function onKeyDown(e: KeyboardEvent<HTMLUListElement>) {
    const nodes = Array.from(
      listRef.current?.querySelectorAll<HTMLAnchorElement>("[data-rail-item]") ?? [],
    );
    if (!nodes.length) return;
    const i = nodes.indexOf(document.activeElement as HTMLAnchorElement);
    if (e.key === "ArrowDown" || e.key === "ArrowRight") {
      e.preventDefault();
      nodes[Math.min(i + 1, nodes.length - 1)]?.focus();
    } else if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
      e.preventDefault();
      nodes[Math.max(i - 1, 0)]?.focus();
    } else if (e.key === "Home") {
      e.preventDefault();
      nodes[0]?.focus();
    } else if (e.key === "End") {
      e.preventDefault();
      nodes[nodes.length - 1]?.focus();
    }
  }

  return (
    <nav className={className ? `md-rail ${className}` : "md-rail"} aria-label={title || backLabel}>
      <div className="md-rail-head">
        {backHref ? (
          <Link className="md-back" href={backHref} prefetch={false}>
            <span aria-hidden>←</span> {backLabel}
          </Link>
        ) : null}
        {title ? <span className="md-rail-title">{title}</span> : null}
      </div>
      <div className="md-rail-body">
        {loading ? <p className="md-rail-note">Loading…</p> : null}
        {error ? (
          <div className="md-rail-note md-rail-err">
            <span>{error}</span>
            {onRetry ? (
              <button type="button" className="btn btn-sm" onClick={onRetry}>
                Retry
              </button>
            ) : null}
          </div>
        ) : null}
        {!loading && !error && !items.length ? (
          <p className="md-rail-note">{emptyText}</p>
        ) : null}
        <ul className="md-list" role="list" ref={listRef} onKeyDown={onKeyDown}>
          {items.map((it) => (
            <li key={it.id}>
              <Link
                className="md-card"
                href={it.href}
                prefetch={false}
                data-rail-item
                aria-current={it.id === activeId ? "page" : undefined}
              >
                <span className="md-card-title">{it.title}</span>
                {it.meta && it.meta.length ? (
                  <span className="md-card-meta">{it.meta.filter(Boolean).join(" · ")}</span>
                ) : null}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </nav>
  );
}
