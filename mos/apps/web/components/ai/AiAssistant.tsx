"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAiContext } from "./aiContextStore";

/**
 * Mari Copilot —— 全局弹出式 AI 助手。
 *
 * 右下角悬浮按钮（或 Ctrl+J）唤起滑出面板；自动带上当前页面/实体上下文，
 * 支持问答与一键总结/日报。**AI 只建议，人工确认**：面板不写任何业务数据。
 *
 * 计费：平台公用网关按量付费时后端返回 402 QUOTA_EXCEEDED，此处给出充值提示。
 */

type Msg = { role: "user" | "assistant"; text: string; source?: string };

type Status = {
  available: boolean;
  provider: string | null;
  metering: boolean;
  balance: number | null;
  fallback_mode: string | null;
};

const QUICK_ACTIONS = [
  { task: "summarize", key: "ai.assist.quick_summarize" },
  { task: "daily_report", key: "ai.assist.quick_daily" },
  { task: "explain", key: "ai.assist.quick_explain" },
] as const;

export function AiAssistant() {
  const { t } = useI18n();
  const ctx = useAiContext();
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<Status | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [mounted, setMounted] = useState(false);
  // 已配置模型但本轮回落到规则引擎 → 给一条友好说明
  const [replyFallback, setReplyFallback] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => setMounted(true), []);

  // Ctrl+J 切换；输入框内不拦截（沿用 OmniSearch 的 inEditable 守卫）
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && (e.key === "j" || e.key === "J")) {
        e.preventDefault();
        setOpen((o) => !o);
        return;
      }
      if (e.key === "Escape" && open) {
        const tag = (e.target as HTMLElement)?.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // 打开时拉一次可用性（含计费余额）
  useEffect(() => {
    if (!open || status) return;
    apiGet("/api/v1/ai/assist/status")
      .then((s: Status) => setStatus(s))
      .catch(() => setStatus({ available: false, provider: null, metering: false, balance: null, fallback_mode: "rules" }));
  }, [open, status]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [msgs, busy]);

  function contextPayload() {
    return {
      page: ctx?.page || (typeof window !== "undefined" ? window.location.pathname : undefined),
      entity_type: ctx?.entity_type,
      entity_id: ctx?.entity_id,
    };
  }

  async function ask(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    setInput("");
    setMsgs((m) => [...m, { role: "user", text: q }]);
    setBusy(true);
    try {
      const res = (await apiPost("/api/v1/ai/assist/ask", {
        message: q,
        context: contextPayload(),
      })) as { response: string; source?: string };
      if (res.source && res.source !== "llm" && status?.available !== false) setReplyFallback(true);
      setMsgs((m) => [...m, { role: "assistant", text: res.response || "—", source: res.source }]);
    } catch (ex: any) {
      const quota = ex?.status === 402 || ex?.code === "QUOTA_EXCEEDED";
      setMsgs((m) => [
        ...m,
        {
          role: "assistant",
          text: quota
            ? t("ai.assist.quota_exceeded", "AI 额度不足 — 请在设置中充值或改用租户自有 API Key。")
            : ex?.message || t("ai.assist.error", "请求失败，请重试。"),
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  async function runQuick(task: (typeof QUICK_ACTIONS)[number]["task"]) {
    if (busy) return;
    setBusy(true);
    try {
      const res = (await apiPost("/api/v1/ai/assist/fill", {
        task,
        context: contextPayload(),
      })) as { narrative: string; source?: string };
      if (res.source && res.source !== "llm" && status?.available !== false) setReplyFallback(true);
      setMsgs((m) => [
        ...m,
        { role: "user", text: t(`ai.assist.${task}`, task.replace("_", " ")) },
        { role: "assistant", text: res.narrative || "—", source: res.source },
      ]);
    } catch (ex: any) {
      setMsgs((m) => [...m, { role: "assistant", text: ex?.message || t("ai.assist.error", "请求失败，请重试。") }]);
    } finally {
      setBusy(false);
    }
  }

  if (!mounted) return null;

  return createPortal(
    <>
      <button
        type="button"
        className="ai-fab"
        title={`${t("ai.assist.open", "AI 助手")} (Ctrl+J)`}
        aria-label={t("ai.assist.open", "AI 助手")}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        {open ? "×" : "✦"}
      </button>

      {open ? (
        <aside className="ai-dock" role="dialog" aria-label={t("ai.assist.title", "Mari Copilot")}>
          <div className="ai-dock-head">
            <span className="ai-dock-title">✦ {t("ai.assist.title", "Mari Copilot")}</span>
            <span className="ai-dock-meta">
              {status === null
                ? "…"
                : status.available
                  ? status.provider || t("ai.assist.ready", "就绪")
                  : t("ai.assist.fallback", "规则模式（未配置模型）")}
            </span>
            <button type="button" className="icon-btn" aria-label={t("ai.assist.close", "关闭")} onClick={() => setOpen(false)}>
              ×
            </button>
          </div>

          <div className="ai-dock-ctx">
            {ctx?.entity_type
              ? t("ai.assist.ctx_record", "当前记录：{type}", { type: ctx.entity_type })
              : t("ai.assist.ctx_screen", "当前页面：{page}", { page: shortPage(ctx?.page) })}
          </div>

          {status !== null && !status.available ? (
            <div className="ai-dock-fallback-note" role="status">
              {t(
                "ai.assist.no_model_hint",
                "尚未配置 AI 模型 — 回复由内置规则生成。可在 设置 → AI 中配置模型以启用完整智能问答。",
              )}
            </div>
          ) : null}
          {status?.available && replyFallback ? (
            <div className="ai-dock-fallback-note" role="status">
              {t(
                "ai.assist.fallback_reply_hint",
                "模型本轮未响应 — 该回复由内置规则生成。可在 设置 → AI 检查模型连接。",
              )}
            </div>
          ) : null}

          <div className="ai-dock-list" ref={listRef}>
            {msgs.length === 0 ? (
              <p className="ai-dock-empty">
                {t(
                  "ai.assist.hint",
                  "问我关于当前记录的任何问题，或用下方按钮生成总结/日报。AI 只提建议，提交前请人工确认。",
                )}
              </p>
            ) : (
              msgs.map((m, i) => (
                <div key={i} className={`ai-msg ai-msg-${m.role}`}>
                  <div className="ai-msg-body">{m.text}</div>
                  {m.source ? (
                    <div
                      className="ai-msg-src"
                      title={
                        m.source === "llm"
                          ? t("ai.assist.llm_hint", "由已配置的 AI 模型生成")
                          : t("ai.assist.rules_hint", "内置规则应答（模型未配置或暂不可用）")
                      }
                    >
                      {m.source === "llm" ? "AI" : t("ai.assist.rules_badge", "rules")}
                    </div>
                  ) : null}
                </div>
              ))
            )}
            {busy ? <div className="ai-msg ai-msg-assistant ai-msg-busy">…</div> : null}
          </div>

          <div className="ai-dock-actions">
            {QUICK_ACTIONS.map((a) => (
              <button key={a.task} type="button" className="btn btn-sm" disabled={busy} onClick={() => runQuick(a.task).catch(() => undefined)}>
                {t(a.key, a.task.replace("_", " "))}
              </button>
            ))}
          </div>

          <form
            className="ai-dock-form"
            onSubmit={(e) => {
              e.preventDefault();
              ask(input).catch(() => undefined);
            }}
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={t("ai.assist.placeholder", "问点什么… (Enter 发送)")}
              aria-label={t("ai.assist.placeholder", "问点什么")}
            />
            <button type="submit" className="btn btn-primary btn-sm" disabled={busy || !input.trim()}>
              {t("ai.assist.send", "发送")}
            </button>
          </form>

          {status?.metering && status.balance != null ? (
            <div className="ai-dock-billing">
              {t("ai.assist.balance", "剩余额度：{n} tokens", { n: Math.round(status.balance) })}
            </div>
          ) : null}
        </aside>
      ) : null}
    </>,
    document.body,
  );
}

function shortPage(p?: string) {
  if (!p) return "—";
  const seg = p.split("/").filter(Boolean);
  return seg.length ? `/${seg[seg.length - 1]}` : p;
}
