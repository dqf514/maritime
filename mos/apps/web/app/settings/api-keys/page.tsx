"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { RecordModal } from "@/components/RecordModal";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type KeyRow = {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  status: string;
  raw_key?: string | null;
};

export default function ApiKeysPage() {
  const { t } = useI18n();
  const [rows, setRows] = useState<KeyRow[]>([]);
  const [name, setName] = useState("集成密钥");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [rawOnce, setRawOnce] = useState("");
  const [open, setOpen] = useState<KeyRow | null>(null);
  const [edit, setEdit] = useState({ name: "", status: "active", scopes: "read,write" });
  const [saving, setSaving] = useState(false);

  async function load() {
    setRows(await apiGet("/api/v1/settings/api-keys"));
  }

  useEffect(() => {
    load().catch((e) => setErr(String(e?.message || e)));
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    setErr("");
    setMsg("");
    try {
      const created = await apiPost("/api/v1/settings/api-keys", {
        name,
        scopes: ["read", "write"],
      });
      setRawOnce(created.raw_key || "");
      setMsg(t("page.apikeys.created", "API 密钥已创建 — 请立即复制密钥，之后不会再显示。"));
      await load();
    } catch (ex: any) {
      setErr(ex?.message || t("common.failed", "失败"));
    }
  }

  function openRow(r: KeyRow) {
    setOpen(r);
    setEdit({ name: r.name, status: r.status, scopes: (r.scopes || []).join(",") });
  }

  async function save() {
    if (!open) return;
    setSaving(true);
    try {
      await apiPatch(`/api/v1/settings/api-keys/${open.id}`, {
        name: edit.name,
        status: edit.status,
        scopes: edit.scopes
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      });
      setMsg(t("common.saved", "已保存"));
      setOpen(null);
      await load();
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!open) return;
    setSaving(true);
    try {
      await apiDelete(`/api/v1/settings/api-keys/${open.id}`);
      setMsg(t("common.recycled", "已移入回收站"));
      setOpen(null);
      await load();
    } finally {
      setSaving(false);
    }
  }

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.apikeys.title", "API 密钥")}</h1>
          <p className="page-sub">{t("page.apikeys.sub", "用于集成与合作方系统。点击行打开编辑或删除。")}</p>
        </div>
        <Link href="/settings/recycle" className="btn btn-ghost">
          {t("nav.recycle", "回收站")}
        </Link>
      </div>
      {msg ? <p className="flash">{msg}</p> : null}
      {err ? <div className="error">{err}</div> : null}
      {rawOnce ? (
        <div className="panel" style={{ borderLeft: "4px solid var(--accent)" }}>
          <strong>{t("page.apikeys.secret", "密钥（仅显示一次）")}</strong>
          <code style={{ display: "block", marginTop: "0.5rem", wordBreak: "break-all" }}>{rawOnce}</code>
        </div>
      ) : null}
      <form className="panel form-grid" onSubmit={create}>
        <label>
          {t("common.name", "名称")}
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <div style={{ alignSelf: "end" }}>
          <button className="btn btn-primary" type="submit">
            {t("page.apikeys.create", "新建密钥")}
          </button>
        </div>
      </form>
      <div className="panel" style={{ marginTop: "1rem" }}>
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.name", "名称")}</th>
              <th>{t("page.apikeys.prefix", "前缀")}</th>
              <th>{t("page.apikeys.scopes", "权限范围")}</th>
              <th>{t("common.status", "状态")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="row-openable" onClick={() => openRow(r)}>
                <td>{r.name}</td>
                <td>
                  <code>{r.key_prefix}…</code>
                </td>
                <td>{(r.scopes || []).join(", ")}</td>
                <td>{r.status}</td>
              </tr>
            ))}
            {!rows.length ? (
              <tr>
                <td colSpan={4} className="muted">
                  {t("common.no_data", "暂无数据")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <RecordModal
        open={Boolean(open)}
        title={t("page.apikeys.edit", "编辑 API 密钥")}
        onClose={() => setOpen(null)}
        onSave={save}
        onDelete={remove}
        saving={saving}
      >
        <p className="muted">
          <code>{open?.key_prefix}…</code>
        </p>
        <label>
          {t("common.name", "名称")}
          <input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} required />
        </label>
        <label>
          {t("page.apikeys.scopes", "权限范围")}
          <input value={edit.scopes} onChange={(e) => setEdit({ ...edit, scopes: e.target.value })} placeholder="read,write" />
        </label>
        <label>
          {t("common.status", "状态")}
          <select value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
            <option value="active">active</option>
            <option value="revoked">revoked</option>
          </select>
        </label>
      </RecordModal>
    </AppShell>
  );
}
