"use client";

import { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { DateInput } from "@/components/DateInput";
import { RecordModal } from "@/components/RecordModal";
import { StateView } from "@/components/StateView";
import { apiGet, apiPatch, apiPost, type TaskAssignee, type TaskOut } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Tab = "open" | "done" | "all";

const PRIORITIES: TaskOut["priority"][] = ["low", "normal", "high", "urgent"];

type Draft = {
  id: string | null;
  title: string;
  description: string;
  priority: TaskOut["priority"];
  due_at: string;
  assignee_user_id: string;
};

const EMPTY_DRAFT: Draft = {
  id: null,
  title: "",
  description: "",
  priority: "normal",
  due_at: "",
  assignee_user_id: "",
};

export default function TasksPage() {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>("open");
  const [tasks, setTasks] = useState<TaskOut[]>([]);
  const [assignees, setAssignees] = useState<TaskAssignee[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    const qs = tab === "done" ? "?status=done" : tab === "all" ? "?include_done=true" : "";
    try {
      const rows = await apiGet(`/api/v1/tasks/my${qs}`);
      setTasks(Array.isArray(rows) ? rows : []);
    } catch (e: any) {
      setError(e?.message || t("common.failed", "加载失败"));
    } finally {
      setLoading(false);
    }
  }, [tab, t]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    apiGet("/api/v1/tasks/assignees")
      .then((rows) => setAssignees(Array.isArray(rows) ? rows : []))
      .catch(() => undefined);
  }, []);

  function dueLabel(task: TaskOut) {
    if (!task.due_at) return null;
    const due = new Date(task.due_at);
    if (Number.isNaN(due.getTime())) return null;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const day = new Date(due);
    day.setHours(0, 0, 0, 0);
    const diff = Math.round((day.getTime() - today.getTime()) / 86_400_000);
    if (task.status !== "done" && task.status !== "cancelled") {
      if (diff < 0) return { text: t("page.tasks.overdue_days", "已逾期 {n} 天", { n: -diff }), overdue: true };
      if (diff === 0) return { text: t("page.tasks.due_today", "今天截止"), overdue: false };
    }
    return { text: task.due_at.slice(0, 10), overdue: false };
  }

  async function saveDraft() {
    if (!draft) return;
    if (!draft.title.trim()) {
      setMsg(t("page.tasks.need_title", "请填写任务标题"));
      return;
    }
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        title: draft.title.trim(),
        description: draft.description.trim() || null,
        priority: draft.priority,
        due_at: draft.due_at || null,
        assignee_user_id: draft.assignee_user_id || null,
      };
      if (draft.id) {
        await apiPatch(`/api/v1/tasks/${draft.id}`, payload);
        setMsg(t("page.tasks.updated", "任务已更新"));
      } else {
        await apiPost("/api/v1/tasks", payload);
        setMsg(t("page.tasks.created", "任务已创建"));
      }
      setDraft(null);
      await load();
    } catch (e: any) {
      setMsg(e?.message || t("common.failed", "操作失败"));
    } finally {
      setSaving(false);
    }
  }

  async function transition(task: TaskOut, action: "complete" | "reopen") {
    setBusyId(task.id);
    try {
      await apiPost(`/api/v1/tasks/${task.id}/${action}`);
      await load();
    } catch (e: any) {
      setMsg(e?.message || t("common.failed", "操作失败"));
    } finally {
      setBusyId("");
    }
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: "open", label: t("page.tasks.tab_open", "待办") },
    { id: "done", label: t("page.tasks.tab_done", "已完成") },
    { id: "all", label: t("page.tasks.tab_all", "全部") },
  ];

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.tasks.title", "我的任务")}</h1>
          <p className="page-sub">{t("page.tasks.sub", "跟进指派给你的待办、截止与完成情况。")}</p>
        </div>
        <div className="quick-row">
          <button type="button" className="btn btn-primary" onClick={() => setDraft({ ...EMPTY_DRAFT })}>
            {t("page.tasks.new", "新建任务")}
          </button>
        </div>
      </div>
      {msg ? <p className="flash">{msg}</p> : null}

      <div className="page-tabs" role="tablist">
        {tabs.map((x) => (
          <button
            key={x.id}
            type="button"
            role="tab"
            aria-selected={tab === x.id}
            className={`page-tab ${tab === x.id ? "active" : ""}`}
            onClick={() => setTab(x.id)}
          >
            {x.label}
          </button>
        ))}
      </div>

      <div className="panel">
        <StateView
          loading={loading}
          error={error}
          empty={!tasks.length}
          emptyText={t("page.tasks.empty", "暂无任务")}
          onRetry={load}
        >
          {tasks.map((task) => {
            const due = dueLabel(task);
            const done = task.status === "done" || task.status === "cancelled";
            return (
              <div key={task.id} className={`task-row ${done ? "task-done" : ""}`}>
                <span className="task-row-main">
                  <span className="task-row-title">
                    <span className={`pill ${task.priority}`}>{task.priority}</span>
                    {task.title}
                    {task.status === "in_progress" ? (
                      <span className="pill">{t("page.tasks.in_progress", "进行中")}</span>
                    ) : null}
                    {task.status === "cancelled" ? (
                      <span className="pill cancelled">{t("page.tasks.cancelled", "已取消")}</span>
                    ) : null}
                  </span>
                  {task.description ? <small className="muted">{task.description}</small> : null}
                  <small className="muted">
                    {task.assignee
                      ? t("page.tasks.assignee", "指派：{name}", {
                          name: task.assignee.full_name || task.assignee.email,
                        })
                      : t("page.tasks.unassigned", "未指派")}
                    {due ? " · " : ""}
                    {due ? <span className={due.overdue ? "overdue" : ""}>{due.text}</span> : null}
                  </small>
                </span>
                <span className="task-row-ops">
                  {!done ? (
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={busyId === task.id}
                      onClick={() => transition(task, "complete")}
                    >
                      {t("page.tasks.complete", "完成")}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      disabled={busyId === task.id}
                      onClick={() => transition(task, "reopen")}
                    >
                      {t("page.tasks.reopen", "重开")}
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() =>
                      setDraft({
                        id: task.id,
                        title: task.title,
                        description: task.description || "",
                        priority: task.priority,
                        due_at: task.due_at ? task.due_at.slice(0, 10) : "",
                        assignee_user_id: task.assignee?.id || "",
                      })
                    }
                  >
                    {t("common.edit", "编辑")}
                  </button>
                </span>
              </div>
            );
          })}
        </StateView>
      </div>

      <RecordModal
        open={Boolean(draft)}
        title={draft?.id ? t("page.tasks.edit", "编辑任务") : t("page.tasks.new", "新建任务")}
        onClose={() => setDraft(null)}
        onSave={saveDraft}
        canDelete={false}
        saving={saving}
      >
        <label>
          {t("page.tasks.field_title", "标题")}
          <input
            value={draft?.title || ""}
            required
            onChange={(e) => setDraft((d) => (d ? { ...d, title: e.target.value } : d))}
          />
        </label>
        <label>
          {t("page.tasks.field_desc", "描述")}
          <textarea
            rows={3}
            value={draft?.description || ""}
            onChange={(e) => setDraft((d) => (d ? { ...d, description: e.target.value } : d))}
          />
        </label>
        <label>
          {t("page.tasks.field_priority", "优先级")}
          <select
            value={draft?.priority || "normal"}
            onChange={(e) => setDraft((d) => (d ? { ...d, priority: e.target.value as TaskOut["priority"] } : d))}
          >
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {t(`page.tasks.priority_${p}`, p)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("page.tasks.field_due", "截止日期")}
          <DateInput
            value={draft?.due_at || ""}
            onChange={(v) => setDraft((d) => (d ? { ...d, due_at: v } : d))}
          />
        </label>
        <label>
          {t("page.tasks.field_assignee", "指派人")}
          <select
            value={draft?.assignee_user_id || ""}
            onChange={(e) => setDraft((d) => (d ? { ...d, assignee_user_id: e.target.value } : d))}
          >
            <option value="">{t("page.tasks.unassigned", "未指派")}</option>
            {assignees.map((a) => (
              <option key={a.id} value={a.id}>
                {a.full_name || a.email}
              </option>
            ))}
          </select>
        </label>
      </RecordModal>
    </AppShell>
  );
}
