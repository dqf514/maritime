"use client";

/**
 * 例行任务中枢 —— 待确认草稿收件箱 / 例行任务 / 技能模板 三个 Tab。
 *
 * 三条不可协商的规则（与后端一致，UI 上也必须守）：
 * 1. 草稿不自动落库 —— 只有「采纳」才写业务表，且走二次确认；
 * 2. 只落被勾选的字段（字段子集）—— 没勾的字段不写、不参与计算；
 * 3. 失败显性 —— 失败草稿带 error，不会悄悄消失。
 */

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { PageGuide } from "@/components/PageGuide";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { RecordModal } from "@/components/RecordModal";
import { StateView } from "@/components/StateView";
import { StatusBadge } from "@/components/StatusBadge";
import { Tabs, type TabItem } from "@/components/Tabs";
import { Toolbar } from "@/components/Toolbar";
import { useToast } from "@/components/ToastProvider";
import { apiGet, apiList, apiPatch, apiPost, apiPut } from "@/lib/api";
import { formatInTz } from "@/lib/datetime";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";

// ── 类型 ──────────────────────────────────────────────────────────────────

type Evidence = {
  source?: string;
  field: string;
  quote?: string;
  value?: unknown;
  extracted_by?: string;
};

type SourceEmail = {
  subject?: string | null;
  from_email?: string | null;
  sent_at?: string | null;
  body_excerpt?: string | null;
  body_truncated?: boolean;
};

type DraftOut = {
  id: string;
  routine_task_id: string;
  task_code: string | null;
  task_name: string | null;
  owner_role: string | null;
  source_kind: string;
  source_email_id: string | null;
  target_entity: string | null;
  target_id: string | null;
  payload: Record<string, unknown>;
  field_diff: {
    llm_vs_rules?: string[];
    dropped_without_evidence?: string[];
    warnings?: string[];
  } | null;
  evidence: Evidence[] | null;
  confidence: number | null;
  status: string;
  error: string | null;
  decided_comment: string | null;
  created_at: string | null;
  /** 服务端判定的确认闸门（四眼：自己触发的草稿不能自己确认） */
  can_confirm?: boolean | null;
  blocked_reason?: string | null;
  source_email?: SourceEmail | null;
};

type TaskOut = {
  id: string;
  code: string;
  name: string;
  direction: string;
  module_code: string;
  trigger_type: string;
  skill_code: string;
  output_target: string | null;
  owner_role: string;
  sla_minutes: number;
  enabled: boolean;
  created_at: string | null;
};

type TriggerRule = {
  id?: string;
  sender_emails: string[];
  sender_domains: string[];
  subject_regex: string | null;
  body_markers: string[];
  folder: string;
  direction: string;
  priority: number;
  enabled: boolean;
};

type SkillField = { type?: string; required?: boolean };
type SkillOut = {
  id: string;
  code: string;
  scope: string;
  name: string;
  purpose: string | null;
  output_schema: { kind?: string; required?: string[]; fields?: Record<string, SkillField> } | null;
  validator_rules: { ranges?: Record<string, number[]>; one_of?: Record<string, string[]> } | null;
  deterministic_engine: string | null;
  version: number;
  enabled: boolean;
  based_on: string | null;
  updated_at: string | null;
};

const DRAFT_STATUSES = ["pending", "applied", "rejected", "failed", "superseded"];
const FOLDER_OPTIONS = ["*", "inbox", "sentitems", "drafts", "archive", "junkemail"];
const DIRECTION_OPTIONS = ["*", "inbound", "outbound"];

/** 结构化值（数组/对象）—— 不能塞进单行输入框 */
function isStructuredValue(value: unknown): boolean {
  return value !== null && typeof value === "object";
}

