"use client";

// 模态对话框的焦点陷阱（focus trap）+ 焦点归还（focus restore）。
//
// 统一从 RecordModal / ConfirmDialog 里成熟的那套实现抽出来，供所有
// `aria-modal="true"` 的对话框复用：
//   1. 打开时把焦点移进对话框（第一个可聚焦元素）；
//   2. Tab / Shift+Tab 在对话框内循环，不会跑到背后的页面上；
//   3. 关闭时把焦点还给打开它的那个元素。
//
// 用法：
//   const ref = useFocusTrap<HTMLDivElement>(open);
//   <div ref={ref} role="dialog" aria-modal="true" onKeyDown={onKeyDown}>…</div>
//
// `onKeyDown` 由 hook 返回：调用方把它挂在对话框容器上即可。
//
// `skipRestoreRef`：非模态浮层（如下拉菜单）在「点击别处关闭」时不想抢回焦点，
// 关闭前把 skipRestoreRef.current 设为 true 即可。

import { useCallback, useEffect, useRef, type KeyboardEvent as ReactKeyboardEvent } from "react";

const FOCUSABLE =
  'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

export function useFocusTrap<T extends HTMLElement = HTMLDivElement>(open: boolean) {
  const ref = useRef<T | null>(null);
  const triggerRef = useRef<HTMLElement | null>(null);
  /**
   * 置为 true 可抑制「关闭时归还焦点」。
   * 用于「点击别处关闭」的下拉菜单：此时用户已经把焦点点到别处了，
   * 再抢回焦点反而是干扰。关闭前把 skipRestoreRef.current 设为 true 即可。
   */
  const skipRestoreRef = useRef(false);

  // 打开：记住触发元素 + 移入焦点；关闭：归还焦点
  useEffect(() => {
    if (!open) return;
    const trigger =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    triggerRef.current = trigger;
    const raf = requestAnimationFrame(() => {
      const el = ref.current;
      if (!el) return;
      const focusable = el.querySelectorAll<HTMLElement>(FOCUSABLE);
      if (focusable.length) focusable[0].focus();
      else el.focus();
    });
    return () => {
      cancelAnimationFrame(raf);
      const t = triggerRef.current;
      triggerRef.current = null;
      const skip = skipRestoreRef.current;
      skipRestoreRef.current = false;
      if (!skip && t && t.isConnected) t.focus();
    };
  }, [open]);

  const onKeyDown = useCallback((e: ReactKeyboardEvent) => {
    if (e.key !== "Tab") return;
    const el = ref.current;
    if (!el) return;
    const focusable = Array.from(el.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
      (n) => n.offsetParent !== null || n === document.activeElement,
    );
    if (!focusable.length) {
      e.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement as HTMLElement | null;
    if (e.shiftKey && (active === first || !el.contains(active))) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (active === last || !el.contains(active))) {
      e.preventDefault();
      first.focus();
    }
  }, []);

  return { ref, onKeyDown, skipRestoreRef };
}
