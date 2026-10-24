"use client";

import { RefreshButton } from "@/components/RefreshButton";
import { FormEvent, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { SavedViews } from "@/components/SavedViews";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { Tabs } from "@/components/Tabs";
import { StateView } from "@/components/StateView";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { RowActions } from "@/components/RowActions";
import { useToast } from "@/components/ToastProvider";
import { apiGet, apiPatch, apiPost, apiDelete } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";

type ProfileRow = {
  id: string;
  code: string;
  name: string;
  kind: string;
  cloud_provider?: string | null;
  region?: string | null;
  description?: string | null;
  is_builtin?: boolean;
  status?: string;
  template?: Record<string, unknown>;
  last_applied_at?: string | null;
};

type AlertRow = {
  id: string;
  code?: string;
  name: string;
  metric_code: string;
  operator: string;
  threshold: number;
  severity: string;
  last_state?: string;
  enabled: boolean;
  description?: string | null;
};

type Tab = "datasource" | "tenants" | "init" | "deploy" | "monitor";
const TAB_IDS: readonly string[] = ["datasource", "tenants", "init", "deploy", "monitor"];

function PlatformOpsPage() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const { query, setQuery } = useListQuery();
  const tab: Tab = TAB_IDS.includes(query.tab ?? "") ? (query.tab as Tab) : "datasource";
  const setTab = (id: Tab) => setQuery({ tab: id === "datasource" ? null : id, page: null });
  const [overview, setOverview] = useState<Record<string, unknown> | null>(null);
  const [bindings, setBindings] = useState<Array<Record<string, unknown>>>([]);
  const [tenants, setTenants] = useState<Array<Record<string, unknown>>>([]);
  const [steps, setSteps] = useState<Array<Record<string, unknown>>>([]);
  const [profiles, setProfiles] = useState<ProfileRow[]>([]);
  const [alerts, setAlerts] = useState<AlertRow[]>([]);
  const [snapshot, setSnapshot] = useState<Record<string, unknown> | null>(null);
  const [msg, setMsg] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [bindingOpen, setBindingOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState<ProfileRow | null>(null);
  const [profileEdit, setProfileEdit] = useState({ name: "", kind: "", cloud_provider: "", region: "", description: "" });
  const [profileSaving, setProfileSaving] = useState(false);
  // 取数错误（不得静默变空数组 —— 空列表与「后端挂了」必须区分）
  const [coreLoading, setCoreLoading] = useState(true);
  const [coreErr, setCoreErr] = useState<string | null>(null);
  const [stepsErr, setStepsErr] = useState<string | null>(null);
  const [profilesErr, setProfilesErr] = useState<string | null>(null);
  const [monitorErr, setMonitorErr] = useState<string | null>(null);
  // 破坏性操作二次确认（待执行动作）
  const [pending, setPending] = useState<{ message: string; danger?: boolean; action: () => void } | null>(null);

  const [form, setForm] = useState({
    tenant_id: "",
    display_name: "Tenant primary DB",
    engine: "sqlite",
    host_mode: "local",
    cloud_provider: "",
    connection_url: "sqlite+pysqlite:///./tenant_demo.db",
    routing_policy: "bind_only",
  });

  const loadCore = useCallback(async () => {
    setCoreLoading(true);
    setCoreErr(null);
    try {
      const [ov, ds, tn] = await Promise.all([
        apiGet("/api/v1/platform/ops/overview"),
        apiGet("/api/v1/platform/ops/datastores"),
        apiGet("/api/v1/platform/tenants"),
      ]);
      setOverview(ov);
      setBindings(ds);
      setTenants(tn);
      if (!form.tenant_id && tn?.[0]?.id) {
        setForm((f) => ({ ...f, tenant_id: String(tn[0].id) }));
      }
    } catch (ex) {
      setCoreErr(msgOf(ex));
    } finally {
      setCoreLoading(false);
    }
  }, [form.tenant_id]);

  useEffect(() => {
    loadCore();
  }, [loadCore]);

  const loadSteps = useCallback(async () => {
    setStepsErr(null);
    try {
      setSteps(await apiGet("/api/v1/platform/ops/init/steps"));
    } catch (ex) {
      setStepsErr(msgOf(ex));
    }
  }, []);

  const loadProfiles = useCallback(async () => {
    setProfilesErr(null);
    try {
      setProfiles(await apiGet("/api/v1/platform/ops/deploy/profiles"));
    } catch (ex) {
      setProfilesErr(msgOf(ex));
    }
  }, []);

  const loadMonitor = useCallback(async () => {
    setMonitorErr(null);
    try {
      const [a, s] = await Promise.all([
        apiGet("/api/v1/platform/ops/monitor/alerts"),
        apiGet("/api/v1/platform/ops/monitor/snapshot"),
      ]);
      setAlerts(a);
      setSnapshot(s);
    } catch (ex) {
      setMonitorErr(msgOf(ex));
    }
  }, []);

  useEffect(() => {
    if (tab === "init") loadSteps();
    if (tab === "deploy") loadProfiles();
    if (tab === "monitor") loadMonitor();
  }, [tab, loadSteps, loadProfiles, loadMonitor]);

  const tabs = useMemo(
    () => [
      { key: "datasource" as Tab, label: t("page.ops.tab.ds", "Runtime datasource") },
      { key: "tenants" as Tab, label: t("page.ops.tab.tenant", "Tenant DB bindings") },
      { key: "init" as Tab, label: t("page.ops.tab.init", "System init") },
      { key: "deploy" as Tab, label: t("page.ops.tab.deploy", "Deploy profiles") },
      { key: "monitor" as Tab, label: t("page.ops.tab.monitor", "Monitor & alerts") },
    ],
    [t],
  );

  function openCreate() {
    setBindingOpen(true);
    if (tab !== "tenants") setTab("tenants");
  }

  useListHotkeys(openCreate);

  async function onCreateBinding(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg("");
    try {
      await apiPost("/api/v1/platform/ops/datastores", {
        tenant_id: form.tenant_id,
        purpose: "primary",
        engine: form.engine,
        host_mode: form.host_mode,
        cloud_provider: form.cloud_provider || null,
        display_name: form.display_name,
        connection_url: form.connection_url,
        routing_policy: form.routing_policy,
      });
      setMsg(t("page.ops.saved", "Binding saved (connection string stored encrypted)"));
      setBindingOpen(false);
      await loadCore();
    } catch (err) {
      setMsg(msgOf(err, t("page.ops.save_fail", "Save failed")));
    } finally {
      setBusy(false);
    }
  }

  const testBinding = useCallback(async (id: string) => {
    setBusy(true);
    try {
      const r = await apiPost(`/api/v1/platform/ops/datastores/${id}/test`);
      setMsg(
        r.ok
          ? t("page.ops.test_ok", "Connected OK ({ms} ms)", { ms: r.elapsed_ms })
          : t("page.ops.test_fail", "Failed: {msg}", { msg: r.message }),
      );
      await loadCore();
    } catch (err) {
      setMsg(msgOf(err, t("page.ops.test_fail_generic", "Test failed")));
    } finally {
      setBusy(false);
    }
  }, [loadCore, t]);

  const removeBinding = useCallback(async (id: string) => {
    setBusy(true);
    try {
      await apiDelete(`/api/v1/platform/ops/datastores/${id}`);
      setMsg(t("page.ops.deleted", "Binding deleted"));
      await loadCore();
    } catch (err) {
      setMsg(msgOf(err, t("page.ops.delete_fail", "Delete failed")));
    } finally {
      setBusy(false);
    }
  }, [loadCore, t]);

  /** 删除租户 DB 绑定 —— 不可逆，先二次确认（指名对象） */
  const askRemoveBinding = useCallback((row: Record<string, unknown>) => {
    setPending({
      message: t(
        "page.ops.confirm_delete_binding",
        "删除租户 DB 绑定「{name}」？该绑定将被解除，删除后不可恢复。",
        { name: String(row.display_name || row.id) },
      ),
      danger: true,
      action: () => {
        removeBinding(String(row.id)).catch((ex) => setMsg(msgOf(ex, t("page.ops.delete_fail", "Delete failed"))));
      },
    });
  }, [removeBinding, t]);

  /** 执行初始化步骤 —— 会写库，先二次确认（指名步骤） */
  function askRunStep(step: Record<string, unknown>) {
    setPending({
      message: t(
        "page.ops.confirm_run_step",
        "执行初始化步骤「{title}」？该步骤会在平台库执行写操作，可能改动现有对象。",
        { title: String(step.title || step.id) },
      ),
      danger: true,
      action: () => {
        runStep(String(step.id)).catch((ex) => setMsg(msgOf(ex, t("page.ops.run_fail", "Run failed"))));
      },
    });
  }

  async function runStep(id: string) {
    setBusy(true);
    try {
      const r = await apiPost(`/api/v1/platform/ops/init/steps/${id}/run`);
      setMsg(`${r.title}: ${r.last_result?.message || r.status}`);
      setSteps(await apiGet("/api/v1/platform/ops/init/steps"));
    } catch (err) {
      setMsg(msgOf(err, t("page.ops.run_fail", "Run failed")));
    } finally {
      setBusy(false);
    }
  }

  async function applyProfile(id: string) {
    setBusy(true);
    try {
      const r = await apiPost(`/api/v1/platform/ops/deploy/profiles/${id}/apply`);
      setMsg(r.apply_log?.message || t("page.ops.deploy_guide", "Deployment guide generated"));
      setProfiles(await apiGet("/api/v1/platform/ops/deploy/profiles"));
    } catch (err) {
      setMsg(msgOf(err, t("page.ops.apply_fail", "Apply failed")));
    } finally {
      setBusy(false);
    }
  }

  async function refreshMonitor() {
    setBusy(true);
    try {
      const s = await apiGet("/api/v1/platform/ops/monitor/snapshot");
      setSnapshot(s);
      setAlerts(await apiGet("/api/v1/platform/ops/monitor/alerts"));
      setMsg(t("page.ops.monitor_refreshed", "Monitor snapshot refreshed"));
    } catch (err) {
      setMsg(msgOf(err, t("page.ops.refresh_fail", "Refresh failed")));
    } finally {
      setBusy(false);
    }
  }

  const toggleAlert = useCallback(async (id: string, enabled: boolean) => {
    try {
      await apiPatch(`/api/v1/platform/ops/monitor/alerts/${id}`, { enabled: !enabled });
      setAlerts(await apiGet("/api/v1/platform/ops/monitor/alerts"));
    } catch (err) {
      setMsg(msgOf(err, t("page.ops.update_fail", "Update failed")));
    }
  }, [t]);

  // ── 告警行内编辑：值未变化不发请求 ──
  async function onAlertCellSave(rowId: string, colKey: string, value: unknown, row: AlertRow) {
    const src = row as unknown as Record<string, unknown>;
    let payload: Record<string, unknown>;
    if (colKey === "threshold") {
      const next = value === null || value === "" ? null : Number(value);
      // P1-24：非法输入不能静默丢弃 —— 明确告诉用户这一格没写进去
      if (next !== null && !Number.isFinite(next)) {
        toast.error(t("page.ops.err_numeric", {
          en: "{field} must be a valid number",
          zh: "{field} 必须是有效数字",
        }, { field: colKey }));
        return;
      }
      if (next === null) return;
      if (Number(src[colKey]) === next) return;
      payload = { threshold: next };
    } else {
      const next = value == null ? "" : String(value);
      if (String(src[colKey] ?? "") === next) return;
      payload = { [colKey]: next };
    }
    try {
      await apiPatch(`/api/v1/platform/ops/monitor/alerts/${rowId}`, payload);
      toast.success(t("common.saved", "Saved"));
      setAlerts(await apiGet("/api/v1/platform/ops/monitor/alerts"));
    } catch (ex) {
      toast.error(msgOf(ex, t("page.ops.update_fail", "Update failed")));
    }
  }

  const deleteAlert = useCallback(async (row: AlertRow) => {
    try {
      await apiDelete(`/api/v1/platform/ops/monitor/alerts/${row.id}`);
      toast.success(t("common.deleted", "Deleted"));
      setAlerts(await apiGet("/api/v1/platform/ops/monitor/alerts"));
    } catch (ex) {
      toast.error(msgOf(ex, t("page.ops.delete_fail", "Delete failed")));
    }
  }, [t, toast]);

  // ── 部署档案：表单编辑 + 删除（内置档案不可删） ──
  function openProfile(p: ProfileRow) {
    setProfileOpen(p);
    setProfileEdit({
      name: p.name || "",
      kind: p.kind || "",
      cloud_provider: p.cloud_provider || "",
      region: p.region || "",
      description: p.description || "",
    });
  }

  async function saveProfile(e: FormEvent) {
    e.preventDefault();
    if (!profileOpen) return;
    setProfileSaving(true);
    try {
      await apiPatch(`/api/v1/platform/ops/deploy/profiles/${profileOpen.id}`, {
        name: profileEdit.name,
        kind: profileEdit.kind,
        cloud_provider: profileEdit.cloud_provider || null,
        region: profileEdit.region || null,
        description: profileEdit.description || null,
      });
      toast.success(t("common.saved", "Saved"));
      setProfileOpen(null);
      setProfiles(await apiGet("/api/v1/platform/ops/deploy/profiles"));
    } catch (ex) {
      toast.error(msgOf(ex, t("page.ops.save_fail", "Save failed")));
    } finally {
      setProfileSaving(false);
    }
  }

  async function deleteProfile(p: ProfileRow) {
    try {
      await apiDelete(`/api/v1/platform/ops/deploy/profiles/${p.id}`);
      toast.success(t("common.deleted", "Deleted"));
      setProfileOpen(null);
      setProfiles(await apiGet("/api/v1/platform/ops/deploy/profiles"));
    } catch (ex) {
      toast.error(msgOf(ex, t("page.ops.delete_fail", "Delete failed")));
    }
  }

  const ds = (overview?.datasource || {}) as Record<string, unknown>;
  const caps = (overview?.capabilities || {}) as Record<string, unknown>;

  type OpsRow = Record<string, unknown>;

  const bindingColumns = useMemo<ColumnDef<OpsRow>[]>(() => [
    { key: "display_name", title: t("page.ops.col.name", "Name"), value: (r) => r.display_name },
    {
      key: "engine",
      title: t("page.ops.col.engine", "Engine"),
      value: (r) => `${String(r.engine)} / ${String(r.host_mode)}`,
      render: (v) => String(v),
    },
    {
      key: "cloud_provider",
      title: t("page.ops.col.form", "Form factor"),
      value: (r) => r.cloud_provider || "—",
    },
    {
      key: "connection_hint",
      title: t("page.ops.col.conn", "Masked connection"),
      value: (r) => r.connection_hint,
      render: (v) => <code>{String(v)}</code>,
    },
    {
      key: "status",
      title: t("common.status", "Status"),
      value: (r) =>
        `${String(r.status)}${r.last_test_ok === true ? " · OK" : r.last_test_ok === false ? " · Fail" : ""}`,
    },
    {
      key: "actions",
      title: t("common.actions", "Actions"),
      width: 150,
      render: (_v, row) => (
        <span style={{ whiteSpace: "nowrap" }}>
          <button type="button" className="btn" disabled={busy} onClick={() => testBinding(String(row.id))}>
            {t("common.test", "Test")}
          </button>{" "}
          <button type="button" className="btn" disabled={busy} onClick={() => askRemoveBinding(row)}>
            {t("common.delete", "Delete")}
          </button>
        </span>
      ),
    },
  ], [t, busy, testBinding, askRemoveBinding]);

  const metricColumns = useMemo<ColumnDef<OpsRow>[]>(() => [
    { key: "name", title: t("page.ops.col.metric", "Metric"), value: (r) => r.name },
    { key: "category", title: t("common.category", "Category"), value: (r) => r.category },
    { key: "value", title: t("common.value", "Value"), value: (r) => r.value, align: "right" },
    { key: "unit", title: t("page.ops.col.unit", "Unit"), value: (r) => r.unit },
  ], [t]);

  const alertColumns = useMemo<ColumnDef<AlertRow>[]>(() => [
    {
      key: "name",
      title: t("page.ops.col.name", "Name"),
      value: (r) => r.name,
      editor: { type: "text" },
    },
    { key: "metric_code", title: t("page.ops.col.metric", "Metric"), value: (r) => r.metric_code },
    {
      key: "operator",
      title: t("page.ops.col.operator", "Operator"),
      width: 90,
      value: (r) => r.operator,
      editor: {
        type: "select",
        options: ["gt", "gte", "lt", "lte", "eq", "ne"].map((op) => ({ value: op, label: op })),
      },
    },
    {
      key: "threshold",
      title: t("page.ops.col.threshold", "Threshold"),
      width: 110,
      align: "right",
      value: (r) => r.threshold,
      editor: { type: "number", step: 0.1 },
    },
    {
      key: "severity",
      title: t("page.ops.col.severity", "Severity"),
      width: 110,
      value: (r) => r.severity,
      editor: {
        type: "select",
        options: ["info", "warning", "critical"].map((s) => ({ value: s, label: s })),
      },
    },
    { key: "last_state", title: t("common.status", "Status"), width: 90, value: (r) => r.last_state },
    {
      key: "enabled",
      title: t("page.ops.col.enabled", "Enabled"),
      width: 90,
      render: (_v, row) => (
        <button type="button" className="btn" onClick={() => toggleAlert(String(row.id), Boolean(row.enabled))}>
          {row.enabled ? t("common.disable", "Disable") : t("common.enable", "Enable")}
        </button>
      ),
    },
    {
      key: "_actions",
      title: "",
      width: 30,
      align: "center",
      render: (_v, r) => <RowActions onDelete={() => deleteAlert(r)} label={r.name} />,
    },
  ], [t, toggleAlert, deleteAlert]);

  return (
    <AppShell>
      <PageHeader
        title={t("page.ops.title", "Platform data plane & deployment")}
        subtitle={t(
          "page.ops.sub",
          "Configure runtime datasource, tenant DB bindings, init wizard, deploy profiles and monitor alerts. Business sessions still use the platform primary DB; per-tenant engines are reserved.",
        )}
        breadcrumb={[{ label: t("page.platform.title", "Platform"), href: "/platform" }, { label: t("page.ops.title", "Platform data plane & deployment") }]}
        actions={<SavedViews storageKey="platform_ops" onApply={(qs) => router.replace(`${pathname}${qs}`)} />}
      />

      <Toolbar>
        <button type="button" className="btn btn-primary" onClick={openCreate}>
          {t("page.ops.bind_new", "New tenant DB binding")}
        </button>
        <RefreshButton label={t("common.refresh", "Refresh")} className="btn btn-sm" onClick={() => loadCore()} />
      </Toolbar>

      <Tabs
        items={tabs}
        value={tab}
        onChange={(k) => setTab(k as Tab)}
        variant="line"
      />

      {msg ? (
        <div className="panel" style={{ marginBottom: 12, color: "var(--text, inherit)" }}>
          {msg}
        </div>
      ) : null}

      {tab === "datasource" && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>{t("page.ops.runtime", "Current runtime")}</h3>
          {coreErr ? <p className="text-danger">{coreErr}</p> : null}
          <dl className="kv-grid">
            <div>
              <dt>{t("page.ops.dialect", "Dialect")}</dt>
              <dd className="kv">{String(ds.dialect ?? "—")}</dd>
            </div>
            <div>
              <dt>{t("page.ops.driver", "Driver")}</dt>
              <dd className="kv">{String(ds.driver ?? "—")}</dd>
            </div>
            <div>
              <dt>{t("page.ops.conn_masked", "Connection (masked)")}</dt>
              <dd className="kv">
                <code>{String(ds.url_masked ?? "—")}</code>
              </dd>
            </div>
            <div>
              <dt>{t("page.ops.multi_tenant", "Multi-tenant mode")}</dt>
              <dd className="kv">{String(ds.multi_tenant_mode ?? "—")}</dd>
            </div>
            <div>
              <dt>{t("page.ops.engine_routing", "Tenant engine routing")}</dt>
              <dd className="kv">{String(ds.tenant_engine_routing ?? "—")}</dd>
            </div>
            <div>
              <dt>{t("page.ops.notes", "Notes")}</dt>
              <dd className="kv">{String(ds.notes ?? "")}</dd>
            </div>
          </dl>
          <p style={{ fontSize: 13, opacity: 0.85 }}>
            {t("page.ops.capabilities", "Capabilities")}: {t("page.ops.cap_binding", "binding")} {caps.tenant_db_binding ? "✓" : "—"} ·{" "}
            {t("page.ops.cap_test", "connectivity test")} {caps.connectivity_test ? "✓" : "—"} ·{" "}
            {t("page.ops.cap_switch", "engine switch")} {caps.tenant_engine_switch ? "✓" : t("page.ops.cap_reserved", "reserved")}
          </p>
          <button
            type="button"
            className="btn"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                const r = await apiPost("/api/v1/platform/ops/datasource/test", {});
                setMsg(
                  r.ok
                    ? t("page.ops.primary_ok", "Primary DB connected ({ms} ms)", { ms: r.elapsed_ms })
                    : t("page.ops.primary_fail", "Primary DB probe failed: {msg}", { msg: r.message }),
                );
              } catch (err) {
                setMsg(msgOf(err, t("page.ops.update_fail", "Update failed")));
              } finally {
                setBusy(false);
              }
            }}
          >
            {t("page.ops.test_primary", "Test primary DB")}
          </button>
        </div>
      )}

      {tab === "tenants" && (
        <div style={{ display: "grid", gap: 16 }}>
          <div className="panel">
            <h3 style={{ marginTop: 0 }}>{t("page.ops.existing_bindings", "Existing bindings")}</h3>
            <StateView
              loading={coreLoading}
              error={coreErr ?? undefined}
              empty={!bindings.length}
              onRetry={() => loadCore()}
              emptyText={t("page.ops.no_bindings", "No tenant DB bindings yet.")}
            >
              <DataGrid
                columns={bindingColumns}
                data={bindings}
                rowKey={(r) => String(r.id)}
                storageKey="platform_ops_bindings"
                emptyText={t("common.empty", "No records")}
              />
            </StateView>
          </div>
        </div>
      )}

      {tab === "init" && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>{t("page.ops.init_title", "Init wizard")}</h3>
          <p className="page-sub">{t("page.ops.init_sub", "Run schema create, catalog seed, demo data and readiness checks step by step.")}</p>
          <StateView
            loading={false}
            error={stepsErr ?? undefined}
            empty={!steps.length}
            onRetry={() => loadSteps()}
            emptyText={t("page.ops.no_steps", "No init steps available.")}
          >
            <ol style={{ paddingLeft: 18 }}>
              {steps.map((s) => (
                <li key={String(s.id)} style={{ marginBottom: 12 }}>
                  <strong>{String(s.title)}</strong>{" "}
                  <span style={{ opacity: 0.75 }}>
                    [{String(s.status)}] {s.required ? t("page.ops.step_required", "required") : t("page.ops.step_optional", "optional")}
                  </span>
                  <div style={{ fontSize: 13 }}>{String(s.description || "")}</div>
                  {s.last_result && (s.last_result as any).message ? (
                    <div style={{ fontSize: 12, opacity: 0.8 }}>{t("page.ops.step_last", "Last")}: {String((s.last_result as any).message)}</div>
                  ) : null}
                  <button type="button" className="btn primary" disabled={busy} onClick={() => askRunStep(s)} style={{ marginTop: 6 }}>
                    {t("page.ops.step_run", "Run")}
                  </button>
                </li>
              ))}
            </ol>
          </StateView>
        </div>
      )}

      {tab === "deploy" && (
        <StateView
          loading={false}
          error={profilesErr ?? undefined}
          empty={!profiles.length}
          onRetry={() => loadProfiles()}
          emptyText={t("page.ops.no_profiles", "No deploy profiles available.")}
        >
          <div className="workbench-grid">
            {profiles.map((p) => (
              <div key={String(p.id)} className="wb-tile" style={{ cursor: "default" }}>
                <h3>{String(p.name)}</h3>
                <p>{String(p.description || "")}</p>
                <div style={{ fontSize: 12, opacity: 0.8 }}>
                  {String(p.kind)}
                  {p.cloud_provider ? ` · ${String(p.cloud_provider)}` : ""}
                  {p.region ? ` · ${String(p.region)}` : ""}
                  {p.is_builtin ? ` · ${t("page.ops.builtin", "built-in")}` : ""}
                </div>
                <ul style={{ fontSize: 13, paddingLeft: 18 }}>
                  {(((p.template as any)?.steps as string[]) || []).slice(0, 4).map((step, i) => (
                    <li key={i}>{step}</li>
                  ))}
                  {(((p.template as any)?.steps as string[]) || []).length > 4 ? (
                    <li className="muted">
                      {t("page.ops.more_steps", "+{n} more steps", {
                        n: String((((p.template as any)?.steps as string[]) || []).length - 4),
                      })}
                    </li>
                  ) : null}
                </ul>
                <div className="form-actions">
                  <button type="button" className="btn primary" disabled={busy} onClick={() => applyProfile(p.id)}>
                    {t("page.ops.gen_guide", "Generate deploy guide")}
                  </button>
                  <button type="button" className="btn" onClick={() => openProfile(p)}>
                    {t("common.edit", "Edit")}
                  </button>
                </div>
                {p.last_applied_at ? (
                  <div style={{ fontSize: 12, marginTop: 8 }}>{t("page.ops.step_last", "Last")}: {String(p.last_applied_at)}</div>
                ) : null}
              </div>
            ))}
          </div>
        </StateView>
      )}

      {tab === "monitor" && (
        <div style={{ display: "grid", gap: 16 }}>
          <div className="panel">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h3 style={{ margin: 0 }}>{t("page.ops.snapshot", "Resource & metric snapshot")}</h3>
              <button type="button" className="btn" disabled={busy} onClick={refreshMonitor}>
                {t("common.refresh", "Refresh")}
              </button>
            </div>
            {snapshot ? (
              <>
                <p className="page-sub">
                  {String(snapshot.host)} · {String(snapshot.platform)} · {String(snapshot.captured_at)}
                </p>
                <DataGrid
                  columns={metricColumns}
                  data={((snapshot.metrics as OpsRow[]) || []).map((m) => ({ ...m, id: m.code }))}
                  rowKey={(r) => String(r.id)}
                  storageKey="platform_ops_metrics"
                  emptyText={t("common.empty", "No records")}
                />
                {((snapshot.alerts_firing as any[]) || []).length > 0 ? (
                  <p style={{ color: "#b45309" }}>
                    {t("page.ops.firing", "Firing")}:{" "}
                    {((snapshot.alerts_firing as any[]) || []).map((a) => a.name).join("、")}
                  </p>
                ) : (
                  <p className="page-sub">{t("page.ops.no_firing", "No alerts firing.")}</p>
                )}
              </>
            ) : (
              <p className="page-sub">{t("common.loading", "Loading…")}</p>
            )}
          </div>
          <div className="panel">
            <h3 style={{ marginTop: 0 }}>{t("page.ops.alert_rules", "Alert rules")}</h3>
            <StateView
              loading={false}
              error={monitorErr ?? undefined}
              empty={!alerts.length}
              onRetry={() => loadMonitor()}
              emptyText={t("page.ops.no_alerts", "No alert rules.")}
            >
              <DataGrid
                columns={alertColumns}
                data={alerts}
                rowKey={(r) => String(r.id)}
                storageKey="platform_ops_alerts"
                emptyText={t("common.empty", "No records")}
                editable
                onCellSave={onAlertCellSave}
              />
            </StateView>
          </div>
        </div>
      )}

      <RecordModal
        open={Boolean(profileOpen)}
        title={t("page.ops.edit_profile", "Edit deploy profile")}
        onClose={() => setProfileOpen(null)}
        onSave={saveProfile}
        saving={profileSaving}
        // 内置档案后端 IN_USE 409，隐藏删除
        canDelete={!profileOpen?.is_builtin}
        onDelete={profileOpen ? () => deleteProfile(profileOpen) : undefined}
      >
        <div className="form-grid">
          <label>
            {t("common.name", "Name")}
            <input value={profileEdit.name} onChange={(e) => setProfileEdit({ ...profileEdit, name: e.target.value })} required />
          </label>
          <label>
            {t("page.ops.field_kind", "Kind")}
            <input value={profileEdit.kind} onChange={(e) => setProfileEdit({ ...profileEdit, kind: e.target.value })} required />
          </label>
          <label>
            {t("page.ops.field_cloud", "Cloud provider (optional)")}
            <input value={profileEdit.cloud_provider} onChange={(e) => setProfileEdit({ ...profileEdit, cloud_provider: e.target.value })} />
          </label>
          <label>
            {t("page.ops.field_region", "Region")}
            <input value={profileEdit.region} onChange={(e) => setProfileEdit({ ...profileEdit, region: e.target.value })} />
          </label>
          <label>
            {t("page.ops.field_desc", "Description")}
            <input value={profileEdit.description} onChange={(e) => setProfileEdit({ ...profileEdit, description: e.target.value })} />
          </label>
        </div>
      </RecordModal>

      <RecordModal
        open={bindingOpen}
        title={t("page.ops.bind_new", "New tenant DB binding")}
        onClose={() => setBindingOpen(false)}
        onSave={onCreateBinding}
        saving={busy}
        canDelete={false}
      >
        <div className="form-grid">
          <label>
            {t("page.ops.field_tenant", "Tenant")}
            <select
              value={form.tenant_id}
              onChange={(e) => setForm({ ...form, tenant_id: e.target.value })}
              required
            >
              <option value="">{t("page.ops.pick_tenant", "Select tenant")}</option>
              {tenants.map((tn) => (
                <option key={String(tn.id)} value={String(tn.id)}>
                  {String(tn.code)} — {String(tn.name)}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("page.ops.field_display_name", "Display name")}
            <input
              value={form.display_name}
              onChange={(e) => setForm({ ...form, display_name: e.target.value })}
              required
            />
          </label>
          <label>
            {t("page.ops.field_engine", "Engine")}
            <select value={form.engine} onChange={(e) => setForm({ ...form, engine: e.target.value })}>
              <option value="sqlite">{t("page.ops.engine_sqlite", "SQLite (local)")}</option>
              <option value="postgres">PostgreSQL</option>
              <option value="mysql">MySQL</option>
              <option value="cloud_rds">{t("page.ops.engine_rds", "Cloud RDS")}</option>
            </select>
          </label>
          <label>
            {t("page.ops.field_host_mode", "Host mode")}
            <select value={form.host_mode} onChange={(e) => setForm({ ...form, host_mode: e.target.value })}>
              <option value="local">{t("page.ops.host_local", "Local file / machine")}</option>
              <option value="server">{t("page.ops.host_server", "Database server")}</option>
              <option value="cloud">{t("page.ops.host_cloud", "Cloud database")}</option>
            </select>
          </label>
          <label>
            {t("page.ops.field_cloud", "Cloud provider (optional)")}
            <select
              value={form.cloud_provider}
              onChange={(e) => setForm({ ...form, cloud_provider: e.target.value })}
            >
              <option value="">{t("common.none", "None")}</option>
              <option value="aliyun">Alibaba Cloud</option>
              <option value="tencent">Tencent Cloud</option>
              <option value="huawei">Huawei Cloud</option>
              <option value="aws">AWS</option>
              <option value="azure">Azure</option>
            </select>
          </label>
          <label>
            {t("page.ops.field_routing", "Routing policy")}
            <select
              value={form.routing_policy}
              onChange={(e) => setForm({ ...form, routing_policy: e.target.value })}
            >
              <option value="bind_only">{t("page.ops.route_bind", "Bind only")}</option>
              <option value="prefer_tenant">{t("page.ops.route_prefer", "Prefer tenant DB (reserved)")}</option>
              <option value="force_tenant">{t("page.ops.route_force", "Force tenant DB (reserved, falls back to primary)")}</option>
            </select>
          </label>
          <label style={{ gridColumn: "1 / -1" }}>
            {t("page.ops.field_conn", "Connection string")}
            <input
              value={form.connection_url}
              onChange={(e) => setForm({ ...form, connection_url: e.target.value })}
              required
              placeholder="postgresql+psycopg://user:pass@host:5432/db"
            />
          </label>
        </div>
      </RecordModal>

      <ConfirmDialog
        open={Boolean(pending)}
        title={t("common.confirm", "Confirm")}
        message={pending?.message || ""}
        danger={pending?.danger}
        onConfirm={() => {
          const fn = pending?.action;
          setPending(null);
          fn?.();
        }}
        onCancel={() => setPending(null)}
      />
    </AppShell>
  );
}

// Next 16: useSearchParams（useListQuery）须位于 Suspense 边界内
export default function Page() {
  return (
    <Suspense fallback={null}>
      <PlatformOpsPage />
    </Suspense>
  );
}
