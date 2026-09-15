"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AppShell, useShellBootstrap } from "@/components/AppShell";
import { HubTile } from "@/components/HubTile";
import { StateView } from "@/components/StateView";
import { apiGet, apiMe, apiPost, type HomeSummary, type TaskOut } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

function dueLabel(dueAt: string | null, t: (k: string, f?: string, v?: Record<string, string | number>) => string) {
  if (!dueAt) return null;
  const due = new Date(dueAt);
  if (Number.isNaN(due.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const day = new Date(due);
  day.setHours(0, 0, 0, 0);
  const diff = Math.round((day.getTime() - today.getTime()) / 86_400_000);
  if (diff < 0) return { text: t("page.home.overdue_days", "已逾期 {n} 天", { n: -diff }), overdue: true };
  if (diff === 0) return { text: t("page.home.due_today", "今天截止"), overdue: false };
  return { text: dueAt.slice(0, 10), overdue: false };
}

export default function WorkbenchPage() {
  const { shell } = useShellBootstrap();
  const { t, locale } = useI18n();
  const [fullName, setFullName] = useState("");
  const [summary, setSummary] = useState<HomeSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState("");

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
      await loadSummary();
    } catch {
      // summary refresh on next poll/manual retry
    } finally {
      setBusyId("");
    }
  }

  const hour = new Date().getHours();
  const greeting =
    hour < 12 ? t("page.home.morning", "早上好") : hour < 18 ? t("page.home.afternoon", "下午好") : t("page.home.evening", "晚上好");
  const todayText = new Date().toLocaleDateString(locale.startsWith("zh") ? "zh-CN" : "en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "long",
  });

  const openTasks = summary?.tasks.open ?? 0;
  const unread = summary?.notifications.unread ?? 0;
  const approvals = summary?.approvals.count ?? 0;

  return (
    <AppShell>
      <div className="panel home-greet">
        <div>
          <h1 style={{ margin: 0 }}>
            {t("page.home.greeting", "{greeting}，{name}", { greeting, name: fullName || "…" })}
          </h1>
          <p className="page-sub">{todayText}</p>
        </div>
        <p className="home-greet-summary">
          {t("page.home.overview", "你有 {tasks} 个待办任务、{unread} 条未读通知、{approvals} 项待审批。", {
            tasks: openTasks,
            unread,
            approvals,
          })}
        </p>
        {shell?.quick_actions?.length ? (
          <div className="quick-row">
            {shell.quick_actions.map((a) => (
              <Link key={a.href + a.label} href={a.href} className="btn btn-ghost btn-sm">
                {a.label}
              </Link>
            ))}
          </div>
        ) : null}
      </div>

      <StateView
        loading={loading && !summary}
        error={error}
        empty={false}
        onRetry={loadSummary}
      >
        {summary?.kpis?.length ? (
          <div className="kpi-row home-kpi-row">
            {summary.kpis.map((k) => {
              const label = locale.startsWith("zh") ? k.label.zh || k.label.en : k.label.en;
              const card = (
                <>
                  <span>{label}</span>
                  <strong>{k.value}</strong>
                  {k.hint ? <small className="muted">{k.hint}</small> : null}
                </>
              );
              return k.href ? (
                <Link key={k.key} href={k.href} className="kpi-card kpi-link">
                  {card}
                </Link>
              ) : (
                <div key={k.key} className="kpi-card">
                  {card}
                </div>
              );
            })}
          </div>
        ) : null}

        <div className="desk-grid-3">
          <div className="panel desk-card">
            <div className="desk-card-head">
              <h2>{t("page.home.my_tasks", "我的任务")}</h2>
              <Link href="/tasks" className="btn btn-ghost btn-sm">
                {t("page.home.view_all", "查看全部")}
              </Link>
            </div>
            {summary?.tasks.items.length ? (
              summary.tasks.items.slice(0, 5).map((task) => {
                const due = dueLabel(task.due_at, t);
                return (
                  <div key={task.id} className="task-row">
                    <input
                      type="checkbox"
                      className="task-check"
                      aria-label={t("page.home.complete_task", "完成任务")}
                      disabled={busyId === task.id}
                      checked={false}
                      onChange={() => completeTask(task)}
                    />
                    <span className="task-row-main">
                      <span className="task-row-title">
                        <span className={`pill ${task.priority}`}>{task.priority}</span>
                        {task.title}
                      </span>
                      {due ? (
                        <small className={due.overdue ? "overdue" : "muted"}>{due.text}</small>
                      ) : null}
                    </span>
                  </div>
                );
              })
            ) : (
              <p className="muted">{t("page.home.no_tasks", "今日无待办")}</p>
            )}
          </div>

          <div className="panel desk-card">
            <div className="desk-card-head">
              <h2>{t("page.home.todo_alerts", "待办与提醒")}</h2>
            </div>
            <Link href="/workflows/inbox" className="approval-row">
              <span>{t("page.home.approvals", "待审批")}</span>
              <strong>{approvals}</strong>
            </Link>
            {(summary?.approvals.items || []).slice(0, 3).map((a, i) => (
              <Link key={i} href={a.href || "/workflows/inbox"} className="alert-row">
                <span className="alert-row-title">{a.title || t("page.home.approval_item", "审批事项")}</span>
              </Link>
            ))}
            {(summary?.alerts || []).map((a, i) => (
              <Link key={`${a.kind}-${i}`} href={a.href || "/home"} className={`alert-row ${a.severity === "critical" ? "critical" : "warning"}`}>
                <span className="alert-row-title">{a.title}</span>
                {a.detail ? <small className="muted">{a.detail}</small> : null}
              </Link>
            ))}
            {!summary?.alerts?.length && !summary?.approvals.items?.length ? (
              <p className="muted">{t("page.home.no_alerts", "暂无提醒")}</p>
            ) : null}
          </div>

          <div className="panel desk-card">
            <div className="desk-card-head">
              <h2>{t("page.home.schedule", "近期日程")}</h2>
            </div>
            {summary?.schedule.length ? (
              summary.schedule.map((s, i) => {
                const d = new Date(s.start);
                const when = Number.isNaN(d.getTime())
                  ? s.start
                  : d.toLocaleString(locale.startsWith("zh") ? "zh-CN" : "en-US", {
                      month: "2-digit",
                      day: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                    });
                const inner = (
                  <>
                    <span className="schedule-when">{when}</span>
                    <span className="schedule-main">
                      <strong>{s.title}</strong>
                      {s.subtitle ? <small className="muted">{s.subtitle}</small> : null}
                    </span>
                  </>
                );
                return s.href ? (
                  <Link key={i} href={s.href} className="schedule-row">
                    {inner}
                  </Link>
                ) : (
                  <div key={i} className="schedule-row">
                    {inner}
                  </div>
                );
              })
            ) : (
              <p className="muted">{t("page.home.no_schedule", "近期暂无日程安排")}</p>
            )}
          </div>
        </div>
      </StateView>

      <h2 className="home-quick-title">{t("page.home.quick_links", "快捷入口")}</h2>
      <div className="workbench-grid">
        {(shell?.home_widgets || []).map((w) => (
          <HubTile key={w.id} href={w.href} title={w.title} description={w.hint} />
        ))}
      </div>
    </AppShell>
  );
}
