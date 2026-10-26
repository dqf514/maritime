"use client";

/**
 * 通用实体附件面板（行业实践：单证依据挂业务对象）。
 *
 * 后端 /api/v1/entities/{entity_type}/{entity_id}/files —— 版本化上传/列表，
 * /api/v1/files/{id}（current|download|DELETE）管理版本。写操作按模块角色轴
 * 门控（viewer 只读）；组件不做权限判断，403 由 msgOf 展示。
 * 零内联样式（一致性基线）。
 */

import { useCallback, useEffect, useState } from "react";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StateView } from "@/components/StateView";
import { API_BASE, apiDelete, apiGet, apiPost, apiUpload } from "@/lib/api";
import { handled, msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type AttachmentRow = {
  id: string;
  version_no: number;
  is_current: boolean;
  file_name: string;
  size: number | null;
  note: string | null;
  created_at: string | null;
  download_url: string;
};

/** 平台 document 策略允许的扩展名（与后端 upload_policy 一致） */
const FILE_ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp,.xlsx,.xlsm,.csv";
const MAX_FILE_BYTES = 10 * 1024 * 1024;

function fmtSize(n: number | null): string {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function AttachmentsPanel({
  entityType,
  entityId,
}: {
  entityType: string;
  entityId: string;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [rows, setRows] = useState<AttachmentRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<AttachmentRow | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const list = (await apiGet(`/api/v1/entities/${entityType}/${entityId}/files`)) as AttachmentRow[];
      setRows(Array.isArray(list) ? list : []);
      setErr(null);
    } catch (ex) {
      setRows([]);
      setErr(msgOf(ex, t("att.load_fail", "附件加载失败")));
    } finally {
      setLoading(false);
    }
  }, [entityType, entityId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  function pickFile(f: File | null) {
    if (!f) {
      setUploadFile(null);
      return;
    }
    if (f.size > MAX_FILE_BYTES) {
      toast.error(t("ship.cert.file_too_big", "文件不能超过 10MB"));
      setUploadFile(null);
      return;
    }
    const ext = `.${(f.name.split(".").pop() || "").toLowerCase()}`;
    if (!FILE_ACCEPT.split(",").includes(ext)) {
      toast.error(t("att.bad_type", "Only PDF / PNG / JPG / WebP / XLSX / CSV files are allowed"));
      setUploadFile(null);
      return;
    }
    setUploadFile(f);
  }

  async function submitUpload() {
    if (!uploadFile) {
      toast.error(t("att.need_file", "Choose a file first"));
      return;
    }
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", uploadFile);
      if (note.trim()) form.append("note", note.trim());
      await apiUpload(`/api/v1/entities/${entityType}/${entityId}/files`, form);
      toast.success(t("att.upload_ok", "Uploaded"));
      setUploadFile(null);
      setNote("");
      await load();
    } catch (ex) {
      toast.error(msgOf(ex, t("common.failed", "操作失败")));
    } finally {
      setBusy(false);
    }
  }

  async function setCurrent(f: AttachmentRow) {
    setBusy(true);
    try {
      await apiPost(`/api/v1/files/${f.id}/current`);
      toast.success(t("att.set_current_ok", "Current version updated"));
      await load();
    } catch (ex) {
      toast.error(msgOf(ex, t("common.failed", "操作失败")));
    } finally {
      setBusy(false);
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setBusy(true);
    try {
      await apiDelete(`/api/v1/files/${pendingDelete.id}`);
      toast.success(t("att.delete_ok", "File deleted"));
      setPendingDelete(null);
      await load();
    } catch (ex) {
      toast.error(msgOf(ex, t("common.failed", "操作失败")));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel att-panel">
      <h4>{t("att.title", "附件")}</h4>
      <StateView
        loading={loading}
        error={err ?? undefined}
        empty={!loading && !err && rows.length === 0}
        emptyText={t("att.empty", "No attachments yet")}
        onRetry={() => void load()}
      >
        <table className="table att-table">
          <thead>
            <tr>
              <th>{t("common.name", "名称")}</th>
              <th>{t("att.col_version", "Version")}</th>
              <th>{t("common.note", "备注")}</th>
              <th>{t("common.size", "大小")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((f) => (
              <tr key={f.id}>
                <td>
                  {f.is_current ? <span className="badge badge-info">{t("att.current", "当前版")}</span> : null}{" "}
                  {f.file_name}
                </td>
                <td>{t("att.version", "v{n}", { n: f.version_no })}</td>
                <td>{f.note || "—"}</td>
                <td>{fmtSize(f.size)}</td>
                <td className="row-actions">
                  <a className="btn btn-ghost btn-sm" href={`${API_BASE}${f.download_url}`} download={f.file_name}>
                    {t("common.download", "下载")}
                  </a>
                  {!f.is_current ? (
                    <button className="btn btn-sm" type="button" disabled={busy} onClick={() => void setCurrent(f)}>
                      {t("att.set_current", "设为当前版")}
                    </button>
                  ) : null}
                  <button className="btn btn-sm" type="button" disabled={busy} onClick={() => setPendingDelete(f)}>
                    {t("att.delete", "删除")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </StateView>
      <p className="row-actions">
        <input type="file" accept={FILE_ACCEPT} onChange={(e) => pickFile(e.target.files?.[0] ?? null)} />
        <input
          type="text"
          value={note}
          placeholder={t("att.note", "备注")}
          onChange={(e) => setNote(e.target.value)}
        />
        <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => void submitUpload()}>
          {uploadFile ? t("att.next_version", "Upload as new version") : t("att.upload", "上传")}
        </button>
      </p>
      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title={t("common.confirm", "确认操作")}
        message={t("att.delete_confirm", "Delete this file? A new version can be uploaded afterwards.")}
        danger
        onConfirm={() => void confirmDelete()}
        onCancel={() => setPendingDelete(null)}
      />
    </section>
  );
}
