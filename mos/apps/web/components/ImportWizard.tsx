"use client";

// 数据导入向导 — CSV 粘贴/上传 → 服务端校验预览 → 提交入库。
// 公式注入防护：预览阶段由 API 拒绝 = + @ 制表符/回车 或非纯数字 - 开头的单元格。
// 提交阶段剥离前导 `'` 守卫符；全程不 eval。

import { ChangeEvent, useCallback, useMemo, useRef, useState } from "react";
import { RecordModal } from "@/components/RecordModal";
import { StatusBadge } from "@/components/StatusBadge";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiPost } from "@/lib/api";
import { parseCsv } from "@/lib/csv";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

export type ImportEntity = "ports" | "counterparties" | "vessels";

type PreviewRow = {
  row_no: number;
  data: Record<string, unknown>;
  errors: string[];
  valid: boolean;
};

type PreviewResponse = {
  entity: string;
  rows: PreviewRow[];
  summary: { total: number; valid: number; invalid: number };
  key_fields: string[];
};

type CommitResponse = {
  created: number;
  failed: { index: number; errors: string[] }[];
  created_ids: string[];
};

type Props = {
  entity: ImportEntity;
  onDone?: () => void;
};

const SAMPLE: Record<ImportEntity, string> = {
  ports: "name,unlocode,country,timezone\nShanghai,CNSHA,CN,Asia/Shanghai",
  counterparties: "name,type,country\nAcme Shipping,owner,CN",
  vessels: "name,imo,vessel_type,dwt\nOcean Star,9990001,Bulk Carrier,50000",
};

const LABELS: Record<ImportEntity, string> = {
  ports: "ports",
  counterparties: "counterparties",
  vessels: "vessels",
};

