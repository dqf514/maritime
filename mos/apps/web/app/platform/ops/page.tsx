"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiPatch, apiPost, apiDelete } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Tab = "datasource" | "tenants" | "init" | "deploy" | "monitor";

export default function PlatformOpsPage() {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>("datasource");
  const [overview, setOverview] = useState<Record<string, unknown> | null>(null);
  const [bindings, setBindings] = useState<Array<Record<string, unknown>>>([]);
  const [tenants, setTenants] = useState<Array<Record<string, unknown>>>([]);
  const [steps, setSteps] = useState<Array<Record<string, unknown>>>([]);
  const [profiles, setProfiles] = useState<Array<Record<string, unknown>>>([]);
  const [alerts, setAlerts] = useState<Array<Record<string, unknown>>>([]);
  const [snapshot, setSnapshot] = useState<Record<string, unknown> | null>(null);
  const [msg, setMsg] = useState<string>("");
  const [busy, setBusy] = useState(false);

  const [form, setForm] = useState({
    tenant_id: "",
    display_name: "租户主库",
    engine: "sqlite",
    host_mode: "local",
    cloud_provider: "",
    connection_url: "sqlite+pysqlite:///./tenant_demo.db",
    routing_policy: "bind_only",
  });

  const loadCore = useCallback(async () => {
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
  }, [form.tenant_id]);

  useEffect(() => {
    loadCore().catch((e) => setMsg(String(e.message || e)));
  }, [loadCore]);

  useEffect(() => {
    if (tab === "init") {
      apiGet("/api/v1/platform/ops/init/steps").then(setSteps).catch(() => setSteps([]));
    }
    if (tab === "deploy") {
      apiGet("/api/v1/platform/ops/deploy/profiles").then(setProfiles).catch(() => setProfiles([]));
    }
    if (tab === "monitor") {
      Promise.all([apiGet("/api/v1/platform/ops/monitor/alerts"), apiGet("/api/v1/platform/ops/monitor/snapshot")])
        .then(([a, s]) => {
          setAlerts(a);
          setSnapshot(s);
        })
        .catch(() => undefined);
    }
  }, [tab]);

  const tabs: { id: Tab; label: string }[] = [
    { id: "datasource", label: t("page.ops.tab.ds", "运行时数据源") },
    { id: "tenants", label: t("page.ops.tab.tenant", "租户库绑定") },
    { id: "init", label: t("page.ops.tab.init", "系统初始化") },
    { id: "deploy", label: t("page.ops.tab.deploy", "部署档案") },
    { id: "monitor", label: t("page.ops.tab.monitor", "监控与预警") },
  ];

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
      setMsg(t("page.ops.saved", "已保存绑定（连接串已加密存储）"));
      await loadCore();
    } catch (err: any) {
      setMsg(err?.detail?.message || err.message || "保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function testBinding(id: string) {
    setBusy(true);
    try {
      const r = await apiPost(`/api/v1/platform/ops/datastores/${id}/test`);
      setMsg(r.ok ? `连通正常（${r.elapsed_ms} ms）` : `失败：${r.message}`);
      await loadCore();
    } catch (err: any) {
      setMsg(err?.detail?.message || err.message || "测试失败");
    } finally {
      setBusy(false);
    }
  }

  async function removeBinding(id: string) {
    setBusy(true);
    try {
      await apiDelete(`/api/v1/platform/ops/datastores/${id}`);
      setMsg("已删除绑定");
      await loadCore();
    } catch (err: any) {
      setMsg(err.message || "删除失败");
    } finally {
      setBusy(false);
    }
  }

  async function runStep(id: string) {
    setBusy(true);
    try {
      const r = await apiPost(`/api/v1/platform/ops/init/steps/${id}/run`);
      setMsg(`${r.title}: ${r.last_result?.message || r.status}`);
      setSteps(await apiGet("/api/v1/platform/ops/init/steps"));
    } catch (err: any) {
      setMsg(err?.detail?.message || err.message || "执行失败");
    } finally {
      setBusy(false);
    }
  }

  async function applyProfile(id: string) {
    setBusy(true);
    try {
      const r = await apiPost(`/api/v1/platform/ops/deploy/profiles/${id}/apply`);
      setMsg(r.apply_log?.message || "已生成部署指引");
      setProfiles(await apiGet("/api/v1/platform/ops/deploy/profiles"));
    } catch (err: any) {
      setMsg(err?.detail?.message || err.message || "应用失败");
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
      setMsg("监控快照已刷新");
    } catch (err: any) {
      setMsg(err.message || "刷新失败");
    } finally {
      setBusy(false);
    }
  }

  async function toggleAlert(id: string, enabled: boolean) {
    try {
      await apiPatch(`/api/v1/platform/ops/monitor/alerts/${id}`, { enabled: !enabled });
      setAlerts(await apiGet("/api/v1/platform/ops/monitor/alerts"));
    } catch (err: any) {
      setMsg(err.message || "更新失败");
    }
  }

  const ds = (overview?.datasource || {}) as Record<string, unknown>;
  const caps = (overview?.capabilities || {}) as Record<string, unknown>;

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.ops.title", "平台数据面与部署")}</h1>
          <p className="page-sub">
            {t(
              "page.ops.sub",
              "配置运行时数据源、租户库绑定、初始化向导、部署档案与监控预警。业务会话当前仍使用平台主库；租户独立引擎已预留。"
            )}
          </p>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
        {tabs.map((x) => (
          <button
            key={x.id}
            type="button"
            className={tab === x.id ? "btn primary" : "btn"}
            onClick={() => setTab(x.id)}
          >
            {x.label}
          </button>
        ))}
      </div>

      {msg ? (
        <div className="panel" style={{ marginBottom: 12, color: "var(--text, inherit)" }}>
          {msg}
        </div>
      ) : null}

      {tab === "datasource" && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>{t("page.ops.runtime", "当前运行时")}</h3>
          <dl className="kv-grid">
            <div>
              <dt>方言</dt>
              <dd className="kv">{String(ds.dialect ?? "—")}</dd>
            </div>
            <div>
              <dt>驱动</dt>
              <dd className="kv">{String(ds.driver ?? "—")}</dd>
            </div>
            <div>
              <dt>连接（脱敏）</dt>
              <dd className="kv">
                <code>{String(ds.url_masked ?? "—")}</code>
              </dd>
            </div>
            <div>
              <dt>多租户模式</dt>
              <dd className="kv">{String(ds.multi_tenant_mode ?? "—")}</dd>
            </div>
            <div>
              <dt>租户引擎路由</dt>
              <dd className="kv">{String(ds.tenant_engine_routing ?? "—")}</dd>
            </div>
            <div>
              <dt>说明</dt>
              <dd className="kv">{String(ds.notes ?? "")}</dd>
            </div>
          </dl>
          <p style={{ fontSize: 13, opacity: 0.85 }}>
            能力：绑定 {caps.tenant_db_binding ? "✓" : "—"} · 连通测试 {caps.connectivity_test ? "✓" : "—"} ·
            独立引擎切换 {caps.tenant_engine_switch ? "✓" : "预留"}
          </p>
          <button
            type="button"
            className="btn"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                const r = await apiPost("/api/v1/platform/ops/datasource/test", {});
                setMsg(r.ok ? `主库连通正常（${r.elapsed_ms} ms）` : `主库探测失败：${r.message}`);
              } catch (err: any) {
                setMsg(err?.detail?.message || err.message);
              } finally {
                setBusy(false);
              }
            }}
          >
            {t("page.ops.test_primary", "测试主库连通")}
          </button>
        </div>
      )}

      {tab === "tenants" && (
        <div style={{ display: "grid", gap: 16 }}>
          <form className="panel" onSubmit={onCreateBinding}>
            <h3 style={{ marginTop: 0 }}>{t("page.ops.bind_new", "新建 / 更新租户库绑定")}</h3>
            <div className="form-grid">
              <label>
                租户
                <select
                  value={form.tenant_id}
                  onChange={(e) => setForm({ ...form, tenant_id: e.target.value })}
                  required
                >
                  <option value="">选择租户</option>
                  {tenants.map((tn) => (
                    <option key={String(tn.id)} value={String(tn.id)}>
                      {String(tn.code)} — {String(tn.name)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                显示名
                <input
                  value={form.display_name}
                  onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                  required
                />
              </label>
              <label>
                引擎
                <select value={form.engine} onChange={(e) => setForm({ ...form, engine: e.target.value })}>
                  <option value="sqlite">SQLite（本地）</option>
                  <option value="postgres">PostgreSQL</option>
                  <option value="mysql">MySQL</option>
                  <option value="cloud_rds">云托管 RDS</option>
                </select>
              </label>
              <label>
                部署形态
                <select value={form.host_mode} onChange={(e) => setForm({ ...form, host_mode: e.target.value })}>
                  <option value="local">本地文件 / 本机</option>
                  <option value="server">数据库服务器</option>
                  <option value="cloud">主流云数据库</option>
                </select>
              </label>
              <label>
                云厂商（可选）
                <select
                  value={form.cloud_provider}
                  onChange={(e) => setForm({ ...form, cloud_provider: e.target.value })}
                >
                  <option value="">无</option>
                  <option value="aliyun">阿里云</option>
                  <option value="tencent">腾讯云</option>
                  <option value="huawei">华为云</option>
                  <option value="aws">AWS</option>
                  <option value="azure">Azure</option>
                </select>
              </label>
              <label>
                路由策略
                <select
                  value={form.routing_policy}
                  onChange={(e) => setForm({ ...form, routing_policy: e.target.value })}
                >
                  <option value="bind_only">仅绑定登记</option>
                  <option value="prefer_tenant">优先租户库（预留）</option>
                  <option value="force_tenant">强制租户库（预留，当前仍回落主库）</option>
                </select>
              </label>
              <label style={{ gridColumn: "1 / -1" }}>
                连接串
                <input
                  value={form.connection_url}
                  onChange={(e) => setForm({ ...form, connection_url: e.target.value })}
                  required
                  placeholder="postgresql+psycopg://user:pass@host:5432/db"
                />
              </label>
            </div>
            <button type="submit" className="btn primary" disabled={busy} style={{ marginTop: 12 }}>
              保存绑定
            </button>
          </form>

          <div className="panel">
            <h3 style={{ marginTop: 0 }}>已有绑定</h3>
            {bindings.length === 0 ? (
              <p className="page-sub">暂无租户库绑定。</p>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>名称</th>
                    <th>引擎</th>
                    <th>形态</th>
                    <th>脱敏连接</th>
                    <th>状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {bindings.map((b) => (
                    <tr key={String(b.id)}>
                      <td>{String(b.display_name)}</td>
                      <td>
                        {String(b.engine)} / {String(b.host_mode)}
                      </td>
                      <td>{String(b.cloud_provider || "—")}</td>
                      <td>
                        <code>{String(b.connection_hint)}</code>
                      </td>
                      <td>
                        {String(b.status)}
                        {b.last_test_ok === true ? " · OK" : b.last_test_ok === false ? " · Fail" : ""}
                      </td>
                      <td style={{ whiteSpace: "nowrap" }}>
                        <button type="button" className="btn" disabled={busy} onClick={() => testBinding(String(b.id))}>
                          测试
                        </button>{" "}
                        <button type="button" className="btn" disabled={busy} onClick={() => removeBinding(String(b.id))}>
                          删除
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {tab === "init" && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>{t("page.ops.init_title", "初始化向导")}</h3>
          <p className="page-sub">按步骤执行建表、目录种子、演示数据与就绪检查。</p>
          <ol style={{ paddingLeft: 18 }}>
            {steps.map((s) => (
              <li key={String(s.id)} style={{ marginBottom: 12 }}>
                <strong>{String(s.title)}</strong>{" "}
                <span style={{ opacity: 0.75 }}>
                  [{String(s.status)}] {s.required ? "必选" : "可选"}
                </span>
                <div style={{ fontSize: 13 }}>{String(s.description || "")}</div>
                {s.last_result && (s.last_result as any).message ? (
                  <div style={{ fontSize: 12, opacity: 0.8 }}>上次：{String((s.last_result as any).message)}</div>
                ) : null}
                <button type="button" className="btn primary" disabled={busy} onClick={() => runStep(String(s.id))} style={{ marginTop: 6 }}>
                  执行
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}

      {tab === "deploy" && (
        <div className="workbench-grid">
          {profiles.map((p) => (
            <div key={String(p.id)} className="wb-tile" style={{ cursor: "default" }}>
              <h3>{String(p.name)}</h3>
              <p>{String(p.description || "")}</p>
              <div style={{ fontSize: 12, opacity: 0.8 }}>
                {String(p.kind)}
                {p.cloud_provider ? ` · ${String(p.cloud_provider)}` : ""}
                {p.region ? ` · ${String(p.region)}` : ""}
              </div>
              <ul style={{ fontSize: 13, paddingLeft: 18 }}>
                {(((p.template as any)?.steps as string[]) || []).slice(0, 4).map((step, i) => (
                  <li key={i}>{step}</li>
                ))}
              </ul>
              <button type="button" className="btn primary" disabled={busy} onClick={() => applyProfile(String(p.id))}>
                生成部署指引
              </button>
              {p.last_applied_at ? (
                <div style={{ fontSize: 12, marginTop: 8 }}>上次：{String(p.last_applied_at)}</div>
              ) : null}
            </div>
          ))}
        </div>
      )}

      {tab === "monitor" && (
        <div style={{ display: "grid", gap: 16 }}>
          <div className="panel">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h3 style={{ margin: 0 }}>资源与指标快照</h3>
              <button type="button" className="btn" disabled={busy} onClick={refreshMonitor}>
                刷新
              </button>
            </div>
            {snapshot ? (
              <>
                <p className="page-sub">
                  {String(snapshot.host)} · {String(snapshot.platform)} · {String(snapshot.captured_at)}
                </p>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>指标</th>
                      <th>分类</th>
                      <th>值</th>
                      <th>单位</th>
                    </tr>
                  </thead>
                  <tbody>
                    {((snapshot.metrics as any[]) || []).map((m) => (
                      <tr key={m.code}>
                        <td>{m.name}</td>
                        <td>{m.category}</td>
                        <td>{m.value}</td>
                        <td>{m.unit}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {((snapshot.alerts_firing as any[]) || []).length > 0 ? (
                  <p style={{ color: "#b45309" }}>
                    触发中：
                    {((snapshot.alerts_firing as any[]) || []).map((a) => a.name).join("、")}
                  </p>
                ) : (
                  <p className="page-sub">当前无触发预警。</p>
                )}
              </>
            ) : (
              <p className="page-sub">加载中…</p>
            )}
          </div>
          <div className="panel">
            <h3 style={{ marginTop: 0 }}>预警规则</h3>
            <table className="data-table">
              <thead>
                <tr>
                  <th>名称</th>
                  <th>指标</th>
                  <th>条件</th>
                  <th>级别</th>
                  <th>状态</th>
                  <th>启用</th>
                </tr>
              </thead>
              <tbody>
                {alerts.map((a) => (
                  <tr key={String(a.id)}>
                    <td>{String(a.name)}</td>
                    <td>{String(a.metric_code)}</td>
                    <td>
                      {String(a.operator)} {String(a.threshold)}
                    </td>
                    <td>{String(a.severity)}</td>
                    <td>{String(a.last_state)}</td>
                    <td>
                      <button type="button" className="btn" onClick={() => toggleAlert(String(a.id), Boolean(a.enabled))}>
                        {a.enabled ? "关闭" : "开启"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </AppShell>
  );
}
