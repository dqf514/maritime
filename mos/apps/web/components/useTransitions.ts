"use client";

// 状态机动作可见性（IMOS G6）：从 /meta/transitions 拉全量转移表，
// 详情页只渲染当前状态可执行的动作 — 非法动作不出现，而非点击后 409。

import { useEffect, useMemo, useState } from "react";
import { apiGet } from "@/lib/api";

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

/** 某实体当前状态下允许迁移到的目标状态列表（加载前返回 []） */
export function useStateActions(entity: string, status: string | undefined): string[] {
  const [table, setTable] = useState<Transitions | null>(cache);

  useEffect(() => {
    if (cache) return;
    fetchTransitions().then(setTable).catch(() => undefined);
  }, []);

  return useMemo(() => {
    if (!table || !entity || !status) return [];
    return table[entity]?.[status] ?? [];
  }, [table, entity, status]);
}
