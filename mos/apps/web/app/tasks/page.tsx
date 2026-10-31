"use client";

import { Suspense } from "react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DateInput } from "@/components/DateInput";
import { ExportButton } from "@/components/ExportButton";
import { PageGuide } from "@/components/PageGuide";
import { RecordModal } from "@/components/RecordModal";
import { SavedViews } from "@/components/SavedViews";
import { Tabs, type TabItem } from "@/components/Tabs";
import { Toolbar } from "@/components/Toolbar";
import { StateView } from "@/components/StateView";
import { TaskDetailModal } from "@/components/TaskDetailModal";
import { TaskRow, taskStatusLabel } from "@/components/TaskRow";
import { TaskTeamBoard } from "@/components/TaskTeamBoard";
import { useListHotkeys } from "@/components/useListHotkeys";
import {
  apiDelete,
  apiGet,
  apiPatch,
  apiPost,
  type ActionSpec,
  type KeyResultOut,
  type ObjectiveOut,
  type TaskOut,
  type TaskPerson,
  type TaskStats,
  type WorkPackageOut,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { msgOf } from "@/lib/errors";
import { useListQuery } from "@/lib/useListQuery";
import { useToast } from "@/components/ToastProvider";

/**
 * 任务中心 —— 个人 todo + 团队协同 + 系统动作联动 + OKR 分解。
 *
 * 六个视角：
 *   我的 / 分配给我的 / 我分配的 / 团队 / 工作包 / OKR
 *
 * 与 ``/routine``（例行任务中枢：邮件→草稿→落库）是两件事：这里是人与人之间的
 * 任务协同；``/routine`` 是把外部邮件转成待办草稿的系统管道。
 */

const TABS = ["mine", "assigned_to_me", "assigned_by_me", "team", "work_package", "okr"] as const;
type TabKey = (typeof TABS)[number];

const PRIORITIES: TaskOut["priority"][] = ["low", "normal", "high", "urgent"];

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type Draft = {
  id: string | null;
  title: string;
  description: string;
  priority: TaskOut["priority"];
  due_at: string;
  assignee_user_id: string;
  action_code: string;
  entity_type: string;
  entity_id: string;
  weight: string;
  collaborator_ids: string[];
  work_package_id: string;
  objective_id: string;
};

const EMPTY_DRAFT: Draft = {
  id: null,
  title: "",
  description: "",
  priority: "normal",
  due_at: "",
  assignee_user_id: "",
  action_code: "",
  entity_type: "",
  entity_id: "",
  weight: "1",
  collaborator_ids: [],
  work_package_id: "",
  objective_id: "",
};

function TasksPageInner() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const { query, setQuery, page, limit } = useListQuery();

  const tab = (TABS as readonly string[]).includes(query.tab) ? (query.tab as TabKey) : "mine";
  const offset = Math.max(0, (page - 1) * limit);

  const [rows, setRows] = useState<TaskOut[]>([]);
  const [total, setTotal] = useState(0);
  const [people, setPeople] = useState<TaskPerson[]>([]);
  const [catalog, setCatalog] = useState<ActionSpec[]>([]);
  const [packages, setPackages] = useState<WorkPackageOut[]>([]);
  const [objectives, setObjectives] = useState<ObjectiveOut[]>([]);
  const [krs, setKrs] = useState<Record<string, KeyResultOut[]>>({});
  const [stats, setStats] = useState<TaskStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refWarn, setRefWarn] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState("");
  const [deletePending, setDeletePending] = useState<(() => void) | null>(null);
  const [deleteLabel, setDeleteLabel] = useState("");
  const [detailId, setDetailId] = useState<string | null>(null);

  useListHotkeys(() => setDraft({ ...EMPTY_DRAFT }));

  // ── 参考数据（人员 / 动作目录 / 工作包 / 目标） ──────────────────────
  useEffect(() => {
    apiGet("/api/v1/tasks/people")
      .then((rows) => setPeople(Array.isArray(rows) ? (rows as TaskPerson[]) : []))
      .catch(() => setRefWarn(t("page.tasks.people_fail", "Could not load the people list.")));
    apiGet("/api/v1/tasks/action-catalog")
      .then((rows) => setCatalog(Array.isArray(rows) ? (rows as ActionSpec[]) : []))
      .catch(() => setRefWarn(t("page.tasks.catalog_fail", "Could not load the system action catalogue.")));
    // 统计条不在这里取 —— 统一由 load() → loadStats() 刷，避免两个请求竞态导致顶部数字回退
    apiGet("/api/v1/tasks/work-packages")
      .then((rows) => setPackages(Array.isArray(rows) ? (rows as WorkPackageOut[]) : []))
      .catch(() => setRefWarn(t("page.tasks.packages_fail", "Could not load work packages.")));
  }, [t]);

  const loadObjectives = useCallback(async () => {
    try {
      const rows = await apiGet("/api/v1/tasks/objectives");
      const list = Array.isArray(rows) ? (rows as ObjectiveOut[]) : [];
      setObjectives(list);
      const entries = await Promise.all(
        list.map(async (o) => {
          try {
            const kr = await apiGet(`/api/v1/tasks/objectives/${o.id}/key-results`);
            return [o.id, Array.isArray(kr) ? (kr as KeyResultOut[]) : []] as const;
          } catch {
            return [o.id, []] as const;
          }
        }),
      );
      setKrs(Object.fromEntries(entries));
    } catch {
      setObjectives([]);
      setRefWarn(t("page.tasks.objectives_fail", "Could not load OKR objectives."));
    }
  }, []);

  useEffect(() => {
    void loadObjectives();
  }, [loadObjectives]);

  // 统计条与列表一起刷新 —— 否则建任务 / 勾完成后顶部数字是旧的。
  const loadStats = useCallback(async () => {
    try {
      setStats((await apiGet("/api/v1/tasks/stats")) as TaskStats);
    } catch {
      setStats(null);
    }
  }, []);

  const loadPackages = useCallback(async () => {
    try {
      const rows = await apiGet("/api/v1/tasks/work-packages");
      setPackages(Array.isArray(rows) ? (rows as WorkPackageOut[]) : []);
    } catch {
      setRefWarn(t("page.tasks.packages_fail", "Could not load work packages."));
    }
  }, [t]);

  // ── 主列表 ─────────────────────────────────────────────────────────
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    const params = new URLSearchParams();
    params.set("tab", tab);
    params.set("limit", String(limit));
    params.set("offset", String(offset));
    if (query.status) params.set("status", query.status);
    if (query.priority) params.set("priority", query.priority);
    if (query.assignee) params.set("assignee_user_id", query.assignee);
    if (query.action) params.set("action_code", query.action);
    if (query.overdue === "1") params.set("overdue", "true");
    if (query.q) params.set("q", query.q);
    if (query.include_done === "1") params.set("include_done", "true");
    if (query.work_package_id) params.set("work_package_id", query.work_package_id);
    if (query.objective_id) params.set("objective_id", query.objective_id);
    try {
      const body = await apiGet(`/api/v1/tasks?${params.toString()}`);
      const data = body as { items?: TaskOut[]; total?: number };
      setRows(Array.isArray(data.items) ? data.items : []);
      setTotal(data.total ?? 0);
    } catch (e: any) {
      setError(msgOf(e, t("common.failed", "Failed")));
    } finally {
      setLoading(false);
    }
    void loadStats();
    if (tab === "work_package") void loadPackages();
    if (tab === "okr") void loadObjectives();
  }, [
    tab,
    limit,
    offset,
    query.status,
    query.priority,
    query.assignee,
    query.action,
    query.overdue,
    query.q,
    query.include_done,
    query.work_package_id,
    query.objective_id,
    t,
    loadStats,
    loadPackages,
    loadObjectives,
  ]);

  useEffect(() => {
    void load();
  }, [load]);

  // ── 操作 ───────────────────────────────────────────────────────────
  async function transition(task: TaskOut, action: "complete" | "reopen") {
    setBusyId(task.id);
    try {
      await apiPost(`/api/v1/tasks/${task.id}/${action}`);
      await load();
    } catch (e: any) {
      toast.error(msgOf(e, t("common.failed", "Failed")));
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
      toast.error(msgOf(e, t("common.failed", "Failed")));
    } finally {
      setBusyId("");
    }
  }

  async function saveDraft() {
    if (!draft) return;
    if (!draft.title.trim()) {
      toast.error(t("page.tasks.need_title", "Enter a task title"));
      return;
    }
    if (draft.entity_id && !UUID_RE.test(draft.entity_id.trim())) {
      toast.error(t("page.tasks.bad_entity_id", "The linked record id must be a UUID."));
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
        action_code: draft.action_code || null,
        entity_type: draft.entity_type || null,
        entity_id: draft.entity_id || null,
        weight: Number(draft.weight) || 1,
        collaborator_ids: draft.collaborator_ids,
        work_package_id: draft.work_package_id || null,
        objective_id: draft.objective_id || null,
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
      toast.error(msgOf(e, t("common.failed", "Failed")));
    } finally {
      setSaving(false);
    }
  }

  // ── 渲染 ───────────────────────────────────────────────────────────
  const tabItems: TabItem[] = [
    { key: "mine", label: t("page.tasks.tab_mine", "My tasks") },
    { key: "assigned_to_me", label: t("page.tasks.tab_assigned_to_me", "Assigned to me") },
    { key: "assigned_by_me", label: t("page.tasks.tab_assigned_by_me", "Assigned by me") },
    { key: "team", label: t("page.tasks.tab_team", "Team") },
    { key: "work_package", label: t("page.tasks.tab_work_package", "Work packages") },
    { key: "okr", label: t("page.tasks.tab_okr", "OKR") },
  ];

  const filteredByPackage = !!query.work_package_id;
  const filteredByObjective = !!query.objective_id;
  const showList =
    tab === "mine" ||
    tab === "assigned_to_me" ||
    tab === "assigned_by_me" ||
    tab === "team" ||
    filteredByPackage ||
    filteredByObjective;
  const totalPages = Math.max(1, Math.ceil(total / limit));

  // 不做 useMemo —— React Compiler 认为这里的依赖无法保持一致，直接算更省事。
  const actionOptions = draft?.entity_type
    ? catalog.filter((a) => a.entity_type === draft.entity_type)
    : catalog;
  const chosenAction = draft?.action_code
    ? catalog.find((a) => a.code === draft.action_code) || null
    : null;

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.tasks", "Tasks") }]}
        title={t("page.tasks.title", "Task centre")}
        subtitle={
          <>
            {t(
              "page.tasks.sub",
              "Personal todos, team delegation, system-action linkage and OKR breakdown in one place.",
            )}{" "}
            <span className="muted">
              {t(
                "page.tasks.vs_routine",
                "Not the inbound-mail pipeline — that lives in Routine Tasks.",
              )}
            </span>
          </>
        }
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

      {stats ? (
        <div className="tk-stat-strip">
          <span className="tk-stat">
            <strong>{stats.open}</strong> {t("page.tasks.stat_open", "open")}
          </span>
          <span className="tk-stat tk-stat-danger">
            <strong>{stats.overdue}</strong> {t("page.tasks.stat_overdue", "overdue")}
          </span>
          <span className="tk-stat">
            <strong>{stats.due_today}</strong> {t("page.tasks.stat_due_today", "due today")}
          </span>
          <span className="tk-stat">
            <strong>{stats.done}</strong> {t("page.tasks.stat_done", "done")}
          </span>
        </div>
      ) : null}

      <Tabs
        items={tabItems}
        value={tab}
        onChange={(k) =>
          setQuery(
            { tab: k === "mine" ? null : k, work_package_id: null, objective_id: null },
            { resetPage: true },
          )
        }
        variant="pill"
      />

      {/* ── 筛选条 ── */}
      <div className="tk-filters">
        <input
          className="tk-filter-input"
          placeholder={t("page.tasks.filter_q", "Search tasks…")}
          defaultValue={query.q || ""}
          onKeyDown={(e) => {
            if (e.key === "Enter")
              setQuery({ q: (e.target as HTMLInputElement).value || null }, { resetPage: true });
          }}
        />
        <select
          className="tk-filter-select"
          value={query.status || ""}
          onChange={(e) => setQuery({ status: e.target.value || null }, { resetPage: true })}
          aria-label={t("page.tasks.filter_status", "Any status")}
        >
          <option value="">{t("page.tasks.filter_status", "Any status")}</option>
          {["todo", "in_progress", "done", "cancelled"].map((s) => (
            <option key={s} value={s}>
              {taskStatusLabel(t, s)}
            </option>
          ))}
        </select>
        <select
          className="tk-filter-select"
          value={query.priority || ""}
          onChange={(e) => setQuery({ priority: e.target.value || null }, { resetPage: true })}
          aria-label={t("page.tasks.filter_priority", "Any priority")}
        >
          <option value="">{t("page.tasks.filter_priority", "Any priority")}</option>
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>
              {t(`page.tasks.priority_${p}`, p)}
            </option>
          ))}
        </select>
        <select
          className="tk-filter-select"
          value={query.assignee || ""}
          onChange={(e) => setQuery({ assignee: e.target.value || null }, { resetPage: true })}
          aria-label={t("page.tasks.filter_assignee", "Anyone")}
        >
          <option value="">{t("page.tasks.filter_assignee", "Anyone")}</option>
          {people.map((p) => (
            <option key={p.id} value={p.id}>
              {p.full_name || p.email}
            </option>
          ))}
        </select>
        <select
          className="tk-filter-select"
          value={query.action || ""}
          onChange={(e) => setQuery({ action: e.target.value || null }, { resetPage: true })}
          aria-label={t("page.tasks.filter_action", "Any action")}
        >
          <option value="">{t("page.tasks.filter_action", "Any action")}</option>
          {catalog.map((a) => (
            <option key={a.code} value={a.code}>
              {a.label}
            </option>
          ))}
        </select>
        <label className="tk-filter-check">
          <input
            type="checkbox"
            checked={query.overdue === "1"}
            onChange={(e) => setQuery({ overdue: e.target.checked ? "1" : null }, { resetPage: true })}
          />
          {t("page.tasks.filter_overdue", "Overdue only")}
        </label>
        <label className="tk-filter-check">
          <input
            type="checkbox"
            checked={query.include_done === "1"}
            onChange={(e) => setQuery({ include_done: e.target.checked ? "1" : null }, { resetPage: true })}
          />
          {t("page.tasks.filter_include_done", "Include done")}
        </label>
      </div>

      {refWarn ? <p className="flash-err">{refWarn}</p> : null}

      {/* ── 工作包视角 ── */}
      {tab === "work_package" ? (
        <div className="panel">
          <StateView
            loading={false}
            error=""
            empty={!packages.length}
            emptyText={t("page.tasks.no_packages", "No work packages yet.")}
          >
            <div className="tk-card-grid">
              {packages.map((p) => (
                <div key={p.id} className={`tk-card ${p.id === query.work_package_id ? "active" : ""}`}>
                  <div className="tk-card-head">
                    <span className="tk-badge">{p.code}</span>
                    <strong>{p.title}</strong>
                    <span className={`pill ${p.status === "closed" ? "cancelled" : "pending"}`}>{p.status}</span>
                  </div>
                  {p.description ? <p className="muted">{p.description}</p> : null}
                  <progress
                    className="tk-progress"
                    value={Math.round(p.progress)}
                    max={100}
                    aria-label={t("page.tasks.progress", "Progress")}
                  />
                  <div className="tk-card-foot">
                    <span className="muted">{Math.round(p.progress)}%</span>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() =>
                        setQuery(
                          {
                            work_package_id: p.id === query.work_package_id ? null : p.id,
                            objective_id: null,
                          },
                          { resetPage: true },
                        )
                      }
                    >
                      {t("page.tasks.view_tasks", "View tasks")}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </StateView>
        </div>
      ) : null}

      {/* ── OKR 视角 ── */}
      {tab === "okr" ? (
        <div className="panel">
          <StateView
            loading={false}
            error=""
            empty={!objectives.length}
            emptyText={t("page.tasks.no_objectives", "No objectives yet.")}
          >
            <div className="tk-okr-tree">
              {objectives.map((o) => (
                <div key={o.id} className={`tk-okr-node ${o.id === query.objective_id ? "active" : ""}`}>
                  <div className="tk-okr-head">
                    <span className="tk-badge">{o.code}</span>
                    <strong>{o.title}</strong>
                    {o.period ? <span className="muted">{o.period}</span> : null}
                    <span className="muted">{Math.round(o.progress)}%</span>
                  </div>
                  <progress
                    className="tk-progress"
                    value={Math.round(o.progress)}
                    max={100}
                    aria-label={t("page.tasks.progress", "Progress")}
                  />
                  <ul className="tk-kr-list">
                    {(krs[o.id] || []).map((kr) => (
                      <li key={kr.id} className="tk-kr">
                        <span className="tk-kr-title">{kr.title}</span>
                        <span className="muted">
                          {kr.current_value}/{kr.target_value} {kr.unit || ""}
                        </span>
                        <span className="muted">{Math.round(kr.progress)}%</span>
                      </li>
                    ))}
                  </ul>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() =>
                      setQuery(
                        {
                          objective_id: o.id === query.objective_id ? null : o.id,
                          work_package_id: null,
                        },
                        { resetPage: true },
                      )
                    }
                  >
                    {t("page.tasks.view_tasks", "View tasks")}
                  </button>
                </div>
              ))}
            </div>
          </StateView>
        </div>
      ) : null}

      {/* ── 列表视角 ── */}
      {showList ? (
        <div className="panel">
          {tab === "team" ? (
            <StateView
              loading={loading}
              error={error}
              empty={!rows.length}
              emptyText={t("page.tasks.empty", "No tasks.")}
              onRetry={load}
            >
              <TaskTeamBoard
                rows={rows}
                people={people}
                busyId={busyId}
                onComplete={(x) => transition(x, "complete")}
                onReopen={(x) => transition(x, "reopen")}
                onOpen={(x) => setDetailId(x.id)}
              />
            </StateView>
          ) : (
            <StateView
              loading={loading}
              error={error}
              empty={!rows.length}
              emptyText={t("page.tasks.empty", "No tasks.")}
              onRetry={load}
            >
              {rows.map((task) => (
                <TaskRow
                  key={task.id}
                  task={task}
                  busy={busyId === task.id}
                  onComplete={(x) => transition(x, "complete")}
                  onReopen={(x) => transition(x, "reopen")}
                  onOpen={(x) => setDetailId(x.id)}
                />
              ))}
            </StateView>
          )}

          {total > limit ? (
            <div className="tk-pager">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={page <= 1}
                onClick={() => setQuery({ page: page - 1 })}
              >
                {t("common.prev_page", "Previous")}
              </button>
              <span className="muted">
                {t("page.tasks.page_of", "Page {p} of {n}", { p: page, n: totalPages })} · {total}
              </span>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={page >= totalPages}
                onClick={() => setQuery({ page: page + 1 })}
              >
                {t("common.next_page", "Next")}
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      <ConfirmDialog
        open={Boolean(deletePending)}
        title={t("common.confirm", "Confirm")}
        message={t("page.tasks.confirm_delete", 'Delete "{name}"?', { name: deleteLabel })}
        danger
        confirmLabel={t("common.delete", "Delete")}
        onConfirm={() => {
          const fn = deletePending;
          setDeletePending(null);
          fn?.();
        }}
        onCancel={() => setDeletePending(null)}
      />

      {/* ── 新建 / 编辑任务 ── */}
      <RecordModal
        open={Boolean(draft)}
        title={draft?.id ? t("page.tasks.edit", "Edit task") : t("page.tasks.new", "New task")}
        onClose={() => setDraft(null)}
        onSave={saveDraft}
        canDelete={!!draft?.id}
        onDelete={
          draft?.id
            ? () => {
                setDeleteLabel(draft.title);
                setDeletePending(() => () => deleteTask(draft.id as string));
              }
            : undefined
        }
        saving={saving}
        size="lg"
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
            onChange={(e) =>
              setDraft((d) => (d ? { ...d, priority: e.target.value as TaskOut["priority"] } : d))
            }
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
            {people.map((p) => (
              <option key={p.id} value={p.id}>
                {p.full_name || p.email}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("page.tasks.field_action", "System action (auto-complete)")}
          <select
            value={draft?.action_code || ""}
            onChange={(e) => {
              const code = e.target.value;
              const spec = catalog.find((a) => a.code === code);
              setDraft((d) =>
                d
                  ? {
                      ...d,
                      action_code: code,
                      entity_type: spec ? spec.entity_type : d.entity_type,
                    }
                  : d,
              );
            }}
          >
            <option value="">{t("page.tasks.action_none_pick", "None")}</option>
            {actionOptions.map((a) => (
              <option key={a.code} value={a.code}>
                {a.label}
              </option>
            ))}
          </select>
        </label>
        {chosenAction ? (
          <p className="tk-hint">
            {t(
              "page.tasks.action_hint",
              "When this action is done in the system, the task is ticked automatically.",
            )}
          </p>
        ) : null}
        <label>
          {t("page.tasks.field_entity_type", "Linked record type")}
          <input
            value={draft?.entity_type || ""}
            placeholder="voyage / invoice / claim …"
            onChange={(e) => setDraft((d) => (d ? { ...d, entity_type: e.target.value } : d))}
          />
        </label>
        <label>
          {t("page.tasks.field_entity_id", "Linked record id")}
          <input
            value={draft?.entity_id || ""}
            placeholder="UUID"
            onChange={(e) => setDraft((d) => (d ? { ...d, entity_id: e.target.value } : d))}
          />
        </label>
        <label>
          {t("page.tasks.field_weight", "Weight")}
          <input
            type="number"
            step="0.5"
            min="0.5"
            value={draft?.weight || "1"}
            onChange={(e) => setDraft((d) => (d ? { ...d, weight: e.target.value } : d))}
          />
        </label>
        <label>
          {t("page.tasks.field_collaborators", "Collaborators")}
          <select
            multiple
            size={4}
            value={draft?.collaborator_ids || []}
            onChange={(e) =>
              setDraft((d) =>
                d
                  ? {
                      ...d,
                      collaborator_ids: Array.from(e.target.selectedOptions).map((o) => o.value),
                    }
                  : d,
              )
            }
          >
            {people.map((p) => (
              <option key={p.id} value={p.id}>
                {p.full_name || p.email}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("page.tasks.field_work_package", "Work package")}
          <select
            value={draft?.work_package_id || ""}
            onChange={(e) => setDraft((d) => (d ? { ...d, work_package_id: e.target.value } : d))}
          >
            <option value="">{t("page.tasks.none", "None")}</option>
            {packages.map((p) => (
              <option key={p.id} value={p.id}>
                {p.code} · {p.title}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("page.tasks.field_objective", "OKR objective")}
          <select
            value={draft?.objective_id || ""}
            onChange={(e) => setDraft((d) => (d ? { ...d, objective_id: e.target.value } : d))}
          >
            <option value="">{t("page.tasks.none", "None")}</option>
            {objectives.map((o) => (
              <option key={o.id} value={o.id}>
                {o.code} · {o.title}
              </option>
            ))}
          </select>
        </label>
      </RecordModal>

      <TaskDetailModal
        taskId={detailId}
        people={people}
        onClose={() => setDetailId(null)}
        onChanged={load}
      />
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
