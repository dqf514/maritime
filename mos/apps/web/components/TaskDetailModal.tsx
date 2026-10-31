"use client";

/**
 * 任务详情弹窗 —— 任务中心的"协同中枢"。
 *
 * 一屏里能看到并操作：
 *   * 系统动作绑定状态（动作做完自动勾完成 / 已被系统勾掉）
 *   * 子任务树（可加、可勾）—— 进度按权重上卷
 *   * 主责 / 协作人 / 权重 / 工作包 / OKR 目标
 *   * 转派（上下级之间改主责）
 *   * 评论流 + @提及（被提及的人收到通知）
 */

import { useCallback, useEffect, useState } from "react";
import {
  apiGet,
  apiPost,
  type ActionSpec,
  type TaskComment,
  type TaskDetail,
  type TaskPerson,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { msgOf } from "@/lib/errors";
import { useToast } from "@/components/ToastProvider";
import { taskPriorityLabel, taskStatusLabel } from "@/components/TaskRow";

type Props = {
  taskId: string | null;
  people: TaskPerson[];
  onClose: () => void;
  onChanged: () => void | Promise<void>;
};

/** 状态 / 优先级展示文案 —— 与任务列表共用一份（TaskRow）。 */
const statusLabel = taskStatusLabel;
const priorityLabel = taskPriorityLabel;

export function TaskDetailModal({ taskId, people, onClose, onChanged }: Props) {
  const { t } = useI18n();
  const toast = useToast();
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [catalog, setCatalog] = useState<ActionSpec[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [comment, setComment] = useState("");
  const [mentions, setMentions] = useState<string[]>([]);
  const [childTitle, setChildTitle] = useState("");
  const [transferTo, setTransferTo] = useState("");
  const [transferReason, setTransferReason] = useState("");

  const load = useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    setErr("");
    try {
      const d = await apiGet(`/api/v1/tasks/${taskId}`);
      setDetail(d as TaskDetail);
    } catch (e: any) {
      setErr(msgOf(e, t("common.failed", "Failed")));
    } finally {
      setLoading(false);
    }
  }, [taskId, t]);

  useEffect(() => {
    if (!taskId) {
      setDetail(null);
      return;
    }
    void load();
  }, [taskId, load]);

  useEffect(() => {
    if (!taskId || catalog.length) return;
    apiGet("/api/v1/tasks/action-catalog")
      .then((rows) => setCatalog(Array.isArray(rows) ? (rows as ActionSpec[]) : []))
      .catch(() => setErr(t("page.tasks.catalog_fail", "Could not load the system action catalogue.")));
  }, [taskId, catalog.length]);

  async function run(fn: () => Promise<unknown>, okMsg?: string) {
    setBusy(true);
    try {
      await fn();
      if (okMsg) toast.success(okMsg);
      await load();
      await onChanged();
    } catch (e: any) {
      toast.error(msgOf(e, t("common.failed", "Failed")));
    } finally {
      setBusy(false);
    }
  }

  async function addComment() {
    if (!detail || !comment.trim()) return;
    await run(
      () => apiPost(`/api/v1/tasks/${detail.id}/comments`, { body: comment.trim(), mentions }),
      t("page.tasks.comment_added", "Comment added"),
    );
    setComment("");
    setMentions([]);
  }

  async function addChild() {
    if (!detail || !childTitle.trim()) return;
    await run(
      () =>
        apiPost("/api/v1/tasks", {
          title: childTitle.trim(),
          parent_id: detail.id,
          entity_type: detail.entity_type,
          entity_id: detail.entity_id,
        }),
      t("page.tasks.subtask_added", "Sub-task added"),
    );
    setChildTitle("");
  }

  if (!taskId) return null;

  const done = detail?.status === "done" || detail?.status === "cancelled";
  const action = detail?.action;

  return (
    <div className="tk-modal-backdrop" role="dialog" aria-modal="true" aria-label={t("page.tasks.detail", "Task detail")}>
      <div className="tk-modal">
        <div className="tk-modal-head">
          <div className="tk-modal-title">
            {detail?.title || t("page.tasks.detail", "Task detail")}
            {detail?.auto_completed ? (
              <span className="pill tk-pill-auto">{t("page.tasks.auto_done", "Auto-completed")}</span>
            ) : null}
          </div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
            {t("common.close", "Close")}
          </button>
        </div>

        <div className="tk-modal-body">
          {loading ? <p className="muted">{t("common.loading", "Loading…")}</p> : null}
          {err ? (
            <p className="flash-err" role="alert">
              {err}
            </p>
          ) : null}

          {detail ? (
            <>
              {/* ── 概要 ── */}
              <div className="tk-detail-grid">
                <div>
                  <span className="tk-k">{t("page.tasks.field_status", "Status")}</span>
                  <span className="tk-v">{statusLabel(t, detail.status)}</span>
                </div>
                <div>
                  <span className="tk-k">{t("page.tasks.field_priority", "Priority")}</span>
                  <span className="tk-v">{priorityLabel(t, detail.priority)}</span>
                </div>
                <div>
                  <span className="tk-k">{t("page.tasks.field_assignee", "Assignee")}</span>
                  <span className="tk-v">{detail.assignee?.full_name || detail.assignee?.email || t("page.tasks.unassigned", "Unassigned")}</span>
                </div>
                <div>
                  <span className="tk-k">{t("page.tasks.field_due", "Due date")}</span>
                  <span className="tk-v">{detail.due_at ? detail.due_at.slice(0, 10) : "—"}</span>
                </div>
                <div>
                  <span className="tk-k">{t("page.tasks.field_weight", "Weight")}</span>
                  <span className="tk-v">{detail.weight ?? 1}</span>
                </div>
                <div>
                  <span className="tk-k">{t("page.tasks.field_progress", "Progress")}</span>
                  <span className="tk-v">{detail.progress}%</span>
                </div>
                {detail.entity_href && detail.entity_title ? (
                  <div>
                    <span className="tk-k">{t("page.tasks.field_linked_record", "Linked record")}</span>
                    <span className="tk-v">
                      <a href={detail.entity_href} className="tk-link">
                        {detail.entity_title}
                      </a>
                    </span>
                  </div>
                ) : null}
              </div>

              {detail.description ? <p className="tk-detail-desc">{detail.description}</p> : null}

              {/* ── 进度条 ── */}
              <progress
                className="tk-progress"
                value={Math.round(detail.progress)}
                max={100}
                aria-label={t("page.tasks.progress", "Progress")}
              />

              {/* ── 系统动作绑定 ── */}
              <section className="tk-section">
                <h4 className="tk-section-title">{t("page.tasks.section_action", "System action")}</h4>
                {action ? (
                  <div className="tk-action-box">
                    <div className="tk-action-head">
                      <strong>{t(action.label_key, action.label)}</strong>
                      <span className="tk-badge">{action.code}</span>
                    </div>
                    <p className="muted">
                      {detail.auto_completed
                        ? t("page.tasks.action_done", "The system action was completed — the task was ticked automatically.")
                        : t("page.tasks.action_pending", "When this action is completed in the system, the task is ticked automatically.")}
                    </p>
                    {action.href && action.href !== "/tasks" ? (
                      <a className="btn btn-ghost btn-sm" href={action.href}>
                        {t("page.tasks.action_open", "Open in module")}
                      </a>
                    ) : null}
                  </div>
                ) : (
                  <p className="muted">{t("page.tasks.action_none", "No system action bound to this task.")}</p>
                )}
              </section>

              {/* ── 子任务 ── */}
              <section className="tk-section">
                <h4 className="tk-section-title">
                  {t("page.tasks.section_children", "Sub-tasks")}
                  <span className="muted"> ({detail.children.length})</span>
                </h4>
                {detail.children.length ? (
                  <ul className="tk-child-list">
                    {detail.children.map((c) => (
                      <li key={c.id} className={`tk-child ${c.status === "done" ? "done" : ""}`}>
                        <span className="tk-child-title">{c.title}</span>
                        <span className="muted">w{c.weight ?? 1}</span>
                        {c.status === "done" ? (
                          <span className="pill done">{t("page.tasks.done", "Done")}</span>
                        ) : (
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            disabled={busy}
                            onClick={() => run(() => apiPost(`/api/v1/tasks/${c.id}/complete`))}
                          >
                            {t("page.tasks.complete", "Complete")}
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">{t("page.tasks.no_children", "No sub-tasks.")}</p>
                )}
                <div className="tk-inline-form">
                  <input
                    value={childTitle}
                    placeholder={t("page.tasks.new_subtask_ph", "New sub-task…")}
                    onChange={(e) => setChildTitle(e.target.value)}
                  />
                  <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={addChild}>
                    {t("common.add", "Add")}
                  </button>
                </div>
              </section>

              {/* ── 转派 ── */}
              <section className="tk-section">
                <h4 className="tk-section-title">{t("page.tasks.section_transfer", "Transfer")}</h4>
                <div className="tk-inline-form">
                  <select value={transferTo} onChange={(e) => setTransferTo(e.target.value)}>
                    <option value="">{t("page.tasks.pick_assignee", "Pick a new owner…")}</option>
                    {people.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.full_name || p.email}
                        {p.manager_name ? ` (${p.manager_name})` : ""}
                      </option>
                    ))}
                  </select>
                  <input
                    value={transferReason}
                    placeholder={t("page.tasks.transfer_reason_ph", "Reason…")}
                    onChange={(e) => setTransferReason(e.target.value)}
                  />
                  <button
                    type="button"
                    className="btn btn-sm btn-primary"
                    disabled={busy || !transferTo}
                    onClick={() =>
                      run(
                        () =>
                          apiPost(`/api/v1/tasks/${detail.id}/transfer`, {
                            assignee_user_id: transferTo,
                            reason: transferReason || null,
                          }),
                        t("page.tasks.transferred", "Task transferred"),
                      ).then(() => {
                        setTransferTo("");
                        setTransferReason("");
                      })
                    }
                  >
                    {t("page.tasks.transfer", "Transfer")}
                  </button>
                </div>
              </section>

              {/* ── 评论 ── */}
              <section className="tk-section">
                <h4 className="tk-section-title">
                  {t("page.tasks.section_comments", "Comments")}
                  <span className="muted"> ({detail.comments.length})</span>
                </h4>
                {detail.comments.length ? (
                  <ul className="tk-comment-list">
                    {detail.comments.map((c: TaskComment) => (
                      <li key={c.id} className="tk-comment">
                        <div className="tk-comment-head">
                          <strong>{c.author?.full_name || c.author?.email || "—"}</strong>
                          <span className="muted">{c.created_at ? c.created_at.slice(0, 16).replace("T", " ") : ""}</span>
                        </div>
                        <div>{c.body}</div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">{t("page.tasks.no_comments", "No comments yet.")}</p>
                )}
                <textarea
                  rows={2}
                  value={comment}
                  placeholder={t("page.tasks.comment_ph", "Write a comment…")}
                  onChange={(e) => setComment(e.target.value)}
                />
                <div className="tk-inline-form">
                  <select
                    multiple
                    size={3}
                    value={mentions}
                    onChange={(e) =>
                      setMentions(Array.from(e.target.selectedOptions).map((o) => o.value))
                    }
                    aria-label={t("page.tasks.mention_pick", "Mention people")}
                  >
                    {people.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.full_name || p.email}
                      </option>
                    ))}
                  </select>
                  <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={addComment}>
                    {t("page.tasks.comment_send", "Comment")}
                  </button>
                </div>
              </section>
            </>
          ) : null}
        </div>

        <div className="tk-modal-foot">
          {detail ? (
            <>
              {done ? (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  disabled={busy}
                  onClick={() => run(() => apiPost(`/api/v1/tasks/${detail.id}/reopen`))}
                >
                  {t("page.tasks.reopen", "Reopen")}
                </button>
              ) : (
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={busy}
                  onClick={() => run(() => apiPost(`/api/v1/tasks/${detail.id}/complete`))}
                >
                  {t("page.tasks.complete", "Complete")}
                </button>
              )}
              <span className="muted">{t("page.tasks.detail_hint", "Auto-completion never blocks a manual change.")}</span>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
