"use client";

// Workbench — 专业工作台布局
// 集成任务管理、审批、异常、日程、KPI 于一体
// 采用软件式面板网格布局，信息密度高

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AppShell, useShellBootstrap } from "@/components/AppShell";
import { OnboardingCard } from "@/components/OnboardingCard";
import { PageGuide } from "@/components/PageGuide";
import { StateView } from "@/components/StateView";
import { NavIcon, resolveIconId } from "@/components/NavIcon";
import { apiGet, apiMe, apiPost, apiPatch, type HomeSummary, type TaskOut, type TaskAssignee } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

const PRIORITY_COLORS: Record<string, string> = {
  urgent: "#dc2626",
  high: "#d97706",
  normal: "#3b82f6",
  low: "#6b7280",
};

function dueInfo(dueAt: string | null, t: any, locale: string) {
  if (!dueAt) return null;
  const due = new Date(dueAt);
  if (Number.isNaN(due.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const day = new Date(due);
  day.setHours(0, 0, 0, 0);
  const diff = Math.round((day.getTime() - today.getTime()) / 86_400_000);
  if (diff < 0) return { text: t("page.home.overdue_days", "逾期{n}天", { n: -diff }), overdue: true, days: diff };
  if (diff === 0) return { text: t("page.home.due_today", "今天"), overdue: false, days: 0 };
  if (diff === 1) return { text: t("page.home.due_tomorrow", "明天"), overdue: false, days: 1 };
  return { text: dueAt.slice(5, 10), overdue: false, days: diff };
}

type TaskFilter = "all" | "open" | "today" | "overdue" | "done";

export default function WorkbenchPage() {
  const { shell } = useShellBootstrap();
  const { t, locale } = useI18n();
  const toast = useToast();
  const [fullName, setFullName] = useState("");
  const [summary, setSummary] = useState<HomeSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState("");
  const [taskFilter, setTaskFilter] = useState<TaskFilter>("open");
  const [showNewTask, setShowNewTask] = useState(false);
  const [newTaskTitle, setNewTaskTitle] = useState("");
  const [newTaskPriority, setNewTaskPriority] = useState("normal");
  const [newTaskDue, setNewTaskDue] = useState("");

  const loadSummary = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setSummary(await apiGet("/api/v1/home/summary"));
    } catch (e: any) {
      setError(e?.message || t("common.failed", "加载失败"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    apiMe()
      .then((m) => setFullName(m.user.full_name || m.user.email))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  async function completeTask(task: TaskOut) {
    setBusyId(task.id);
    try {
      await apiPost(`/api/v1/tasks/${task.id}/complete`);
      toast.success(t("page.home.task_done", "任务已完成"));
      await loadSummary();
    } catch {
      toast.error(t("common.failed", "操作失败"));
    } finally {
      setBusyId("");
    }
  }

  async function createTask() {
    if (!newTaskTitle.trim()) return;
    try {
      await apiPost("/api/v1/tasks", {
        title: newTaskTitle.trim(),
        priority: newTaskPriority,
        due_at: newTaskDue || null,
      });
      toast.success(t("page.home.task_created", "任务已创建"));
      setNewTaskTitle("");
      setNewTaskPriority("normal");
      setNewTaskDue("");
      setShowNewTask(false);
      await loadSummary();
    } catch {
      toast.error(t("common.failed", "创建失败"));
    }
  }

  // Filter tasks
  const filteredTasks = useMemo(() => {
    const items = summary?.tasks.items || [];
    switch (taskFilter) {
      case "done":
        return items.filter((x) => x.status === "done");
      case "today":
        return items.filter((x) => {
          const d = dueInfo(x.due_at, t, locale);
          return d?.days === 0;
        });
      case "overdue":
        return items.filter((x) => {
          const d = dueInfo(x.due_at, t, locale);
          return d?.overdue;
        });
      case "open":
      default:
        return items.filter((x) => x.status !== "done" && x.status !== "cancelled");
    }
  }, [summary?.tasks.items, taskFilter, t, locale]);

  const todayText = new Date().toLocaleDateString(locale.startsWith("zh") ? "zh-CN" : "en-US", {
    month: "short",
    day: "numeric",
    weekday: "short",
  });

  const openTasks = summary?.tasks.open ?? 0;
  const unread = summary?.notifications.unread ?? 0;
  const approvals = summary?.approvals.count ?? 0;
  const excCritical = summary?.exceptions?.critical ?? 0;
  const excWarning = summary?.exceptions?.warning ?? 0;

  return (
    <AppShell>
      {/* ── Top status bar ── */}
      <div className="wb-statusbar">
        <div className="wb-statusbar-left">
          <span className="wb-greet">{fullName}</span>
          <span className="wb-date">{todayText}</span>
        </div>
        <div className="wb-statusbar-kpis">
          <Link href="/tasks" className="wb-kpi-chip">
            <span className="wb-kpi-chip-val">{openTasks}</span>
            <span className="wb-kpi-chip-label">{t("page.home.stat_tasks", "待办")}</span>
          </Link>
          <Link href="/workflows/inbox" className="wb-kpi-chip">
            <span className="wb-kpi-chip-val">{approvals}</span>
            <span className="wb-kpi-chip-label">{t("page.home.stat_approvals", "审批")}</span>
          </Link>
          <span className="wb-kpi-chip">
            <span className="wb-kpi-chip-val">{unread}</span>
            <span className="wb-kpi-chip-label">{t("page.home.stat_unread", "未读")}</span>
          </span>
          {excCritical > 0 ? (
            <Link href="/exceptions" className="wb-kpi-chip wb-kpi-danger">
              <span className="wb-kpi-chip-val">{excCritical}</span>
              <span className="wb-kpi-chip-label">{t("page.home.exc", "异常")}</span>
            </Link>
          ) : null}
        </div>
        <div className="wb-statusbar-right">
          {shell?.quick_actions?.slice(0, 3).map((a) => (
            <Link key={a.href + a.label} href={a.href} className="wb-quick-btn">
              {a.label}
            </Link>
          ))}
          <PageGuide pageKey="home" />
        </div>
      </div>

      <OnboardingCard />

      <StateView loading={loading && !summary} error={error} empty={false} onRetry={loadSummary}>
        {/* ── KPI strip ── */}
        {summary?.kpis?.length ? (
          <div className="wb-kpi-strip">
            {summary.kpis.map((k) => {
              const label = locale.startsWith("zh") ? k.label.zh || k.label.en : k.label.en;
              return (
                <Link key={k.key} href={k.href || "/home"} className="wb-kpi-item">
                  <span className="wb-kpi-val">{k.value}</span>
                  <span className="wb-kpi-label">{label}</span>
                </Link>
              );
            })}
          </div>
        ) : null}

        {/* ── Main grid: Tasks (2/3) + Right panel (1/3) ── */}
        <div className="wb-grid">
          {/* Left: Tasks with full management */}
          <div className="wb-panel">
            <div className="wb-panel-head">
              <h2 className="wb-panel-title">
                <NavIcon id="tasks" size={14} />
                {t("page.home.my_tasks", "我的任务")}
              </h2>
              <div className="wb-panel-actions">
                {/* Filter tabs */}
                <div className="wb-task-filters">
                  {(["open", "today", "overdue", "done"] as TaskFilter[]).map((f) => (
                    <button
                      key={f}
                      type="button"
                      className={`wb-filter-btn ${taskFilter === f ? "active" : ""}`}
                      onClick={() => setTaskFilter(f)}
                    >
                      {f === "open"
                        ? t("page.home.filter_open", "进行中")
                        : f === "today"
                          ? t("page.home.filter_today", "今天")
                          : f === "overdue"
                            ? t("page.home.filter_overdue", "逾期")
                            : t("page.home.filter_done", "已完成")}
                    </button>
                  ))}
                </div>
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  onClick={() => setShowNewTask((v) => !v)}
                >
                  + {t("page.home.new_task", "新建")}
                </button>
              </div>
            </div>

            {/* New task inline form */}
            {showNewTask ? (
              <div className="wb-new-task">
                <input
                  type="text"
                  className="wb-new-task-input"
                  placeholder={t("page.home.task_title_ph", "任务标题…")}
                  value={newTaskTitle}
                  onChange={(e) => setNewTaskTitle(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && createTask()}
                  autoFocus
                />
                <select
                  value={newTaskPriority}
                  onChange={(e) => setNewTaskPriority(e.target.value)}
                  className="wb-new-task-pri"
                >
                  <option value="low">{t("page.home.pri_low", "低")}</option>
                  <option value="normal">{t("page.home.pri_normal", "中")}</option>
                  <option value="high">{t("page.home.pri_high", "高")}</option>
                  <option value="urgent">{t("page.home.pri_urgent", "紧急")}</option>
                </select>
                <input
                  type="date"
                  value={newTaskDue}
                  onChange={(e) => setNewTaskDue(e.target.value)}
                  className="wb-new-task-due"
                />
                <button type="button" className="btn btn-sm btn-primary" onClick={createTask}>
                  {t("common.add", "添加")}
                </button>
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => setShowNewTask(false)}>
                  {t("common.cancel", "取消")}
                </button>
              </div>
            ) : null}

            {/* Task list */}
            <div className="wb-task-list">
              {filteredTasks.length ? (
                filteredTasks.slice(0, 15).map((task) => {
                  const due = dueInfo(task.due_at, t, locale);
                  return (
                    <div key={task.id} className={`wb-task-row ${task.status === "done" ? "done" : ""}`}>
                      <button
                        type="button"
                        className="wb-task-check"
                        disabled={busyId === task.id}
                        onClick={() => completeTask(task)}
                        title={t("page.home.mark_done", "标记完成")}
                      >
                        {task.status === "done" ? "✓" : ""}
                      </button>
                      <span
                        className="wb-task-pri-dot"
                        style={{ background: PRIORITY_COLORS[task.priority] || PRIORITY_COLORS.normal }}
                      />
                      <span className="wb-task-title">{task.title}</span>
                      {due ? (
                        <span className={`wb-task-due ${due.overdue ? "overdue" : ""}`}>{due.text}</span>
                      ) : null}
                      {task.assignee?.full_name || task.assignee?.email ? (
                        <span className="wb-task-assignee">{task.assignee.full_name || task.assignee.email}</span>
                      ) : null}
                    </div>
                  );
                })
              ) : (
                <div className="wb-empty">{t("page.home.no_tasks", "暂无待办")}</div>
              )}
            </div>
            {summary?.tasks.items && summary.tasks.items.length > 15 ? (
              <div className="wb-panel-foot">
                <Link href="/tasks" className="wb-more">
                  {t("page.home.view_all", "查看全部")} ({summary.tasks.items.length}) →
                </Link>
              </div>
            ) : null}
          </div>

          {/* Right: Alerts + Schedule + Queues */}
          <div className="wb-right-col">
            {/* Alerts & Approvals */}
            <div className="wb-panel">
              <div className="wb-panel-head">
                <h2 className="wb-panel-title">
                  <NavIcon id="exceptions" size={14} />
                  {t("page.home.todo_alerts", "待办与提醒")}
                </h2>
              </div>
              <div className="wb-alert-list">
                {summary?.exceptions && (excCritical > 0 || excWarning > 0) ? (
                  <Link href="/exceptions" className="wb-alert-item wb-alert-danger">
                    <span>{t("page.home.exceptions", "业务异常")}</span>
                    <span className="wb-alert-badges">
                      {excCritical > 0 ? <span className="exc-badge critical">{excCritical}</span> : null}
                      {excWarning > 0 ? <span className="exc-badge warning">{excWarning}</span> : null}
                    </span>
                  </Link>
                ) : null}
                <Link href="/workflows/inbox" className="wb-alert-item wb-alert-info">
                  <span>{t("page.home.approvals", "待审批")}</span>
                  <strong>{approvals}</strong>
                </Link>
                {(summary?.approvals.items || []).slice(0, 3).map((a, i) => (
                  <Link key={i} href={a.href || "/workflows/inbox"} className="wb-alert-item">
                    <span className="wb-alert-title">{a.title || t("page.home.approval_item", "审批事项")}</span>
                  </Link>
                ))}
                {(summary?.alerts || []).slice(0, 4).map((a, i) => (
                  <Link
                    key={`${a.kind}-${i}`}
                    href={a.href || "/home"}
                    className={`wb-alert-item ${a.severity === "critical" ? "wb-alert-danger" : "wb-alert-warn"}`}
                  >
                    <span className="wb-alert-title">{a.title}</span>
                    {a.detail ? <span className="wb-alert-detail">{a.detail}</span> : null}
                  </Link>
                ))}
                {!summary?.alerts?.length && !summary?.approvals.items?.length && excCritical === 0 ? (
                  <div className="wb-empty">{t("page.home.no_alerts", "暂无提醒")}</div>
                ) : null}
              </div>
            </div>

            {/* Schedule */}
            <div className="wb-panel">
              <div className="wb-panel-head">
                <h2 className="wb-panel-title">
                  <NavIcon id="tasks" size={14} />
                  {t("page.home.schedule", "日程")}
                </h2>
              </div>
              <div className="wb-sched-list">
                {summary?.schedule.length ? (
                  summary.schedule.slice(0, 6).map((s, i) => {
                    const d = new Date(s.start);
                    const when = Number.isNaN(d.getTime())
                      ? s.start
                      : d.toLocaleString(locale.startsWith("zh") ? "zh-CN" : "en-US", {
                          month: "2-digit",
                          day: "2-digit",
                          hour: "2-digit",
                          minute: "2-digit",
                        });
                    return s.href ? (
                      <Link key={i} href={s.href} className="wb-sched-row">
                        <span className="wb-sched-time">{when}</span>
                        <span className="wb-sched-title">{s.title}</span>
                      </Link>
                    ) : (
                      <div key={i} className="wb-sched-row">
                        <span className="wb-sched-time">{when}</span>
                        <span className="wb-sched-title">{s.title}</span>
                      </div>
                    );
                  })
                ) : (
                  <div className="wb-empty">{t("page.home.no_schedule", "暂无日程")}</div>
                )}
              </div>
            </div>

            {/* Work queues */}
            {summary?.queues?.length ? (
              <div className="wb-panel">
                <div className="wb-panel-head">
                  <h2 className="wb-panel-title">
                    <NavIcon id="inbox" size={14} />
                    {t("page.home.work_queues", "工作队列")}
                  </h2>
                </div>
                <div className="wb-queue-list">
                  {summary.queues.map((q) => {
                    const label = locale.startsWith("zh") ? q.label.zh || q.label.en : q.label.en;
                    return (
                      <div key={q.id} className="wb-queue-group">
                        <div className="wb-queue-group-head">
                          <span>{label}</span>
                          <span className="wb-queue-count">{q.items.length}</span>
                        </div>
                        {q.items.slice(0, 3).map((it) => (
                          <Link
                            key={it.id}
                            href={it.href}
                            className={`wb-queue-item ${it.urgency === "critical" ? "wb-queue-critical" : it.urgency === "warning" ? "wb-queue-warning" : ""}`}
                          >
                            <span className="wb-queue-title">{it.title}</span>
                            {it.meta ? <span className="wb-queue-meta">{it.meta}</span> : null}
                          </Link>
                        ))}
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : null}
          </div>
        </div>

        {/* ── Quick links ── */}
        <div className="wb-links-head">{t("page.home.quick_links", "快捷入口")}</div>
        <div className="wb-links">
          {(shell?.home_widgets || []).map((w) => (
            <Link key={w.id} href={w.href} className="wb-link-tile">
              <NavIcon id={w.icon || resolveIconId(w.href)} size={14} />
              <span>{w.title}</span>
            </Link>
          ))}
        </div>
      </StateView>
    </AppShell>
  );
}
