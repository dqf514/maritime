"use client";

// 密集表单布局：多列网格，替代单列 label 堆叠。
// 用法：<FormPanel><FormSection title="Basic"><label>…</label>…</FormSection></FormPanel>

import { ReactNode } from "react";

type FormPanelProps = {
  children: ReactNode;
  /** 列数：auto = 自适应，1/2/3 = 固定 */
  columns?: "auto" | 1 | 2 | 3;
  className?: string;
};

export function FormPanel({ children, columns = "auto", className = "" }: FormPanelProps) {
  const colClass = columns === "auto" ? "" : ` form-panel-${columns}col`;
  return <div className={`form-panel${colClass} ${className}`}>{children}</div>;
}

type FormSectionProps = {
  title?: string;
  children: ReactNode;
  /** 紧凑模式下标题与内容行间不留白 */
  dense?: boolean;
};

export function FormSection({ title, children, dense }: FormSectionProps) {
  return (
    <fieldset className={`form-section${dense ? " form-section-dense" : ""}`}>
      {title ? <legend className="form-section-title">{title}</legend> : null}
      <div className="form-section-body">{children}</div>
    </fieldset>
  );
}

/** 单个字段行：label + control 紧凑排列 */
export function FieldRow({ label, children, span }: { label: string; children: ReactNode; span?: number }) {
  return (
    <label className="field-row" style={span ? { gridColumn: `span ${span}` } : undefined}>
      <span className="field-label">{label}</span>
      {children}
    </label>
  );
}
