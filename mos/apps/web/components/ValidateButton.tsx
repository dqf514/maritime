"use client";

// B3 三色校验按钮（IMOS 同款）：绿=通过 / 黄=有警告可继续 / 红=阻断。
// 用法：<ValidateButton onValidate={() => issues} />
// issues 为空 → 绿；仅 warn → 黄（可继续）；存在 error → 红（阻断保存）。

import { useState } from "react";
import { useI18n } from "@/lib/i18n";

export type ValidateIssue = { level: "error" | "warn"; message: string };

type Props = {
  onValidate: () => ValidateIssue[] | Promise<ValidateIssue[]>;
  disabled?: boolean;
  className?: string;
};

export function ValidateButton({ onValidate, disabled, className }: Props) {
  const { t } = useI18n();
  const [issues, setIssues] = useState<ValidateIssue[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);

  const errors = issues?.filter((i) => i.level === "error").length ?? 0;
  const warns = issues?.filter((i) => i.level === "warn").length ?? 0;
  const tone = issues === null ? undefined : errors > 0 ? "danger" : warns > 0 ? "warn" : "ok";

  async function run() {
    setBusy(true);
    try {
      const result = await onValidate();
      setIssues(result);
      setOpen(true);
    } finally {
      setBusy(false);
    }
  }

  const label =
    tone === "ok"
      ? t("validate.ok", "Passed")
      : tone === "warn"
        ? t("validate.warn", "{n} warning(s)", { n: warns })
        : tone === "danger"
          ? t("validate.err", "{n} blocking issue(s)", { n: errors })
          : t("validate.run", "Validate");

  return (
    <span className={`validate-wrap${className ? ` ${className}` : ""}`}>
      <button
        type="button"
        className={`btn btn-sm validate-btn${tone ? ` validate-btn--${tone}` : ""}`}
        disabled={disabled || busy}
        title={t("validate.hint", "Run checks: green = pass, amber = warnings, red = blocking")}
        onClick={() => {
          if (open && issues !== null) setOpen(false);
          else void run();
        }}
      >
        {busy ? t("common.loading", "…") : label}
      </button>
      {open && issues !== null ? (
        <div className={`validate-pop validate-pop--${tone ?? "info"}`} role="status">
          {issues.length === 0 ? (
            <div className="validate-line">{t("validate.all_clear", "All checks passed.")}</div>
          ) : (
            issues.map((i, idx) => (
              <div key={idx} className={`validate-line validate-line--${i.level}`}>
                {i.level === "error" ? "⛔ " : "⚠ "}
                {i.message}
              </div>
            ))
          )}
        </div>
      ) : null}
    </span>
  );
}
