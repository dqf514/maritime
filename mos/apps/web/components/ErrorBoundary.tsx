"use client";

import { Component, ReactNode } from "react";

type Props = {
  children: ReactNode;
  fallback?: ReactNode | ((error: Error, retry: () => void) => ReactNode);
};

type State = {
  error: Error | null;
};

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
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
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "1rem",
          padding: "3rem 1.5rem",
          minHeight: "50vh",
          color: "var(--ink)",
        }}
      >
        <div
          style={{
            width: 48,
            height: 48,
            borderRadius: "50%",
            background: "#fde8e6",
            color: "var(--danger)",
            display: "grid",
            placeItems: "center",
            fontSize: "1.4rem",
            fontWeight: 700,
          }}
        >
          ✕
        </div>
        <h2 style={{ margin: 0, fontSize: "1.15rem" }}>Something went wrong</h2>
        <p style={{ margin: 0, color: "var(--muted)", fontSize: "0.92rem", maxWidth: "32rem", textAlign: "center" }}>
          {error.message || "An unexpected error occurred."}
        </p>
        <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
          <button type="button" className="btn btn-primary" onClick={this.retry}>
            Retry
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => {
              window.location.href = "/home";
            }}
          >
            Go Home
          </button>
        </div>
      </div>
    );
  }
}