export function ImportWizard({ entity, onDone }: Props) {
  const { t } = useI18n();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);

  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [content, setContent] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [localRows, setLocalRows] = useState<number>(0);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [result, setResult] = useState<CommitResponse | null>(null);

  const reset = useCallback(() => {
    setStep(1);
    setContent("");
    setFileName(null);
    setLocalRows(0);
    setPreview(null);
    setResult(null);
    setConfirmOpen(false);
  }, []);

  function onContentChange(v: string) {
    setContent(v);
    setFileName(null);
    try {
      const rows = parseCsv(v).filter((r, i) => i > 0 || r.some((c) => c.trim()));
      setLocalRows(Math.max(0, rows.length - 1));
    } catch {
      setLocalRows(0);
    }
  }

  function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".csv")) {
      toast.error(t("imp.need_csv", "Please choose a .csv file"));
      e.target.value = "";
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      onContentChange(String(reader.result ?? ""));
      setFileName(file.name);
    };
    reader.onerror = () => toast.error(t("imp.read_fail", "Failed to read file"));
    reader.readAsText(file, "utf-8");
    e.target.value = "";
  }

  async function runPreview() {
    if (!content.trim()) {
      toast.error(t("imp.empty", "Paste CSV content or upload a file first"));
      return;
    }
    setBusy(true);
    try {
      const res = (await apiPost("/api/v1/imports/preview", {
        entity,
        format: "csv",
        content,
      })) as PreviewResponse;
      setPreview(res);
      setStep(2);
    } catch (err) {
      const detail = (err as { detail?: { code?: string; max_rows?: number; max_bytes?: number } }).detail;
      if (detail?.code === "ROW_LIMIT") {
        toast.error(t("imp.row_limit", "Too many rows (max {n})", { n: detail.max_rows ?? 500 }));
      } else if (detail?.code === "CONTENT_TOO_LARGE") {
        toast.error(t("imp.too_large", "File too large (max 2MB)"));
      } else {
        toast.error(t("imp.preview_fail", "Preview failed: {err}", { err: String(err) }));
      }
    } finally {
      setBusy(false);
    }
  }

  async function runCommit() {
    if (!preview) return;
    const rows = preview.rows.filter((r) => r.valid).map((r) => r.data);
    setBusy(true);
    try {
      const res = (await apiPost("/api/v1/imports/commit", { entity, rows })) as CommitResponse;
      setResult(res);
      setConfirmOpen(false);
      setStep(3);
      toast.success(
        t("imp.committed", "Imported {n} rows", { n: res.created }),
      );
      onDone?.();
    } catch (err) {
      toast.error(t("imp.commit_fail", "Import failed: {err}", { err: String(err) }));
    } finally {
      setBusy(false);
    }
  }

  const validCount = preview?.summary.valid ?? 0;
  const invalidCount = preview?.summary.invalid ?? 0;

  const columns: ColumnDef<PreviewRow>[] = useMemo(() => {
    const keyFields = preview?.key_fields ?? ["name"];
    const cols: ColumnDef<PreviewRow>[] = [
      {
        key: "row_no",
        title: t("imp.col_row", "Row"),
        width: 70,
        value: (r) => r.row_no,
      },
    ];
    for (const field of keyFields) {
      cols.push({
        key: `d_${field}`,
        title: field,
        minWidth: 120,
        value: (r) => {
          const v = r.data[field];
          return v === null || v === undefined ? "" : String(v);
        },
        render: (v) => <span title={String(v ?? "")}>{String(v ?? "")}</span>,
      });
    }
    cols.push({
      key: "valid",
      title: t("imp.col_status", "Status"),
      width: 100,
      value: (r) => (r.valid ? "ok" : "invalid"),
      render: (_v, r) =>
        r.valid ? (
          <StatusBadge status={t("imp.valid", "Valid")} tone="ok" />
        ) : (
          <StatusBadge status={t("imp.invalid", "Invalid")} tone="danger" />
        ),
    });
    cols.push({
      key: "errors",
      title: t("imp.col_errors", "Errors"),
      minWidth: 180,
      value: (r) => r.errors.join("; "),
      render: (_v, r) =>
        r.errors.length ? (
          <span style={{ color: "var(--danger)" }} title={r.errors.join("; ")}>
            {r.errors.join("; ")}
          </span>
        ) : (
          ""
        ),
    });
    return cols;
  }, [preview, t]);

  const stepLabel = (n: number, label: string) => (
    <span
      key={n}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        opacity: step === n ? 1 : 0.55,
        fontWeight: step === n ? 600 : 400,
      }}
    >
      <span
        aria-hidden
        style={{
          width: 20,
          height: 20,
          borderRadius: "50%",
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 11,
          background: step >= n ? "var(--accent, #2563eb)" : "var(--border, #ccc)",
          color: step >= n ? "#fff" : "var(--muted, #888)",
        }}
      >
        {n}
      </span>
      {label}
    </span>
  );

  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", fontSize: "var(--font-label)" }}>
        {stepLabel(1, t("imp.step1", "Paste / upload"))}
        <span aria-hidden>→</span>
        {stepLabel(2, t("imp.step2", "Preview & validate"))}
        <span aria-hidden>→</span>
        {stepLabel(3, t("imp.step3", "Import"))}
      </div>

      {step === 1 && (
        <>
          <p className="muted" style={{ margin: 0 }}>
            {t(
              "imp.hint",
              "CSV with a header row. Formulas (= + @ tab CR, or - not followed by a pure number) are rejected. Max 500 rows / 2MB.",
            )}
          </p>
          <div className="muted" style={{ fontSize: "var(--font-label)" }}>
            {t("imp.columns", "Columns for {entity}:", { entity: t(`imp.entity_${entity}`, LABELS[entity]) })}{" "}
            <code>{SAMPLE[entity].split("\n")[0]}</code>
          </div>
          <label className="field">
            <span>{t("imp.csv_content", "CSV content")}</span>
            <textarea
              className="input"
              rows={8}
              value={content}
              onChange={(e) => onContentChange(e.target.value)}
              placeholder={SAMPLE[entity]}
              spellCheck={false}
            />
          </label>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,text/csv"
              style={{ display: "none" }}
              onChange={onFile}
            />
            <button type="button" className="btn btn-sm" onClick={() => fileRef.current?.click()}>
              {t("imp.upload", "Upload .csv")}
            </button>
            {fileName ? (
              <span className="muted" style={{ fontSize: "var(--font-label)" }}>
                {fileName} · {t("imp.rows_detected", "{n} data rows", { n: localRows })}
              </span>
            ) : content.trim() ? (
              <span className="muted" style={{ fontSize: "var(--font-label)" }}>
                {t("imp.rows_detected", "{n} data rows", { n: localRows })}
              </span>
            ) : null}
            <span style={{ flex: 1 }} />
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy || !content.trim()}
              onClick={() => runPreview()}
            >
              {busy ? t("imp.working", "Working…") : t("imp.preview_btn", "Preview")}
            </button>
          </div>
        </>
      )}

      {step === 2 && preview && (
        <>
          <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <StatusBadge
              status={t("imp.summary", "{valid} valid / {invalid} invalid / {total} total", {
                valid: validCount,
                invalid: invalidCount,
                total: preview.summary.total,
              })}
              tone={invalidCount ? "warn" : "ok"}
            />
            <span style={{ flex: 1 }} />
            <button type="button" className="btn btn-sm" onClick={() => setStep(1)} disabled={busy}>
              {t("imp.back", "Back")}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy || validCount === 0}
              onClick={() => setConfirmOpen(true)}
            >
              {t("imp.commit_btn", "Import {n} valid rows", { n: validCount })}
            </button>
          </div>
          <DataGrid<PreviewRow>
            columns={columns}
            data={preview.rows}
            rowKey={(r) => String(r.row_no)}
            storageKey={`import_preview_${entity}`}
            emptyText={t("imp.empty_preview", "No rows")}
            showFooter={false}
          />
        </>
      )}

      {step === 3 && result && (
        <>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <StatusBadge
              status={t("imp.done", "Imported {n} rows", { n: result.created })}
              tone="ok"
            />
            {result.failed.length > 0 && (
              <span style={{ color: "var(--danger)" }}>
                {t("imp.failed_count", "{n} rows failed", { n: result.failed.length })}
              </span>
            )}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" className="btn btn-primary" onClick={reset}>
              {t("imp.again", "Import another file")}
            </button>
          </div>
        </>
      )}

      <RecordModal
        open={confirmOpen}
        title={t("imp.confirm_title", "Confirm import")}
        onClose={() => setConfirmOpen(false)}
        onSave={() => runCommit()}
        canDelete={false}
        saving={busy}
        size="md"
      >
        <p style={{ margin: "8px 0" }}>
          {t(
            "imp.confirm_body",
            "Create {n} {entity} rows? Invalid rows are skipped. This cannot be undone from here.",
            { n: validCount, entity: t(`imp.entity_${entity}`, LABELS[entity]) },
          )}
        </p>
        {invalidCount > 0 && (
          <p className="muted" style={{ margin: 0 }}>
            {t("imp.confirm_skip", "{n} invalid rows will be skipped.", { n: invalidCount })}
          </p>
        )}
      </RecordModal>
    </div>
  );
}
