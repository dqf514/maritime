"use client";

import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { Toolbar } from "@/components/Toolbar";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiRunSelfCheck } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Result = { check_id: string; severity: string; status: string; message?: string };

export default function SelfCheckPage() {
  const { t } = useI18n();
  const [loading, setLoading] = useState(false);
  const [score, setScore] = useState<number | null>(null);
  const [results, setResults] = useState<Result[]>([]);
  const [error, setError] = useState("");

  async function run() {
    setLoading(true);
    setError("");
    try {
      const data = await apiRunSelfCheck();
      setScore(data.score);
      setResults(data.results || []);
    } catch {
      setError(t("page.selfcheck.error", "Failed to run SelfCheck. Is the API up?"));
    } finally {
      setLoading(false);
    }
  }

  const columns: ColumnDef<Result>[] = [
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
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[
          { label: t("nav.settings_hub", "System settings"), href: "/settings" },
          { label: t("page.selfcheck.title", "SelfCheck") },
        ]}
        title={t("page.selfcheck.title", "SelfCheck")}
        subtitle={t("page.selfcheck.sub", "Install & runtime diagnostics.")}
      />
      <Toolbar>
        <button className="btn btn-primary" type="button" onClick={run} disabled={loading}>
          {loading ? t("page.selfcheck.running", "Running…") : t("page.selfcheck.run", "Run SelfCheck")}
        </button>
      </Toolbar>
      {error ? <p style={{ color: "var(--danger)" }}>{error}</p> : null}
      {score !== null ? (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>
            {t("common.score", "Score")}: {score}
          </h3>
          <DataGrid<Result>
            columns={columns}
            data={results}
            rowKey={(r) => r.check_id}
            storageKey="settings_selfcheck_grid"
            emptyText={t("common.no_data", "No data")}
          />
        </div>
      ) : null}
    </AppShell>
  );
}
