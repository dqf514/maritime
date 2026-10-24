"use client";

import { Component, ReactNode } from "react";
import { useI18n } from "@/lib/i18n";

type Props = {
  children: ReactNode;
  fallback?: ReactNode | ((error: Error, retry: () => void) => ReactNode);
};

type State = {
  error: Error | null;
};

/** 内层类组件额外接收外层从词表取好的文案（类组件里不能用 hook）。 */
type InnerProps = Props & {
  title: string;
  detail: string;
  retryLabel: string;
  homeLabel: string;
};

class ErrorBoundaryInner extends Component<InnerProps, State> {
  constructor(props: InnerProps) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: { componentStack: string }) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  retry = () => {
    this.setState({ error: null });
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    if (this.props.fallback) {
      if (typeof this.props.fallback === "function") {
        return this.props.fallback(error, this.retry);
      }
      return this.props.fallback;
    }

    return (
      <div className="error-boundary">
        <div className="error-boundary-icon" aria-hidden="true">
          ✕
        </div>
        <h2 className="error-boundary-title">{this.props.title}</h2>
        <p className="error-boundary-msg">{error.message || this.props.detail}</p>
        <div className="error-boundary-actions">
          <button type="button" className="btn btn-primary" onClick={this.retry}>
            {this.props.retryLabel}
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => {
              window.location.href = "/home";
            }}
          >
            {this.props.homeLabel}
          </button>
        </div>
      </div>
    );
  }
}

/**
 * 错误边界。
 *
 * 必须挂在 I18nProvider **内部**（见 app/providers.tsx），否则这里拿不到词表、
 * 只能显示硬编码英文（审计项：ErrorBoundary 在 I18nProvider 之外无法 t()）。
 * 放在内部后仍能兜住 I18nProvider 以下的整棵树。
 */
export function ErrorBoundary({ children, fallback }: Props) {
  const { t } = useI18n();
  return (
    <ErrorBoundaryInner
      fallback={fallback}
      title={t("error.boundary_title", "Something went wrong")}
      detail={t("error.boundary_detail", "An unexpected error occurred.")}
      retryLabel={t("common.retry", "Retry")}
      homeLabel={t("error.go_home", "Go Home")}
    >
      {children}
    </ErrorBoundaryInner>
  );
}
