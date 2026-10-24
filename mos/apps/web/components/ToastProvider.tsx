"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useState, ReactNode } from "react";
import { useI18n } from "@/lib/i18n";

type ToastKind = "success" | "error" | "warning" | "info";

type ToastEntry = {
  id: number;
  kind: ToastKind;
  msg: string;
  action?: string;
  onAction?: () => void;
  exiting?: boolean;
};

type ToastOptions = {
  action?: string;
  onAction?: () => void;
};

type ToastCtx = {
  success: (msg: string, opts?: ToastOptions) => void;
  error: (msg: string, opts?: ToastOptions) => void;
  warning: (msg: string, opts?: ToastOptions) => void;
  info: (msg: string, opts?: ToastOptions) => void;
};

const Ctx = createContext<ToastCtx | null>(null);

const ICONS: Record<ToastKind, string> = {
  success: "✓",
  error: "✕",
  warning: "!",
  info: "i",
};

const AUTO_MS: Record<ToastKind, number> = {
  success: 3000,
  error: 0,
  warning: 4000,
  info: 3000,
};

const MAX_VISIBLE = 5;

export function ToastProvider({ children }: { children: ReactNode }) {
  // 注意：渲染时 map 的回调参数也叫 t，这里把翻译函数改名 tr 避免遮蔽。
  const { t: tr } = useI18n();
  const [toasts, setToasts] = useState<ToastEntry[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.map((t) => (t.id === id ? { ...t, exiting: true } : t)));
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 150);
  }, []);

  const push = useCallback(
    (kind: ToastKind, msg: string, opts?: ToastOptions) => {
      const id = nextId.current++;
      setToasts((prev) => {
        const next = [...prev, { id, kind, msg, action: opts?.action, onAction: opts?.onAction }];
        if (next.length <= MAX_VISIBLE) return next;
        // 溢出时优先丢弃最旧的**非错误**提示 —— 错误提示不自动消失，最该被留住。
        const dropIdx = next.findIndex((t) => t.kind !== "error");
        if (dropIdx >= 0) next.splice(dropIdx, 1);
        else next.splice(0, next.length - MAX_VISIBLE);
        return next;
      });

      const autoMs = AUTO_MS[kind];
      if (autoMs > 0) {
        setTimeout(() => dismiss(id), autoMs);
      }
    },
    [dismiss],
  );

  // context value 必须稳定：否则任何一次 toast 都会让所有 useToast() 的页面重渲染。
  const ctx: ToastCtx = useMemo(
    () => ({
      success: (msg, opts) => push("success", msg, opts),
      error: (msg, opts) => push("error", msg, opts),
      warning: (msg, opts) => push("warning", msg, opts),
      info: (msg, opts) => push("info", msg, opts),
    }),
    [push],
  );

  return (
    <Ctx.Provider value={ctx}>
      {children}
      <div className="toast-container" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.kind}${t.exiting ? " toast-exit" : ""}`} role="alert">
            <span className="toast-icon">{ICONS[t.kind]}</span>
            <div className="toast-body">
              <span className="toast-msg">{t.msg}</span>
              {t.action && t.onAction && (
                <button
                  type="button"
                  className="toast-action"
                  onClick={() => {
                    t.onAction?.();
                    dismiss(t.id);
                  }}
                >
                  {t.action}
                </button>
              )}
            </div>
            <button
              type="button"
              className="toast-close"
              onClick={() => dismiss(t.id)}
              aria-label={tr("common.close", "Close")}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast(): ToastCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useToast must be used within <ToastProvider>");
  return ctx;
}
