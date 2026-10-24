"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { Toolbar } from "@/components/Toolbar";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiRunSelfCheck } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";

type Result = { check_id: string; severity: string; status: string; message?: string };

export default function SelfCheckPage() {
  const { t } = useI18n();
  const [loading, setLoading] = useState(false);
  const [score, setScore] = useState<number | null>(null);
  const [results, setResults] = useState<Result[]>([]);
  const [error, setError] = useState("");
  const [ran, setRan] = useState(false);

  const run = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await apiRunSelfCheck();
      setScore(data.score);
      setResults(data.results || []);
    } catch (ex) {
      setError(msgOf(ex, t("page.selfcheck.error", "Failed to run SelfCheck. Is the API up?")));
    } finally {
      setLoading(false);
      setRan(true);
    }
  }, [t]);

  // 进页自动执行一次，避免空白页（走查问题：页面只有标题+按钮）
  useEffect(() => {
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const columns = useMemo<ColumnDef<Result>[]>(() => [
    { key: "check_id", title: t("page.selfcheck.check", "Check"), minWidth: 180, value: (r) => r.check_id },
    { key: "severity", title: t("page.selfcheck.severity", "Severity"), width: 110, value: (r) => r.severity },
    {
      key: "status",
      title: t("common.status", "Status"),
      width: 100,
      value: (r) => r.status,
      render: (v) => (
        <span className={`badge badge-${v === "pass" ? "pass" : v === "warn" ? "warn" : "fail"}`}>{String(v)}</span>
      ),
    },
    {
      key: "message",
      title: t("page.selfcheck.message", "Message"),
      minWidth: 220,
      value: (r) => r.message || "",
    },
  ], [t]);

  const passCount = results.filter((r) => r.status === "pass").length;
  const warnCount = results.filter((r) => r.status === "warn").length;
  const failCount = results.filter((r) => r.status === "fail").length;

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[
          { label: t("nav.settings_hub", "System settings"), href: "/settings" },
          { label: t("page.selfcheck.title", "SelfCheck") },
        ]}
        title={t("page.selfcheck.title", "SelfCheck")}
        subtitle={t("page.selfcheck.hint", "Runs install & runtime gold checks against the live API.")}
      />
      <Toolbar>
        <button className="btn btn-primary" type="button" onClick={run} disabled={loading}>
          {loading ? t("page.selfcheck.running", "Running…") : t("page.selfcheck.run", "Run SelfCheck")}
        </button>
      </Toolbar>
      {error ? <p className="text-danger">{error}</p> : null}
      {!ran && !error ? <p className="muted">{t("common.loading", "加载中…")}</p> : null}
      {ran && score === null && !error ? (
        <div className="panel">
          <p className="muted">{t("page.selfcheck.empty", "No results yet — run SelfCheck to see checks.")}</p>
        </div>
      ) : null}
      {score !== null ? (
        <>
          <div className="wb-kpi-strip">
            <div className="wb-kpi-item">
              <span className="wb-kpi-val">{score}</span>
              <span className="wb-kpi-label">{t("page.selfcheck.score", "Score")}</span>
            </div>
            <div className="wb-kpi-item">
              <span className="wb-kpi-val">{passCount}</span>
              <span className="wb-kpi-label">{t("status.success", "Passed")}</span>
            </div>
            <div className="wb-kpi-item">
              <span className="wb-kpi-val">{warnCount}</span>
              <span className="wb-kpi-label">{t("status.pending", "Warnings")}</span>
            </div>
            <div className="wb-kpi-item">
              <span className="wb-kpi-val">{failCount}</span>
              <span className="wb-kpi-label">{t("status.failed", "Failed")}</span>
            </div>
          </div>
          <div className="panel">
            <DataGrid<Result>
              columns={columns}
              data={results}
              rowKey={(r) => r.check_id}
              storageKey="settings_selfcheck_grid"
              emptyText={t("common.no_data", "No data")}
            />
          </div>
        </>
      ) : null}
    </AppShell>
  );
}
