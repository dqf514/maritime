"use client";

// 统一状态徽章 — 全站唯一状态色表（styles/status-colors.css）。
// 状态字符串 → 语义色：绿=正常完成 / 黄=进行中待办 / 红=异常阻断 / 蓝=预测未实现 / 灰=终止归档。

import { ReactNode } from "react";
import { useI18n } from "@/lib/i18n";

/** 语义色调 */
export type StatusTone = "ok" | "warn" | "danger" | "info" | "muted";

/** 常见状态 → 色调映射（不在表内时按关键词兜底） */
const EXACT: Record<string, StatusTone> = {
  // 正常完成
  completed: "ok",
  complete: "ok",
  closed: "muted",
  posted: "ok",
  paid: "ok",
  active: "ok",
  approved: "ok",
  fixed: "ok",
  done: "ok",
  settled: "ok",
  confirmed: "ok",
  accepted: "ok",
  delivered: "ok",
  compliant: "ok",
  success: "ok",
  // 进行中 / 待办
  draft: "warn",
  pending: "warn",
  in_progress: "warn",
  "in progress": "warn",
  progress: "warn",
  open: "warn",
  created: "warn",
  nominated: "warn",
  submitted: "warn",
  negotiating: "warn",
  reviewing: "warn",
  scheduled: "info",
  forecast: "info",
  projected: "info",
  planned: "info",
  prepared: "info",
  ready: "info",
  nominated_: "warn",
  // 异常 / 阻断
  failed: "danger",
  error: "danger",
  blocked: "danger",
  rejected: "danger",
  overdue: "danger",
  breached: "danger",
  critical: "danger",
  cancelled: "muted",
  canceled: "muted",
  inactive: "muted",
  deleted: "muted",
  archived: "muted",
  expired: "muted",
  void: "muted",
};

function deriveTone(status: string): StatusTone {
  const s = status.toLowerCase().trim();
  if (EXACT[s]) return EXACT[s];
  if (/(fail|error|breach|overdue|reject|block|critical|invalid)/.test(s)) return "danger";
  if (/(cancel|terminat|void|archiv|deactiv|inactiv)/.test(s)) return "muted";
  if (/(done|complete|success|paid|posted|approv|valid|ok)/.test(s)) return "ok";
  if (/(pend|progress|review|wait|queue|todo|due|draft|open)/.test(s)) return "warn";
  if (/(forecast|project|plan|schedule|estimate|future)/.test(s)) return "info";
  return "info";
}

type Props = {
  /** 原始状态字符串（自动派生色调）；给了 tone 则以 tone 为准 */
  status: string;
  tone?: StatusTone;
  /** 自定义显示文本（默认 = status） */
  label?: ReactNode;
  /** 紧凑模式（仅色点 + 文本，无边框） */
  dot?: boolean;
  title?: string;
  className?: string;
};

export function StatusBadge({ status, tone, label, dot, title, className }: Props) {
  const { t } = useI18n();
  const toneClass = tone || deriveTone(status);
  // 状态码统一走 status.* 词表（seed_i18n_extra.py），zh 界面显示中文
  const text = label ?? t(`status.${status}`, status.replace(/_/g, " "));
  return (
    <span
      className={`status-badge status-badge--${toneClass}${dot ? " status-badge--dot" : ""}${className ? ` ${className}` : ""}`}
      title={title ?? status}
      data-status={status}
    >
      {text}
    </span>
  );
}
