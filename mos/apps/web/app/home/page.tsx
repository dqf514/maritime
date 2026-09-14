"use client";

import Link from "next/link";
import { AppShell, useShellBootstrap } from "@/components/AppShell";
import { HubTile } from "@/components/HubTile";
import { useI18n } from "@/lib/i18n";

export default function WorkbenchPage() {
  const { shell, error, retry } = useShellBootstrap();
  const { t } = useI18n();

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("home.title", "Workbench")}</h1>
          <p className="page-sub">{t("home.subtitle", "Role-personalized desk — workspace tabs or Ctrl+K.")}</p>
        </div>
        <div className="quick-row">
          {(shell?.quick_actions || []).map((a) => (
            <Link key={a.href + a.label} href={a.href} className="btn btn-ghost">
              {a.label}
            </Link>
          ))}
        </div>
      </div>

      <div className="panel muted-panel" style={{ marginBottom: "1rem", borderLeft: "4px solid var(--accent)" }}>
        <strong>{t("home.decision_walls", "Decision walls")}</strong>
        <p style={{ margin: "0.35rem 0 0.75rem" }}>
          {t(
            "home.decision_body",
            "Fullscreen live dashboards for owner / director / chartering / ops / finance / technical.",
          )}
        </p>
        <Link href="/dashboards" className="btn btn-primary">
          {t("home.open_dashboards", "Open live dashboards")}
        </Link>
      </div>

      <div className="workbench-grid">
        {(shell?.home_widgets || []).map((w) => (
          <HubTile key={w.id} href={w.href} title={w.title} description={w.hint} />
        ))}
        {error ? (
          <div className="wb-tile wb-tile-icon" style={{ cursor: "default" }}>
            <span className="wb-tile-icon-mark" aria-hidden>
              !
            </span>
            <span className="wb-tile-body">
              <h3>{t("home.load_failed", "加载失败")}</h3>
              <p>{t("home.load_failed_hint", "工作台数据加载失败，请检查网络后重试。")}</p>
              <button type="button" className="btn btn-ghost" onClick={retry}>
                {t("common.retry", "重试")}
              </button>
            </span>
          </div>
        ) : null}
        {!error && shell && !shell.home_widgets?.length ? (
          <div className="wb-tile wb-tile-icon" style={{ cursor: "default" }}>
            <span className="wb-tile-icon-mark" aria-hidden>
              —
            </span>
            <span className="wb-tile-body">
              <h3>{t("home.no_widgets", "No widgets")}</h3>
              <p>{t("home.no_widgets_hint", "Your role has limited access.")}</p>
            </span>
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}
