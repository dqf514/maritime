"use client";

import { createContext, useCallback, useContext, useRef, useState, ReactNode } from "react";

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
  const [toasts, setToasts] = useState<ToastEntry[]>([]);
  const nextId = useRef(1);

  const push = useCallback((kind: ToastKind, msg: string, opts?: ToastOptions) => {
    const id = nextId.current++;
    setToasts((prev) => {
      const next = [...prev, { id, kind, msg, action: opts?.action, onAction: opts?.onAction }];
      return next.length > MAX_VISIBLE ? next.slice(-MAX_VISIBLE) : next;
    });

    const autoMs = AUTO_MS[kind];
    if (autoMs > 0) {
      setTimeout(() => dismiss(id), autoMs);
    }
  }, []);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.map((t) => (t.id === id ? { ...t, exiting: true } : t)));
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 150);
  }, []);

  const ctx: ToastCtx = {
    success: (msg, opts) => push("success", msg, opts),
    error: (msg, opts) => push("error", msg, opts),
    warning: (msg, opts) => push("warning", msg, opts),
    info: (msg, opts) => push("info", msg, opts),
  };

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
                    t.onAction();
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
              aria-label="Close"
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
