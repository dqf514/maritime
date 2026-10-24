"use client";

import { useEffect, useRef } from "react";
import { useI18n } from "@/lib/i18n";

type Props = {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

/**
 * Controlled confirm dialog — replaces window.confirm.
 *
 * Usage (store the pending action, run it on confirm):
 *
 *   const [pending, setPending] = useState<(() => void) | null>(null);
 *   ...
 *   <button onClick={() => setPending(() => () => doDelete(id))}>删除</button>
 *   <ConfirmDialog
 *     open={Boolean(pending)}
 *     title={t("common.confirm", "确认操作")}
 *     message={t("common.confirm_delete", "Delete this record?")}
 *     danger
 *     onConfirm={() => { const fn = pending; setPending(null); fn?.(); }}
 *     onCancel={() => setPending(null)}
 *   />
 */
export function ConfirmDialog({ open, title, message, confirmLabel, danger, onConfirm, onCancel }: Props) {
  const { t } = useI18n();
  const confirmRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    // 焦点陷阱 + 焦点归还（WCAG 2.4.3 / 2.4.7）：打开时把焦点收进对话框，
    // 关闭时还给触发它的那个按钮。
    triggerRef.current = document.activeElement as HTMLElement | null;
    confirmRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onCancel();
        return;
      }
      if (e.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => el.offsetParent !== null || el === document.activeElement,
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      triggerRef.current?.focus?.();
      triggerRef.current = null;
    };
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div
      className="record-modal-backdrop confirm-backdrop"
      role="presentation"
      onClick={(e) => {
        e.stopPropagation();
        onCancel();
      }}
    >
      <div
        ref={dialogRef}
        className="record-modal confirm-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="record-modal-head">
          <h2>{title}</h2>
          <button type="button" className="icon-btn record-modal-x" onClick={onCancel} aria-label={t("common.close", "关闭")}>
            ×
          </button>
        </header>
        <div className="record-modal-body">
          <p className="confirm-message">{message}</p>
          <footer className="record-modal-foot">
            <span />
            <div className="record-modal-actions">
              <button type="button" className="btn btn-ghost" onClick={onCancel}>
                {t("common.cancel", "取消")}
              </button>
              <button
                type="button"
                ref={confirmRef}
                className={danger ? "btn btn-danger" : "btn btn-primary"}
                onClick={onConfirm}
              >
                {confirmLabel || t("common.confirm", "确认")}
              </button>
            </div>
          </footer>
        </div>
      </div>
    </div>
  );
}
