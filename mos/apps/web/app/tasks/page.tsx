"use client";

import { Suspense } from "react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { DateInput } from "@/components/DateInput";
import { ExportButton } from "@/components/ExportButton";
import { PageGuide } from "@/components/PageGuide";
import { RecordModal } from "@/components/RecordModal";
import { SavedViews } from "@/components/SavedViews";
import { StatusLegend } from "@/components/StatusLegend";
import { Tabs, type TabItem } from "@/components/Tabs";
import { Toolbar } from "@/components/Toolbar";
import { StateView } from "@/components/StateView";
import { useListHotkeys } from "@/components/useListHotkeys";
import { apiDelete, apiGet, apiPatch, apiPost, type TaskAssignee, type TaskOut } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { useI18n } from "@/lib/i18n";
import { formatInTz, utcDayDiff } from "@/lib/datetime";
import { useListQuery } from "@/lib/useListQuery";
import { useToast } from "@/components/ToastProvider";

type Tab = "open" | "done" | "all";

type TaskRow = TaskOut & { updated_at?: string | null };

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

function TasksPageInner() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const { query, setQuery } = useListQuery();
  const tab: Tab = query.tab === "done" || query.tab === "all" ? query.tab : "open";
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  const [assignees, setAssignees] = useState<TaskAssignee[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState("");

  useListHotkeys(() => setDraft({ ...EMPTY_DRAFT }));

  const rowCtx = useContextMenu<TaskRow>();

  function fmtStamp(iso?: string | null) {
    if (!iso) return "—";
    return formatInTz(iso, null, { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  }

  function exportRows(selected: TaskRow[]) {
    downloadCsv(
      "tasks",
      ["id", "title", "status", "priority", "due_at", "updated_at", "assignee", "description"],
      selected.map((r) => [
        r.id,
        r.title,
        r.status,
        r.priority,
        r.due_at ?? "",
        r.updated_at ?? "",
        r.assignee?.full_name || r.assignee?.email || "",
        r.description ?? "",
      ]),
    );
  }

  function openEdit(task: TaskRow) {
    setDraft({
      id: task.id,
      title: task.title,
      description: task.description || "",
      priority: task.priority,
      due_at: task.due_at ? task.due_at.slice(0, 10) : "",
      assignee_user_id: task.assignee?.id || "",
    });
  }

  function rowMenuItems(target: TaskRow): ContextMenuItem[] {
    const done = target.status === "done" || target.status === "cancelled";
    return [
      { key: "open", label: t("common.open", "Open"), onClick: () => openEdit(target) },
      { key: "copy", label: t("common.copy_id", "Copy id"), onClick: () => void navigator.clipboard?.writeText(target.id) },
      { key: "export", label: t("page.finance.export_selected", "Export selected"), onClick: () => exportRows([target]) },
      { key: "div", divider: true, label: "" },
      ...(done
        ? [{ key: "reopen", label: t("page.tasks.reopen", "Reopen"), onClick: () => transition(target, "reopen") } as ContextMenuItem]
        : [{ key: "complete", label: t("page.tasks.complete", "Complete"), onClick: () => transition(target, "complete") } as ContextMenuItem]),
      { key: "edit", label: t("common.edit", "Edit"), onClick: () => openEdit(target) },
      { key: "d2", divider: true, label: "" },
      { key: "delete", label: t("common.delete", "Delete"), danger: true, onClick: () => void deleteTask(target.id) },
    ];
  }

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    const qs = tab === "done" ? "?status=done" : tab === "all" ? "?include_done=true" : "";
    try {
      const rows = await apiGet(`/api/v1/tasks/my${qs}`);
      setTasks(Array.isArray(rows) ? rows : []);
    } catch (e: any) {
      setError(e?.message || t("common.failed", "Failed"));
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
    const diff = utcDayDiff(task.due_at);
    if (diff === null) return null;
    if (task.status !== "done" && task.status !== "cancelled") {
      if (diff < 0) return { text: t("page.tasks.overdue_days", "Overdue by {n} days", { n: -diff }), overdue: true };
      if (diff === 0) return { text: t("page.tasks.due_today", "Due today"), overdue: false };
    }
    return { text: task.due_at.slice(0, 10), overdue: false };
  }

  async function saveDraft() {
    if (!draft) return;
    if (!draft.title.trim()) {
      toast.success(t("page.tasks.need_title", "Enter a task title"));
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
        toast.success(t("page.tasks.updated", "Task updated."));
      } else {
        await apiPost("/api/v1/tasks", payload);
        toast.success(t("page.tasks.created", "Task created."));
      }
      setDraft(null);
      await load();
    } catch (e: any) {
      toast.error(e?.message || t("common.failed", "Failed"));
    } finally {
      setSaving(false);
    }
  }

  async function transition(task: TaskRow, action: "complete" | "reopen") {
    setBusyId(task.id);
    try {
      await apiPost(`/api/v1/tasks/${task.id}/${action}`);
      await load();
    } catch (e: any) {
      toast.error(e?.message || t("common.failed", "Failed"));
    } finally {
      setBusyId("");
    }
  }

  async function deleteTask(id: string) {
    setBusyId(id);
    try {
      await apiDelete(`/api/v1/tasks/${id}`);
      toast.success(t("page.tasks.deleted", "Task deleted"));
      setDraft(null);
      await load();
    } catch (e: any) {
      toast.error(e?.message || t("common.failed", "Failed"));
    } finally {
      setBusyId("");
    }
  }

  const tabs: TabItem[] = [
    { key: "open", label: t("page.tasks.tab_open", "Open") },
    { key: "done", label: t("page.tasks.tab_done", "Done") },
    { key: "all", label: t("page.tasks.tab_all", "All") },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.tasks", "Tasks") }]}
        title={t("page.tasks.title", "My tasks")}
        subtitle={t("page.tasks.sub", "Track open items, due dates and completions assigned to you.")}
        actions={
          <>
            <PageGuide pageKey="tasks" />
            <SavedViews storageKey="tasks_list" onApply={(q) => router.replace(`/tasks${q}`)} />
          </>
        }
      />

      <Toolbar right={<ExportButton entity="tasks" />}>
        <button type="button" className="btn btn-primary btn-sm" onClick={() => setDraft({ ...EMPTY_DRAFT })}>
          {t("page.tasks.new", "New task")}
        </button>
      </Toolbar>

      <Tabs items={tabs} value={tab} onChange={(k) => setQuery({ tab: k === "open" ? null : k })} variant="pill" />

      <StatusLegend statuses={["todo", "in_progress", "done", "cancelled"]} />

      <div className="panel">
        <StateView
          loading={loading}
          error={error}
          empty={!tasks.length}
          emptyText={t("page.tasks.empty", "No tasks.")}
          onRetry={load}
        >
          {tasks.map((task) => {
            const due = dueLabel(task);
            const done = task.status === "done" || task.status === "cancelled";
            return (
              <div
                key={task.id}
                className={`task-row ${done ? "task-done" : ""}`}
                onContextMenu={rowCtx.open(task)}
              >
                <span className="task-row-main">
                  <span className="task-row-title">
                    <span className={`pill ${task.priority}`}>{task.priority}</span>
                    {task.title}
                    {task.status === "in_progress" ? (
                      <span className="pill">{t("page.tasks.in_progress", "In progress")}</span>
                    ) : null}
                    {task.status === "cancelled" ? (
                      <span className="pill cancelled">{t("page.tasks.cancelled", "Cancelled")}</span>
                    ) : null}
                  </span>
                  {task.description ? <small className="muted">{task.description}</small> : null}
                  <small className="muted">
                    {task.assignee
                      ? t("page.tasks.assignee", "Assignee", {
                          name: task.assignee.full_name || task.assignee.email,
                        })
                      : t("page.tasks.unassigned", "Unassigned")}
                    {due ? " · " : ""}
                    {due ? <span className={due.overdue ? "overdue" : ""}>{due.text}</span> : null}
                    {" · "}
                    {t("common.last_modified", "Updated")} {fmtStamp(task.updated_at)}
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
                      {t("page.tasks.complete", "Complete")}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      disabled={busyId === task.id}
                      onClick={() => transition(task, "reopen")}
                    >
                      {t("page.tasks.reopen", "Reopen")}
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => openEdit(task)}
                  >
                    {t("common.edit", "Edit")}
                  </button>
                </span>
              </div>
            );
          })}
        </StateView>
      </div>

      <ContextMenu controller={rowCtx} items={rowMenuItems} />

      <RecordModal
        open={Boolean(draft)}
        title={draft?.id ? t("page.tasks.edit", "Edit task") : t("page.tasks.new", "New task")}
        onClose={() => setDraft(null)}
        onSave={saveDraft}
        canDelete={!!draft?.id}
        onDelete={draft?.id ? () => void deleteTask(draft.id as string) : undefined}
        saving={saving}
      >
        <label>
          {t("page.tasks.field_title", "Title")}
          <input
            value={draft?.title || ""}
            required
            onChange={(e) => setDraft((d) => (d ? { ...d, title: e.target.value } : d))}
          />
        </label>
        <label>
          {t("page.tasks.field_desc", "Description")}
          <textarea
            rows={3}
            value={draft?.description || ""}
            onChange={(e) => setDraft((d) => (d ? { ...d, description: e.target.value } : d))}
          />
        </label>
        <label>
          {t("page.tasks.field_priority", "Priority")}
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
          {t("page.tasks.field_due", "Due date")}
          <DateInput
            value={draft?.due_at || ""}
            onChange={(v) => setDraft((d) => (d ? { ...d, due_at: v } : d))}
          />
        </label>
        <label>
          {t("page.tasks.field_assignee", "Assignee")}
          <select
            value={draft?.assignee_user_id || ""}
            onChange={(e) => setDraft((d) => (d ? { ...d, assignee_user_id: e.target.value } : d))}
          >
            <option value="">{t("page.tasks.unassigned", "Unassigned")}</option>
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

export default function TasksPage() {
  return (
    <Suspense fallback={null}>
      <TasksPageInner />
    </Suspense>
  );
}
