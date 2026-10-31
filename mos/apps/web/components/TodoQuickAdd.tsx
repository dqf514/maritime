"use client";

// 快速添加个人待办 —— 右键菜单 / 工作台按钮通用。
// 用法：const todo = useTodoAdd(); 菜单项里放 todo.menuItem({...})，页面尾部渲染 {todo.element}。

import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { RecordModal } from "@/components/RecordModal";
import { useToast } from "@/components/ToastProvider";
import type { ContextMenuItem } from "@/components/ContextMenu";
import { apiGet, apiPost, type ActionSpec } from "@/lib/api";
import { fromUtcInput } from "@/lib/datetime";
import { useI18n } from "@/lib/i18n";

export type TodoTarget = {
  /** 关联实体类型：voyage | invoice | charter | cargo | ... */
  entityType: string;
  entityId: string;
  /** 预填标题（通常为单号/名称） */
  title: string;
  /** 可选：补充说明（如 "Follow up on demurrage"） */
  hint?: string;
};

type Draft = {
  title: string;
  description: string;
  priority: "low" | "normal" | "high" | "urgent";
  due_at: string;
  /** 绑定的系统动作 —— 动作在系统里做完了，待办自动勾完成 */
  action_code: string;
};

const EMPTY: Draft = { title: "", description: "", priority: "normal", due_at: "", action_code: "" };

export function useTodoAdd() {
  const { t } = useI18n();
  const toast = useToast();
  const [target, setTarget] = useState<TodoTarget | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [saving, setSaving] = useState(false);
  /** 系统动作目录（只取与本单据类型匹配的动作） */
  const [catalog, setCatalog] = useState<ActionSpec[]>([]);

  const openFor = useCallback((next: TodoTarget) => {
    setTarget(next);
    setDraft({ ...EMPTY, title: next.title, description: next.hint ?? "" });
  }, []);

  // 打开弹窗时取一次动作目录 —— 只展示与本单据类型对得上的动作
  useEffect(() => {
    if (!target) return;
    apiGet("/api/v1/tasks/action-catalog")
      .then((rows) => setCatalog(Array.isArray(rows) ? (rows as ActionSpec[]) : []))
      .catch(() => setCatalog([]));
  }, [target]);

  /** 右键菜单项：添加到我的待办 */
  const menuItem = useCallback(
    (next: TodoTarget): ContextMenuItem => ({
      key: "add-todo",
      label: t("ctx.add_todo", "Add to my todos"),
      onClick: () => openFor(next),
    }),
    [openFor, t],
  );

  async function save(e?: FormEvent) {
    e?.preventDefault();
    if (!target || !draft.title.trim()) return;
    setSaving(true);
    try {
      await apiPost("/api/v1/tasks", {
        title: draft.title.trim(),
        description: draft.description.trim() || null,
        priority: draft.priority,
        // 输入框是 UTC 墙钟（平台约定：naive = UTC）——用 fromUtcInput 回写，
        // 避免 new Date() 按浏览器本地时区解释造成整点偏移。
        due_at: fromUtcInput(draft.due_at),
        entity_type: target.entityType,
        entity_id: target.entityId,
        action_code: draft.action_code || null,
      });
      toast.success(t("todo.created", "Added to my todos"));
      setTarget(null);
    } catch (ex: any) {
      toast.error(ex?.message || t("common.failed", "Failed"));
    } finally {
      setSaving(false);
    }
  }

  const element: ReactNode = (
    <RecordModal
      open={!!target}
      title={t("todo.modal_title", "Add to my todos")}
      onClose={() => setTarget(null)}
      onSave={save}
      canDelete={false}
      saving={saving}
    >
      {/* RecordModal 自带 <form> 包裹 —— 这里只放字段网格，避免嵌套 form */}
      <div className="form-grid">
        <label className="span-all">
          {t("common.title", "Title")}
          <input
            value={draft.title}
            onChange={(e) => setDraft({ ...draft, title: e.target.value })}
            required
            autoFocus
          />
        </label>
        <label className="span-all">
          {t("common.description", "Description")}
          <textarea
            rows={2}
            value={draft.description}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
          />
        </label>
        <label>
          {t("page.tasks.priority", "Priority")}
          <select
            value={draft.priority}
            onChange={(e) => setDraft({ ...draft, priority: e.target.value as Draft["priority"] })}
          >
            <option value="low">{t("page.tasks.priority.low", "Low")}</option>
            <option value="normal">{t("page.tasks.priority.normal", "Normal")}</option>
            <option value="high">{t("page.tasks.priority.high", "High")}</option>
            <option value="urgent">{t("page.tasks.priority.urgent", "Urgent")}</option>
          </select>
        </label>
        <label>
          {t("page.tasks.due", "Due date")}
          <input
            type="datetime-local"
            value={draft.due_at}
            onChange={(e) => setDraft({ ...draft, due_at: e.target.value })}
          />
        </label>
        {target ? (
          <p className="muted span-all">
            {t("todo.linked_hint", "Linked to {e} — open it from the task inbox.", { e: target.entityType })}
          </p>
        ) : null}
        <label className="span-all">
          {t("todo.action_label", "System action (auto-complete when done)")}
          <select
            value={draft.action_code}
            onChange={(e) => setDraft({ ...draft, action_code: e.target.value })}
          >
            <option value="">{t("todo.action_none", "None")}</option>
            {catalog
              .filter((a) => a.entity_type === target?.entityType)
              .map((a) => (
                <option key={a.code} value={a.code}>
                  {a.label}
                </option>
              ))}
          </select>
        </label>
        {draft.action_code ? (
          <p className="muted span-all">
            {t(
              "todo.action_hint",
              "When this action is completed in the system, the todo is ticked automatically.",
            )}
          </p>
        ) : null}
      </div>
    </RecordModal>
  );

  return useMemo(() => ({ openFor, menuItem, element }), [openFor, menuItem, element]);
}
