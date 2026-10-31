"use client";

/**
 * 任务行 —— 任务中心与工作台**共用**一份实现。
 *
 * 以前这里有两套重复实现（`app/tasks/page.tsx` 的 `.task-row` 与
 * `app/home/page.tsx` 的 `.wb-task-row`），改一处忘另一处就会出现
 * "两个页面显示不一样"的割裂感。现在统一到本组件：
 *   * `compact` —— 工作台窄栏用（一行、勾选圈、可点标题）
 *   * 默认 —— 任务中心列表用（状态/优先级/负责人/到期，操作按钮在右）
 */

import { TaskOut } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { utcDayDiff } from "@/lib/datetime";
import Link from "next/link";

export type TaskDueInfo = { text: string; overdue: boolean } | null;

/** 到期文案：逾期 / 今天 / 日期。 */
export function taskDueInfo(task: TaskOut, t: (k: string, f?: string, p?: any) => string): TaskDueInfo {
  if (!task.due_at) return null;
  const diff = utcDayDiff(task.due_at);
  if (diff === null) return null;
  if (task.status !== "done" && task.status !== "cancelled") {
    if (diff < 0) return { text: t("page.tasks.overdue_days", "Overdue by {n} days", { n: -diff }), overdue: true };
    if (diff === 0) return { text: t("page.tasks.due_today", "Due today"), overdue: false };
  }
  return { text: task.due_at.slice(0, 10), overdue: false };
}

export const PRIORITY_COLORS: Record<string, string> = {
  low: "var(--muted)",
  normal: "var(--accent)",
  high: "var(--warn-text)",
  urgent: "var(--danger)",
};

/** 优先级展示文案 —— 不把 high / urgent 这类内部枚举直接扔给用户。 */
export function taskPriorityLabel(t: (k: string, f?: string) => string, p?: string): string {
  switch (p) {
    case "low":
      return t("page.tasks.priority_low", "Low");
    case "normal":
      return t("page.tasks.priority_normal", "Normal");
    case "high":
      return t("page.tasks.priority_high", "High");
    case "urgent":
      return t("page.tasks.priority_urgent", "Urgent");
    default:
      return p || "—";
  }
}

/** 状态展示文案。 */
export function taskStatusLabel(t: (k: string, f?: string) => string, s?: string): string {
  switch (s) {
    case "todo":
      return t("page.tasks.status_todo", "To do");
    case "in_progress":
      return t("page.tasks.in_progress", "In progress");
    case "done":
      return t("page.tasks.done", "Done");
    case "cancelled":
      return t("page.tasks.cancelled", "Cancelled");
    default:
      return s || "—";
  }
}

type Props = {
  task: TaskOut;
  /** 工作台窄栏的一行式 */
  compact?: boolean;
  busy?: boolean;
  onComplete?: (task: TaskOut) => void;
  onReopen?: (task: TaskOut) => void;
  onOpen?: (task: TaskOut) => void;
  onContextMenu?: (task: TaskOut) => void;
};

export function TaskRow({ task, compact = false, busy = false, onComplete, onReopen, onOpen, onContextMenu }: Props) {
  const { t } = useI18n();
  const due = taskDueInfo(task, t);
  const done = task.status === "done" || task.status === "cancelled";
  const assigneeName = task.assignee?.full_name || task.assignee?.email || "";
  const click = () => onOpen?.(task);
  // 绑定的系统动作 —— 显示可读文案，技术码留在 title 里备查
  const actionBadge = task.action_code ? (
    <span className="tk-badge tk-badge-action" title={task.action_code}>
      {task.action_label_key
        ? t(task.action_label_key, task.action_code)
        : task.action_code}
    </span>
  ) : null;
  // 任务挂着的单据 —— 跳回系统里那一张。标题里已经写了单号就不重复显示。
  const entityChip =
    task.entity_href && task.entity_title && !task.title.includes(task.entity_title) ? (
      <Link href={task.entity_href} className="tk-badge tk-badge-entity" title={task.entity_type || undefined}>
        {task.entity_title}
      </Link>
    ) : null;

  if (compact) {
    return (
      <div
        className={`wb-task-row ${task.status === "done" ? "done" : ""}`}
        onContextMenu={onContextMenu ? (e) => onContextMenu(task) : undefined}
      >
        <button
          type="button"
          className="wb-task-check"
          disabled={busy}
          onClick={() => (done ? onReopen?.(task) : onComplete?.(task))}
          title={done ? t("page.tasks.reopen", "Reopen") : t("page.home.mark_done", "Mark done")}
        >
          {task.status === "done" ? "✓" : ""}
        </button>
        <span className="wb-task-pri-dot" data-priority={task.priority} />
        <span className="wb-task-title" onClick={click}>
          {task.title}
        </span>
        {actionBadge}
        {entityChip}
        {due ? <span className={`wb-task-due ${due.overdue ? "overdue" : ""}`}>{due.text}</span> : null}
        {assigneeName ? <span className="wb-task-assignee">{assigneeName}</span> : null}
      </div>
    );
  }

  return (
    <div
      className={`task-row ${done ? "task-done" : ""}`}
      onContextMenu={onContextMenu ? (e) => onContextMenu(task) : undefined}
    >
      <span className="task-row-main">
        <span className="task-row-title">
          <span className={`pill ${task.priority}`}>{taskPriorityLabel(t, task.priority)}</span>
          <button type="button" className="tk-link" onClick={click}>
            {task.title}
          </button>
          {task.status === "in_progress" ? (
            <span className="pill normal">{t("page.tasks.in_progress", "In progress")}</span>
          ) : null}
          {task.status === "cancelled" ? (
            <span className="pill cancelled">{t("page.tasks.cancelled", "Cancelled")}</span>
          ) : null}
          {task.auto_completed ? (
            <span className="pill tk-pill-auto">{t("page.tasks.auto_done", "Auto-completed")}</span>
          ) : null}
          {actionBadge}
          {entityChip}
        </span>
        {task.description ? <small className="muted">{task.description}</small> : null}
        <small className="muted">
          {task.assignee
            ? t("page.tasks.assignee", "Assignee", { name: task.assignee.full_name || task.assignee.email })
            : t("page.tasks.unassigned", "Unassigned")}
          {due ? " · " : ""}
          {due ? <span className={due.overdue ? "overdue" : ""}>{due.text}</span> : null}
          {task.collaborator_ids && task.collaborator_ids.length ? (
            <> · {t("page.tasks.collaborators", "{n} collaborators", { n: task.collaborator_ids.length })}</>
          ) : null}
        </small>
      </span>
      <span className="task-row-ops">
        {!done ? (
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={busy}
            onClick={() => onComplete?.(task)}
          >
            {t("page.tasks.complete", "Complete")}
          </button>
        ) : (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            disabled={busy}
            onClick={() => onReopen?.(task)}
          >
            {t("page.tasks.reopen", "Reopen")}
          </button>
        )}
      </span>
    </div>
  );
}
