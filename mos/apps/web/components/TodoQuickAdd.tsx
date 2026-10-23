"use client";

// 快速添加个人待办 —— 右键菜单 / 工作台按钮通用。
// 用法：const todo = useTodoAdd(); 菜单项里放 todo.menuItem({...})，页面尾部渲染 {todo.element}。

import { FormEvent, ReactNode, useCallback, useMemo, useState } from "react";
import { RecordModal } from "@/components/RecordModal";
import { useToast } from "@/components/ToastProvider";
import type { ContextMenuItem } from "@/components/ContextMenu";
import { apiPost } from "@/lib/api";
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
};

const EMPTY: Draft = { title: "", description: "", priority: "normal", due_at: "" };

export function useTodoAdd() {
  const { t } = useI18n();
  const toast = useToast();
  const [target, setTarget] = useState<TodoTarget | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [saving, setSaving] = useState(false);

  const openFor = useCallback((next: TodoTarget) => {
    setTarget(next);
    setDraft({ ...EMPTY, title: next.title, description: next.hint ?? "" });
  }, []);

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
        due_at: draft.due_at ? new Date(draft.due_at).toISOString() : null,
        entity_type: target.entityType,
        entity_id: target.entityId,
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
      </div>
    </RecordModal>
  );

  return useMemo(() => ({ openFor, menuItem, element }), [openFor, menuItem, element]);
}
