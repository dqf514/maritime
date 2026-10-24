"use client";

// 详情页头：标题 + 状态徽章 + 状态机动作按钮。
// 详情页必须使用本组件（或 DetailPageTemplate），动作区只渲染当前状态可执行项。

import { ReactNode } from "react";
import { PageHeader } from "@/components/PageHeader";
import { RecordAttribution } from "@/components/RecordAttribution";
import { StatusBadge, StatusTone } from "@/components/StatusBadge";
import { BreadcrumbItem } from "@/components/Breadcrumb";

export type DetailAction = {
  key: string;
  label: ReactNode;
  onClick?: () => void;
  /** primary = 实心主按钮（保存/提交类），其余为普通按钮 */
  variant?: "primary" | "default" | "danger";
  disabled?: boolean;
  title?: string;
};

type Props = {
  title: ReactNode;
  status?: string;
  statusTone?: StatusTone;
  subtitle?: ReactNode;
  breadcrumb?: BreadcrumbItem[];
  actions?: DetailAction[];
  /** 状态右侧附加徽标（旗标、锁定图标等） */
  badges?: ReactNode;
  /** 归属条（创建人/修改人 + 时间）—— 与 entityId 同时提供时显示 */
  entityType?: string;
  entityId?: string;
};

export function DetailHeader({ title, status, statusTone, subtitle, breadcrumb, actions, badges, entityType, entityId }: Props) {
  return (
    <PageHeader
      breadcrumb={breadcrumb}
      title={
        <>
          {title}
          {status ? <StatusBadge status={status} tone={statusTone} /> : null}
          {badges}
        </>
      }
      subtitle={
        entityType && entityId ? (
          <>
            {subtitle ? <>{subtitle} · </> : null}
            <RecordAttribution entityType={entityType} entityId={entityId} />
          </>
        ) : (
          subtitle
        )
      }
      actions={
        actions?.length
          ? actions.map((a) => (
              <button
                key={a.key}
                type="button"
                className={`btn btn-sm${a.variant === "primary" ? " btn-primary" : a.variant === "danger" ? " btn-danger" : ""}`}
                disabled={a.disabled}
                title={a.title}
                onClick={a.onClick}
              >
                {a.label}
              </button>
            ))
          : undefined
      }
    />
  );
}
