"use client";

import { ReactNode, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useFocusTrap } from "@/components/useFocusTrap";
import { useI18n } from "@/lib/i18n";

type Props = {
  title: string;
  children: ReactNode;
  className?: string;
};

/**
 * 工作台区块：标题 + ⤢ 放大（局部放大为 modal 查看/操作）。
 * 子内容为受控组件时可在页内与放大弹层中同时渲染、状态共享。
 */
export function DeskSection({ title, children, className }: Props) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  // 模态放大层：焦点陷阱 + 关闭后焦点归还
  const { ref: modalRef, onKeyDown: trapKeyDown } = useFocusTrap<HTMLDivElement>(open);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className={className ? `desk-section ${className}` : "desk-section"}>
      <div className="desk-section-head">
        <h3>{title}</h3>
        <button
          type="button"
          className="icon-btn"
          onClick={() => setOpen(true)}
          title={t("page.common.expand", "放大")}
          aria-label={t("page.common.expand", "放大")}
        >
          ⤢
        </button>
      </div>
      {children}
      {open
        ? createPortal(
            <div className="record-modal-backdrop" role="presentation" onClick={() => setOpen(false)}>
              <div
                className="record-modal modal-xl"
                role="dialog"
                aria-modal="true"
                aria-label={title}
                ref={modalRef}
                onKeyDown={trapKeyDown}
                onClick={(e) => e.stopPropagation()}
              >
                <header className="record-modal-head">
                  <h2>{title}</h2>
                  <button
                    type="button"
                    className="icon-btn record-modal-x"
                    onClick={() => setOpen(false)}
                    aria-label={t("common.close", "关闭")}
                  >
                    ×
                  </button>
                </header>
                <div className="record-modal-body">{children}</div>
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
