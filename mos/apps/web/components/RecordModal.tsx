"use client";

import { FormEvent, ReactNode, useState } from "react";
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

/** Shared record drawer/modal — edit & delete live here, not in table rows. */
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
  if (!open) return null;

  return (
    <div className="record-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="record-modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
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
}
