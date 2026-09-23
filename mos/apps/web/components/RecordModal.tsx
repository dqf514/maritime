"use client";

import { FormEvent, ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useI18n } from "@/lib/i18n";

type Props = {
  open: boolean;
  title: string;
  onClose: () => void;
  onSave?: (e: FormEvent) => void | Promise<void>;
  onDelete?: () => void | Promise<void>;
  canEdit?: boolean;
  canDelete?: boolean;
  saving?: boolean;
  children: ReactNode;
};

const FOCUSABLE = 'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

export function RecordModal({
  open,
  title,
  onClose,
  onSave,
  onDelete,
  canEdit = true,
  canDelete = true,
  saving,
  children,
}: Props) {
  const { t } = useI18n();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const modalRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<Element | null>(null);

  useEffect(() => {
    if (open) {
      triggerRef.current = document.activeElement;
      document.body.style.overflow = "hidden";

      requestAnimationFrame(() => {
        const el = modalRef.current;
        if (!el) return;
        const focusable = el.querySelectorAll<HTMLElement>(FOCUSABLE);
        if (focusable.length) focusable[0].focus();
      });
    }

    return () => {
      if (!open) return;
      document.body.style.overflow = "";
      if (triggerRef.current instanceof HTMLElement) {
        triggerRef.current.focus();
      }
      triggerRef.current = null;
    };
  }, [open]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key === "Tab" && modalRef.current) {
        const focusable = modalRef.current.querySelectorAll<HTMLElement>(FOCUSABLE);
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
    },
    [onClose],
  );

  if (!open) return null;

  const content = (
    <div className="record-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        ref={modalRef}
        className="record-modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        <header className="record-modal-head">
          <h2>{title}</h2>
          <button type="button" className="icon-btn record-modal-x" onClick={onClose} aria-label={t("common.close", "关闭")}>
            ×
          </button>
        </header>
        <form
          className="record-modal-body"
          onSubmit={(e) => {
            e.preventDefault();
            if (canEdit && onSave) onSave(e);
          }}
        >
          {children}
          <footer className="record-modal-foot">
            {canDelete && onDelete ? (
              <button
                type="button"
                className="btn btn-danger"
                disabled={saving}
                onClick={() => setConfirmDelete(true)}
              >
                {t("common.delete", "Delete")}
              </button>
            ) : (
              <span />
            )}
            <div className="record-modal-actions">
              <button type="button" className="btn btn-ghost" onClick={onClose}>
                {t("common.cancel", "取消")}
              </button>
              {canEdit && onSave ? (
                <button type="submit" className="btn btn-primary" disabled={saving}>
                  {saving ? "…" : t("common.save", "保存")}
                </button>
              ) : null}
            </div>
          </footer>
        </form>
        <ConfirmDialog
          open={confirmDelete}
          title={t("common.confirm", "确认操作")}
          message={t("common.confirm_delete", "Delete this record? It will move to the recycle bin and can be restored.")}
          danger
          onConfirm={() => {
            setConfirmDelete(false);
            onDelete?.();
          }}
          onCancel={() => setConfirmDelete(false)}
        />
      </div>
    </div>
  );

  return createPortal(content, document.body);
}
