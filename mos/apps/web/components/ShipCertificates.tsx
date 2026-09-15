"use client";

import { useCallback, useEffect, useState } from "react";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DateInput } from "@/components/DateInput";
import { ExportButton } from "@/components/ExportButton";
import { RecordModal } from "@/components/RecordModal";
import { StateView } from "@/components/StateView";
import { API_BASE, apiDelete, apiGet, apiPatch, apiPost, apiUpload } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export type CertAttachment = {
  id: string;
  entity_type: string;
  entity_id: string;
  version_no: number;
  is_current: boolean;
  file_name: string;
  mime_type: string;
  size: number;
  note: string | null;
  uploaded_by: string | null;
  created_at: string;
  download_url: string;
};

export type VesselCert = {
  id: string;
  vessel_id?: string;
  cert_code: string;
  cert_name: string;
  issued_on: string | null;
  expires_on: string | null;
  status: string;
  issuing_body: string | null;
  external_ref: string | null;
  vessel_name?: string;
  days_to_expiry?: number | null;
  current_file?: CertAttachment | null;
};

const MAX_FILE_BYTES = 10 * 1024 * 1024;
const FILE_ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp";
const CERT_STATUSES = ["valid", "expiring", "expired", "pending"];

function fmtSize(n: number): string {
  if (!Number.isFinite(n)) return "";
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

function daysLeft(expiresOn: string | null | undefined): number | null {
  if (!expiresOn) return null;
  const due = new Date(expiresOn);
  if (Number.isNaN(due.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  due.setHours(0, 0, 0, 0);
  return Math.round((due.getTime() - today.getTime()) / 86_400_000);
}

function certDays(c: VesselCert): number | null {
  return typeof c.days_to_expiry === "number" ? c.days_to_expiry : daysLeft(c.expires_on);
}

export function CertOverview({ onOpenVessel }: { onOpenVessel: (vesselId: string) => void }) {
  const { t } = useI18n();
  const [rows, setRows] = useState<VesselCert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [expiring30, setExpiring30] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    const qs = new URLSearchParams();
    if (status) qs.set("status", status);
    if (expiring30) qs.set("expiring_within_days", "30");
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    try {
      const data = await apiGet(`/api/v1/ship/certificates${suffix}`);
      setRows(Array.isArray(data) ? data : []);
    } catch (e: any) {
      setError(e?.message || t("common.failed", "加载失败"));
    } finally {
      setLoading(false);
    }
  }, [status, expiring30, t]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="panel">
      <div className="desk-toolbar cert-filter-bar">
        <label>
          {t("ship.cert.filter_status", "状态")}
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("ship.cert.status_all", "全部状态")}</option>
            {CERT_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`ship.cert.status_${s}`, s)}
              </option>
            ))}
          </select>
        </label>
        <label className="cert-filter-toggle">
          <input type="checkbox" checked={expiring30} onChange={(e) => setExpiring30(e.target.checked)} />
          {t("ship.cert.expiring_30", "30 天内到期")}
        </label>
        <ExportButton entity="certificates" />
      </div>
      <StateView
        loading={loading}
        error={error}
        empty={!rows.length}
        emptyText={t("ship.cert.empty", "没有符合条件的证书")}
        onRetry={load}
      >
        <table className="data-table">
          <thead>
            <tr>
              <th>{t("ship.cert.col_vessel", "船舶")}</th>
              <th>{t("ship.cert.col_cert", "证书")}</th>
              <th>{t("ship.cert.col_issued", "签发日期")}</th>
              <th>{t("ship.cert.col_expires", "到期日期")}</th>
              <th>{t("ship.cert.col_days", "剩余天数")}</th>
              <th>{t("common.status", "状态")}</th>
              <th>{t("ship.cert.col_version", "当前版本")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => {
              const days = certDays(c);
              return (
                <tr key={c.id} onClick={() => c.vessel_id && onOpenVessel(c.vessel_id)}>
                  <td>{c.vessel_name || "—"}</td>
                  <td>
                    <strong>{c.cert_name}</strong>
                    <div className="muted">{c.cert_code}</div>
                  </td>
                  <td>{c.issued_on || "—"}</td>
                  <td>{c.expires_on || "—"}</td>
                  <td>
                    {days == null ? (
                      "—"
                    ) : days < 0 ? (
                      <span className="overdue">{t("ship.cert.expired_days", "已过期 {n} 天", { n: -days })}</span>
                    ) : (
                      days
                    )}
                  </td>
                  <td>
                    <span className={`pill ${c.status}`}>{t(`ship.cert.status_${c.status}`, c.status)}</span>
                  </td>
                  <td>
                    {c.current_file ? (
                      <span title={c.current_file.file_name}>
                        v{c.current_file.version_no} · {c.current_file.file_name}
                      </span>
                    ) : (
                      <span className="muted">{t("ship.cert.no_file", "未上传")}</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </StateView>
    </div>
  );
}

type EditDraft = {
  cert_name: string;
  issued_on: string;
  expires_on: string;
  issuing_body: string;
  external_ref: string;
};

export function VesselCertificates({ certs, onChanged }: { certs: VesselCert[]; onChanged: () => void | Promise<void> }) {
  const { t } = useI18n();
  const [msg, setMsg] = useState("");
  const [uploadCert, setUploadCert] = useState<VesselCert | null>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadNote, setUploadNote] = useState("");
  const [historyCert, setHistoryCert] = useState<VesselCert | null>(null);
  const [files, setFiles] = useState<CertAttachment[]>([]);
  const [filesLoading, setFilesLoading] = useState(false);
  const [editCert, setEditCert] = useState<VesselCert | null>(null);
  const [draft, setDraft] = useState<EditDraft | null>(null);
  const [pendingDelete, setPendingDelete] = useState<VesselCert | null>(null);
  const [pendingFileDelete, setPendingFileDelete] = useState<CertAttachment | null>(null);
  const [busy, setBusy] = useState(false);

  const loadFiles = useCallback(async (certId: string) => {
    setFilesLoading(true);
    try {
      const data = await apiGet(`/api/v1/ship/certificates/${certId}/files`);
      setFiles(Array.isArray(data) ? data : []);
    } catch {
      setFiles([]);
    } finally {
      setFilesLoading(false);
    }
  }, []);

  function openUpload(c: VesselCert) {
    setUploadCert(c);
    setUploadFile(null);
    setUploadNote("");
    setMsg("");
  }

  function openHistory(c: VesselCert) {
    setHistoryCert(c);
    setFiles([]);
    loadFiles(c.id);
  }

  function openEdit(c: VesselCert) {
    setEditCert(c);
    setDraft({
      cert_name: c.cert_name || "",
      issued_on: c.issued_on || "",
      expires_on: c.expires_on || "",
      issuing_body: c.issuing_body || "",
      external_ref: c.external_ref || "",
    });
  }

  function pickFile(f: File | null) {
    if (!f) {
      setUploadFile(null);
      return;
    }
    if (f.size > MAX_FILE_BYTES) {
      setMsg(t("ship.cert.file_too_big", "文件不能超过 10MB"));
      setUploadFile(null);
      return;
    }
    const ext = `.${(f.name.split(".").pop() || "").toLowerCase()}`;
    if (!FILE_ACCEPT.split(",").includes(ext)) {
      setMsg(t("ship.cert.file_bad_type", "仅支持 PDF / PNG / JPG / WebP 文件"));
      setUploadFile(null);
      return;
    }
    setMsg("");
    setUploadFile(f);
  }

  async function submitUpload() {
    if (!uploadCert || !uploadFile) {
      setMsg(t("ship.cert.need_file", "请选择要上传的文件"));
      return;
    }
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", uploadFile);
      if (uploadNote.trim()) form.append("note", uploadNote.trim());
      await apiUpload(`/api/v1/ship/certificates/${uploadCert.id}/files`, form);
      setMsg(t("ship.cert.upload_ok", "扫描件已上传"));
      setUploadCert(null);
      await onChanged();
    } catch (e: any) {
      setMsg(e?.message || t("common.failed", "操作失败"));
    } finally {
      setBusy(false);
    }
  }

  async function submitEdit() {
    if (!editCert || !draft) return;
    setBusy(true);
    try {
      await apiPatch(`/api/v1/ship/certificates/${editCert.id}`, {
        cert_name: draft.cert_name.trim() || undefined,
        issued_on: draft.issued_on || null,
        expires_on: draft.expires_on || null,
        issuing_body: draft.issuing_body.trim() || null,
        external_ref: draft.external_ref.trim() || null,
      });
      setMsg(t("ship.cert.edit_ok", "证书已更新"));
      setEditCert(null);
      await onChanged();
    } catch (e: any) {
      setMsg(e?.message || t("common.failed", "操作失败"));
    } finally {
      setBusy(false);
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setBusy(true);
    try {
      await apiDelete(`/api/v1/ship/certificates/${pendingDelete.id}`);
      setMsg(t("ship.cert.delete_ok", "证书已删除"));
      setPendingDelete(null);
      await onChanged();
    } catch (e: any) {
      setMsg(e?.message || t("common.failed", "操作失败"));
    } finally {
      setBusy(false);
    }
  }

  async function setCurrent(f: CertAttachment) {
    if (!historyCert) return;
    setBusy(true);
    try {
      await apiPost(`/api/v1/files/${f.id}/current`);
      await loadFiles(historyCert.id);
      await onChanged();
    } catch (e: any) {
      setMsg(e?.message || t("common.failed", "操作失败"));
    } finally {
      setBusy(false);
    }
  }

  async function confirmFileDelete() {
    if (!pendingFileDelete || !historyCert) return;
    setBusy(true);
    try {
      await apiDelete(`/api/v1/files/${pendingFileDelete.id}`);
      setPendingFileDelete(null);
      await loadFiles(historyCert.id);
      await onChanged();
    } catch (e: any) {
      setMsg(e?.message || t("common.failed", "操作失败"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="cert-manager">
      {msg ? <p className="flash">{msg}</p> : null}
      {certs.length ? (
        certs.map((c) => {
          const days = certDays(c);
          return (
            <div key={c.id} className="cert-row">
              <div className="cert-row-main">
                <span className="cert-row-title">
                  <span className={`pill ${c.status}`}>{t(`ship.cert.status_${c.status}`, c.status)}</span>
                  {c.cert_name}
                </span>
                <small className="muted">
                  {t("ship.cert.col_expires", "到期日期")}: {c.expires_on || "n/a"}
                  {days != null
                    ? days < 0
                      ? ` · ${t("ship.cert.expired_days", "已过期 {n} 天", { n: -days })}`
                      : ` · ${t("ship.cert.days_left", "剩余 {n} 天", { n: days })}`
                    : ""}
                </small>
                <small className="muted">
                  {c.current_file
                    ? `v${c.current_file.version_no} · ${c.current_file.file_name}`
                    : t("ship.cert.no_file", "未上传扫描件")}
                </small>
              </div>
              <div className="cert-row-ops">
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => openUpload(c)}>
                  {t("ship.cert.upload", "上传扫描件")}
                </button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => openHistory(c)}>
                  {t("ship.cert.versions", "版本历史")}
                </button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => openEdit(c)}>
                  {t("common.edit", "编辑")}
                </button>
                <button type="button" className="btn btn-danger btn-sm" disabled={busy} onClick={() => setPendingDelete(c)}>
                  {t("common.delete", "删除")}
                </button>
              </div>
            </div>
          );
        })
      ) : (
        <p className="muted">{t("ship.cert.none", "该船暂无证书")}</p>
      )}

      <RecordModal
        open={Boolean(uploadCert)}
        title={t("ship.cert.upload_title", "上传扫描件 · {name}", { name: uploadCert?.cert_name || "" })}
        onClose={() => setUploadCert(null)}
        onSave={submitUpload}
        canDelete={false}
        saving={busy}
      >
        <label>
          {t("ship.cert.file", "文件（PDF / PNG / JPG / WebP，≤10MB）")}
          <input type="file" accept={FILE_ACCEPT} onChange={(e) => pickFile(e.target.files?.[0] || null)} />
        </label>
        <label>
          {t("ship.cert.note", "备注")}
          <input value={uploadNote} onChange={(e) => setUploadNote(e.target.value)} />
        </label>
      </RecordModal>

      <RecordModal
        open={Boolean(historyCert)}
        title={t("ship.cert.versions_title", "版本历史 · {name}", { name: historyCert?.cert_name || "" })}
        onClose={() => setHistoryCert(null)}
        canEdit={false}
        canDelete={false}
      >
        <StateView
          loading={filesLoading}
          empty={!files.length}
          emptyText={t("ship.cert.no_versions", "尚未上传任何版本")}
        >
          {files.map((f) => (
            <div key={f.id} className="cert-file-row">
              <div className="cert-file-main">
                <span className="cert-file-name">
                  <strong>v{f.version_no}</strong> {f.file_name}
                  {f.is_current ? (
                    <span className="pill valid">{t("ship.cert.current", "当前")}</span>
                  ) : null}
                </span>
                <small className="muted">
                  {fmtSize(f.size)} · {f.uploaded_by || "—"} · {(f.created_at || "").slice(0, 16).replace("T", " ")}
                </small>
                {f.note ? <small className="muted">{f.note}</small> : null}
              </div>
              <div className="cert-row-ops">
                <a className="btn btn-ghost btn-sm" href={`${API_BASE}${f.download_url}`} download={f.file_name}>
                  {t("common.download", "下载")}
                </a>
                {!f.is_current ? (
                  <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => setCurrent(f)}>
                    {t("ship.cert.set_current", "设为当前版本")}
                  </button>
                ) : null}
                <button
                  type="button"
                  className="btn btn-danger btn-sm"
                  disabled={busy}
                  onClick={() => setPendingFileDelete(f)}
                >
                  {t("common.delete", "删除")}
                </button>
              </div>
            </div>
          ))}
        </StateView>
      </RecordModal>

      <RecordModal
        open={Boolean(editCert)}
        title={t("ship.cert.edit_title", "编辑证书 · {name}", { name: editCert?.cert_name || "" })}
        onClose={() => setEditCert(null)}
        onSave={submitEdit}
        canDelete={false}
        saving={busy}
      >
        <label>
          {t("ship.cert.field_name", "证书名称")}
          <input
            value={draft?.cert_name || ""}
            onChange={(e) => setDraft((d) => (d ? { ...d, cert_name: e.target.value } : d))}
          />
        </label>
        <label>
          {t("ship.cert.col_issued", "签发日期")}
          <DateInput value={draft?.issued_on || ""} onChange={(v) => setDraft((d) => (d ? { ...d, issued_on: v } : d))} />
        </label>
        <label>
          {t("ship.cert.col_expires", "到期日期")}
          <DateInput value={draft?.expires_on || ""} onChange={(v) => setDraft((d) => (d ? { ...d, expires_on: v } : d))} />
        </label>
        <label>
          {t("ship.cert.field_body", "签发机构")}
          <input
            value={draft?.issuing_body || ""}
            onChange={(e) => setDraft((d) => (d ? { ...d, issuing_body: e.target.value } : d))}
          />
        </label>
        <label>
          {t("ship.cert.field_ref", "外部编号")}
          <input
            value={draft?.external_ref || ""}
            onChange={(e) => setDraft((d) => (d ? { ...d, external_ref: e.target.value } : d))}
          />
        </label>
      </RecordModal>

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title={t("common.confirm", "确认操作")}
        message={t("ship.cert.confirm_delete", "确定删除证书「{name}」及其所有版本文件？", {
          name: pendingDelete?.cert_name || "",
        })}
        danger
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
      <ConfirmDialog
        open={Boolean(pendingFileDelete)}
        title={t("common.confirm", "确认操作")}
        message={t("ship.cert.confirm_delete_file", "确定删除版本 v{n}（{file}）？", {
          n: pendingFileDelete?.version_no ?? "",
          file: pendingFileDelete?.file_name || "",
        })}
        danger
        onConfirm={confirmFileDelete}
        onCancel={() => setPendingFileDelete(null)}
      />
    </div>
  );
}
