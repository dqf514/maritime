"use client";

import { useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import {
  apiAddMigrationSource,
  apiCommitMigration,
  apiCreateMigration,
  apiListProposals,
  apiRunAnalyze,
  apiUploadMigrationExcel,
} from "@/lib/api";
import { msgOf } from "@/lib/errors";
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
  const [err, setErr] = useState<string | null>(null);
  // 提交迁移不可逆 → 输入确认（键入关键字）
  const COMMIT_KEYWORD = "COMMIT";
  const [commitOpen, setCommitOpen] = useState(false);
  const [commitText, setCommitText] = useState("");

  async function refreshProposals(id: string) {
    setErr(null);
    try {
      const rows = await apiListProposals(id);
      setProposals(Array.isArray(rows) ? rows : []);
      const init: Record<string, boolean> = {};
      for (const r of rows) {
        if (r.status === "proposed") init[r.id] = r.confidence >= 0.9;
      }
      setSelected(init);
    } catch (ex) {
      setErr(msgOf(ex));
      setProposals([]);
    }
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

  const selectedIds = Object.entries(selected)
    .filter(([, v]) => v)
    .map(([k]) => k);

  async function commit() {
    if (!jobId) return;
    const ids = selectedIds;
    try {
      toast.success(t("page.migrate.committing", "Committing {n} proposals…", { n: ids.length }));
      const res = await apiCommitMigration(jobId, ids);
      setStep("done");
      setCommitOpen(false);
      setCommitText("");
      toast.success(
        t("page.migrate.committed", "Committed — vessels {v}, ports {p}, counterparties {c}.", {
          v: res.applied?.vessel ?? 0,
          p: res.applied?.port ?? 0,
          c: res.applied?.counterparty ?? 0,
        }),
      );
    } catch (ex) {
      toast.error(msgOf(ex, t("page.migrate.commit_fail", "Commit failed")));
    }
  }

  const columns = useMemo<ColumnDef<Proposal>[]>(() => [
    {
      key: "_select",
      title: "",
      width: 40,
      render: (_v, p) =>
        p.status === "proposed" ? (
          <input
            type="checkbox"
            checked={!!selected[p.id]}
            onChange={(e) => setSelected((s) => ({ ...s, [p.id]: e.target.checked }))}
          />
        ) : null,
    },
    { key: "entity_type", title: t("page.migrate.entity", "Entity"), width: 120, value: (r) => r.entity_type },
    { key: "action", title: t("page.migrate.action", "Action"), width: 110, value: (r) => r.action },
    {
      key: "confidence",
      title: t("page.migrate.confidence", "Confidence"),
      width: 110,
      value: (r) => r.confidence,
      render: (v) => `${(Number(v) * 100).toFixed(0)}%`,
    },
    { key: "status", title: t("common.status", "Status"), width: 110, value: (r) => r.status },
    {
      key: "payload",
      title: t("page.migrate.preview", "Preview"),
      minWidth: 220,
      value: (r) => JSON.stringify(r.payload),
      render: (v) => <code>{String(v)}</code>,
    },
  ], [selected, t]);

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[
          { label: t("nav.settings_hub", "System settings"), href: "/settings" },
          { label: t("page.migrate.title", "AI Migration Wizard") },
        ]}
        title={t("page.migrate.title", "AI Migration Wizard")}
        subtitle={t("page.migrate.sub", "Connect sources, analyze, confirm, commit.")}
        actions={
          step === "connect" ? (
            <button className="btn btn-primary" type="button" onClick={() => start().catch(() => toast.error(t("common.failed", "Failed")))}>
              {t("page.migrate.connect", "Connect sources & start")}
            </button>
          ) : step === "analyze" || step === "review" ? (
            <>
              {step === "analyze" ? (
                <button className="btn btn-primary" type="button" onClick={() => analyze().catch(() => toast.error(t("page.migrate.analyze_fail", "Analyze failed")))}>
                  {t("page.migrate.run_ai", "Run AI analysis")}
                </button>
              ) : null}
              <label className="btn" style={{ cursor: "pointer" }}>
                {t("page.migrate.upload", "Upload Excel")}
                <input
                  type="file"
                  accept=".xlsx,.xlsm,.xls"
                  style={{ display: "none" }}
                  onChange={(e) => onExcel(e.target.files?.[0] || null).catch(() => toast.error(t("page.migrate.excel_fail", "Excel upload failed")))}
                />
              </label>
            </>
          ) : null
        }
      />
      {err ? <div className="error">{err}</div> : null}
      {proposals.length ? (
        <>
          <DataGrid<Proposal>
            columns={columns}
            data={proposals}
            rowKey={(r) => r.id}
            storageKey="settings_dataops_migrate_grid"
            emptyText={t("common.no_data", "No data")}
          />
          {step === "review" ? (
            <button
              className="btn btn-primary"
              type="button"
              onClick={() => {
                setCommitOpen(true);
                setCommitText("");
              }}
              style={{ marginTop: "1rem" }}
            >
              {t("page.migrate.apply", "Apply selected")}
            </button>
          ) : null}
          {commitOpen ? (
            <div className="panel" style={{ marginTop: "0.75rem", borderColor: "var(--danger)" }}>
              <p style={{ marginTop: 0 }}>
                {t(
                  "page.migrate.commit_confirm_hint",
                  "将把选中的 {n} 条迁移建议写入正式业务数据，且不可撤销。请输入 {kw} 以确认：",
                  { n: String(selectedIds.length), kw: COMMIT_KEYWORD },
                )}
              </p>
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
                <input
                  value={commitText}
                  onChange={(e) => setCommitText(e.target.value)}
                  aria-label={t("page.migrate.commit_confirm_input", "Type the confirmation keyword to commit")}
                  placeholder={COMMIT_KEYWORD}
                  style={{ maxWidth: 220 }}
                />
                <button
                  className="btn btn-danger"
                  type="button"
                  disabled={commitText.trim().toUpperCase() !== COMMIT_KEYWORD}
                  onClick={() => commit()}
                >
                  {t("page.migrate.commit_run", "确认提交迁移")}
                </button>
                <button
                  className="btn btn-ghost"
                  type="button"
                  onClick={() => {
                    setCommitOpen(false);
                    setCommitText("");
                  }}
                >
                  {t("common.cancel", "取消")}
                </button>
              </div>
            </div>
          ) : null}
        </>
      ) : null}
    </AppShell>
  );
}
