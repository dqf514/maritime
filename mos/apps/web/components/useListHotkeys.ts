"use client";

// B6 列表页键盘效率：按 `N` 唤起新建（RecordModal / 整页 new 路由，IMOS Add Details 同款）。
// 输入框 / 文本域 / 可编辑元素聚焦时、或带修饰键时不触发。

import { useEffect, useRef } from "react";

export function useListHotkeys(onNew?: () => void) {
  const cbRef = useRef(onNew);
  // 回调可能随渲染变化，同步进 ref 只能在 effect 中做（render 中写 ref 违反 react-hooks/refs）。
  useEffect(() => {
    cbRef.current = onNew;
  }, [onNew]);

  useEffect(() => {
    if (!cbRef.current) return;
    function onKey(e: KeyboardEvent) {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key.toLowerCase() !== "n") return;
      const tgt = e.target as HTMLElement | null;
      if (tgt) {
        const tag = tgt.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || tgt.isContentEditable) return;
      }
      e.preventDefault();
      cbRef.current?.();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
