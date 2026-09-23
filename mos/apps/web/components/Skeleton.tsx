"use client";

import { ReactNode } from "react";

type SkeletonProps = {
  width?: number | string;
  height?: number | string;
  className?: string;
};

export function Skeleton({ width, height = 16, className }: SkeletonProps) {
  const style: React.CSSProperties = {
    width: typeof width === "number" ? `${width}px` : width ?? "100%",
    height: typeof height === "number" ? `${height}px` : height,
  };
  return <span className={`skeleton${className ? ` ${className}` : ""}`} style={style} aria-hidden="true" />;
}

export function SkeletonCard({ children }: { children?: ReactNode }) {
  return (
    <div className="skeleton-card" aria-busy="true" aria-label="Loading">
      {children ?? (
        <>
          <Skeleton width={120} height={20} />
          <Skeleton width={80} height={32} />
          <Skeleton width={200} height={14} />
        </>
      )}
    </div>
  );
}

export function SkeletonTable({ rows = 5, columns = 4 }: { rows?: number; columns?: number }) {
  return (
    <table className="skeleton-table" aria-busy="true" aria-label="Loading">
      <thead>
        <tr>
          {Array.from({ length: columns }, (_, i) => (
            <th key={i}>
              <Skeleton height={14} />
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: rows }, (_, r) => (
          <tr key={r}>
            {Array.from({ length: columns }, (_, c) => (
              <td key={c}>
                <Skeleton height={14} width={`${60 + ((r + c) % 3) * 15}%`} />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function SkeletonForm({ rows = 6 }: { rows?: number }) {
  return (
    <div className="skeleton-form" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton-form-row">
          <Skeleton height={14} width={80 + (i % 3) * 10} />
          <Skeleton height={36} />
        </div>
      ))}
    </div>
  );
}
