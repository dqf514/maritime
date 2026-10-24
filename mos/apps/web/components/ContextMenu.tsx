"use client";

// 右键上下文菜单（IMOS 一等交互）。
// 用法：
//   const ctx = useContextMenu<CargoRow>();
//   <tr onContextMenu={ctx.open(row)} ... />
//   <ContextMenu controller={ctx} items={makeItems} />
// items 是回调：打开时按当前行生成动作列表，与工具栏共用同一 action 函数源。

import { ReactNode, useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useFocusTrap } from "@/components/useFocusTrap";

export type ContextMenuItem = {
  key: string;
  /** 分隔线时可省略 */
  label?: ReactNode;
  icon?: ReactNode;
  danger?: boolean;
  disabled?: boolean;
  /** 分隔线（传 divider: true） */
  divider?: boolean;
  onClick?: () => void;
};

type CtxState<T> = {
  x: number;
  y: number;
  target: T | null;
} | null;

export type ContextMenuController<T> = {
  state: CtxState<T>;
  /** 绑到行：onContextMenu={ctx.open(row)} */
  open: (target: T) => (e: React.MouseEvent) => void;
  close: () => void;
};

export function useContextMenu<T>(): ContextMenuController<T> {
  const [state, setState] = useState<CtxState<T>>(null);

  const open = useCallback((target: T) => (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const margin = 8;
    const x = Math.min(e.clientX, window.innerWidth - margin);
    const y = Math.min(e.clientY, window.innerHeight - margin);
    setState({ x, y, target });
  }, []);

  const close = useCallback(() => setState(null), []);

  return { state, open, close };
}

type Props<T> = {
  controller: ContextMenuController<T>;
  /** 生成菜单项；target 为右键目标 */
  items: (target: T) => ContextMenuItem[];
  /** 菜单宽度（默认 180） */
  width?: number;
};

export function ContextMenu<T>({ controller, items, width = 180 }: Props<T>) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);

  const st = controller.state;

  // 上下文菜单不是模态层：复用共享 hook 只做「打开时移入焦点 / 关闭时归还焦点」，
  // 不设 aria-modal；Tab 由 hook 在菜单内循环，方向键在菜单项之间移动。
  const { ref: menuRef, onKeyDown: trapKeyDown, skipRestoreRef } =
    useFocusTrap<HTMLDivElement>(!!st);

  useEffect(() => {
    if (!st) return;
    // 首次渲染后按实际尺寸翻转，避免超出视口
    const el = menuRef.current;
    if (el) {
      const r = el.getBoundingClientRect();
      const x = st.x + r.width > window.innerWidth - 4 ? Math.max(4, st.x - r.width) : st.x;
      const y = st.y + r.height > window.innerHeight - 4 ? Math.max(4, st.y - r.height) : st.y;
      setPos({ x, y });
    }
    const onDown = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) {
        // 用户已经点了别处，别再把焦点抢回菜单触发点
        skipRestoreRef.current = true;
        controller.close();
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") controller.close();
    };
    const onScroll = () => controller.close();
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [st, controller, menuRef, skipRestoreRef]);

  // 方向键在菜单项之间漫游（ARIA menu 模式）
  const onMenuKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Home" || e.key === "End") {
        const root = menuRef.current;
        if (!root) return;
        const nodes = Array.from(
          root.querySelectorAll<HTMLElement>('[role="menuitem"]:not([disabled])'),
        ).filter((n) => n.offsetParent !== null || n === document.activeElement);
        if (!nodes.length) return;
        e.preventDefault();
        const active = document.activeElement as HTMLElement | null;
        const idx = active ? nodes.indexOf(active) : -1;
        let next = 0;
        if (e.key === "Home") next = 0;
        else if (e.key === "End") next = nodes.length - 1;
        else if (e.key === "ArrowDown") next = idx < 0 ? 0 : (idx + 1) % nodes.length;
        else next = idx < 0 ? nodes.length - 1 : (idx - 1 + nodes.length) % nodes.length;
        nodes[next].focus();
        return;
      }
      trapKeyDown(e);
    },
    [menuRef, trapKeyDown],
  );

  if (!st) return null;

  const list = items(st.target as T);
  const at = pos ?? { x: st.x, y: st.y };

  return createPortal(
    <div
      ref={menuRef}
      className="context-menu"
      role="menu"
      tabIndex={-1}
      onKeyDown={onMenuKeyDown}
      // 打开瞬间可能超出视口，先隐藏一帧
      style={{ left: at.x, top: at.y, width, visibility: pos ? "visible" : "hidden" }}
    >
      {list.map((it, i) =>
        it.divider ? (
          <div key={`d-${i}`} className="context-menu-divider" role="separator" />
        ) : (
          <button
            key={it.key}
            type="button"
            role="menuitem"
            className={`context-menu-item${it.danger ? " danger" : ""}`}
            disabled={it.disabled}
            onClick={() => {
              controller.close();
              it.onClick?.();
            }}
          >
            {it.icon ? <span className="context-menu-icon">{it.icon}</span> : null}
            <span>{it.label}</span>
          </button>
        ),
      )}
    </div>,
    document.body,
  );
}
