"use client";

import { RefreshButton } from "@/components/RefreshButton";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { StateView } from "@/components/StateView";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { msgOf, handled } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type KeyRow = {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  status: string;
  raw_key?: string | null;
};

function parseScopes(v: string): string[] {
  return v
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

export default function ApiKeysPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [rows, setRows] = useState<KeyRow[]>([]);
  const [err, setErr] = useState("");
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [rawOnce, setRawOnce] = useState("");
  // 密钥默认脱敏；明文仅在用户主动点「显示」时渲染，复制走剪贴板
  const [revealKey, setRevealKey] = useState(false);
  const [open, setOpen] = useState<KeyRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [edit, setEdit] = useState({ name: "", status: "active", scopes: "read,write" });
  const [saving, setSaving] = useState(false);

  async function load() {
    setLoading(true);
    setLoadErr(null);
    try {
      const rows = await apiGet("/api/v1/settings/api-keys");
      setRows(Array.isArray(rows) ? rows : []);
    } catch (ex) {
      setLoadErr(msgOf(ex));
      setRows([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  /** 脱敏显示：仅首尾片段可见 */
  function maskKey(raw: string): string {
    if (!raw) return "";
    if (raw.length <= 8) return raw.slice(0, 2) + "…";
    return `${raw.slice(0, 4)}…${raw.slice(-4)}`;
  }

  async function copyRawKey() {
    if (!rawOnce) return;
    try {
      await navigator.clipboard.writeText(rawOnce);
      toast.success(t("common.copied", "已复制"));
    } catch {
      toast.error(t("page.apikeys.copy_fail", "复制失败，请显示密钥后手动复制。"));
    }
  }

  function openCreate() {
    setCreating(true);
    setOpen(null);
    setErr("");
    setEdit({
      name: t("page.apikeys.default_name", "Integration key"),
      status: "active",
      scopes: "read,write",
    });
  }

  useListHotkeys(openCreate);

  function closeModal() {
    setOpen(null);
    setCreating(false);
  }

  function openRow(r: KeyRow) {
    setCreating(false);
    setOpen(r);
    setEdit({ name: r.name, status: r.status, scopes: (r.scopes || []).join(",") });
  }

  async function save() {
    setSaving(true);
    try {
      if (creating || !open) {
        setErr("");
        const created = await apiPost("/api/v1/settings/api-keys", {
          name: edit.name,
          scopes: parseScopes(edit.scopes).length ? parseScopes(edit.scopes) : ["read", "write"],
        });
        setRawOnce(created.raw_key || "");
        setRevealKey(false);
        toast.success(t("page.apikeys.created", "API 密钥已创建 — 请立即复制密钥，之后不会再显示。"));
      } else {
        await apiPatch(`/api/v1/settings/api-keys/${open.id}`, {
          name: edit.name,
          status: edit.status,
          scopes: parseScopes(edit.scopes),
        });
        toast.success(t("common.saved", "已保存"));
      }
      closeModal();
      await load();
    } catch (ex) {
      if (creating) {
        setErr(msgOf(ex, t("common.failed", "失败")));
      } else {
        toast.error(msgOf(ex, t("common.failed", "失败")));
      }
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!open) return;
    setSaving(true);
    try {
      await apiDelete(`/api/v1/settings/api-keys/${open.id}`);
      toast.success(t("common.recycled", "已移入回收站"));
      closeModal();
      await load();
    } finally {
      setSaving(false);
    }
  }

  const columns = useMemo<ColumnDef<KeyRow>[]>(() => [
    {
      key: "name",
      title: t("common.name", "Name"),
      minWidth: 160,
      value: (r) => r.name,
      render: (v, r) => (
        <button type="button" className="linklike" onClick={() => openRow(r)}>
          {String(v)}
        </button>
      ),
    },
    {
      key: "key_prefix",
      title: t("page.apikeys.prefix", "Prefix"),
      width: 140,
      value: (r) => r.key_prefix,
      render: (v) => <code>{String(v)}…</code>,
    },
    {
      key: "scopes",
      title: t("page.apikeys.scopes", "Scopes"),
      minWidth: 160,
      value: (r) => (r.scopes || []).join(", "),
    },
    { key: "status", title: t("common.status", "Status"), width: 100, value: (r) => r.status },
  ], [t]);

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[
          { label: t("nav.settings_hub", "System settings"), href: "/settings" },
          { label: t("page.apikeys.title", "API keys") },
        ]}
        title={t("page.apikeys.title", "API keys")}
        subtitle={t("page.apikeys.sub", "For integrations and partner systems. Click a row to edit or delete.")}
        actions={
          <Link href="/settings/recycle" className="btn btn-ghost">
            {t("nav.recycle", "Recycle bin")}
          </Link>
        }
      />
      {err ? <div className="error">{err}</div> : null}
      {rawOnce ? (
        <div className="panel" style={{ borderLeft: "4px solid var(--accent)" }}>
          <strong>{t("page.apikeys.secret", "Secret (shown once)")}</strong>
          <code style={{ display: "block", marginTop: "0.5rem", wordBreak: "break-all" }}>
            {revealKey ? rawOnce : maskKey(rawOnce)}
          </code>
          <div className="row-actions">
            <button type="button" className="btn btn-ghost" onClick={() => copyRawKey().catch(handled)}>
              {t("page.apikeys.copy_key", "复制密钥")}
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              aria-expanded={revealKey}
              aria-label={t("page.apikeys.reveal_key", "显示密钥")}
              onClick={() => setRevealKey((v) => !v)}
            >
              {revealKey ? t("page.apikeys.hide_key", "隐藏密钥") : t("page.apikeys.reveal_key", "显示密钥")}
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => {
                setRawOnce("");
                setRevealKey(false);
              }}
            >
              {t("common.close", "关闭")}
            </button>
          </div>
        </div>
      ) : null}
      <Toolbar>
        <button type="button" className="btn btn-primary" onClick={openCreate}>
          {t("page.apikeys.create", "New API key")}
        </button>
        <RefreshButton label={t("common.refresh", "Refresh")} className="btn btn-sm" onClick={() => load()} />
      </Toolbar>
      <StateView
        loading={loading}
        error={loadErr ?? undefined}
        empty={!rows.length}
        onRetry={() => load()}
        emptyText={t("common.no_data", "No data")}
      >
        <DataGrid<KeyRow>
          columns={columns}
          data={rows}
          rowKey={(r) => r.id}
          storageKey="settings_api_keys_grid"
          onRowDoubleClick={(r) => openRow(r)}
          emptyText={t("common.no_data", "No data")}
        />
      </StateView>

      <RecordModal
        open={creating || Boolean(open)}
        title={creating ? t("page.apikeys.create", "新建密钥") : t("page.apikeys.edit", "编辑 API 密钥")}
        onClose={closeModal}
        onSave={save}
        onDelete={creating ? undefined : remove}
        canDelete={!creating}
        saving={saving}
      >
        {!creating ? (
          <p className="muted">
            <code>{open?.key_prefix}…</code>
          </p>
        ) : null}
        <label>
          {t("common.name", "名称")}
          <input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} required />
        </label>
        <label>
          {t("page.apikeys.scopes", "权限范围")}
          <input value={edit.scopes} onChange={(e) => setEdit({ ...edit, scopes: e.target.value })} placeholder="read,write" />
        </label>
        {!creating ? (
          <label>
            {t("common.status", "状态")}
            <select value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
              <option value="active">active</option>
              <option value="revoked">revoked</option>
            </select>
          </label>
        ) : null}
      </RecordModal>
    </AppShell>
  );
}
