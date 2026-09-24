"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AppShell, useShellBootstrap } from "@/components/AppShell";
import { OnboardingCard } from "@/components/OnboardingCard";
import { PageGuide } from "@/components/PageGuide";
import { StateView } from "@/components/StateView";
import { NavIcon, resolveIconId } from "@/components/NavIcon";
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
  if (diff < 0) return { text: t("page.home.overdue_days", "逾期{n}天", { n: -diff }), overdue: true };
  if (diff === 0) return { text: t("page.home.due_today", "今天"), overdue: false };
  if (diff === 1) return { text: t("page.home.due_tomorrow", "明天"), overdue: false };
  return { text: dueAt.slice(5, 10), overdue: false };
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
      {/* Compact toolbar header */}
      <div className="wb-toolbar">
        <div className="wb-toolbar-left">
          <span className="wb-greet">{fullName}</span>
          <span className="wb-date">{todayText}</span>
          <span className="wb-sep">|</span>
          <span className="wb-stat">
            {t("page.home.stat_tasks", "待办")} <strong>{openTasks}</strong>
          </span>
          <span className="wb-stat">
            {t("page.home.stat_unread", "未读")} <strong>{unread}</strong>
          </span>
          <span className="wb-stat">
            {t("page.home.stat_approvals", "审批")} <strong>{approvals}</strong>
          </span>
          {excCritical > 0 ? (
            <Link href="/exceptions" className="wb-stat wb-stat-danger">
              {t("page.home.exc", "异常")} <strong>{excCritical}</strong>
            </Link>
          ) : null}
        </div>
        <div className="wb-toolbar-right">
          {shell?.quick_actions?.slice(0, 4).map((a) => (
            <Link key={a.href + a.label} href={a.href} className="wb-quick-btn">
              {a.label}
            </Link>
          ))}
        </div>
        <PageGuide pageKey="home" />
      </div>

      <OnboardingCard />

      <StateView loading={loading && !summary} error={error} empty={false} onRetry={loadSummary}>
        {/* KPI strip — inline compact */}
        {summary?.kpis?.length ? (
          <div className="wb-kpi-strip">
            {summary.kpis.map((k) => {
              const label = locale.startsWith("zh") ? k.label.zh || k.label.en : k.label.en;
              const inner = (
                <>
                  <span className="wb-kpi-val">{k.value}</span>
                  <span className="wb-kpi-label">{label}</span>
                </>
              );
              return k.href ? (
                <Link key={k.key} href={k.href} className="wb-kpi-item">
                  {inner}
                </Link>
              ) : (
                <span key={k.key} className="wb-kpi-item">
                  {inner}
                </span>
              );
            })}
          </div>
        ) : null}

        {/* Main 3-panel desk — compact */}
        <div className="wb-desk">
          {/* Tasks */}
          <div className="wb-col">
            <div className="wb-col-head">
              <h2>{t("page.home.my_tasks", "我的任务")}</h2>
              <Link href="/tasks" className="wb-more">{t("page.home.view_all", "全部")} →</Link>
            </div>
            <div className="wb-task-list">
              {summary?.tasks.items.length ? (
                summary.tasks.items.slice(0, 8).map((task) => {
                  const due = dueLabel(task.due_at, t);
                  return (
                    <label key={task.id} className="wb-task">
                      <input
                        type="checkbox"
                        className="task-check"
                        disabled={busyId === task.id}
                        checked={false}
                        onChange={() => completeTask(task)}
                      />
                      <span className={`wb-task-pri pill-${task.priority}`}>{task.priority[0]?.toUpperCase()}</span>
                      <span className="wb-task-title">{task.title}</span>
                      {due ? (
                        <span className={`wb-task-due ${due.overdue ? "overdue" : ""}`}>{due.text}</span>
                      ) : null}
                    </label>
                  );
                })
              ) : (
                <div className="wb-empty">{t("page.home.no_tasks", "暂无待办")}</div>
              )}
            </div>
          </div>

          {/* Alerts & Approvals */}
          <div className="wb-col">
            <div className="wb-col-head">
              <h2>{t("page.home.todo_alerts", "待办与提醒")}</h2>
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
              {(summary?.alerts || []).map((a, i) => (
                <Link
                  key={`${a.kind}-${i}`}
                  href={a.href || "/home"}
                  className={`wb-alert-item ${a.severity === "critical" ? "wb-alert-danger" : "wb-alert-warn"}`}
                >
                  <span className="wb-alert-title">{a.title}</span>
                  {a.detail ? <span className="wb-alert-detail">{a.detail}</span> : null}
                </Link>
              ))}
              {!summary?.alerts?.length && !summary?.approvals.items?.length ? (
                <div className="wb-empty">{t("page.home.no_alerts", "暂无提醒")}</div>
              ) : null}
            </div>
          </div>

          {/* Schedule */}
          <div className="wb-col">
            <div className="wb-col-head">
              <h2>{t("page.home.schedule", "日程")}</h2>
            </div>
            <div className="wb-sched-list">
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
                      <span className="wb-sched-time">{when}</span>
                      <span className="wb-sched-title">{s.title}</span>
                    </>
                  );
                  return s.href ? (
                    <Link key={i} href={s.href} className="wb-sched-row">
                      {inner}
                    </Link>
                  ) : (
                    <div key={i} className="wb-sched-row">
                      {inner}
                    </div>
                  );
                })
              ) : (
                <div className="wb-empty">{t("page.home.no_schedule", "暂无日程")}</div>
              )}
            </div>
          </div>
        </div>

        {/* Quick links — compact grid */}
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
