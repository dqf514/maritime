"use client";

import { useState } from "react";
import { apiPost } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";

/**
 * AiFill —— 表单内「一键 AI 填充」。
 *
 * 点击后调 `/ai/assist/fill` 取回字段建议，**先展示给用户逐项确认，
 * 再由 onApply 写回表单**；本组件自身不提交任何数据。
 */

type Props = {
  task?: "fill_form" | "summarize" | "daily_report" | "draft_note" | "explain";
  /** 当前表单字段快照（值作为 AI 的参考上下文） */
  formFields?: Record<string, unknown>;
  /** 实体上下文（填写则 AI 能带上该记录的既有字段） */
  entityType?: string;
  entityId?: string;
  /** 用户确认后回调；不传则只展示建议文本 */
  onApply?: (suggestions: Record<string, unknown>) => void;
  /** 额外指令，例如「按租约条款填」 */
  instruction?: string;
  label?: string;
};

export function AiFill({
  task = "fill_form",
  formFields,
  entityType,
  entityId,
  onApply,
  instruction,
  label,
}: Props) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [suggestions, setSuggestions] = useState<Record<string, unknown> | null>(null);
  const [narrative, setNarrative] = useState<string | null>(null);
  const [source, setSource] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const res = (await apiPost("/api/v1/ai/assist/fill", {
        task,
        form_fields: formFields,
        instruction,
        context: entityType && entityId ? { entity_type: entityType, entity_id: entityId } : undefined,
      })) as { suggestions: Record<string, unknown>; narrative: string; source: string };
      setSuggestions(res.suggestions || {});
      setNarrative(res.narrative || null);
      setSource(res.source || null);
    } catch (ex: any) {
      setError(msgOf(ex, t("ai.fill.fail", "AI 填充失败")));
    } finally {
      setBusy(false);
    }
  }

  const entries = suggestions ? Object.entries(suggestions).filter(([, v]) => v !== null && v !== "") : [];

  return (
    <span className="ai-fill">
      <button
        type="button"
        className="btn btn-sm ai-fill-btn"
        disabled={busy}
        onClick={() => void run()}
        title={t("ai.fill.hint", "用 AI 生成建议值（需人工确认）")}
      >
        {busy ? "…" : "✦"} {label || t("ai.fill.btn", "AI 填充")}
      </button>

      {error ? <span className="ai-fill-error">{error}</span> : null}

      {suggestions !== null || narrative ? (
        <span className="ai-fill-pop" role="dialog" aria-label={t("ai.fill.title", "AI 建议")}>
          <span className="ai-fill-pop-head">
            {t("ai.fill.title", "AI 建议")}
            {source ? <span className="ai-fill-src">{source === "llm" ? "AI" : "rules"}</span> : null}
          </span>

          {source && source !== "llm" ? (
            <span className="ai-fill-note">
              {t(
                "ai.fill.rules_note",
                "AI 模型未配置或暂不可用 — 以上建议由内置规则生成。",
              )}
            </span>
          ) : null}

          {entries.length ? (
            <span className="ai-fill-rows">
              {entries.map(([k, v]) => (
                <span className="ai-fill-row" key={k}>
                  <span className="ai-fill-key">{k}</span>
                  <span className="ai-fill-val">{String(v)}</span>
                </span>
              ))}
            </span>
          ) : null}

          {narrative ? <span className="ai-fill-narrative">{narrative}</span> : null}

          <span className="ai-fill-actions">
            {entries.length && onApply ? (
              <button
                type="button"
                className="btn btn-sm btn-primary"
                onClick={() => {
                  onApply(suggestions || {});
                  setSuggestions(null);
                  setNarrative(null);
                }}
              >
                {t("ai.fill.apply", "应用到表单")}
              </button>
            ) : null}
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => {
                setSuggestions(null);
                setNarrative(null);
              }}
            >
              {t("common.cancel", "取消")}
            </button>
          </span>
        </span>
      ) : null}
    </span>
  );
}
