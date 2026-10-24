"use client";

// 状态机动作可见性（IMOS G6）：从 /meta/transitions 拉全量转移表，
// 详情页只渲染当前状态可执行的动作 — 非法动作不出现，而非点击后 409。
//
// 取数失败必须可见：转移表拉不到时不能静默地「没有可用动作」，
// useTransitionTable 暴露 error，页面据此给出提示与重试。

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet } from "@/lib/api";
import { msgOf } from "@/lib/errors";

type Transitions = Record<string, Record<string, string[]>>;

let cache: Transitions | null = null;
let inflight: Promise<Transitions> | null = null;

function fetchTransitions(): Promise<Transitions> {
  if (cache) return Promise.resolve(cache);
  if (!inflight) {
    inflight = apiGet("/api/v1/meta/transitions")
      .then((rows) => {
        cache = rows as Transitions;
        return cache;
      })
      .catch((err) => {
        inflight = null;
        throw err;
      });
  }
  return inflight;
}

/**
 * 转移表取数状态。
 * - table：转移表（未取到为 null）
 * - error：取数失败原因（null 表示成功或仍在加载）
 * - loading：是否正在取数
 * - reload：重新取数（失败后重试用）
 */
export function useTransitionTable() {
  const [table, setTable] = useState<Transitions | null>(cache);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!cache);

  /** 统一落库：成功 → 清 error，失败 → 记 error，两者都结束 loading。 */
  const apply = useCallback((next: Transitions | null, err: string | null) => {
    setTable(next);
    setError(err);
    setLoading(false);
  }, []);

  /** 重新取数（失败后重试用）。返回取消函数。 */
  const reload = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    fetchTransitions()
      .then((t) => {
        if (!cancelled) apply(t, null);
      })
      .catch((ex) => {
        if (!cancelled) apply(null, msgOf(ex));
      });
    return () => {
      cancelled = true;
    };
  }, [apply]);

  useEffect(() => {
    // 首次挂载：拉一次（不在 effect body 里同步 setState）
    if (cache) return;
    let cancelled = false;
    fetchTransitions()
      .then((t) => {
        if (!cancelled) apply(t, null);
      })
      .catch((ex) => {
        if (!cancelled) apply(null, msgOf(ex));
      });
    return () => {
      cancelled = true;
    };
  }, [apply]);

  return { table, error, loading, reload };
}

/** 某实体当前状态下允许迁移到的目标状态列表（加载前返回 []） */
export function useStateActions(entity: string, status: string | undefined): string[] {
  const { table } = useTransitionTable();

  return useMemo(() => {
    if (!table || !entity || !status) return [];
    return table[entity]?.[status] ?? [];
  }, [table, entity, status]);
}
