"use client";

// AI Settings — 供应商 / 模型设置 / 技能绑定 / 用量 四标签工作区
// Tab1 Providers: DataGrid + RecordModal CRUD + Test Connection
// Tab2 Model Settings: 全局默认 + 按 agent 覆盖 + Available Models
// Tab3 Skill Bindings: skill → primary/fallback provider
// Tab4 Usage: token 用量看板（by agent / conversation / day）

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { FormPanel, FormSection, FieldRow } from "@/components/form/FormPanel";
import { apiGet, apiPost, apiPatch, apiDelete, apiPut } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type Provider = {
  id: string;
  name: string;
  provider_type: string;
  base_url: string | null;
  model_default: string | null;
  secret_ref?: string | null;
  status: string;
  temperature?: number | null;
  max_tokens?: number | null;
  config?: Record<string, unknown> | null;
};

type ProviderForm = {
  name: string;
  provider_type: string;
  base_url: string;
  api_key: string;
  model_default: string;
  temperature: string;
  max_tokens: string;
};

type TestResult = {
  provider_name: string;
  ok: boolean;
  latency_ms: number | null;
  models: string[];
  model: string | null;
  message: string;
  tested_at: string;
};

type ModelEntry = { provider_id?: string; provider_name?: string; models: string[] };
type ModelsResponse = {
  defaults?: { model?: string; temperature?: number; max_tokens?: number; timeout_s?: number };
  providers?: ModelEntry[];
};

type AgentRow = {
  agent_name: string;
  display_name: string;
  model_name: string;
  description?: string | null;
};

type UsageRow = {
  key: string;
  label?: string | null;
  requests?: number | null;
  tokens_in?: number | null;
  tokens_out?: number | null;
  tokens_total?: number | null;
  cost_usd?: number | null;
  avg_latency_ms?: number | null;
};

type UsageResponse = {
  by_agent?: UsageRow[];
  by_conversation?: UsageRow[];
  by_day?: UsageRow[];
  totals?: { requests?: number; tokens_total?: number; cost_usd?: number };
};

type Skill = { skill_code: string; module: string; description: string };
type Binding = {
  id?: string;
  skill_code: string;
  primary_provider_id: string | null;
  fallback_provider_id: string | null;
  params: Record<string, unknown>;
  enabled: boolean;
};

type Tab = "providers" | "models" | "skills" | "usage";

const PROVIDER_TYPES = ["anthropic", "openai", "ollama"];

