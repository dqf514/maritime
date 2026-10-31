"use client";

/**
 * 自绘文件选择控件。
 *
 * 原生 `<input type="file">` 的按钮文字（"选择文件 / 未选择文件"）由**浏览器
 * 界面语言**决定 —— 中文系统的 Chrome 在英文界面里也会显示中文。这里把原生
 * 控件藏起来，用 i18n 文案自绘按钮与文件名，文案跟着应用语言走。
 */

import { useRef } from "react";
import { useI18n } from "@/lib/i18n";

export function FilePicker({
  accept,
  file,
  onPick,
  disabled,
}: {
  /** 同原生 accept：".pdf,.png,image/*" */
  accept?: string;
  /** 当前已选文件（受控 —— 由调用方做大小/类型校验） */
  file: File | null;
  onPick: (file: File | null) => void;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  const inputRef = useRef<HTMLInputElement | null>(null);

  return (
    <span className="file-picker">
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
      >
        {t("common.choose_file", "Choose file")}
      </button>
      <span className="file-picker-name" title={file?.name || undefined}>
        {file?.name || t("common.no_file_selected", "No file selected")}
      </span>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="file-picker-input"
        disabled={disabled}
        onChange={(e) => {
          const picked = e.target.files?.[0] ?? null;
          onPick(picked);
          // 允许重新选择同一个文件（否则 onChange 不再触发）
          e.target.value = "";
        }}
      />
    </span>
  );
}
