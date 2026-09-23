"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Report = {
  id: string;
  report_name: string;
  report_type: string;
  data_source: string;
  is_system: boolean;
  description: string | null;
};

type ReportResult = {
  columns: { key: string; label: string; format?: string; width?: number }[];
  rows: Record<string, unknown>[];
  total_rows: number;
  error?: string;
};

export default function ReportsPage() {
  const { t } = useI18n();
  const [reports, setReports] = useState<Report[]>([]);
  const [selected, setSelected] = useState<Report | null>(null);
  const [result, setResult] = useState<ReportResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState("");

  async function load() {
    try {
      const data = await apiGet("/api/v1/reports");
      setReports(data);
    } catch {
      setReports([]);
    }
  }

  useEffect(() => { load(); }, []);

  async function seedSystem() {
    try {
      const res = await apiPost("/api/v1/reports/system/seed", {});
      setMsg(res.message || "System reports seeded");
      load();
    } catch {
      setMsg("Failed to seed reports");
    }
  }

  async function executeReport(report: Report) {
    setSelected(report);
    setLoading(true);
    setResult(null);
    try {
      const res = await apiPost(`/api/v1/reports/${report.id}/execute`, {});
      setResult(res);
    } catch {
      setResult({ columns: [], rows: [], total_rows: 0, error: "Execution failed" });
    }
    setLoading(false);
  }

  async function exportCsv(report: Report) {
    try {
      const res = await apiGet(`/api/v1/reports/${report.id}/export/csv`);
      const blob = new Blob([res.csv], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${report.report_name.replace(/\s+/g, "_")}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setMsg("Export failed");
    }
  }

  function formatCell(val: unknown, format?: string): string {
    if (val === null || val === undefined) return "—";
    if (format === "currency") return `$${Number(val).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
    if (format === "number") return Number(val).toLocaleString(undefined, { maximumFractionDigits: 2 });
    if (format === "date") return String(val).slice(0, 10);
    return String(val);
  }

  return (
    <AppShell title="Reports" subtitle="Configurable report engine — preset and custom reports">
      <div style={{ display: "flex", gap: 24, alignItems: "flex-start" }}>
        {/* Report list sidebar */}
        <div style={{ width: 280, flexShrink: 0 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>Reports</h3>
            <button className="btn btn-sm" onClick={seedSystem}>
              Seed system
            </button>
          </div>
          {reports.length === 0 && (
            <p style={{ color: "var(--text-muted)", fontSize: 13 }}>
              No reports yet. Click "Seed system" to create preset reports.
            </p>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {reports.map((r) => (
              <button
                key={r.id}
                className={`btn btn-sm ${selected?.id === r.id ? "btn-primary" : ""}`}
                style={{ textAlign: "left", justifyContent: "flex-start" }}
                onClick={() => executeReport(r)}
              >
                {r.is_system && <span style={{ marginRight: 6, opacity: 0.5 }}>*</span>}
                {r.report_name}
              </button>
            ))}
          </div>
          {msg && <p style={{ color: "var(--accent)", fontSize: 12, marginTop: 8 }}>{msg}</p>}
        </div>

        {/* Report result */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {!selected && !loading && (
            <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>
              Select a report from the left to execute it.
            </div>
          )}
          {loading && (
            <div style={{ padding: 40, textAlign: "center" }}>
              <div className="skeleton" style={{ height: 200, borderRadius: 8 }} />
            </div>
          )}
          {result && !loading && (
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>
                  {selected?.report_name}
                  <span style={{ color: "var(--text-muted)", fontWeight: 400, marginLeft: 8, fontSize: 13 }}>
                    {result.total_rows} rows
                  </span>
                </h3>
                {selected && (
                  <button className="btn btn-sm" onClick={() => exportCsv(selected)}>
                    Export CSV
                  </button>
                )}
              </div>
              {result.error && (
                <div style={{ padding: 12, background: "var(--danger-bg, #fef2f2)", borderRadius: 6, color: "var(--danger, #dc2626)", fontSize: 13, marginBottom: 12 }}>
                  {result.error}
                </div>
              )}
              {result.columns.length > 0 && result.rows.length > 0 && (
                <div style={{ overflowX: "auto", borderRadius: 8, border: "1px solid var(--border)" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                    <thead>
                      <tr style={{ background: "var(--bg-secondary)" }}>
                        {result.columns.map((c) => (
                          <th
                            key={c.key}
                            style={{
                              padding: "8px 12px",
                              textAlign: "left",
                              fontWeight: 600,
                              borderBottom: "1px solid var(--border)",
                              whiteSpace: "nowrap",
                              minWidth: c.width || 80,
                            }}
                          >
                            {c.label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.rows.slice(0, 100).map((row, i) => (
                        <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
                          {result.columns.map((c) => (
                            <td
                              key={c.key}
                              style={{
                                padding: "6px 12px",
                                whiteSpace: "nowrap",
                                fontVariantNumeric: c.format === "currency" || c.format === "number" ? "tabular-nums" : undefined,
                                color: c.format === "currency" ? "var(--text)" : undefined,
                              }}
                            >
                              {formatCell(row[c.key], c.format)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {result.rows.length === 0 && !result.error && (
                <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>
                  No data available. Ensure demo data is seeded.
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
