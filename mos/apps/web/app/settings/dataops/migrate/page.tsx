"use client";

import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import {
  apiAddMigrationSource,
  apiCommitMigration,
  apiCreateMigration,
  apiListProposals,
  apiRunAnalyze,
  apiUploadMigrationExcel,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type Proposal = {
  id: string;
  entity_type: string;
  action: string;
  confidence: number;
  payload: Record<string, unknown>;
  status: string;
};

export default function MigratePage() {
  const { t } = useI18n();
  const toast = useToast();
  const [jobId, setJobId] = useState<string | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [step, setStep] = useState("connect");

  async function refreshProposals(id: string) {
    const rows = await apiListProposals(id);
    setProposals(rows);
    const init: Record<string, boolean> = {};
    for (const r of rows) {
      if (r.status === "proposed") init[r.id] = r.confidence >= 0.9;
    }
    setSelected(init);
  }

  async function start() {
    toast.success(t("page.migrate.creating", "Creating migration job…"));
    const job = await apiCreateMigration("Wave 1 guided migrate");
    setJobId(job.id);
    await apiAddMigrationSource(job.id, "excel_pack");
    await apiAddMigrationSource(job.id, "m365_mail");
    await apiAddMigrationSource(job.id, "pst");
    setStep("analyze");
    toast.success(t("page.migrate.connected", "Sources connected. Run analysis or upload Excel."));
  }

  async function analyze() {
    if (!jobId) return;
    toast.success(t("page.migrate.analyzing", "Analyzing…"));
    await apiRunAnalyze(jobId);
    await refreshProposals(jobId);
    setStep("review");
    toast.success(t("page.migrate.review", "Review AI proposals — checkboxes only."));
  }

  async function onExcel(file: File | null) {
    if (!jobId || !file) return;
    toast.success(t("page.migrate.parsing", "Parsing {name}…", { name: file.name }));
    const res = await apiUploadMigrationExcel(jobId, file);
    await refreshProposals(jobId);
    setStep("review");
    toast.success(t("page.migrate.excel_done", "Excel produced {n} proposal(s).", { n: res.proposals_from_excel }));
  }

  async function commit() {
    if (!jobId) return;
    const ids = Object.entries(selected)
      .filter(([, v]) => v)
      .map(([k]) => k);
    toast.success(t("page.migrate.committing", "Committing {n} proposals…", { n: ids.length }));
    const res = await apiCommitMigration(jobId, ids);
    setStep("done");
    toast.success(
      t("page.migrate.committed", "Committed — vessels {v}, ports {p}, counterparties {c}.", {
        v: res.applied?.vessel ?? 0,
        p: res.applied?.port ?? 0,
        c: res.applied?.counterparty ?? 0,
      }),
    );
  }

  return (
    <AppShell>
      <PageHeader
        title={t("page.migrate.title", "AI Migration Wizard")}
        subtitle={t("page.migrate.sub", "Connect sources, analyze, confirm, commit.")}
        actions={
          step === "connect" ? (
            <button className="btn btn-primary" type="button" onClick={() => start().catch(() => toast.success(t("common.failed", "Failed")))}>
              {t("page.migrate.connect", "Connect sources & start")}
            </button>
          ) : step === "analyze" || step === "review" ? (
            <>
              {step === "analyze" ? (
                <button className="btn btn-primary" type="button" onClick={() => analyze().catch(() => toast.success(t("page.migrate.analyze_fail", "Analyze failed")))}>
                  {t("page.migrate.run_ai", "Run AI analysis")}
                </button>
              ) : null}
              <label className="btn" style={{ cursor: "pointer" }}>
                {t("page.migrate.upload", "Upload Excel")}
                <input
                  type="file"
                  accept=".xlsx,.xlsm,.xls"
                  style={{ display: "none" }}
                  onChange={(e) => onExcel(e.target.files?.[0] || null).catch(() => toast.success(t("page.migrate.excel_fail", "Excel upload failed")))}
                />
              </label>
            </>
          ) : null
        }
      />
      {proposals.length ? (
        <div className="panel">
          <table className="table">
            <thead>
              <tr>
                <th></th>
                <th>{t("page.migrate.entity", "Entity")}</th>
                <th>{t("page.migrate.action", "Action")}</th>
                <th>{t("page.migrate.confidence", "Confidence")}</th>
                <th>{t("common.status", "Status")}</th>
                <th>{t("page.migrate.preview", "Preview")}</th>
              </tr>
            </thead>
            <tbody>
              {proposals.map((p) => (
                <tr key={p.id}>
                  <td>
                    {p.status === "proposed" ? (
                      <input
                        type="checkbox"
                        checked={!!selected[p.id]}
                        onChange={(e) => setSelected((s) => ({ ...s, [p.id]: e.target.checked }))}
                      />
                    ) : null}
                  </td>
                  <td>{p.entity_type}</td>
                  <td>{p.action}</td>
                  <td>{(p.confidence * 100).toFixed(0)}%</td>
                  <td>{p.status}</td>
                  <td>
                    <code>{JSON.stringify(p.payload)}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {step === "review" ? (
            <button
              className="btn btn-primary"
              type="button"
              onClick={() => commit().catch(() => toast.success(t("page.migrate.commit_fail", "Commit failed")))}
              style={{ marginTop: "1rem" }}
            >
              {t("page.migrate.apply", "Apply selected")}
            </button>
          ) : null}
        </div>
      ) : null}
    </AppShell>
  );
}
