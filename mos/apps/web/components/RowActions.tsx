"use client";

// RowActions — 全站统一的行内「编辑 / 删除」动作（dense 表格行尾动作列）。
// 删除走 ConfirmDialog 二次确认；调用方只负责实际的 apiPatch/apiDelete。

import { useState } from "react";
import { useI18n } from "@/lib/i18n";
import { ConfirmDialog } from "./ConfirmDialog";

type Props = {
  onEdit?: () => void;
  onDelete?: () => void | Promise<void>;
  canEdit?: boolean;
  canDelete?: boolean;
  /** 用于删除确认文案的行标识（如名称/编号） */
  label?: string;
};

export function RowActions({ onEdit, onDelete, canEdit = true, canDelete = true, label }: Props) {
  const { t } = useI18n();
  const [pending, setPending] = useState(false);

  return (
    <>
      <span className="row-actions">
        {canEdit && onEdit ? (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            title={t("common.edit", "Edit")}
            aria-label={t("common.edit", "Edit")}
            onClick={(e) => {
              e.stopPropagation();
              onEdit();
            }}
          >
            ✎
          </button>
        ) : null}
        {canDelete && onDelete ? (
          <button
            type="button"
            className="btn btn-ghost btn-sm row-action-danger"
            title={t("common.delete", "Delete")}
            aria-label={t("common.delete", "Delete")}
            onClick={(e) => {
              e.stopPropagation();
              setPending(true);
            }}
          >
            ✕
          </button>
        ) : null}
      </span>
      <ConfirmDialog
        open={pending}
        title={t("common.confirm", "Confirm")}
        message={
          label
            ? t("common.confirm_delete_named", 'Delete "{name}"?', { name: label })
            : t("common.confirm_delete", "Delete this record?")
        }
        danger
        confirmLabel={t("common.delete", "Delete")}
        onConfirm={() => {
          setPending(false);
          onDelete?.();
        }}
        onCancel={() => setPending(false)}
      />
    </>
  );
}
