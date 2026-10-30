"use client";

// 左栏取数 —— 兄弟记录清单。
//
// 为什么由「页面」调用而不是由外壳自己取数：
//   * 左栏的作用域通常 ≠ 列表页的作用域（发票详情页的左栏是全部发票，
//     列表却挂在财务中枢的 tab 里分页）；
//   * 当前记录可能在第 3 页，列表页自己的那一次取数给不出它；
//   * 页面已经掌握了取数口径（筛选条件、字段映射），外壳不该替它猜。
//
// 缓存：模块级 TTL 缓存（60s），键 = endpoint + 参数。连点 20 条兄弟记录
// 只打 1 次请求，不是 20 次。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiGet } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import type { RailItem } from "@/components/masterdetail/DetailRail";

export type RailSource<T> = {
  /** 后端列表端点，如 "/api/v1/invoices" */
  endpoint: string;
  /** 额外查询参数（作用域） */
  params?: Record<string, string | number | null | undefined>;
  /** 行 → 左栏条目；返回 null 表示跳过该行 */
  mapRow: (row: T) => RailItem | null;
  /** 条数上限（默认 100） */
  limit?: number;
  /** 端点不直接返回数组时，从响应里挑出「行数组」（如帮助中心的 catalog） */
  pick?: (data: unknown) => T[];
};

type CacheEntry = { at: number; items: RailItem[] };
const CACHE = new Map<string, CacheEntry>();
const TTL_MS = 60_000;

export function useRailItems<T>(src: RailSource<T>) {
  const mapRef = useRef(src.mapRow);
  const pickRef = useRef(src.pick);
  // 回调随渲染变化 —— 同步进 ref 只能在 effect 中做（render 中写 ref 违反 react-hooks/refs）。
  // 声明在取数 effect 之前：effect 按声明顺序执行，同一 commit 内先同步再取数。
  useEffect(() => {
    mapRef.current = src.mapRow;
    pickRef.current = src.pick;
  });

  const key = useMemo(
    () => `${src.endpoint}|${JSON.stringify(src.params ?? {})}|${src.limit ?? 100}|${src.pick ? "pick" : "rows"}`,
    [src.endpoint, src.params, src.limit, src.pick],
  );

  const [items, setItems] = useState<RailItem[]>(() => CACHE.get(key)?.items ?? []);
  const [loading, setLoading] = useState(() => !CACHE.has(key));
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let alive = true;
    const cached = CACHE.get(key);
    if (cached && Date.now() - cached.at < TTL_MS) {
      setItems(cached.items);
      setLoading(false);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(src.params ?? {})) {
      if (v !== null && v !== undefined && v !== "") qs.set(k, String(v));
    }
    if (!src.pick) qs.set("limit", String(src.limit ?? 100));
    const url = qs.toString() ? `${src.endpoint}?${qs.toString()}` : src.endpoint;
    apiGet(url)
      .then((data) => {
        if (!alive) return;
        const rows: T[] = pickRef.current
          ? pickRef.current(data)
          : Array.isArray(data)
            ? (data as T[])
            : ((data as { items?: T[] })?.items ?? []);
        const mapped: RailItem[] = [];
        for (const row of rows ?? []) {
          const item = mapRef.current(row);
          if (item) mapped.push(item);
        }
        CACHE.set(key, { at: Date.now(), items: mapped });
        setItems(mapped);
        setLoading(false);
      })
      .catch((err) => {
        if (!alive) return;
        setError(msgOf(err, "Failed to load the list."));
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [key, nonce]);

  const reload = useCallback(() => {
    CACHE.delete(key);
    setNonce((n) => n + 1);
  }, [key]);

  return { items, loading, error, reload };
}

/**
 * 详情页左栏 = 兄弟清单 + 「当前记录」（若不在清单窗口内则补在末尾）。
 * 当前记录必须出现在左栏里 —— 否则深链进来时左栏高亮不到任何东西。
 */
export function useDetailRail<T>(src: RailSource<T>, current: RailItem | null) {
  const { items, loading, error, reload } = useRailItems(src);
  const merged = useMemo(() => {
    if (!current) return items;
    if (items.some((it) => it.id === current.id)) return items;
    return [...items, current];
  }, [items, current]);
  return { items: merged, loading, error, reload };
}
