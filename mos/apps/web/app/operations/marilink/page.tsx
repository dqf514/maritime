"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { RecordModal } from "@/components/RecordModal";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type ShipReport = {
  id: string;
  report_ref: string;
  form_type: string;
  vessel_name: string | null;
  submitted_at: string;
  status: string;
  submitted_by_name: string | null;
};

type ShipForm = {
  id: string;
  form_type: string;
  form_name: string;
  is_active: boolean;
};

export default function MariLinkPage() {
  const { t } = useI18n();
  const [reports, setReports] = useState<ShipReport[]>([]);
  const [forms, setForms] = useState<ShipForm[]>([]);
  const [filter, setFilter] = useState<string>("");
  const [open, setOpen] = useState<ShipReport | null>(null);
  const [reviewNotes, setReviewNotes] = useState("");
  const [msg, setMsg] = useState("");

  async function load() {
    const params = filter ? `?form_type=${filter}` : "";
    setReports(await apiGet(`/api/v1/marilink/reports${params}`));
    setForms(await apiGet("/api/v1/marilink/forms"));
  }

  useEffect(() => {
    load().catch(() => setReports([]));
  }, [filter]);

  async function seedPresets() {
    await apiPost("/api/v1/marilink/forms/seed-presets", {});
    setMsg(t("page.marilink.presets_seeded", "Form presets seeded"));
    await load();
  }

  async function approveReport() {
    if (!open) return;
    await apiPost(`/api/v1/marilink/reports/${open.id}/review`, {
      action: "approve",
      notes: reviewNotes,
    });
    setMsg(t("page.marilink.approved", "Report approved and imported"));
    setOpen(null);
    setReviewNotes("");
    await load();
  }

  async function rejectReport() {
    if (!open) return;
    await apiPost(`/api/v1/marilink/reports/${open.id}/review`, {
      action: "reject",
      notes: reviewNotes,
    });
    setMsg(t("page.marilink.rejected", "Report rejected"));
    setOpen(null);
    setReviewNotes("");
    await load();
  }

  const statusColor = (s: string) => {
    if (s === "approved") return "var(--green-700)";
    if (s === "rejected") return "var(--red-700)";
    if (s === "review") return "var(--amber-700)";
    return "var(--text-secondary)";
  };

  return (
    <AppShell>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <h1 style={{ fontSize: 20, fontWeight: 600, margin: 0 }}>
          {t("page.marilink.title", "MariLink Ship Reports")}
        </h1>
        <button onClick={seedPresets} className="btn btn-secondary">
          {t("page.marilink.seed_forms", "Seed Form Presets")}
        </button>
      </div>

      {msg && (
        <div style={{ padding: "8px 12px", background: "var(--green-50)", color: "var(--green-700)", borderRadius: 6, marginBottom: 16 }}>
          {msg}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          style={{ padding: "6px 12px", borderRadius: 6, border: "1px solid var(--border)" }}
        >
          <option value="">{t("page.marilink.all_types", "All Types")}</option>
          <option value="noon_report">{t("page.marilink.noon_report", "Noon Report")}</option>
          <option value="bunker_report">{t("page.marilink.bunker_report", "Bunker Report")}</option>
          <option value="incident">{t("page.marilink.incident", "Incident")}</option>
        </select>
      </div>

      <div className="card" style={{ overflow: "auto" }}>
        <table className="dataTable" style={{ width: "100%" }}>
          <thead>
            <tr>
              <th>{t("page.marilink.ref", "Reference")}</th>
              <th>{t("page.marilink.type", "Type")}</th>
              <th>{t("page.marilink.vessel", "Vessel")}</th>
              <th>{t("page.marilink.submitted", "Submitted")}</th>
              <th>{t("page.marilink.status", "Status")}</th>
              <th>{t("common.actions", "Actions")}</th>
            </tr>
          </thead>
          <tbody>
            {reports.map((r) => (
              <tr key={r.id}>
                <td style={{ fontFamily: "monospace" }}>{r.report_ref}</td>
                <td>{r.form_type}</td>
                <td>{r.vessel_name || "—"}</td>
                <td>{new Date(r.submitted_at).toLocaleString()}</td>
                <td>
                  <span style={{ color: statusColor(r.status), fontWeight: 500 }}>
                    {r.status}
                  </span>
                </td>
                <td>
                  {r.status === "submitted" && (
                    <button
                      className="btn btn-secondary"
                      style={{ padding: "4px 8px", fontSize: 12 }}
                      onClick={() => setOpen(r)}
                    >
                      {t("common.review", "Review")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {reports.length === 0 && (
              <tr>
                <td colSpan={6} style={{ textAlign: "center", padding: 24, color: "var(--text-secondary)" }}>
                  {t("page.marilink.no_reports", "No ship reports yet")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div style={{ marginTop: 24 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>
          {t("page.marilink.active_forms", "Active Form Form Templates")}
        </h2>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          {forms.map((f) => (
            <div
              key={f.id}
              className="card"
              style={{ padding: 12, minWidth: 200, opacity: f.is_active ? 1 : 0.5 }}
            >
              <div style={{ fontWeight: 500 }}>{f.form_name}</div>
              <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>{f.form_type}</div>
            </div>
          ))}
        </div>
      </div>

      {open && (
        <RecordModal
          title={`${t("common.review", "Review")} ${open.report_ref}`}
          open={!!open}
          onClose={() => { setOpen(null); setReviewNotes(""); }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div>
              <label style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                {t("page.marilink.notes", "Review Notes")}
              </label>
              <textarea
                value={reviewNotes}
                onChange={(e) => setReviewNotes(e.target.value)}
                rows={3}
                style={{ width: "100%", padding: 8, borderRadius: 6, border: "1px solid var(--border)" }}
              />
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn btn-primary" onClick={approveReport}>
                {t("common.approve", "Approve & Import")}
              </button>
              <button className="btn btn-danger" onClick={rejectReport}>
                {t("common.reject", "Reject")}
              </button>
            </div>
          </div>
        </RecordModal>
      )}
    </AppShell>
  );
}