/** 结构化值的可读展开（数组一行一条，对象按键值） */
function formatStructuredValue(value: unknown): string {
  if (Array.isArray(value)) {
    return value
      .map((item) => (typeof item === "object" && item !== null ? JSON.stringify(item) : String(item)))
      .join("\n");
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

type EditableTask = {
  id: string | null;
  code: string;
  name: string;
  module_code: string;
  skill_code: string;
  output_target: string;
  owner_role: string;
  sla_minutes: string;
  enabled: boolean;
};

const EMPTY_TASK: EditableTask = {
  id: null,
  code: "",
  name: "",
  module_code: "operations",
  skill_code: "",
  output_target: "noon_report",
  owner_role: "operations",
  sla_minutes: "120",
  enabled: true,
};

function csvToList(value: string): string[] {
  return value
    .split(/[,\n;]/)
    .map((v) => v.trim())
    .filter(Boolean);
}

function listToCsv(value: string[] | null | undefined): string {
  return (value || []).join(", ");
}

// ── 页面 ──────────────────────────────────────────────────────────────────

function RoutinePageInner() {
  const { t } = useI18n();
  const toast = useToast();
  const { query, setQuery, page, limit } = useListQuery();

  const tab = query.tab === "tasks" || query.tab === "skills" ? query.tab : "drafts";
  const statusFilter = query.status || "";
  const taskFilter = query.task_code || "";

  // 草稿
  const [drafts, setDrafts] = useState<DraftOut[]>([]);
  const [draftTotal, setDraftTotal] = useState(0);
  const [draftsLoading, setDraftsLoading] = useState(true);
  const [draftsError, setDraftsError] = useState("");
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc" | null>(null);

  // 任务 / 技能（管理员面）
  const [tasks, setTasks] = useState<TaskOut[]>([]);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [tasksError, setTasksError] = useState("");
  const [skills, setSkills] = useState<SkillOut[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [skillsError, setSkillsError] = useState("");

  // 详情
  const [detail, setDetail] = useState<DraftOut | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [rejectReason, setRejectReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmAdopt, setConfirmAdopt] = useState(false);

  // 任务编辑 / 触发规则
  const [taskDraft, setTaskDraft] = useState<EditableTask | null>(null);
  const [rulesTask, setRulesTask] = useState<TaskOut | null>(null);
  const [rules, setRules] = useState<TriggerRule[]>([]);
  const [rulesLoading, setRulesLoading] = useState(false);

  // 技能详情
  const [skillView, setSkillView] = useState<SkillOut | null>(null);

  // ── 数据加载 ────────────────────────────────────────────────────────────

  const loadDrafts = useCallback(async () => {
    setDraftsLoading(true);
    try {
      const res = await apiList<DraftOut>("/api/v1/routine/drafts", {
        status: statusFilter || undefined,
        task_code: taskFilter || undefined,
        limit,
        offset: (page - 1) * limit,
      });
      setDrafts(res.items || []);
      setDraftTotal(res.total || 0);
      setDraftsError("");
    } catch (e) {
      setDrafts([]);
      setDraftsError(msgOf(e, t("common.failed", "Failed")));
    } finally {
      setDraftsLoading(false);
    }
  }, [statusFilter, taskFilter, limit, page, t]);

  const loadTasks = useCallback(async () => {
    setTasksLoading(true);
    try {
      const res = await apiList<TaskOut>("/api/v1/routine/tasks");
      setTasks(res.items || []);
      setTasksError("");
    } catch (e) {
      setTasks([]);
      setTasksError(msgOf(e, t("common.failed", "Failed")));
    } finally {
      setTasksLoading(false);
    }
  }, [t]);

  const loadSkills = useCallback(async () => {
    setSkillsLoading(true);
    try {
      const res = await apiList<SkillOut>("/api/v1/routine/skills");
      setSkills(res.items || []);
      setSkillsError("");
    } catch (e) {
      setSkills([]);
      setSkillsError(msgOf(e, t("common.failed", "Failed")));
    } finally {
      setSkillsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadDrafts();
  }, [loadDrafts]);

  useEffect(() => {
    if (tab === "tasks") void loadTasks();
    if (tab === "skills") void loadSkills();
  }, [tab, loadTasks, loadSkills]);

  // ── 草稿详情 ───────────────────────────────────────────────────────────

  const openDetail = useCallback(
    async (id: string) => {
      setDetailLoading(true);
      try {
        const d = (await apiGet(`/api/v1/routine/drafts/${id}`)) as DraftOut;
        const payload = d.payload || {};
        setDetail(d);
        setValues({ ...payload });
        setChecked(new Set(Object.keys(payload)));
        setRejectReason("");
      } catch (e) {
        toast.error(msgOf(e, t("common.failed", "Failed")));
      } finally {
        setDetailLoading(false);
      }
    },
    [t, toast],
  );

  const toggleField = useCallback((key: string) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const adopt = useCallback(async () => {
    if (!detail) return;
    setBusy(true);
    try {
      const payload: Record<string, unknown> = {};
      for (const key of checked) {
        if (key in values) payload[key] = values[key];
      }
      await apiPost(`/api/v1/routine/drafts/${detail.id}/confirm`, {
        payload,
        confirmed: Array.from(checked),
      });
      toast.success(t("page.routine.adopted", "Draft confirmed and written back"));
      setDetail(null);
      await loadDrafts();
    } catch (e) {
      toast.error(msgOf(e, t("common.failed", "Failed")));
    } finally {
      setBusy(false);
      setConfirmAdopt(false);
    }
  }, [detail, checked, values, loadDrafts, t, toast]);

  const reject = useCallback(async () => {
    if (!detail) return;
    if (!rejectReason.trim()) {
      toast.error(t("page.routine.reject_reason_required", "A reason is required to reject a draft"));
      return;
    }
    setBusy(true);
    try {
      await apiPost(`/api/v1/routine/drafts/${detail.id}/reject`, { reason: rejectReason.trim() });
      toast.success(t("page.routine.rejected", "Draft rejected"));
      setDetail(null);
      await loadDrafts();
    } catch (e) {
      toast.error(msgOf(e, t("common.failed", "Failed")));
    } finally {
      setBusy(false);
    }
  }, [detail, rejectReason, loadDrafts, t, toast]);

  const reprocess = useCallback(async () => {
    if (!detail) return;
    setBusy(true);
    try {
      await apiPost(`/api/v1/routine/drafts/${detail.id}/reprocess`);
      toast.success(t("page.routine.reprocessed", "Draft re-processed"));
      await openDetail(detail.id);
      await loadDrafts();
    } catch (e) {
      toast.error(msgOf(e, t("common.failed", "Failed")));
    } finally {
      setBusy(false);
    }
  }, [detail, openDetail, loadDrafts, t, toast]);

  // ── 任务操作 ───────────────────────────────────────────────────────────

  const runTask = useCallback(
    async (task: TaskOut) => {
      setBusy(true);
      try {
        const res = (await apiPost(`/api/v1/routine/tasks/${task.id}/run`)) as { created?: number };
        const n = res?.created ?? 0;
        toast.success(
          n > 0
            ? t("page.routine.run_created", "{n} draft(s) created", { n })
            : t("page.routine.run_none", "No new drafts — nothing matched"),
        );
        await loadDrafts();
      } catch (e) {
        toast.error(msgOf(e, t("common.failed", "Failed")));
      } finally {
        setBusy(false);
      }
    },
    [loadDrafts, t, toast],
  );

  const saveTask = useCallback(async () => {
    if (!taskDraft) return;
    setBusy(true);
    try {
      const body: Record<string, unknown> = {
        name: taskDraft.name,
        module_code: taskDraft.module_code,
        skill_code: taskDraft.skill_code,
        output_target: taskDraft.output_target || null,
        owner_role: taskDraft.owner_role,
        sla_minutes: Number(taskDraft.sla_minutes) || 120,
        enabled: taskDraft.enabled,
      };
      if (taskDraft.id) {
        await apiPatch(`/api/v1/routine/tasks/${taskDraft.id}`, body);
      } else {
        await apiPost("/api/v1/routine/tasks", {
          ...body,
          code: taskDraft.code,
          trigger_type: "inbound_email",
        });
      }
      toast.success(t("page.routine.task_saved", "Routine task saved"));
      setTaskDraft(null);
      await loadTasks();
    } catch (e) {
      toast.error(msgOf(e, t("common.failed", "Failed")));
    } finally {
      setBusy(false);
    }
  }, [taskDraft, loadTasks, t, toast]);

  const openRules = useCallback(
    async (task: TaskOut) => {
      setRulesTask(task);
      setRulesLoading(true);
      try {
        const res = await apiList<TriggerRule>(`/api/v1/routine/tasks/${task.id}/triggers`);
        setRules(res.items || []);
      } catch (e) {
        toast.error(msgOf(e, t("common.failed", "Failed")));
        setRules([]);
      } finally {
        setRulesLoading(false);
      }
    },
    [t, toast],
  );

  const saveRules = useCallback(async () => {
    if (!rulesTask) return;
    setBusy(true);
    try {
      await apiPut(`/api/v1/routine/tasks/${rulesTask.id}/triggers`, {
        rules: rules.map((r) => ({
          sender_emails: r.sender_emails || [],
          sender_domains: r.sender_domains || [],
          subject_regex: r.subject_regex || null,
          body_markers: r.body_markers || [],
          folder: r.folder || "*",
          direction: r.direction || "*",
          priority: r.priority ?? 100,
          enabled: r.enabled !== false,
        })),
      });
      toast.success(t("page.routine.rules_saved", "Trigger rules saved"));
      setRulesTask(null);
    } catch (e) {
      toast.error(msgOf(e, t("common.failed", "Failed")));
    } finally {
      setBusy(false);
    }
  }, [rulesTask, rules, t, toast]);

  // ── 排序（当前页内排序）─────────────────────────────────────────────────

  const sortedDrafts = useMemo(() => {
    if (!sortKey || !sortDir) return drafts;
    const dir = sortDir === "asc" ? 1 : -1;
    return [...drafts].sort((a, b) => {
      const av = (a as unknown as Record<string, unknown>)[sortKey];
      const bv = (b as unknown as Record<string, unknown>)[sortKey];
      if (av === bv) return 0;
      if (av === null || av === undefined) return 1;
      if (bv === null || bv === undefined) return -1;
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
      return String(av).localeCompare(String(bv)) * dir;
    });
  }, [drafts, sortKey, sortDir]);

  const onSortChange = useCallback(
    (key: string, dir: "asc" | "desc" | null) => {
      setSortKey(dir ? key : null);
      setSortDir(dir);
    },
    [],
  );

  // ── 列定义 ─────────────────────────────────────────────────────────────

  const draftColumns = useMemo<ColumnDef<DraftOut>[]>(
    () => [
      {
        key: "source",
        title: t("page.routine.col_source", "Source"),
        minWidth: 220,
        value: (r) => r.source_email?.subject || r.task_code || "",
        render: (_v, r) => (
          <div>
            <div>{r.source_email?.subject || r.source_kind}</div>
            {r.source_email?.from_email ? (
              <div className="muted">{r.source_email.from_email}</div>
            ) : null}
          </div>
        ),
      },
      {
        key: "task_name",
        title: t("page.routine.col_task", "Routine task"),
        minWidth: 180,
        value: (r) => r.task_name || r.task_code || "",
        render: (_v, r) => r.task_name || r.task_code || "—",
      },
      {
        key: "target_entity",
        title: t("page.routine.col_target", "Target"),
        minWidth: 110,
        value: (r) => r.target_entity || "",
        render: (_v, r) => r.target_entity || "—",
      },
      {
        key: "confidence",
        title: t("page.routine.col_confidence", "Confidence"),
        width: 100,
        align: "right",
        sortable: true,
        value: (r) => r.confidence,
        render: (_v, r) =>
          r.confidence === null || r.confidence === undefined
            ? "—"
            : `${Math.round(r.confidence * 100)}%`,
      },
      {
        key: "status",
        title: t("page.routine.col_status", "Status"),
        width: 110,
        sortable: true,
        value: (r) => r.status,
        render: (_v, r) => <StatusBadge status={r.status} />,
      },
      {
        key: "created_at",
        title: t("page.routine.col_created", "Created"),
        minWidth: 140,
        sortable: true,
        value: (r) => r.created_at || "",
        render: (_v, r) => (r.created_at ? formatInTz(r.created_at) : "—"),
      },
      {
        key: "actions",
        title: "",
        width: 100,
        render: (_v, r) => (
          <span className="row-actions" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => void openDetail(r.id)}
              aria-label={t("page.routine.open_detail", "Open draft")}
            >
              {t("page.routine.open", "Open")}
            </button>
          </span>
        ),
      },
    ],
    [t, openDetail],
  );

  const taskColumns = useMemo<ColumnDef<TaskOut>[]>(
    () => [
      { key: "code", title: t("page.routine.col_code", "Code"), minWidth: 160, value: (r) => r.code },
      { key: "name", title: t("page.routine.col_name", "Name"), minWidth: 200, value: (r) => r.name },
      {
        key: "module_code",
        title: t("page.routine.col_module", "Module"),
        width: 120,
        value: (r) => r.module_code,
      },
      {
        key: "skill_code",
        title: t("page.routine.col_skill", "Skill"),
        minWidth: 140,
        value: (r) => r.skill_code,
      },
      {
        key: "owner_role",
        title: t("page.routine.col_owner", "Owner role"),
        width: 130,
        value: (r) => r.owner_role,
      },
      {
        key: "sla_minutes",
        title: t("page.routine.col_sla", "SLA (min)"),
        width: 110,
        align: "right",
        value: (r) => r.sla_minutes,
      },
      {
        key: "enabled",
        title: t("page.routine.col_enabled", "Enabled"),
        width: 100,
        value: (r) => r.enabled,
        render: (_v, r) => (
          <StatusBadge status={r.enabled ? "active" : "inactive"} />
        ),
      },
      {
        key: "actions",
        title: "",
        width: 210,
        render: (_v, r) => (
          <span className="row-actions" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              className="btn btn-sm"
              disabled={busy}
              onClick={() => void runTask(r)}
            >
              {t("page.routine.run_now", "Run now")}
            </button>
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => void openRules(r)}>
              {t("page.routine.triggers", "Triggers")}
            </button>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              onClick={() =>
                setTaskDraft({
                  id: r.id,
                  code: r.code,
                  name: r.name,
                  module_code: r.module_code,
                  skill_code: r.skill_code,
                  output_target: r.output_target || "",
                  owner_role: r.owner_role,
                  sla_minutes: String(r.sla_minutes),
                  enabled: r.enabled,
                })
              }
            >
              {t("common.edit", "Edit")}
            </button>
          </span>
        ),
      },
    ],
    [t, runTask, openRules, busy],
  );

  const skillColumns = useMemo<ColumnDef<SkillOut>[]>(
    () => [
      { key: "code", title: t("page.routine.col_code", "Code"), minWidth: 160, value: (r) => r.code },
      { key: "name", title: t("page.routine.col_name", "Name"), minWidth: 200, value: (r) => r.name },
      {
        key: "scope",
        title: t("page.routine.col_scope", "Scope"),
        width: 110,
        value: (r) => r.scope,
        render: (_v, r) => (
          <StatusBadge
            status={r.scope === "platform" ? "active" : "draft"}
            label={r.scope === "platform" ? t("page.routine.platform", "Platform") : t("page.routine.tenant", "Tenant")}
          />
        ),
      },
      {
        key: "deterministic_engine",
        title: t("page.routine.col_engine", "Engine"),
        minWidth: 150,
        value: (r) => r.deterministic_engine || "",
        render: (_v, r) =>
          r.deterministic_engine || t("page.routine.no_engine", "None — model driven"),
      },
      {
        key: "version",
        title: t("page.routine.col_version", "Version"),
        width: 90,
        align: "right",
        value: (r) => r.version,
      },
      {
        key: "enabled",
        title: t("page.routine.col_enabled", "Enabled"),
        width: 100,
        value: (r) => r.enabled,
        render: (_v, r) => <StatusBadge status={r.enabled ? "active" : "inactive"} />,
      },
      {
        key: "actions",
        title: "",
        width: 100,
        render: (_v, r) => (
          <span className="row-actions" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => setSkillView(r)}
              aria-label={t("page.routine.open_skill", "Open skill template")}
            >
              {t("page.routine.open", "Open")}
            </button>
          </span>
        ),
      },
    ],
    [t],
  );

  // ── 渲染 ───────────────────────────────────────────────────────────────

  const tabs: TabItem[] = [
    { key: "drafts", label: t("page.routine.tab_drafts", "Drafts") },
    { key: "tasks", label: t("page.routine.tab_tasks", "Routine tasks") },
    { key: "skills", label: t("page.routine.tab_skills", "Skill templates") },
  ];

  const pages = Math.max(1, Math.ceil(draftTotal / limit));
  const evidenceByField = useMemo(() => {
    const map: Record<string, Evidence> = {};
    for (const ev of detail?.evidence || []) map[ev.field] = ev;
    return map;
  }, [detail]);
  const fieldKeys = useMemo(() => Object.keys(values), [values]);
  const warnings = detail?.field_diff?.warnings || [];
  const dropped = detail?.field_diff?.dropped_without_evidence || [];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.routine", "Routine Tasks") }]}
        title={t("page.routine.title", "Routine task hub")}
        subtitle={t(
          "page.routine.sub",
          "Inbound mail turns into reviewed drafts — nothing is written to the books until a human confirms it.",
        )}
        actions={<PageGuide pageKey="routine_hub" />}
      />

      <Tabs
        items={tabs}
        value={tab}
        onChange={(k) => setQuery({ tab: k === "drafts" ? null : k }, { resetPage: true })}
        variant="pill"
      />

      {tab === "drafts" ? (
        <>
          <Toolbar
            filterCount={statusFilter || taskFilter ? 1 : 0}
            onClearFilters={() => setQuery({ status: null, task_code: null }, { resetPage: true })}
            right={
              <select
                className="input input-sm"
                value={statusFilter}
                aria-label={t("page.routine.filter_status", "Filter by status")}
                onChange={(e) => setQuery({ status: e.target.value || null }, { resetPage: true })}
              >
                <option value="">{t("page.routine.all_statuses", "All statuses")}</option>
                {DRAFT_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            }
          >
            <div className="row-actions">
              {["", ...DRAFT_STATUSES].map((s) => (
                <button
                  key={s || "all"}
                  type="button"
                  className={`btn btn-sm${statusFilter === s ? " btn-primary" : ""}`}
                  onClick={() => setQuery({ status: s || null }, { resetPage: true })}
                >
                  {s === "" ? t("page.routine.filter_all", "All") : s}
                </button>
              ))}
            </div>
          </Toolbar>

          <div className="panel">
            <StateView
              loading={draftsLoading}
              error={draftsError || undefined}
              empty={!draftsLoading && !draftsError && sortedDrafts.length === 0}
              emptyText={t("page.routine.empty_drafts", "No pending drafts for your role.")}
              onRetry={() => void loadDrafts()}
            >
              <DataGrid<DraftOut>
                columns={draftColumns}
                data={sortedDrafts}
                rowKey={(r) => r.id}
                onRowClick={(r) => void openDetail(r.id)}
                onSortChange={onSortChange}
                storageKey="routine_drafts_grid"
                showFooter={false}
                emptyText={t("page.routine.empty_drafts", "No pending drafts for your role.")}
              />
            </StateView>
            <div className="dt-pager">
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                disabled={page <= 1}
                onClick={() => setQuery({ page: page - 1 })}
                aria-label={t("common.prev_page", "Previous page")}
              >
                ←
              </button>
              <span className="muted">
                {t("page.routine.page_of", "Page {page} / {pages}", { page, pages })}
              </span>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                disabled={page >= pages}
                onClick={() => setQuery({ page: page + 1 })}
                aria-label={t("common.next_page", "Next page")}
              >
                →
              </button>
              <span className="muted">
                {t("page.routine.total_drafts", "{n} draft(s)", { n: draftTotal })}
              </span>
            </div>
          </div>
        </>
      ) : null}

      {tab === "tasks" ? (
        <>
          <Toolbar
            right={
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => setTaskDraft({ ...EMPTY_TASK })}
              >
                {t("page.routine.new_task", "New routine task")}
              </button>
            }
          >
            <span className="muted">{t("page.routine.tasks_hint", "Automation always keeps a manual trigger.")}</span>
          </Toolbar>

          <div className="panel">
            <StateView
              loading={tasksLoading}
              error={tasksError || undefined}
              empty={!tasksLoading && !tasksError && tasks.length === 0}
              emptyText={t("page.routine.empty_tasks", "No routine tasks configured for this tenant.")}
              onRetry={() => void loadTasks()}
            >
              <DataGrid<TaskOut>
                columns={taskColumns}
                data={tasks}
                rowKey={(r) => r.id}
                storageKey="routine_tasks_grid"
                showFooter={false}
                emptyText={t("page.routine.empty_tasks", "No routine tasks configured for this tenant.")}
              />
            </StateView>
          </div>
        </>
      ) : null}

      {tab === "skills" ? (
        <>
          <div className="panel">
            <StateView
              loading={skillsLoading}
              error={skillsError || undefined}
              empty={!skillsLoading && !skillsError && skills.length === 0}
              emptyText={t("page.routine.empty_skills", "No skill templates available.")}
              onRetry={() => void loadSkills()}
            >
              <DataGrid<SkillOut>
                columns={skillColumns}
                data={skills}
                rowKey={(r) => r.id}
                storageKey="routine_skills_grid"
                showFooter={false}
                emptyText={t("page.routine.empty_skills", "No skill templates available.")}
              />
            </StateView>
          </div>
        </>
      ) : null}

      {/* 草稿详情（只读 + 逐字段确认） */}
      <RecordModal
        open={Boolean(detail)}
        title={detail?.task_name || t("page.routine.draft_title", "Draft")}
        onClose={() => setDetail(null)}
        canEdit={false}
        canDelete={false}
        size="lg"
      >
        {detailLoading ? (
          <p className="muted">{t("common.loading", "Loading…")}</p>
        ) : detail ? (
          <>
            <div className="ws-kv-grid">
              <div className="ws-kv">
                <span className="muted">{t("page.routine.kv_task", "Routine task")}</span>
                <strong>
                  {detail.task_name} ({detail.task_code})
                </strong>
              </div>
              <div className="ws-kv">
                <span className="muted">{t("page.routine.kv_status", "Status")}</span>
                <strong>
                  <StatusBadge status={detail.status} />
                </strong>
              </div>
              <div className="ws-kv">
                <span className="muted">{t("page.routine.kv_owner", "Owner role")}</span>
                <strong>{detail.owner_role}</strong>
              </div>
              <div className="ws-kv">
                <span className="muted">{t("page.routine.kv_confidence", "Confidence")}</span>
                <strong>
                  {detail.confidence === null || detail.confidence === undefined
                    ? "—"
                    : `${Math.round(detail.confidence * 100)}%`}
                </strong>
              </div>
              <div className="ws-kv">
                <span className="muted">{t("page.routine.kv_created", "Created")}</span>
                <strong>{detail.created_at ? formatInTz(detail.created_at) : "—"}</strong>
              </div>
              <div className="ws-kv">
                <span className="muted">{t("page.routine.kv_source", "Source mail")}</span>
                <strong>
                  {detail.source_email?.subject || "—"}
                  {detail.source_email?.from_email ? ` · ${detail.source_email.from_email}` : ""}
                </strong>
              </div>
            </div>

            {detail.error ? (
              <p className="flash-warn">
                {t("page.routine.draft_error", "Processing failed")}: {detail.error}
              </p>
            ) : null}
            {warnings.map((w) => (
              <p className="flash-warn" key={w}>
                {w}
              </p>
            ))}
            {dropped.length ? (
              <p className="muted">
                {t("page.routine.dropped_fields", "Dropped for lack of evidence")}: {dropped.join(", ")}
              </p>
            ) : null}
            {detail.can_confirm === false && detail.blocked_reason ? (
              <p className="flash-warn">{detail.blocked_reason}</p>
            ) : null}

            <div className="form-section-title">
              {t("page.routine.fields_title", "Fields to write")}
            </div>
            <p className="muted">
              {t(
                "page.routine.fields_hint",
                "Only checked fields are written — unchecked fields are neither stored nor used in any calculation.",
              )}
            </p>
            <ul className="ai-extract-list">
              {fieldKeys.length === 0 ? (
                <li className="muted">{t("page.routine.no_fields", "No fields extracted.")}</li>
              ) : null}
              {fieldKeys.map((key) => {
                const ev = evidenceByField[key];
                return (
                  <li key={key} className="ai-extract-row">
                    <input
                      type="checkbox"
                      checked={checked.has(key)}
                      onChange={() => toggleField(key)}
                      aria-label={key}
                    />
                    <span className="ai-extract-key">{key}</span>
                    {isStructuredValue(values[key]) ? (
                      /* 结构化值（SOF 事件列表这类）不能塞进单行输入框 ——
                         String([{...}]) 只会显示 "[object Object]"，复核人看不到内容。
                         这里只读展开 JSON，值本身原样带出去（落库仍用原值）。 */
                      <pre className="ai-extract-json">{formatStructuredValue(values[key])}</pre>
                    ) : (
                      <input
                        className="ai-extract-val"
                        value={String(values[key] ?? "")}
                        onChange={(e) => {
                          const raw = e.target.value;
                          const num = Number(raw);
                          setValues((prev) => ({
                            ...prev,
                            [key]: raw !== "" && Number.isFinite(num) ? num : raw,
                          }));
                        }}
                      />
                    )}
                    {ev?.quote ? (
                      <span className="hint" title={ev.quote}>
                        {ev.quote.slice(0, 60)}
                      </span>
                    ) : null}
                    {ev?.extracted_by ? (
                      <span className="badge">{ev.extracted_by}</span>
                    ) : null}
                  </li>
                );
              })}
            </ul>

            {detail.source_email?.body_excerpt ? (
              <>
                <div className="form-section-title">
                  {t("page.routine.source_text", "Original mail")}
                </div>
                <pre className="email-detail-body">{detail.source_email.body_excerpt}</pre>
                {detail.source_email.body_truncated ? (
                  <p className="muted">
                    {t("page.routine.source_truncated", "… truncated for display")}
                  </p>
                ) : null}
              </>
            ) : null}

            <div className="row-actions">
              <button
                type="button"
                className="btn btn-primary btn-sm"
                disabled={busy || detail.status !== "pending" || detail.can_confirm === false}
                title={detail.blocked_reason || undefined}
                onClick={() => setConfirmAdopt(true)}
              >
                {t("page.routine.adopt", "Adopt selected fields")}
              </button>
              <button
                type="button"
                className="btn btn-sm"
                disabled={busy || !["pending", "failed"].includes(detail.status)}
                onClick={() => void reprocess()}
              >
                {t("page.routine.reprocess", "Re-process")}
              </button>
            </div>

            <label>
              {t("page.routine.reject_reason", "Reject reason")}
              <input
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                placeholder={t("page.routine.reject_reason_hint", "Why is this draft wrong?")}
              />
            </label>
            <div className="row-actions">
              <button
                type="button"
                className="btn btn-danger btn-sm"
                disabled={busy || !["pending", "failed"].includes(detail.status)}
                onClick={() => void reject()}
              >
                {t("page.routine.reject", "Reject")}
              </button>
            </div>
          </>
        ) : null}
      </RecordModal>

      {/* 采纳会写业务表 —— 二次确认 */}
      <ConfirmDialog
        open={confirmAdopt}
        title={t("common.confirm", "Confirm")}
        message={t(
          "page.routine.adopt_confirm",
          "Write the checked fields into the business records? This creates real data.",
        )}
        confirmLabel={t("page.routine.adopt", "Adopt selected fields")}
        onConfirm={() => void adopt()}
        onCancel={() => setConfirmAdopt(false)}
      />

      {/* 任务编辑 */}
      <RecordModal
        open={Boolean(taskDraft)}
        title={taskDraft?.id ? t("page.routine.edit_task", "Edit routine task") : t("page.routine.new_task", "New routine task")}
        onClose={() => setTaskDraft(null)}
        onSave={saveTask}
        saving={busy}
      >
        {!taskDraft?.id ? (
          <label>
            {t("page.routine.field_code", "Code")}
            <input
              value={taskDraft?.code || ""}
              required
              onChange={(e) => setTaskDraft((d) => (d ? { ...d, code: e.target.value } : d))}
            />
          </label>
        ) : null}
        <label>
          {t("page.routine.field_name", "Name")}
          <input
            value={taskDraft?.name || ""}
            required
            onChange={(e) => setTaskDraft((d) => (d ? { ...d, name: e.target.value } : d))}
          />
        </label>
        <label>
          {t("page.routine.field_module", "Module code")}
          <input
            value={taskDraft?.module_code || ""}
            required
            onChange={(e) => setTaskDraft((d) => (d ? { ...d, module_code: e.target.value } : d))}
          />
        </label>
        <label>
          {t("page.routine.field_skill", "Skill template code")}
          <input
            value={taskDraft?.skill_code || ""}
            required
            onChange={(e) => setTaskDraft((d) => (d ? { ...d, skill_code: e.target.value } : d))}
          />
        </label>
        <label>
          {t("page.routine.field_target", "Output target")}
          <select
            value={taskDraft?.output_target || ""}
            onChange={(e) => setTaskDraft((d) => (d ? { ...d, output_target: e.target.value } : d))}
          >
            <option value="">{t("page.routine.no_target", "None")}</option>
            <option value="noon_report">noon_report</option>
            <option value="laytime_calc">laytime_calc</option>
            <option value="estimate">estimate</option>
          </select>
        </label>
        <label>
          {t("page.routine.field_owner", "Owner role")}
          <input
            value={taskDraft?.owner_role || ""}
            required
            onChange={(e) => setTaskDraft((d) => (d ? { ...d, owner_role: e.target.value } : d))}
          />
        </label>
        <label>
          {t("page.routine.field_sla", "SLA (minutes)")}
          <input
            type="number"
            min={1}
            value={taskDraft?.sla_minutes || ""}
            onChange={(e) => setTaskDraft((d) => (d ? { ...d, sla_minutes: e.target.value } : d))}
          />
        </label>
        <label className="check-row">
          <input
            type="checkbox"
            checked={taskDraft?.enabled ?? true}
            onChange={(e) => setTaskDraft((d) => (d ? { ...d, enabled: e.target.checked } : d))}
          />
          {t("page.routine.field_enabled", "Enabled")}
        </label>
      </RecordModal>

      {/* 触发规则 */}
      <RecordModal
        open={Boolean(rulesTask)}
        title={t("page.routine.triggers_title", "Trigger rules — {code}", { code: rulesTask?.code || "" })}
        onClose={() => setRulesTask(null)}
        onSave={saveRules}
        saving={busy}
        size="lg"
      >
        {rulesLoading ? <p className="muted">{t("common.loading", "Loading…")}</p> : null}
        {!rulesLoading && rules.length === 0 ? (
          <p className="muted">
            {t(
              "page.routine.no_rules",
              "No trigger rules — this task never matches. A rule needs at least one condition.",
            )}
          </p>
        ) : null}
        {rules.map((rule, idx) => (
          <div key={idx} className="panel">
            <div className="form-section-title">
              {t("page.routine.rule_n", "Rule {n}", { n: idx + 1 })}
            </div>
            <label>
              {t("page.routine.rule_senders", "Sender emails (comma separated)")}
              <input
                value={listToCsv(rule.sender_emails)}
                onChange={(e) =>
                  setRules((prev) =>
                    prev.map((r, i) =>
                      i === idx ? { ...r, sender_emails: csvToList(e.target.value) } : r,
                    ),
                  )
                }
              />
            </label>
            <label>
              {t("page.routine.rule_domains", "Sender domains (comma separated)")}
              <input
                value={listToCsv(rule.sender_domains)}
                onChange={(e) =>
                  setRules((prev) =>
                    prev.map((r, i) =>
                      i === idx ? { ...r, sender_domains: csvToList(e.target.value) } : r,
                    ),
                  )
                }
              />
            </label>
            <label>
              {t("page.routine.rule_subject", "Subject regex")}
              <input
                value={rule.subject_regex || ""}
                onChange={(e) =>
                  setRules((prev) =>
                    prev.map((r, i) =>
                      i === idx ? { ...r, subject_regex: e.target.value || null } : r,
                    ),
                  )
                }
              />
            </label>
            <label>
              {t("page.routine.rule_markers", "Body markers (comma separated)")}
              <input
                value={listToCsv(rule.body_markers)}
                onChange={(e) =>
                  setRules((prev) =>
                    prev.map((r, i) =>
                      i === idx ? { ...r, body_markers: csvToList(e.target.value) } : r,
                    ),
                  )
                }
              />
            </label>
            <label>
              {t("page.routine.rule_folder", "Folder")}
              <select
                value={rule.folder || "*"}
                onChange={(e) =>
                  setRules((prev) =>
                    prev.map((r, i) => (i === idx ? { ...r, folder: e.target.value } : r)),
                  )
                }
              >
                {FOLDER_OPTIONS.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("page.routine.rule_direction", "Direction")}
              <select
                value={rule.direction || "*"}
                onChange={(e) =>
                  setRules((prev) =>
                    prev.map((r, i) => (i === idx ? { ...r, direction: e.target.value } : r)),
                  )
                }
              >
                {DIRECTION_OPTIONS.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </label>
            <label className="check-row">
              <input
                type="checkbox"
                checked={rule.enabled !== false}
                onChange={(e) =>
                  setRules((prev) =>
                    prev.map((r, i) => (i === idx ? { ...r, enabled: e.target.checked } : r)),
                  )
                }
              />
              {t("page.routine.rule_enabled", "Enabled")}
            </label>
            <button
              type="button"
              className="btn btn-sm btn-danger"
              onClick={() => setRules((prev) => prev.filter((_r, i) => i !== idx))}
            >
              {t("page.routine.rule_remove", "Remove rule")}
            </button>
          </div>
        ))}
        <button
          type="button"
          className="btn btn-sm"
          onClick={() =>
            setRules((prev) => [
              ...prev,
              {
                sender_emails: [],
                sender_domains: [],
                subject_regex: null,
                body_markers: [],
                folder: "*",
                direction: "inbound",
                priority: 100,
                enabled: true,
              },
            ])
          }
        >
          {t("page.routine.rule_add", "Add rule")}
        </button>
      </RecordModal>

      {/* 技能模板（只读契约）*/}
      <RecordModal
        open={Boolean(skillView)}
        title={skillView ? `${skillView.name} (${skillView.code})` : ""}
        onClose={() => setSkillView(null)}
        canEdit={false}
        canDelete={false}
        size="lg"
      >
        {skillView ? (
          <>
            <div className="ws-kv-grid">
              <div className="ws-kv">
                <span className="muted">{t("page.routine.kv_scope", "Scope")}</span>
                <strong>
                  {skillView.scope === "platform"
                    ? t("page.routine.platform", "Platform")
                    : t("page.routine.tenant", "Tenant")}
                </strong>
              </div>
              <div className="ws-kv">
                <span className="muted">{t("page.routine.kv_kind", "Extraction kind")}</span>
                <strong>{skillView.output_schema?.kind || "—"}</strong>
              </div>
              <div className="ws-kv">
                <span className="muted">{t("page.routine.kv_engine", "Deterministic engine")}</span>
                <strong>
                  {skillView.deterministic_engine ||
                    t("page.routine.no_engine", "None — model driven")}
                </strong>
              </div>
              <div className="ws-kv">
                <span className="muted">{t("page.routine.kv_purpose", "Purpose")}</span>
                <strong>{skillView.purpose || "—"}</strong>
              </div>
            </div>

            <div className="form-section-title">
              {t("page.routine.contract", "Field contract")}
            </div>
            <dl className="parse-kv">
              {Object.entries(skillView.output_schema?.fields || {}).map(([name, spec]) => {
                const range = skillView.validator_rules?.ranges?.[name];
                const required =
                  (skillView.output_schema?.required || []).includes(name) || spec.required;
                return (
                  <div key={name}>
                    <dt>{name}</dt>
                    <dd>
                      {spec.type || "string"} ·{" "}
                      {required ? t("common.yes", "Yes") : t("page.routine.optional", "Optional")} ·{" "}
                      {range ? `${range[0]} – ${range[1]}` : t("page.routine.no_range", "no range")}
                    </dd>
                  </div>
                );
              })}
            </dl>

            {skillView.scope === "platform" ? (
              <p className="muted">
                {t(
                  "page.routine.platform_readonly",
                  "Platform templates are read-only — copy one into a tenant skill to tighten its validation.",
                )}
              </p>
            ) : null}
          </>
        ) : null}
      </RecordModal>
    </AppShell>
  );
}

export default function RoutinePage() {
  return (
    <Suspense fallback={null}>
      <RoutinePageInner />
    </Suspense>
  );
}
