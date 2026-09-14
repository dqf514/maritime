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

  useEffect(() => {
    if (!open) return;
    confirmRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCancel();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
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
