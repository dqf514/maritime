"use client";

import { useState } from "react";
import { AppShell } from "@/components/AppShell";
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

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("page.selfcheck.title", "SelfCheck")}</h1>
      <p style={{ color: "var(--muted)" }}>{t("page.selfcheck.sub", "Install & runtime diagnostics.")}</p>
      <button className="btn btn-primary" type="button" onClick={run} disabled={loading}>
        {loading ? t("page.selfcheck.running", "Running…") : t("page.selfcheck.run", "Run SelfCheck")}
      </button>
      {error ? <p style={{ color: "var(--danger)" }}>{error}</p> : null}
      {score !== null ? (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>
            {t("common.score", "Score")}: {score}
          </h3>
          <table className="table">
            <thead>
              <tr>
                <th>{t("page.selfcheck.check", "Check")}</th>
                <th>{t("page.selfcheck.severity", "Severity")}</th>
                <th>{t("common.status", "Status")}</th>
                <th>{t("page.selfcheck.message", "Message")}</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <tr key={r.check_id}>
                  <td>{r.check_id}</td>
                  <td>{r.severity}</td>
                  <td>
                    <span className={`badge badge-${r.status === "pass" ? "pass" : r.status === "warn" ? "warn" : "fail"}`}>
                      {r.status}
                    </span>
                  </td>
                  <td>{r.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </AppShell>
  );
}
