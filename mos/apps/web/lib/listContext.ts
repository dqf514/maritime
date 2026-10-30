"use client";

// 列表上下文 —— 让「详情页 → 回列表」这一跳不丢筛选/排序/页码。
//
// 机制：列表页把当前 URL 查询串镜像进 sessionStorage（键 = 列表路由）；
// 详情页生成回列表链接时把这份查询串带上 —— 列表页直接按 URL 恢复筛选，
// 不需要额外标记（早先的 from=detail 标记已删：它只是噪声，还会和列表页
// 自己的 setQuery 抢路由，把标记又带回来）。
//
// 为什么不用 router.back()：深链进来时它会把用户带出应用，而且列表组件
// 是重新挂载的，React state 里的筛选/排序照样丢。
//
// 为什么不用 useSearchParams：详情页有些不在 Suspense 边界内，用它会被迫
// 加边界；这里读 window.location.search（仅在 effect 里），无此问题。

import { useEffect, useState } from "react";

const TTL_MS = 30 * 60 * 1000; // 上下文过期后不再恢复
const KEY_PREFIX = "marios_liststate:";

export type ListContext = {
  /** 列表视图状态（URL 查询串形态） */
  qs: string;
  at: number;
};

const keyOf = (route: string) => KEY_PREFIX + route;

export function publishListContext(route: string, ctx: { qs: string }): void {
  try {
    sessionStorage.setItem(keyOf(route), JSON.stringify({ ...ctx, at: Date.now() }));
  } catch {
    // 隐私模式 / 配额满：忽略，不影响主流程
  }
}

export function peekListContext(route: string): ListContext | null {
  try {
    const raw = sessionStorage.getItem(keyOf(route));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ListContext;
    if (!parsed || typeof parsed !== "object") return null;
    if (Date.now() - (parsed.at ?? 0) > TTL_MS) {
      sessionStorage.removeItem(keyOf(route));
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function splitHref(href: string): [string, URLSearchParams] {
  const [path, qs = ""] = href.split("?");
  return [path, new URLSearchParams(qs)];
}

/**
 * 回列表链接 = 基础 href + 列表上下文的查询串。
 * 基础 href 自带的参数优先（tab/type 这类不能被上下文覆盖）。
 */
export function buildBackHref(baseHref: string): string {
  const [path, sp] = splitHref(baseHref);
  const ctx = peekListContext(path);
  if (ctx?.qs) {
    for (const [k, v] of new URLSearchParams(ctx.qs)) {
      if (!sp.has(k)) sp.set(k, v);
    }
  }
  const qs = sp.toString();
  return qs ? `${path}?${qs}` : path;
}

/**
 * 详情页用：返回列表 href（带列表的筛选/排序/页码）。
 * 首帧用不含上下文的 href（与 SSR 一致，避免 hydration 不一致），挂载后补齐。
 */
export function useListBackHref(baseHref: string): string {
  const [href, setHref] = useState(() => baseHref);
  useEffect(() => {
    setHref(buildBackHref(baseHref));
  }, [baseHref]);
  return href;
}
