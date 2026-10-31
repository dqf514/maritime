"use client";

// Workbench — 专业工作台布局
// 集成任务管理、审批、异常、日程、KPI 于一体
// 采用软件式面板网格布局，信息密度高

import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell, useShellBootstrap } from "@/components/AppShell";
import { ActivityLogModal, actionLabel, type ActivityItem } from "@/components/ActivityLogModal";
import { OnboardingCard } from "@/components/OnboardingCard";
import { PageGuide } from "@/components/PageGuide";
import { PageHeader } from "@/components/PageHeader";
import { SavedViews } from "@/components/SavedViews";
import { StateView } from "@/components/StateView";
import { NavIcon, resolveIconId } from "@/components/NavIcon";
import { useListHotkeys } from "@/components/useListHotkeys";
import { formatInTz, parseUtc, utcDayDiff } from "@/lib/datetime";
import { msgOf } from "@/lib/errors";
import { apiGet, apiMe, apiPost, apiPatch, type HomeSummary, type TaskOut, type TaskAssignee } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";
import { useToast } from "@/components/ToastProvider";

const PRIORITY_COLORS: Record<string, string> = {
  urgent: "#dc2626",
  high: "#d97706",
  normal: "#3b82f6",
  low: "#6b7280",
};

function dueInfo(dueAt: string | null, t: any, locale: string) {
  if (!dueAt) return null;
  if (!parseUtc(dueAt)) return null;
  // 自然日按 UTC 日界比较（后端存 UTC；否则非 UTC 时区会整体偏移一天）。
  const diff = utcDayDiff(dueAt);
  if (diff === null) return null;
  if (diff < 0) return { text: t("page.home.overdue_days", "Overdue {n} days", { n: -diff }), overdue: true, days: diff };
  if (diff === 0) return { text: t("page.home.due_today", "Due today"), overdue: false, days: 0 };
  if (diff === 1) return { text: t("page.home.due_tomorrow", "Tomorrow"), overdue: false, days: 1 };
  return { text: dueAt.slice(5, 10), overdue: false, days: diff };
}

type TaskFilter = "all" | "open" | "today" | "overdue" | "done";

function timeAgo(iso: string | null, t: any): string {
  if (!iso) return "";
  const d = parseUtc(iso);
  if (!d) return "";
  const s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 60) return t("page.home.time_just", "just now");
  if (s < 3600) return t("page.home.time_min", "{n}m", { n: Math.floor(s / 60) });
  if (s < 86400) return t("page.home.time_hr", "{n}h", { n: Math.floor(s / 3600) });
  return t("page.home.time_day", "{n}d", { n: Math.floor(s / 86400) });
}

