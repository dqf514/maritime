"use client";

import { useEffect, useSyncExternalStore } from "react";

/**
 * 全局 AI 上下文 store —— 页面/实体告诉助手「用户正对着什么」。
 *
 * 助手面板打开时读取当前上下文注入 prompt；实体页用 `useAiContextBinder`
 * 在挂载时写入、卸载时清除。极简 module-level 单例：无需 provider。
 */

export type AiContext = {
  page?: string;
  entity_type?: string;
  entity_id?: string;
  form_fields?: Record<string, unknown>;
  selected_text?: string;
  captured_at?: string;
};

let current: AiContext | null = null;
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

export function setAiContext(ctx: AiContext | null) {
  current = ctx ? { ...ctx, captured_at: new Date().toISOString() } : null;
  emit();
}

/** 合并式更新（路由变化时只改 page，保留 entity）。 */
export function patchAiContext(patch: Partial<AiContext>) {
  current = { ...(current || {}), ...patch, captured_at: new Date().toISOString() };
  emit();
}

export function getAiContext(): AiContext | null {
  return current;
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

export function useAiContext(): AiContext | null {
  return useSyncExternalStore(subscribe, getAiContext, () => null);
}

/**
 * 在实体页挂载时绑定上下文，卸载时清除。
 * `entity_id` 为空时只记录页面路径（避免把空记录塞给助手）。
 */
export function useAiContextBinder(input: {
  entity_type?: string;
  entity_id?: string | null;
  page?: string;
}) {
  const { entity_type, entity_id, page } = input;
  const key = `${entity_type || ""}:${entity_id || ""}:${page || ""}`;

  useEffect(() => {
    if (!entity_type || !entity_id) {
      setAiContext({ page: page || window.location.pathname });
      return () => setAiContext(null);
    }
    setAiContext({
      entity_type,
      entity_id,
      page: page || window.location.pathname,
    });
    return () => setAiContext(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
}