const EMPTY_FORM: ProviderForm = {
  name: "",
  provider_type: "anthropic",
  base_url: "",
  api_key: "",
  model_default: "",
  temperature: "0.7",
  max_tokens: "4096",
};

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function fmtNum(v: unknown, digits = 0): string {
  const n = num(v);
  if (n === null) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export default function AiSettingsPage() {
  const { t } = useI18n();
  const toast = useToast();

  const [tab, setTab] = useState<Tab>("providers");

  // —— providers ——
  const [providers, setProviders] = useState<Provider[]>([]);
  const [providersLoading, setProvidersLoading] = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Provider | null>(null);
  const [form, setForm] = useState<ProviderForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);

  // —— model settings ——
  const [globalModel, setGlobalModel] = useState("");
  const [globalTemp, setGlobalTemp] = useState("0.7");
  const [globalMaxTokens, setGlobalMaxTokens] = useState("4096");
  const [globalTimeout, setGlobalTimeout] = useState("60");
  const [agents, setAgents] = useState<AgentRow[]>([]);
  const [agentSel, setAgentSel] = useState("");
  const [agentModel, setAgentModel] = useState("");
  const [agentTemp, setAgentTemp] = useState("");
  const [modelEntries, setModelEntries] = useState<ModelEntry[]>([]);
  const [savingModels, setSavingModels] = useState(false);

  // —— skill bindings ——
  const [skills, setSkills] = useState<Skill[]>([]);
  const [bindings, setBindings] = useState<Binding[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [bindOpen, setBindOpen] = useState(false);
  const [bindSkill, setBindSkill] = useState<Skill | null>(null);
  const [bindPrimary, setBindPrimary] = useState("");
  const [bindFallback, setBindFallback] = useState("");
  const [bindParams, setBindParams] = useState("{}");
  const [bindEnabled, setBindEnabled] = useState(true);

  // —— usage ——
  const [usage, setUsage] = useState<UsageResponse | null>(null);
  const [usageLoading, setUsageLoading] = useState(false);

  // ============================== providers ==============================

  const loadProviders = useCallback(async () => {
    setProvidersLoading(true);
    try {
      const data = await apiGet("/api/v1/settings/ai/providers");
      setProviders(Array.isArray(data) ? data : []);
    } catch {
      setProviders([]);
    }
    setProvidersLoading(false);
  }, []);

  useEffect(() => {
    loadProviders();
  }, [loadProviders]);

  function openCreate() {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormOpen(true);
  }

  function openEdit(p: Provider) {
    setEditing(p);
    const cfg = (p.config ?? {}) as Record<string, unknown>;
    setForm({
      name: p.name,
      provider_type: p.provider_type,
      base_url: p.base_url ?? "",
      api_key: "",
      model_default: p.model_default ?? "",
      temperature: String(p.temperature ?? cfg.temperature ?? "0.7"),
      max_tokens: String(p.max_tokens ?? cfg.max_tokens ?? "4096"),
    });
    setFormOpen(true);
  }

  async function saveProvider(e: FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) {
      toast.error(t("ai.err.name_required", { en: "Provider name is required", zh: "请填写供应商名称" }));
      return;
    }
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        name: form.name.trim(),
        provider_type: form.provider_type,
        base_url: form.base_url.trim() || null,
        model_default: form.model_default.trim() || null,
        temperature: num(form.temperature),
        max_tokens: num(form.max_tokens),
        config: {
          ...(num(form.temperature) !== null ? { temperature: num(form.temperature) } : {}),
          ...(num(form.max_tokens) !== null ? { max_tokens: num(form.max_tokens) } : {}),
        },
      };
      if (form.api_key) {
        payload.api_key = form.api_key;
        payload.secret_ref = form.api_key;
      }
      if (editing) {
        await apiPatch(`/api/v1/settings/ai/providers/${editing.id}`, payload);
        toast.success(t("ai.provider.updated", { en: "Provider updated", zh: "供应商已更新" }));
      } else {
        await apiPost("/api/v1/settings/ai/providers", payload);
        toast.success(t("ai.provider.created", { en: "Provider created", zh: "供应商已创建" }));
      }
      setFormOpen(false);
      await loadProviders();
    } catch (err) {
      toast.error(
        t("ai.provider.save_fail", { en: "Save failed: {msg}", zh: "保存失败：{msg}" }, {
          msg: err instanceof Error ? err.message : String(err),
        }),
      );
    }
    setSaving(false);
  }

  async function deleteProvider(id: string) {
    try {
      await apiDelete(`/api/v1/settings/ai/providers/${id}`);
      toast.success(t("ai.provider.deleted", { en: "Provider deleted", zh: "供应商已删除" }));
      setFormOpen(false);
      await loadProviders();
    } catch (err) {
      toast.error(
        t("ai.provider.delete_fail", { en: "Delete failed: {msg}", zh: "删除失败：{msg}" }, {
          msg: err instanceof Error ? err.message : String(err),
        }),
      );
    }
  }

  async function testProvider(p: Provider) {
    setTestingId(p.id);
    const started = Date.now();
    try {
      const res = await apiPost(`/api/v1/settings/ai/providers/${p.id}/test`, {});
      const clientLatency = Date.now() - started;
      const models = Array.isArray(res?.models) ? res.models.map((m: unknown) => String(m)) : [];
      setTestResult({
        provider_name: p.name,
        ok: res?.ok !== false,
        latency_ms: num(res?.latency_ms) ?? clientLatency,
        models,
        model: res?.model ? String(res.model) : p.model_default,
        message: res?.message ? String(res.message) : String(res?.status ?? ""),
        tested_at: res?.tested_at ? String(res.tested_at) : new Date().toISOString(),
      });
      toast.success(
        t("ai.test.ok", { en: "Connection OK — {ms} ms", zh: "连接正常 — {ms} 毫秒" }, {
          ms: String(num(res?.latency_ms) ?? clientLatency),
        }),
      );
    } catch (err) {
      setTestResult({
        provider_name: p.name,
        ok: false,
        latency_ms: Date.now() - started,
        models: [],
        model: p.model_default,
        message: err instanceof Error ? err.message : String(err),
        tested_at: new Date().toISOString(),
      });
      toast.error(t("ai.test.fail", { en: "Connection test failed", zh: "连接测试失败" }));
    }
    setTestingId(null);
  }

  const providerCols: ColumnDef<Provider>[] = useMemo(
    () => [
      {
        key: "name",
        title: t("common.name", "Name"),
        width: 180,
        sticky: true,
        value: (r) => r.name,
        render: (_v, r) => (
          <span className="ai-provider-name">
            <span className={`dot ${r.status === "active" ? "active" : r.status === "error" ? "error" : ""}`} />
            {r.name}
          </span>
        ),
      },
      {
        key: "provider_type",
        title: t("common.type", "Type"),
        width: 100,
        value: (r) => r.provider_type,
      },
      {
        key: "base_url",
        title: "Base URL",
        width: 220,
        value: (r) => r.base_url ?? "",
        render: (v) => (v ? String(v) : "—"),
      },
      {
        key: "model_default",
        title: t("ai.model_default", "Default model"),
        width: 160,
        value: (r) => r.model_default ?? "",
        render: (v) => (v ? String(v) : "—"),
      },
      {
        key: "status",
        title: t("common.status", "Status"),
        width: 90,
        value: (r) => r.status,
        render: (v) => (
          <span className={`ai-pill ${v === "active" ? "on" : "off"}`}>{String(v ?? "—")}</span>
        ),
      },
      {
        key: "_act",
        title: t("common.actions", "Actions"),
        width: 170,
        value: (r) => r.id,
        render: (_v, r) => (
          <span className="ai-actions">
            <button type="button" onClick={(e) => { e.stopPropagation(); testProvider(r); }} disabled={testingId === r.id}>
              {testingId === r.id ? "…" : t("common.test", "Test")}
            </button>
            <button type="button" onClick={(e) => { e.stopPropagation(); openEdit(r); }}>
              {t("common.edit", "Edit")}
            </button>
            <button
              type="button"
              className="danger"
              onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(r.id); }}
            >
              {t("common.delete", "Delete")}
            </button>
          </span>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, testingId],
  );

  // ============================== model settings ==============================

  const loadModelsTab = useCallback(async () => {
    try {
      const data = (await apiGet("/api/v1/settings/ai/models")) as ModelsResponse | ModelEntry[];
      if (Array.isArray(data)) {
        setModelEntries(data);
      } else {
        setModelEntries(data.providers ?? []);
        const d = data.defaults;
        if (d) {
          if (d.model !== undefined) setGlobalModel(String(d.model));
          if (d.temperature !== undefined) setGlobalTemp(String(d.temperature));
          if (d.max_tokens !== undefined) setGlobalMaxTokens(String(d.max_tokens));
          if (d.timeout_s !== undefined) setGlobalTimeout(String(d.timeout_s));
        }
      }
    } catch {
      setModelEntries([]);
    }
    try {
      const ags = await apiGet("/api/v1/ai/agents");
      const list: AgentRow[] = Array.isArray(ags) ? ags : [];
      setAgents(list);
      setAgentSel((prev) => prev || list[0]?.agent_name || "");
    } catch {
      setAgents([]);
    }
  }, []);

  useEffect(() => {
    if (tab === "models") loadModelsTab();
  }, [tab, loadModelsTab]);

  useEffect(() => {
    const a = agents.find((x) => x.agent_name === agentSel);
    setAgentModel(a?.model_name ?? "");
    setAgentTemp("");
  }, [agentSel, agents]);

  async function saveGlobalDefaults() {
    setSavingModels(true);
    try {
      await apiPatch("/api/v1/settings/ai/agents/global", {
        model: globalModel.trim() || null,
        temperature: num(globalTemp),
        max_tokens: num(globalMaxTokens),
        timeout_s: num(globalTimeout),
      });
      toast.success(t("ai.models.global_saved", { en: "Global defaults saved", zh: "全局默认已保存" }));
    } catch (err) {
      toast.error(
        t("ai.models.save_fail", { en: "Save failed: {msg}", zh: "保存失败：{msg}" }, {
          msg: err instanceof Error ? err.message : String(err),
        }),
      );
    }
    setSavingModels(false);
  }

  async function saveAgentOverride() {
    if (!agentSel) return;
    setSavingModels(true);
    try {
      await apiPatch(`/api/v1/settings/ai/agents/${encodeURIComponent(agentSel)}`, {
        model: agentModel.trim() || null,
        model_name: agentModel.trim() || null,
        temperature: num(agentTemp),
      });
      toast.success(t("ai.models.agent_saved", { en: "Agent model override saved", zh: "Agent 模型覆盖已保存" }));
    } catch (err) {
      toast.error(
        t("ai.models.save_fail", { en: "Save failed: {msg}", zh: "保存失败：{msg}" }, {
          msg: err instanceof Error ? err.message : String(err),
        }),
      );
    }
    setSavingModels(false);
  }

  // ============================== skill bindings ==============================

  const loadSkills = useCallback(async () => {
    setSkillsLoading(true);
    try {
      const [cat, binds] = await Promise.all([
        apiGet("/api/v1/settings/ai/skills/catalog"),
        apiGet("/api/v1/settings/ai/skills/bindings"),
      ]);
      setSkills(Array.isArray(cat) ? cat : []);
      setBindings(Array.isArray(binds) ? binds : []);
    } catch {
      setSkills([]);
      setBindings([]);
    }
    setSkillsLoading(false);
  }, []);

  useEffect(() => {
    if (tab === "skills") loadSkills();
  }, [tab, loadSkills]);

  function openBinding(s: Skill) {
    const existing = bindings.find((b) => b.skill_code === s.skill_code);
    setBindSkill(s);
    setBindPrimary(existing?.primary_provider_id ?? "");
    setBindFallback(existing?.fallback_provider_id ?? "");
    setBindParams(JSON.stringify(existing?.params ?? {}, null, 2));
    setBindEnabled(existing?.enabled ?? true);
    setBindOpen(true);
  }

  async function saveBinding(e: FormEvent) {
    e.preventDefault();
    if (!bindSkill) return;
    let params: Record<string, unknown> = {};
    try {
      const parsed = JSON.parse(bindParams || "{}");
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) params = parsed;
      else throw new Error("params must be a JSON object");
    } catch (err) {
      toast.error(
        t("ai.bind.bad_json", { en: "Params must be valid JSON: {msg}", zh: "参数须为合法 JSON：{msg}" }, {
          msg: err instanceof Error ? err.message : String(err),
        }),
      );
      return;
    }
    try {
      await apiPut(`/api/v1/settings/ai/skills/${encodeURIComponent(bindSkill.skill_code)}/binding`, {
        skill_code: bindSkill.skill_code,
        primary_provider_id: bindPrimary || null,
        fallback_provider_id: bindFallback || null,
        params,
        enabled: bindEnabled,
      });
      toast.success(t("ai.bind.saved", { en: "Binding saved", zh: "绑定已保存" }));
      setBindOpen(false);
      await loadSkills();
    } catch (err) {
      toast.error(
        t("ai.bind.save_fail", { en: "Save failed: {msg}", zh: "保存失败：{msg}" }, {
          msg: err instanceof Error ? err.message : String(err),
        }),
      );
    }
  }

  const skillRows = useMemo(() => {
    return skills.map((s) => {
      const b = bindings.find((x) => x.skill_code === s.skill_code);
      return {
        skill_code: s.skill_code,
        module: s.module,
        description: s.description,
        primary_provider_id: b?.primary_provider_id ?? null,
        fallback_provider_id: b?.fallback_provider_id ?? null,
        enabled: b?.enabled ?? false,
        bound: !!b,
      };
    });
  }, [skills, bindings]);

  const providerName = useCallback(
    (id: string | null | undefined) => {
      if (!id) return "—";
      return providers.find((p) => p.id === id)?.name ?? String(id).slice(0, 8);
    },
    [providers],
  );

  const skillCols: ColumnDef<(typeof skillRows)[number]>[] = useMemo(
    () => [
      { key: "skill_code", title: t("ai.skill", "Skill"), width: 200, sticky: true, value: (r) => r.skill_code },
      { key: "module", title: t("ai.module", "Module"), width: 100, value: (r) => r.module },
      {
        key: "description",
        title: t("ai.description", "Description"),
        width: 280,
        value: (r) => r.description,
      },
      {
        key: "primary_provider_id",
        title: t("ai.primary_provider", "Primary provider"),
        width: 160,
        value: (r) => r.primary_provider_id ?? "",
        render: (v) => providerName(v as string | null),
      },
      {
        key: "fallback_provider_id",
        title: t("ai.fallback_provider", "Fallback provider"),
        width: 160,
        value: (r) => r.fallback_provider_id ?? "",
        render: (v) => providerName(v as string | null),
      },
      {
        key: "enabled",
        title: t("common.status", "Status"),
        width: 100,
        value: (r) => r.enabled,
        render: (v, r) => (
          <span className={`ai-pill ${v ? "on" : "off"}`}>
            {v
              ? t("common.enabled", "Enabled")
              : r.bound
                ? t("common.disabled", "Disabled")
                : t("ai.unbound", "Unbound")}
          </span>
        ),
      },
      {
        key: "_act",
        title: t("common.actions", "Actions"),
        width: 90,
        value: (r) => r.skill_code,
        render: (_v, r) => (
          <span className="ai-actions">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                const s = skills.find((x) => x.skill_code === r.skill_code);
                if (s) openBinding(s);
              }}
            >
              {t("common.edit", "Edit")}
            </button>
          </span>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, providerName, skills],
  );

  // ============================== usage ==============================

  const loadUsage = useCallback(async () => {
    setUsageLoading(true);
    try {
      const data = await apiGet("/api/v1/settings/ai/usage");
      if (Array.isArray(data)) {
        setUsage({ by_agent: data });
      } else {
        setUsage(data ?? null);
      }
    } catch {
      setUsage(null);
    }
    setUsageLoading(false);
  }, []);

  useEffect(() => {
    if (tab === "usage") loadUsage();
  }, [tab, loadUsage]);

  const usageTotals = useMemo(() => {
    const rows = [...(usage?.by_agent ?? []), ...(usage?.by_conversation ?? []), ...(usage?.by_day ?? [])];
    const fromRows = rows.reduce(
      (acc, r) => ({
        requests: acc.requests + (num(r.requests) ?? 0),
        tokens: acc.tokens + (num(r.tokens_total) ?? (num(r.tokens_in) ?? 0) + (num(r.tokens_out) ?? 0)),
        cost: acc.cost + (num(r.cost_usd) ?? 0),
      }),
      { requests: 0, tokens: 0, cost: 0 },
    );
    return {
      requests: usage?.totals?.requests ?? (fromRows.requests || null),
      tokens: usage?.totals?.tokens_total ?? (fromRows.tokens || null),
      cost: usage?.totals?.cost_usd ?? (fromRows.cost || null),
    };
  }, [usage]);

  const usageCols = useMemo(
    (): ColumnDef<UsageRow>[] => [
      { key: "key", title: t("ai.usage.key", "Key"), width: 200, sticky: true, value: (r) => r.key },
      {
        key: "label",
        title: t("ai.usage.label", "Label"),
        width: 180,
        value: (r) => r.label ?? "",
        render: (v) => (v ? String(v) : "—"),
      },
      {
        key: "requests",
        title: t("ai.usage.requests", "Requests"),
        width: 100,
        align: "right",
        agg: "sum",
        value: (r) => num(r.requests),
        render: (v) => fmtNum(v),
      },
      {
        key: "tokens_in",
        title: t("ai.usage.tokens_in", "Tokens in"),
        width: 110,
        align: "right",
        agg: "sum",
        value: (r) => num(r.tokens_in),
        render: (v) => fmtNum(v),
      },
      {
        key: "tokens_out",
        title: t("ai.usage.tokens_out", "Tokens out"),
        width: 110,
        align: "right",
        agg: "sum",
        value: (r) => num(r.tokens_out),
        render: (v) => fmtNum(v),
      },
      {
        key: "tokens_total",
        title: t("ai.usage.tokens_total", "Tokens total"),
        width: 120,
        align: "right",
        agg: "sum",
        value: (r) => num(r.tokens_total) ?? ((num(r.tokens_in) ?? 0) + (num(r.tokens_out) ?? 0)),
        render: (v) => fmtNum(v),
      },
      {
        key: "cost_usd",
        title: t("ai.usage.cost", "Cost (USD)"),
        width: 110,
        align: "right",
        agg: "sum",
        value: (r) => num(r.cost_usd),
        render: (v) => fmtNum(v, 2),
      },
      {
        key: "avg_latency_ms",
        title: t("ai.usage.latency", "Avg latency"),
        width: 110,
        align: "right",
        value: (r) => num(r.avg_latency_ms),
        render: (v) => (num(v) === null ? "—" : `${fmtNum(v)} ms`),
      },
    ],
    [t],
  );

  // ============================== render ==============================

  const tabs: { id: Tab; label: string }[] = [
    { id: "providers", label: t("ai.tab.providers", { en: "Providers", zh: "供应商" }) },
    { id: "models", label: t("ai.tab.models", { en: "Model Settings", zh: "模型设置" }) },
    { id: "skills", label: t("ai.tab.skills", { en: "Skill Bindings", zh: "技能绑定" }) },
    { id: "usage", label: t("ai.tab.usage", { en: "Usage", zh: "用量" }) },
  ];

  return (
    <AppShell>
      <PageHeader
        title={t("page.ai.title", { en: "AI Settings", zh: "AI 设置" })}
        subtitle={t("page.ai.sub", {
          en: "Providers, model defaults, skill bindings and token usage.",
          zh: "供应商、模型默认值、技能绑定与 token 用量。",
        })}
      />
      <div className="ai-shell">
        <div className="ai-tabs" role="tablist">
          {tabs.map((x) => (
            <button
              key={x.id}
              type="button"
              role="tab"
              aria-selected={tab === x.id}
              className={`ai-tab${tab === x.id ? " active" : ""}`}
              onClick={() => setTab(x.id)}
            >
              {x.label}
            </button>
          ))}
        </div>

        {/* ————————————— Tab 1: Providers ————————————— */}
        {tab === "providers" && (
          <div>
            <div className="ai-toolbar">
              <button type="button" className="btn btn-primary btn-sm" onClick={openCreate}>
                {t("ai.provider.add", { en: "Add provider", zh: "新增供应商" })}
              </button>
              <button type="button" className="btn btn-sm" onClick={() => loadProviders()}>
                {t("common.refresh", "Refresh")}
              </button>
              <span className="spacer" />
              <span className="hint">
                {t("ai.provider.hint", {
                  en: "Double-click a row to edit. Test shows latency and available models.",
                  zh: "双击行可编辑。测试将显示延迟与可用模型。",
                })}
              </span>
            </div>

            {testResult && (
              <div className={`ai-test-result${testResult.ok ? "" : " fail"}`}>
                <div className="row">
                  <span>
                    <span className="label">{t("ai.test.provider", "Provider")}: </span>
                    <span className="value">{testResult.provider_name}</span>
                  </span>
                  <span>
                    <span className="label">{t("common.status", "Status")}: </span>
                    <span className="value" style={{ color: testResult.ok ? "var(--ok)" : "var(--danger)" }}>
                      {testResult.ok ? t("ai.test.ok_label", "OK") : t("ai.test.fail_label", "FAILED")}
                    </span>
                  </span>
                  <span>
                    <span className="label">{t("ai.test.latency", "Latency")}: </span>
                    <span className="value">{testResult.latency_ms !== null ? `${testResult.latency_ms} ms` : "—"}</span>
                  </span>
                  <span>
                    <span className="label">{t("ai.model_default", "Default model")}: </span>
                    <span className="value">{testResult.model ?? "—"}</span>
                  </span>
                  <span>
                    <span className="label">{t("ai.test.tested_at", "Tested at")}: </span>
                    <span className="value">{testResult.tested_at.slice(0, 19).replace("T", " ")}</span>
                  </span>
                </div>
                {testResult.models.length > 0 && (
                  <div className="models">
                    <span className="label">{t("ai.test.models", "Models")}:</span>
                    <div className="ai-model-chips">
                      {testResult.models.map((m) => (
                        <span key={m} className="ai-chip">
                          {m}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {testResult.message && (
                  <div style={{ marginTop: 4, color: "var(--muted)" }}>{testResult.message}</div>
                )}
              </div>
            )}

            <DataGrid<Provider>
              columns={providerCols}
              data={providers}
              rowKey={(r) => r.id}
              loading={providersLoading}
              emptyText={t("ai.provider.empty", "No AI providers configured yet.")}
              onRowDoubleClick={(r) => openEdit(r)}
              showFooter={false}
              storageKey="ai_providers"
            />
          </div>
        )}

        {/* ————————————— Tab 2: Model Settings ————————————— */}
        {tab === "models" && (
          <div className="ai-split">
            <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap-md)" }}>
              <div className="ai-panel">
                <div className="ai-panel-head">
                  <h3>{t("ai.models.global", { en: "Global defaults", zh: "全局默认" })}</h3>
                  <span className="sub">
                    {t("ai.models.global_sub", {
                      en: "Applied when a skill or agent has no override.",
                      zh: "当技能或 agent 无覆盖配置时生效。",
                    })}
                  </span>
                </div>
                <div className="ai-form-grid">
                  <label className="field-row">
                    <span className="field-label">{t("ai.models.default_model", "Default model")}</span>
                    <input
                      type="text"
                      value={globalModel}
                      onChange={(e) => setGlobalModel(e.target.value)}
                      placeholder="claude-sonnet-4-5 / gpt-4o / llama3"
                    />
                  </label>
                  <label className="field-row">
                    <span className="field-label">{t("ai.models.temperature", "Temperature")}</span>
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      max="2"
                      value={globalTemp}
                      onChange={(e) => setGlobalTemp(e.target.value)}
                    />
                  </label>
                  <label className="field-row">
                    <span className="field-label">{t("ai.models.max_tokens", "Max tokens")}</span>
                    <input
                      type="number"
                      min="1"
                      value={globalMaxTokens}
                      onChange={(e) => setGlobalMaxTokens(e.target.value)}
                    />
                  </label>
                  <label className="field-row">
                    <span className="field-label">{t("ai.models.timeout", "Timeout (s)")}</span>
                    <input
                      type="number"
                      min="1"
                      value={globalTimeout}
                      onChange={(e) => setGlobalTimeout(e.target.value)}
                    />
                  </label>
                </div>
                <div className="ai-toolbar" style={{ marginTop: "var(--gap-sm)" }}>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    disabled={savingModels}
                    onClick={saveGlobalDefaults}
                  >
                    {savingModels ? "…" : t("common.save", "Save")}
                  </button>
                </div>
              </div>

              <div className="ai-panel">
                <div className="ai-panel-head">
                  <h3>{t("ai.models.per_agent", { en: "Per-agent model override", zh: "按 Agent 覆盖模型" })}</h3>
                  <span className="sub">
                    {t("ai.models.per_agent_sub", {
                      en: "Select an agent, then set its model and temperature.",
                      zh: "选择 agent 后设置其模型与温度。",
                    })}
                  </span>
                </div>
                <div className="ai-agent-bar">
                  <label htmlFor="ai-agent-sel">{t("ai.models.agent", "Agent")}</label>
                  <select id="ai-agent-sel" value={agentSel} onChange={(e) => setAgentSel(e.target.value)}>
                    {agents.length === 0 && <option value="">{t("ai.models.no_agents", "No agents")}</option>}
                    {agents.map((a) => (
                      <option key={a.agent_name} value={a.agent_name}>
                        {a.display_name || a.agent_name}
                      </option>
                    ))}
                  </select>
                  {agentSel && (
                    <span className="hint" style={{ color: "var(--muted)", fontSize: "var(--font-label)" }}>
                      {agents.find((a) => a.agent_name === agentSel)?.description ?? ""}
                    </span>
                  )}
                </div>
                <div className="ai-form-grid">
                  <label className="field-row">
                    <span className="field-label">{t("ai.models.model", "Model")}</span>
                    <input
                      type="text"
                      value={agentModel}
                      onChange={(e) => setAgentModel(e.target.value)}
                      placeholder={globalModel || "inherit"}
                    />
                  </label>
                  <label className="field-row">
                    <span className="field-label">{t("ai.models.temperature", "Temperature")}</span>
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      max="2"
                      value={agentTemp}
                      onChange={(e) => setAgentTemp(e.target.value)}
                      placeholder={globalTemp}
                    />
                  </label>
                </div>
                <div className="ai-toolbar" style={{ marginTop: "var(--gap-sm)" }}>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    disabled={savingModels || !agentSel}
                    onClick={saveAgentOverride}
                  >
                    {savingModels ? "…" : t("ai.models.save_override", { en: "Save override", zh: "保存覆盖" })}
                  </button>
                  {agentModel && (
                    <span className="hint">
                      {t("ai.models.inherit_hint", {
                        en: "Leave empty to inherit the global default.",
                        zh: "留空则继承全局默认。",
                      })}
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* Available Models panel */}
            <div className="ai-panel">
              <div className="ai-panel-head">
                <h3>{t("ai.models.available", { en: "Available models", zh: "可用模型" })}</h3>
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => loadModelsTab()}>
                  {t("common.refresh", "Refresh")}
                </button>
              </div>
              {modelEntries.length === 0 && (
                <p className="hint" style={{ color: "var(--muted)" }}>
                  {t("ai.models.available_empty", {
                    en: "No model inventory yet — run a provider connection test first.",
                    zh: "暂无模型清单——请先执行供应商连接测试。",
                  })}
                </p>
              )}
              {modelEntries.map((entry, i) => (
                <div key={`${entry.provider_id ?? entry.provider_name ?? i}`} style={{ marginBottom: "var(--gap-md)" }}>
                  <div
                    style={{
                      fontSize: "var(--font-label)",
                      fontWeight: 600,
                      marginBottom: 4,
                      display: "flex",
                      justifyContent: "space-between",
                      gap: 8,
                    }}
                  >
                    <span>{entry.provider_name ?? providerName(entry.provider_id) ?? `#${i + 1}`}</span>
                    <span style={{ color: "var(--muted)", fontWeight: 400 }}>
                      {t("ai.models.count", { en: "{n} models", zh: "{n} 个模型" }, { n: String(entry.models?.length ?? 0) })}
                    </span>
                  </div>
                  <div className="ai-model-chips">
                    {(entry.models ?? []).map((m) => (
                      <button
                        key={m}
                        type="button"
                        className={`ai-chip${(agentSel ? agentModel : globalModel) === m ? " selected" : ""}`}
                        title={
                          agentSel
                            ? t("ai.models.click_agent", { en: "Set as agent model", zh: "设为 agent 模型" })
                            : t("ai.models.click_global", { en: "Set as global default", zh: "设为全局默认" })
                        }
                        onClick={() => {
                          if (agentSel) setAgentModel(m);
                          else setGlobalModel(m);
                        }}
                      >
                        {m}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ————————————— Tab 3: Skill Bindings ————————————— */}
        {tab === "skills" && (
          <div>
            <div className="ai-toolbar">
              <button type="button" className="btn btn-sm" onClick={() => loadSkills()}>
                {t("common.refresh", "Refresh")}
              </button>
              <span className="spacer" />
              <span className="hint">
                {t("ai.bind.hint", {
                  en: "Each skill routes to a primary provider with optional fallback.",
                  zh: "每个技能路由到主供应商，并可配置备用供应商。",
                })}
              </span>
            </div>
            <DataGrid<(typeof skillRows)[number]>
              columns={skillCols}
              data={skillRows}
              rowKey={(r) => r.skill_code}
              loading={skillsLoading}
              emptyText={t("ai.bind.empty", "No AI skills in the catalog.")}
              onRowDoubleClick={(r) => {
                const s = skills.find((x) => x.skill_code === r.skill_code);
                if (s) openBinding(s);
              }}
              showFooter={false}
              storageKey="ai_skill_bindings"
            />
          </div>
        )}

        {/* ————————————— Tab 4: Usage ————————————— */}
        {tab === "usage" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap-md)" }}>
            <div className="ai-toolbar">
              <button type="button" className="btn btn-sm" onClick={() => loadUsage()}>
                {t("common.refresh", "Refresh")}
              </button>
              <span className="spacer" />
              <span className="hint">
                {t("ai.usage.hint", {
                  en: "Token consumption by agent, conversation and day.",
                  zh: "按 agent、会话与日期统计 token 消耗。",
                })}
              </span>
            </div>

            <div className="ai-kpi-row">
              <div className="ai-kpi">
                <span>{t("ai.usage.total_requests", "Total requests")}</span>
                <strong>{fmtNum(usageTotals.requests)}</strong>
              </div>
              <div className="ai-kpi">
                <span>{t("ai.usage.total_tokens", "Total tokens")}</span>
                <strong>{fmtNum(usageTotals.tokens)}</strong>
              </div>
              <div className="ai-kpi">
                <span>{t("ai.usage.total_cost", "Est. cost (USD)")}</span>
                <strong>{fmtNum(usageTotals.cost, 2)}</strong>
              </div>
              <div className="ai-kpi">
                <span>{t("ai.usage.agents_tracked", "Agents tracked")}</span>
                <strong>{fmtNum(usage?.by_agent?.length ?? 0)}</strong>
              </div>
            </div>

            {usageLoading && <div className="skeleton" style={{ height: 160, borderRadius: 8 }} />}

            {!usageLoading && !usage && (
              <div className="ai-panel rg-empty">
                {t("ai.usage.empty", "No usage data yet — usage appears after AI calls are made.")}
              </div>
            )}

            {!usageLoading && usage && (
              <>
                <div className="ai-panel">
                  <div className="ai-panel-head">
                    <h3>{t("ai.usage.by_agent", { en: "Usage by agent", zh: "按 Agent 统计" })}</h3>
                  </div>
                  <DataGrid<UsageRow>
                    columns={usageCols}
                    data={usage.by_agent ?? []}
                    rowKey={(r, i) => `agent-${r.key}-${i}`}
                    emptyText={t("ai.usage.no_rows", "No rows")}
                    showFooter
                    storageKey="ai_usage_agent"
                  />
                </div>

                <div className="ai-panel">
                  <div className="ai-panel-head">
                    <h3>{t("ai.usage.by_conversation", { en: "Usage by conversation", zh: "按会话统计" })}</h3>
                  </div>
                  <DataGrid<UsageRow>
                    columns={usageCols}
                    data={usage.by_conversation ?? []}
                    rowKey={(r, i) => `conv-${r.key}-${i}`}
                    emptyText={t("ai.usage.no_rows", "No rows")}
                    showFooter
                    storageKey="ai_usage_conv"
                  />
                </div>

                <div className="ai-panel">
                  <div className="ai-panel-head">
                    <h3>{t("ai.usage.by_day", { en: "Usage by day", zh: "按日统计" })}</h3>
                  </div>
                  <DataGrid<UsageRow>
                    columns={usageCols}
                    data={usage.by_day ?? []}
                    rowKey={(r, i) => `day-${r.key}-${i}`}
                    emptyText={t("ai.usage.no_rows", "No rows")}
                    showFooter
                    storageKey="ai_usage_day"
                  />
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* ————————————— Provider add/edit modal ————————————— */}
      <RecordModal
        open={formOpen}
        title={
          editing
            ? t("ai.provider.edit_title", { en: "Edit provider", zh: "编辑供应商" })
            : t("ai.provider.new_title", { en: "New provider", zh: "新增供应商" })
        }
        onClose={() => setFormOpen(false)}
        onSave={saveProvider}
        onDelete={editing ? () => deleteProvider(editing.id) : undefined}
        canDelete={!!editing}
        saving={saving}
        size="lg"
      >
        <FormPanel columns={2}>
          <FormSection title={t("ai.provider.section_basic", { en: "Basic", zh: "基本信息" })} dense>
            <FieldRow label={t("common.name", "Name")}>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="anthropic-prod"
                required
              />
            </FieldRow>
            <FieldRow label={t("common.type", "Type")}>
              <select
                value={form.provider_type}
                onChange={(e) => setForm({ ...form, provider_type: e.target.value })}
              >
                {PROVIDER_TYPES.map((x) => (
                  <option key={x} value={x}>
                    {x}
                  </option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label="Base URL" span={2}>
              <input
                type="text"
                value={form.base_url}
                onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                placeholder="https://api.anthropic.com"
              />
            </FieldRow>
            <FieldRow label={t("ai.provider.api_key", { en: "API key", zh: "API 密钥" })} span={2}>
              <input
                type="password"
                value={form.api_key}
                onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                placeholder={editing ? t("ai.provider.key_keep", { en: "Leave blank to keep", zh: "留空则保持不变" }) : "sk-…"}
                autoComplete="new-password"
              />
            </FieldRow>
          </FormSection>
          <FormSection title={t("ai.provider.section_model", { en: "Model defaults", zh: "模型默认值" })} dense>
            <FieldRow label={t("ai.model_default", "Default model")} span={2}>
              <input
                type="text"
                value={form.model_default}
                onChange={(e) => setForm({ ...form, model_default: e.target.value })}
                placeholder="claude-sonnet-4-5"
              />
            </FieldRow>
            <FieldRow label={t("ai.models.temperature", "Temperature")}>
              <input
                type="number"
                step="0.1"
                min="0"
                max="2"
                value={form.temperature}
                onChange={(e) => setForm({ ...form, temperature: e.target.value })}
              />
            </FieldRow>
            <FieldRow label={t("ai.models.max_tokens", "Max tokens")}>
              <input
                type="number"
                min="1"
                value={form.max_tokens}
                onChange={(e) => setForm({ ...form, max_tokens: e.target.value })}
              />
            </FieldRow>
          </FormSection>
        </FormPanel>
      </RecordModal>

      {/* ————————————— Skill binding modal ————————————— */}
      <RecordModal
        open={bindOpen}
        title={t("ai.bind.edit_title", { en: "Edit skill binding", zh: "编辑技能绑定" })}
        onClose={() => setBindOpen(false)}
        onSave={saveBinding}
        canDelete={false}
        size="md"
      >
        <FormPanel columns={1}>
          <FormSection title={bindSkill ? `${bindSkill.skill_code} · ${bindSkill.module}` : ""} dense>
            <FieldRow label={t("ai.primary_provider", "Primary provider")}>
              <select value={bindPrimary} onChange={(e) => setBindPrimary(e.target.value)}>
                <option value="">{t("ai.bind.none", "— none —")}</option>
                {providers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.provider_type})
                  </option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label={t("ai.fallback_provider", "Fallback provider")}>
              <select value={bindFallback} onChange={(e) => setBindFallback(e.target.value)}>
                <option value="">{t("ai.bind.none", "— none —")}</option>
                {providers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.provider_type})
                  </option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label={t("ai.bind.params", { en: "Params (JSON)", zh: "参数 (JSON)" })}>
              <textarea
                rows={5}
                value={bindParams}
                onChange={(e) => setBindParams(e.target.value)}
                spellCheck={false}
                style={{ fontFamily: "ui-monospace, Menlo, Consolas, monospace", fontSize: "var(--font-table)" }}
              />
            </FieldRow>
            <FieldRow label={t("common.enabled", "Enabled")}>
              <input
                type="checkbox"
                checked={bindEnabled}
                onChange={(e) => setBindEnabled(e.target.checked)}
                style={{ width: "auto", height: "auto" }}
              />
            </FieldRow>
          </FormSection>
        </FormPanel>
      </RecordModal>

      <ConfirmDialog
        open={confirmDeleteId !== null}
        title={t("common.confirm", "Confirm")}
        message={t("ai.provider.confirm_delete", {
          en: "Delete this provider? Skill bindings referencing it will keep their ids until reassigned.",
          zh: "确认删除该供应商？引用它的技能绑定将保留 id，直到重新分配。",
        })}
        danger
        onConfirm={() => {
          if (confirmDeleteId) deleteProvider(confirmDeleteId);
          setConfirmDeleteId(null);
        }}
        onCancel={() => setConfirmDeleteId(null)}
      />
    </AppShell>
  );
}
