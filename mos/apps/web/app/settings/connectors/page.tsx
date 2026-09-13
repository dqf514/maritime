"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { RecordModal } from "@/components/RecordModal";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

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
  const [rows, setRows] = useState<Connector[]>([]);
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [msg, setMsg] = useState("");
  const [ctype, setCtype] = useState("fx.manual");
  const [iname, setIname] = useState("");
  const [open, setOpen] = useState<Connector | null>(null);
  const [edit, setEdit] = useState({
    instance_name: "",
    endpoint: "",
    connector_type: "",
    secret_ref: "",
    config: {} as Record<string, string>,
  });
  const [saving, setSaving] = useState(false);

  const selectedCatalog = useMemo(
    () => catalog.find((c) => c.connector_type === (open?.connector_type || ctype)),
    [catalog, open, ctype],
  );

  async function load() {
    const loc = locale?.startsWith("zh") ? "zh-CN" : "en";
    const [list, cat] = await Promise.all([
      apiGet("/api/v1/settings/connectors"),
      apiGet(`/api/v1/settings/connectors/catalog?locale=${encodeURIComponent(loc)}`),
    ]);
    setRows(list);
    setCatalog(Array.isArray(cat) ? cat : []);
    if (Array.isArray(cat) && cat[0] && !ctype) setCtype(cat[0].connector_type);
  }

  useEffect(() => {
    load().catch(() => {
      setRows([]);
      setCatalog([]);
    });
  }, [locale]);

  async function create(e: FormEvent) {
    e.preventDefault();
    await apiPost("/api/v1/settings/connectors", {
      connector_type: ctype,
      instance_name: iname || ctype,
      config: {},
    });
    setIname("");
    setMsg(t("common.created", "Created"));
    await load();
  }

  function openRow(r: Connector) {
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
  }

  async function save() {
    if (!open) return;
    setSaving(true);
    try {
      await apiPatch(`/api/v1/settings/connectors/${open.id}`, {
        connector_type: edit.connector_type,
        instance_name: edit.instance_name,
        endpoint: edit.endpoint || null,
        secret_ref: edit.secret_ref || null,
        config: edit.config,
      });
      setMsg(t("common.saved", "Saved"));
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
      await apiDelete(`/api/v1/settings/connectors/${open.id}`);
      setMsg(t("common.recycled", "Moved to recycle bin"));
      setOpen(null);
      await load();
    } finally {
      setSaving(false);
    }
  }

  async function test(id: string) {
    const res = await apiPost(`/api/v1/settings/connectors/${id}/test`);
    setMsg(
      t("page.connectors.health", "Health test: {ok}", {
        ok: res.last_health?.ok ? "OK" : "FAIL",
      }) +
        " — " +
        JSON.stringify(res.last_health || {}),
    );
    await load();
  }

  async function sync(id: string) {
    const res = await apiPost(`/api/v1/settings/connectors/${id}/sync`);
    setMsg(t("page.connectors.synced", "Sync completed") + " — " + JSON.stringify(res));
    await load();
  }

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.connectors.title", "Integration Hub")}</h1>
          <p className="page-sub">
            {t(
              "page.connectors.sub",
              "外部系统对接：汇率、燃油指数、AIS、PMS、ERP/SAP/Oracle、制裁名单、排放上报等。填写配置后可测试与同步。",
            )}
          </p>
        </div>
        <Link href="/settings" className="btn btn-ghost">
          {t("nav.settings_hub", "System settings")}
        </Link>
      </div>
      {msg ? <p>{msg}</p> : null}

      <form className="panel" onSubmit={(e) => create(e).catch(() => setMsg(t("common.failed", "Failed")))}>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
          <label>
            {t("common.type", "类型")}
            <select value={ctype} onChange={(e) => setCtype(e.target.value)}>
              {catalog.map((c) => (
                <option key={c.connector_type} value={c.connector_type}>
                  [{c.category}] {c.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("common.name", "Name")}
            <input value={iname} onChange={(e) => setIname(e.target.value)} placeholder={ctype} />
          </label>
          <button className="btn btn-primary" type="submit">
            {t("page.connectors.create", "New connector")}
          </button>
        </div>
        {selectedCatalog?.description ? <p className="muted">{selectedCatalog.description}</p> : null}
      </form>

      <div className="panel" style={{ marginTop: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>{t("page.connectors.instances", "Instances")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.name", "Name")}</th>
              <th>{t("common.type", "类型")}</th>
              <th>{t("common.status", "Status")}</th>
              <th>{t("page.connectors.last_health", "Last health")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="row-openable" onClick={() => openRow(r)}>
                <td>{r.instance_name}</td>
                <td>{r.connector_type}</td>
                <td>{r.status}</td>
                <td>
                  <code style={{ fontSize: "0.75rem" }}>{JSON.stringify(r.last_health)}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel" style={{ marginTop: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>{t("page.connectors.catalog", "Catalog")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.type", "类型")}</th>
              <th>{t("common.name", "Name")}</th>
              <th>{t("page.connectors.description", "Description")}</th>
            </tr>
          </thead>
          <tbody>
            {catalog.map((c) => (
              <tr key={c.connector_type}>
                <td>{c.connector_type}</td>
                <td>{c.name}</td>
                <td>
                  {c.category} — {c.description || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <RecordModal
        open={Boolean(open)}
        title={t("page.connectors.edit", "Edit connector")}
        onClose={() => setOpen(null)}
        onSave={save}
        onDelete={remove}
        saving={saving}
      >
        <p className="muted">{edit.connector_type}</p>
        <label>
          {t("common.name", "Name")}
          <input value={edit.instance_name} onChange={(e) => setEdit({ ...edit, instance_name: e.target.value })} required />
        </label>
        <label>
          Endpoint / Base URL
          <input value={edit.endpoint} onChange={(e) => setEdit({ ...edit, endpoint: e.target.value })} />
        </label>
        <label>
          Secret ref
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
        <div className="desk-toolbar">
          <button
            type="button"
            className="btn"
            disabled={!open || saving}
            onClick={() => open && test(open.id).catch(() => setMsg(t("page.connectors.test_fail", "Test failed")))}
          >
            {t("common.test", "测试连接")}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!open || saving}
            onClick={() => open && sync(open.id).catch(() => setMsg(t("common.failed", "Failed")))}
          >
            {t("page.connectors.sync", "Sync / pull")}
          </button>
        </div>
      </RecordModal>
    </AppShell>
  );
}
