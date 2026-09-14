"use client";

import { ReactNode } from "react";
import { useI18n } from "@/lib/i18n";

type Props = {
  loading: boolean;
  error?: string;
  empty: boolean;
  emptyText?: string;
  onRetry?: () => void;
  children: ReactNode;
};

/** Three-state container: loading spinner / error+retry / empty hint, else children. */
export function StateView({ loading, error, empty, emptyText, onRetry, children }: Props) {
  const { t } = useI18n();

  if (loading) {
    return (
      <div className="state-view" role="status">
        <span className="spinner" aria-hidden="true" />
        <span className="state-view-text">{t("common.loading", "加载中…")}</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="state-view" role="alert">
        <span className="state-view-text state-view-error">{error}</span>
        {onRetry ? (
          <button type="button" className="btn btn-ghost btn-sm" onClick={onRetry}>
            {t("common.retry", "重试")}
          </button>
        ) : null}
      </div>
    );
  }

  if (empty) {
    return (
      <div className="state-view">
        <span className="state-view-text muted">{emptyText || t("common.empty", "暂无记录")}</span>
      </div>
    );
  }

  return <>{children}</>;
}
