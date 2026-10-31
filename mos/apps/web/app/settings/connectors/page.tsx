"use client";

import { RefreshButton } from "@/components/RefreshButton";
import { useCallback, useEffect, useMemo, useState } from "react";
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
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type FieldSpec = {
  key: string;
  label: string;
  kind?: string;
  required?: boolean;
  placeholder?: string;
  secret?: boolean;
};

type CatalogItem = {
  connector_type: string;
  name: string;
  category?: string;
  description?: string;
  config_schema?: FieldSpec[];
};

type Connector = {
  id: string;
  connector_type: string;
  instance_name: string;
  status: string;
  endpoint?: string | null;
  secret_ref?: string | null;
  config?: Record<string, unknown>;
  last_health: Record<string, unknown>;
};

export default function ConnectorsPage() {
  const { t, locale } = useI18n();
  const toast = useToast();
  const [rows, setRows] = useState<Connector[]>([]);
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [open, setOpen] = useState<Connector | null>(null);
  const [creating, setCreating] = useState(false);
  const [edit, setEdit] = useState({
    instance_name: "",
    endpoint: "",
    connector_type: "",
    secret_ref: "",
    config: {} as Record<string, string>,
  });
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  // 目录（参考数据）失败：局部提示，不阻断整页
  const [catalogErr, setCatalogErr] = useState<string | null>(null);

  const selectedCatalog = useMemo(
    () => catalog.find((c) => c.connector_type === edit.connector_type),
    [catalog, edit.connector_type],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    setCatalogErr(null);
    const loc = locale?.startsWith("zh") ? "zh-CN" : "en";
    try {
      const list = await apiGet("/api/v1/settings/connectors");
      setRows(Array.isArray(list) ? list : []);
    } catch (ex) {
      setErr(msgOf(ex));
      setRows([]);
    }
    try {
      const cat = await apiGet(`/api/v1/settings/connectors/catalog?locale=${encodeURIComponent(loc)}`);
      setCatalog(Array.isArray(cat) ? cat : []);
    } catch (ex) {
      setCatalogErr(msgOf(ex));
      setCatalog([]);
    } finally {
      setLoading(false);
    }
  }, [locale]);

  useEffect(() => {
    load();
  }, [load]);

  function openCreate() {
    setCreating(true);
    setOpen(null);
    setEdit({
      instance_name: "",
      endpoint: "",
      connector_type: catalog.some((c) => c.connector_type === "fx.manual")
        ? "fx.manual"
        : catalog[0]?.connector_type || "fx.manual",
      secret_ref: "",
      config: {},
    });
  }

  useListHotkeys(openCreate);

  function closeModal() {
    setOpen(null);
    setCreating(false);
  }

  const openRow = useCallback((r: Connector) => {
    setCreating(false);
    setOpen(r);
    const cfg: Record<string, string> = {};
    const schema = catalog.find((c) => c.connector_type === r.connector_type)?.config_schema || [];
    for (const f of schema) {
      cfg[f.key] = String((r.config || {})[f.key] ?? "");
    }
    setEdit({
      instance_name: r.instance_name,
      endpoint: r.endpoint || "",
      connector_type: r.connector_type,
      secret_ref: r.secret_ref || "",
      config: cfg,
    });
  }, [catalog]);

  async function save() {
    setSaving(true);
    try {
      if (creating || !open) {
        await apiPost("/api/v1/settings/connectors", {
          connector_type: edit.connector_type,
          instance_name: edit.instance_name || edit.connector_type,
          endpoint: edit.endpoint || null,
          secret_ref: edit.secret_ref || null,
          config: edit.config,
        });
        toast.success(t("common.created", "Created"));
      } else {
        await apiPatch(`/api/v1/settings/connectors/${open.id}`, {
          connector_type: edit.connector_type,
          instance_name: edit.instance_name,
          endpoint: edit.endpoint || null,
          // 掩码 "***" 是只读回显 —— 原样提交会把凭据写成字面量 ***
          secret_ref: edit.secret_ref === "***" ? undefined : edit.secret_ref || null,
          config: edit.config,
        });
        toast.success(t("common.saved", "Saved"));
      }
      closeModal();
      await load();
    } catch (ex) {
      toast.error(msgOf(ex, t("common.failed", "Failed")));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!open) return;
    setSaving(true);
    try {
      await apiDelete(`/api/v1/settings/connectors/${open.id}`);
      toast.success(t("common.recycled", "Moved to recycle bin"));
      closeModal();
      await load();
    } finally {
      setSaving(false);
    }
  }

  async function test(id: string) {
    const res = await apiPost(`/api/v1/settings/connectors/${id}/test`);
    const ok = Boolean(res.last_health?.ok);
    if (ok) toast.success(t("page.connectors.health_ok", "Health test: OK — {detail}", { detail: JSON.stringify(res.last_health || {}) }));
    else toast.error(t("page.connectors.health_fail", "Health test: FAIL — {detail}", { detail: JSON.stringify(res.last_health || {}) }));
    await load();
  }

  async function sync(id: string) {
    const res = await apiPost(`/api/v1/settings/connectors/${id}/sync`);
    const ok = res?.ok !== false && !res?.error;
    if (ok) toast.success(t("page.connectors.synced", "Sync completed") + " — " + JSON.stringify(res));
    else toast.error(t("page.connectors.sync_fail", "Sync failed") + " — " + JSON.stringify(res));
    await load();
  }

  const instanceColumns = useMemo<ColumnDef<Connector>[]>(() => [
    {
      key: "instance_name",
      title: t("common.name", "Name"),
      minWidth: 160,
      value: (r) => r.instance_name,
      render: (v, r) => (
        <button type="button" className="linklike" onClick={() => openRow(r)}>
          {String(v)}
        </button>
      ),
    },
    { key: "connector_type", title: t("common.type", "Type"), width: 140, value: (r) => r.connector_type },
    {
      key: "status",
      title: t("common.status", "Status"),
      width: 100,
      value: (r) => r.status,
      render: (v) => <span className={`badge badge-${v === "active" ? "ok" : "warn"}`}>{t(`status.${v}`, String(v))}</span>,
    },
    {
      key: "last_health",
      title: t("page.connectors.last_health", "Last health"),
      minWidth: 180,
      value: (r) => r.last_health,
      // 健康探针结果 → 可读状态（原为原始 JSON dump）
      render: (v) => {
        const h = (v || {}) as Record<string, unknown>;
        if (!Object.keys(h).length) return <span className="muted">—</span>;
        const ok = h.ok === true;
        const msg = typeof h.message === "string" ? h.message : "";
        return (
          <span className={ok ? "" : "text-danger"}>
            {ok ? "✓ " : "✗ "}
            {ok ? t("page.connectors.ok", "OK") : t("page.connectors.fail", "FAIL")}
            {msg ? ` · ${msg}` : ""}
          </span>
        );
      },
    },
  ], [t, openRow]);

  const catalogColumns = useMemo<ColumnDef<CatalogItem>[]>(() => [
    { key: "connector_type", title: t("common.type", "Type"), width: 150, value: (r) => r.connector_type },
    { key: "name", title: t("common.name", "Name"), minWidth: 150, value: (r) => r.name },
    {
      key: "description",
      title: t("page.connectors.description", "Description"),
      minWidth: 220,
      value: (r) => r,
      render: (_v, r) => {
        const cat = r.category ? t(`page.connectors.cat_${r.category.replace(/[^a-z0-9]+/gi, "_")}`, r.category) : "";
        const desc = r.description || "—";
        return <span>{cat ? `${cat} — ${desc}` : desc}</span>;
      },
    },
  ], [t]);

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[
          { label: t("nav.settings_hub", "System settings"), href: "/settings" },
          { label: t("page.connectors.title", "Integration Hub") },
        ]}
        title={t("page.connectors.title", "Integration Hub")}
        subtitle={t(
          "page.connectors.sub",
          "External adapters: FX, bunker index, AIS, PMS, ERP, sanctions, emissions.",
        )}
        actions={
          <Link href="/settings" className="btn btn-ghost">
            {t("nav.settings_hub", "System settings")}
          </Link>
        }
      />
      <Toolbar>
        <button type="button" className="btn btn-primary" onClick={openCreate}>
          {t("page.connectors.create", "New connector")}
        </button>
        <RefreshButton label={t("common.refresh", "Refresh")} className="btn btn-sm" onClick={() => load()} />
      </Toolbar>

      <div className="panel" style={{ marginTop: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>{t("page.connectors.instances", "Instances")}</h3>
        <StateView
          loading={loading}
          error={err ?? undefined}
          empty={!rows.length}
          onRetry={() => load()}
          emptyText={t("common.no_data", "No data")}
        >
          <DataGrid<Connector>
            columns={instanceColumns}
            data={rows}
            rowKey={(r) => r.id}
            storageKey="settings_connectors_instances_grid"
            onRowDoubleClick={(r) => openRow(r)}
            emptyText={t("common.no_data", "No data")}
          />
        </StateView>
      </div>

      <div className="panel" style={{ marginTop: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>{t("page.connectors.catalog", "Catalog")}</h3>
        {catalogErr ? <p className="text-danger">{catalogErr}</p> : null}
        <StateView
          loading={loading}
          error={catalogErr ?? undefined}
          empty={!catalog.length}
          onRetry={() => load()}
          emptyText={t("common.no_data", "No data")}
        >
          <DataGrid<CatalogItem>
            columns={catalogColumns}
            data={catalog}
            rowKey={(r) => r.connector_type}
            storageKey="settings_connectors_catalog_grid"
            emptyText={t("common.no_data", "No data")}
          />
        </StateView>
      </div>

      <RecordModal
        open={creating || Boolean(open)}
        title={creating ? t("page.connectors.create", "New connector") : t("page.connectors.edit", "Edit connector")}
        onClose={closeModal}
        onSave={save}
        onDelete={creating ? undefined : remove}
        canDelete={!creating}
        saving={saving}
      >
        {creating ? (
          <label>
            {t("common.type", "类型")}
            <select value={edit.connector_type} onChange={(e) => setEdit({ ...edit, connector_type: e.target.value })}>
              {catalog.map((c) => (
                <option key={c.connector_type} value={c.connector_type}>
                  [{c.category}] {c.name}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <p className="muted">{edit.connector_type}</p>
        )}
        {creating && selectedCatalog?.description ? <p className="muted">{selectedCatalog.description}</p> : null}
        <label>
          {t("common.name", "Name")}
          <input
            value={edit.instance_name}
            onChange={(e) => setEdit({ ...edit, instance_name: e.target.value })}
            placeholder={edit.connector_type || undefined}
            required
          />
        </label>
        <label>
          {t("page.connectors.endpoint", "Endpoint / Base URL")}
          <input value={edit.endpoint} onChange={(e) => setEdit({ ...edit, endpoint: e.target.value })} />
        </label>
        <label>
          {t("page.connectors.secret_ref", "Secret ref")}
          <input value={edit.secret_ref} onChange={(e) => setEdit({ ...edit, secret_ref: e.target.value })} />
        </label>
        {(selectedCatalog?.config_schema || []).map((f) => (
          <label key={f.key}>
            {f.label}
            {f.required ? " *" : ""}
            <input
              type={f.secret ? "password" : f.kind === "number" ? "number" : "text"}
              value={edit.config[f.key] || ""}
              placeholder={f.placeholder}
              onChange={(e) => setEdit({ ...edit, config: { ...edit.config, [f.key]: e.target.value } })}
            />
          </label>
        ))}
        {!creating && open ? (
          <div className="desk-toolbar">
            <button
              type="button"
              className="btn"
              disabled={saving}
              onClick={() => open && test(open.id).catch(() => toast.error(t("page.connectors.test_fail", "Test failed")))}
            >
              {t("common.test", "测试连接")}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={saving}
              onClick={() => open && sync(open.id).catch(() => toast.error(t("common.failed", "Failed")))}
            >
              {t("page.connectors.sync", "Sync / pull")}
            </button>
          </div>
        ) : null}
      </RecordModal>
    </AppShell>
  );
}