function WorkbenchPageInner() {
  const { shell } = useShellBootstrap();
  const { t, locale } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const { query, setQuery } = useListQuery();
  const [fullName, setFullName] = useState("");
  const [summary, setSummary] = useState<HomeSummary | null>(null);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  /** 动态流（次级列表）加载失败 —— 局部提示，不影响主面板 */
  const [activityErr, setActivityErr] = useState<string | null>(null);
  /** 顶栏用户信息（参考数据）加载失败 */
  const [meErr, setMeErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState("");
  const taskFilter: TaskFilter =
    query.tf === "today" || query.tf === "overdue" || query.tf === "done" || query.tf === "all" ? query.tf : "open";
  const setTaskFilter = (f: TaskFilter) => setQuery({ tf: f === "open" ? null : f });
  const [showNewTask, setShowNewTask] = useState(false);
  /** 全量操作日志弹窗（分页 + 关键字筛选 + 可全屏） */
  const [showActivityLog, setShowActivityLog] = useState(false);
  const [newTaskTitle, setNewTaskTitle] = useState("");
  const [newTaskPriority, setNewTaskPriority] = useState("normal");
  const [newTaskDue, setNewTaskDue] = useState("");

  useListHotkeys(() => setShowNewTask(true));

  const loadSummary = useCallback(async () => {
    setLoading(true);
    setError("");
    // 主面板（summary）与动态流（次级列表）分别成败 —— 动态流失败只做局部提示
    const [sumR, actR] = await Promise.allSettled([
      apiGet("/api/v1/home/summary"),
      apiGet("/api/v1/activity/feed?limit=12"),
    ]);
    if (sumR.status === "fulfilled") {
      setSummary(sumR.value as HomeSummary);
      setError("");
    } else {
      setError(msgOf(sumR.reason, t("common.failed", "Failed")));
    }
    if (actR.status === "fulfilled") {
      setActivity((actR.value as any)?.items || []);
      setActivityErr(null);
    } else {
      setActivity([]);
      setActivityErr(msgOf(actR.reason));
    }
    setLoading(false);
  }, [t]);

  useEffect(() => {
    apiMe()
      .then((m) => {
        setFullName(m.user.full_name || m.user.email);
        setMeErr(null);
      })
      // 顶栏用户名取不到时给出提示，不能静默显示为空
      .catch((ex) => setMeErr(msgOf(ex)));
  }, []);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  async function completeTask(task: TaskOut) {
    setBusyId(task.id);
    try {
      await apiPost(`/api/v1/tasks/${task.id}/complete`);
      toast.success(t("page.home.task_done", "Task completed"));
      await loadSummary();
    } catch {
      toast.error(t("common.failed", "Failed"));
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
      toast.success(t("page.home.task_created", "Task created"));
      setNewTaskTitle("");
      setNewTaskPriority("normal");
      setNewTaskDue("");
      setShowNewTask(false);
      await loadSummary();
    } catch {
      toast.error(t("common.failed", "Failed"));
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
      <PageHeader
        breadcrumb={[{ label: t("nav.home", "Workbench") }]}
        title={t("page.home.title", "Workbench")}
        subtitle={t("page.home.sub", "Tasks, approvals, exceptions and today's fleet pulse.")}
        actions={
          <>
            <PageGuide pageKey="home" />
            <SavedViews storageKey="home_list" onApply={(q) => router.replace(`/home${q}`)} />
          </>
        }
      />

      {/* ── Top status bar ── */}
      <div className="wb-statusbar">
        <div className="wb-statusbar-left">
          <span className="wb-greet">{fullName}</span>
          {meErr ? (
            <span className="muted">
              {t("page.home.me_fail", "Profile unavailable: {err}", { err: meErr })}
            </span>
          ) : null}
          <span className="wb-date">{todayText}</span>
        </div>
        <div className="wb-statusbar-kpis">
          <Link href="/tasks" className="wb-kpi-chip">
            <span className="wb-kpi-chip-val">{openTasks}</span>
            <span className="wb-kpi-chip-label">{t("page.home.stat_tasks", "Tasks")}</span>
          </Link>
          <Link href="/workflows/inbox" className="wb-kpi-chip">
            <span className="wb-kpi-chip-val">{approvals}</span>
            <span className="wb-kpi-chip-label">{t("page.home.stat_approvals", "Approvals")}</span>
          </Link>
          <span className="wb-kpi-chip">
            <span className="wb-kpi-chip-val">{unread}</span>
            <span className="wb-kpi-chip-label">{t("page.home.stat_unread", "Unread")}</span>
          </span>
          {excCritical > 0 ? (
            <Link href="/exceptions" className="wb-kpi-chip wb-kpi-danger">
              <span className="wb-kpi-chip-val">{excCritical}</span>
              <span className="wb-kpi-chip-label">{t("page.home.exc", "Exceptions")}</span>
            </Link>
          ) : null}
        </div>
        <div className="wb-statusbar-right">
          {shell?.quick_actions?.slice(0, 3).map((a) => (
            <Link key={a.href + a.label} href={a.href} className="wb-quick-btn">
              {locale.startsWith("zh") ? a.label_zh || a.label : a.label}
            </Link>
          ))}
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

        {/* ── Main grid: 12 栏按内容权重分格（每个面板只占自己内容的高度） ── */}
        <div className="wb-grid">
          {/* 我的任务 —— 4 栏：条目不多，宽栏会空出一大片 */}
          <div className="wb-panel wb-span-4">
            <div className="wb-panel-head">
              <h2 className="wb-panel-title">
                <NavIcon id="tasks" size={14} />
                {t("page.home.my_tasks", "My tasks")}
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
                        ? t("page.home.filter_open", "In progress")
                        : f === "today"
                          ? t("page.home.filter_today", "Today")
                          : f === "overdue"
                            ? t("page.home.filter_overdue", "Overdue")
                            : t("page.home.filter_done", "Done")}
                    </button>
                  ))}
                </div>
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  onClick={() => setShowNewTask((v) => !v)}
                >
                  + {t("page.home.new_task", "New")}
                </button>
              </div>
            </div>

            {/* New task inline form */}
            {showNewTask ? (
              <div className="wb-new-task">
                <input
                  type="text"
                  className="wb-new-task-input"
                  aria-label={t("page.home.task_title_ph", "Task title…")}
                  placeholder={t("page.home.task_title_ph", "Task title…")}
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
                  <option value="low">{t("page.home.pri_low", "Low")}</option>
                  <option value="normal">{t("page.home.pri_normal", "Normal")}</option>
                  <option value="high">{t("page.home.pri_high", "High")}</option>
                  <option value="urgent">{t("page.home.pri_urgent", "Urgent")}</option>
                </select>
                <input
                  type="date"
                  value={newTaskDue}
                  onChange={(e) => setNewTaskDue(e.target.value)}
                  className="wb-new-task-due"
                />
                <button type="button" className="btn btn-sm btn-primary" onClick={createTask}>
                  {t("common.add", "Add")}
                </button>
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => setShowNewTask(false)}>
                  {t("common.cancel", "Cancel")}
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
                        title={t("page.home.mark_done", "Mark done")}
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
                <div className="wb-empty">{t("page.home.no_tasks", "No tasks")}</div>
              )}
            </div>
            <div className="wb-panel-foot">
              <span className="muted">
                {t("page.home.task_count", "{n} tasks", { n: summary?.tasks.items?.length ?? 0 })}
              </span>
              {summary?.tasks.items && summary.tasks.items.length > 15 ? (
                <Link href="/tasks" className="wb-more">
                  {t("page.home.view_all", "View all")} →
                </Link>
              ) : null}
            </div>
          </div>

          {/* 最近活动 —— 4 栏：只给最新 8 条预览，全量走弹窗 */}
          <div className="wb-panel wb-span-4">
            <div className="wb-panel-head">
              <h2 className="wb-panel-title">
                <NavIcon id="exceptions" size={14} />
                {t("page.home.recent_activity", "Recent activity")}
              </h2>
              <div className="wb-panel-actions">
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setShowActivityLog(true)}
                  title={t("page.home.activity_log", "Activity log")}
                >
                  {t("page.home.activity_view_all", "View all")}
                </button>
              </div>
            </div>
          <div className="wb-alert-list">
            {activityErr ? (
              <div className="wb-empty" role="alert">
                {t("page.home.activity_fail", "Activity feed could not be loaded: {err}", { err: activityErr })}
              </div>
            ) : null}
            {activity.length ? (
              activity.slice(0, 8).map((a) => {
                const body = (
                  <>
                    <span className="wb-alert-title">
                      {a.actor || t("page.home.someone", "Someone")}{" "}
                      <span className="wb-activity-action">{actionLabel(a.action)}</span>{" "}
                      {a.entity_type}
                    </span>
                    <span className="wb-activity-time">{timeAgo(a.created_at, t)}</span>
                  </>
                );
                return a.href ? (
                  <Link key={a.id} href={a.href} className="wb-alert-item">
                    {body}
                  </Link>
                ) : (
                  <div key={a.id} className="wb-alert-item">
                    {body}
                  </div>
                );
              })
            ) : (
              <div className="wb-empty">{activityErr ? "" : t("page.home.no_activity", "No recent activity")}</div>
            )}
          </div>
          <div className="wb-panel-foot">
            <span className="muted">
              {t("page.home.activity_count", "{n} activities (showing the latest 8)", { n: activity.length })}
            </span>
          </div>
        </div>

        {/* 待办与提醒 —— 4 栏 */}
        <div className="wb-panel wb-span-4">
          <div className="wb-panel-head">
            <h2 className="wb-panel-title">
              <NavIcon id="exceptions" size={14} />
              {t("page.home.todo_alerts", "Tasks & alerts")}
            </h2>
          </div>
          <div className="wb-alert-list">
            {summary?.exceptions && (excCritical > 0 || excWarning > 0) ? (
              <Link href="/exceptions" className="wb-alert-item wb-alert-danger">
                <span>{t("page.home.exceptions", "Business exceptions")}</span>
                <span className="wb-alert-badges">
                  {excCritical > 0 ? <span className="exc-badge critical">{excCritical}</span> : null}
                  {excWarning > 0 ? <span className="exc-badge warning">{excWarning}</span> : null}
                </span>
              </Link>
            ) : null}
            <Link href="/workflows/inbox" className="wb-alert-item wb-alert-info">
              <span>{t("page.home.approvals", "Pending approvals")}</span>
              <strong>{approvals}</strong>
            </Link>
            {(summary?.approvals.items || []).slice(0, 3).map((a, i) => (
              <Link key={i} href={a.href || "/workflows/inbox"} className="wb-alert-item">
                <span className="wb-alert-title">{a.title || t("page.home.approval_item", "Approval items")}</span>
              </Link>
            ))}
            {(summary?.alerts || []).slice(0, 4).map((a, i) => (
              <Link
                key={`${a.kind}-${i}`}
                href={a.href || "/home"}
                className={`wb-alert-item ${a.severity === "critical" ? "wb-alert-danger" : "wb-alert-warn"}`}
              >
                <span className="wb-alert-title">
                  {locale.startsWith("zh") ? a.title_i18n?.zh || a.title : a.title_i18n?.en || a.title}
                </span>
                {a.detail ? <span className="wb-alert-detail">{a.detail}</span> : null}
              </Link>
            ))}
            {!summary?.alerts?.length && !summary?.approvals.items?.length && excCritical === 0 ? (
              <div className="wb-empty">{t("page.home.no_alerts", "No alerts")}</div>
            ) : null}
          </div>
          {(summary?.approvals.items || []).length > 3 || (summary?.alerts || []).length > 4 ? (
            <div className="wb-panel-foot">
              <span className="muted">
                {t(
                  "page.home.alerts_count",
                  "{approvals} approvals · {alerts} alerts (showing the first few)",
                  {
                    approvals: (summary?.approvals.items || []).length,
                    alerts: (summary?.alerts || []).length,
                  },
                )}
              </span>
            </div>
          ) : null}
        </div>

        {/* 近期日程 —— 4 栏 */}
        <div className="wb-panel wb-span-4">
          <div className="wb-panel-head">
            <h2 className="wb-panel-title">
              <NavIcon id="tasks" size={14} />
              {t("page.home.schedule", "Upcoming schedule")}
            </h2>
          </div>
          <div className="wb-sched-list">
            {summary?.schedule.length ? (
              summary.schedule.slice(0, 6).map((s, i) => {
                const d = parseUtc(s.start);
                const when = d
                  ? formatInTz(d, null, {
                      year: undefined,
                      month: "2-digit",
                      day: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  : s.start;
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
              <div className="wb-empty">{t("page.home.no_schedule", "No schedule")}</div>
            )}
          </div>
          {(summary?.schedule.length || 0) > 6 ? (
            <div className="wb-panel-foot">
              <span className="muted">
                {t("page.home.schedule_count", "{n} schedule items (showing the first 6)", {
                  n: summary?.schedule.length ?? 0,
                })}
              </span>
            </div>
          ) : null}
        </div>

        {/* 工作队列 —— 8 栏（队列条目多，需要横向空间） */}
        {summary?.queues?.length ? (
          <div className="wb-panel wb-span-8">
            <div className="wb-panel-head">
              <h2 className="wb-panel-title">
                <NavIcon id="inbox" size={14} />
                {t("page.home.work_queues", "Work queues")}
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

        {/* ── Quick links ── */}
        <div className="wb-links-head">{t("page.home.quick_links", "Quick links")}</div>
        <div className="wb-links">
          {(shell?.home_widgets || []).map((w) => (
            <Link key={w.id} href={w.href} className="wb-link-tile">
              <NavIcon id={w.icon || resolveIconId(w.href)} size={14} />
              <span>{locale.startsWith("zh") ? w.title_zh || w.title : w.title}</span>
            </Link>
          ))}
        </div>
      </StateView>

      {/* 全量操作日志（分页 + 关键字筛选 + 可全屏） */}
      {showActivityLog ? <ActivityLogModal onClose={() => setShowActivityLog(false)} /> : null}
    </AppShell>
  );
}

export default function WorkbenchPage() {
  return (
    <Suspense fallback={null}>
      <WorkbenchPageInner />
    </Suspense>
  );
}
