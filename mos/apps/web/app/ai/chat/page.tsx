"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { Num } from "@/components/Num";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { StatusLegend } from "@/components/StatusLegend";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type Agent = {
  agent_name: string;
  display_name: string;
  description: string | null;
  tools: string[];
};

type Conversation = {
  id: string;
  agent_name: string;
  title: string | null;
  status: string;
  message_count: number;
  created_at: string;
  updated_at?: string | null;
};

type Message = {
  id: string;
  role: string;
  content: string;
  tool_calls_json: Record<string, unknown> | null;
  created_at: string;
  source?: string | null;
};

type AiStatus = { available: boolean; provider: string | null; fallback_mode: string | null };

export default function AiChatPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedAgent, setSelectedAgent] = useState("");
  const [activeConv, setActiveConv] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [renaming, setRenaming] = useState<Conversation | null>(null);
  const [renameTitle, setRenameTitle] = useState("");
  // LLM 可用性：未配置 → 顶部常驻提示；已配置但回落 → 回复后追加提示
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null);
  const [fallbackNotice, setFallbackNotice] = useState(false);
  const convCtx = useContextMenu<Conversation>();

  async function loadAgents() {
    try {
      const data = await apiGet("/api/v1/ai/agents");
      setAgents(data);
      if (data.length > 0 && !selectedAgent) setSelectedAgent(data[0].agent_name);
    } catch {
      setAgents([]);
    }
  }

  async function loadConversations() {
    try {
      const data = await apiGet("/api/v1/ai/conversations");
      setConversations(data);
    } catch {
      setConversations([]);
    }
  }

  async function loadMessages(convId: string) {
    try {
      const data = await apiGet(`/api/v1/ai/conversations/${convId}/messages`);
      setMessages(data);
    } catch {
      setMessages([]);
    }
  }

  useEffect(() => {
    loadAgents();
    loadConversations();
    apiGet("/api/v1/ai/assist/status")
      .then((s: AiStatus) => setAiStatus(s))
      .catch(() => setAiStatus({ available: false, provider: null, fallback_mode: "rules" }));
  }, []);

  useEffect(() => {
    if (activeConv) loadMessages(activeConv.id);
  }, [activeConv?.id]);

  async function seedAgents() {
    await apiPost("/api/v1/ai/agents/seed", {});
    toast.success(t("ai.seeded", "Agents seeded"));
    await loadAgents();
  }

  async function startConversation() {
    if (!selectedAgent) return;
    const conv = await apiPost("/api/v1/ai/conversations", {
      agent_name: selectedAgent,
      title: `${selectedAgent} — ${new Date().toLocaleDateString()}`,
    });
    setActiveConv(conv);
    setMessages([]);
    await loadConversations();
  }

  async function sendMessage(e: FormEvent) {
    e.preventDefault();
    if (!input.trim() || !activeConv) return;
    setLoading(true);
    try {
      const result = (await apiPost(`/api/v1/ai/conversations/${activeConv.id}/chat`, {
        message: input,
      })) as { response: string; message_id?: string; tool_calls?: unknown; source?: string };
      const source = result.source || null;
      // 规则引擎回落（模型未配置/不可达）→ 给出友好说明，而非让用户误以为是 AI
      if (source && source !== "llm" && aiStatus?.available !== false) setFallbackNotice(true);
      setMessages((prev) => [
        ...prev,
        { id: "user-" + Date.now(), role: "user", content: input, tool_calls_json: null, created_at: new Date().toISOString() },
        { id: result.message_id || "ai-" + Date.now(), role: "assistant", content: result.response, tool_calls_json: (result.tool_calls as Record<string, unknown>) || null, created_at: new Date().toISOString(), source },
      ]);
      setInput("");
      setActiveConv({ ...activeConv, message_count: (activeConv.message_count || 0) + 2 });
    } catch {
      toast.error(t("ai.chat.send_fail", "Couldn't send — please try again."));
    }
    setLoading(false);
  }

  const agent = agents.find((a) => a.agent_name === selectedAgent);

  function copyConvId(c: Conversation) {
    void navigator.clipboard.writeText(c.id);
    toast.success(t("ctx.copied_id", "ID copied"));
  }

  function openRename(c: Conversation) {
    setRenaming(c);
    setRenameTitle(c.title || "");
  }

  async function saveRename() {
    if (!renaming) return;
    const next = renameTitle.trim();
    if (!next || next === (renaming.title || "")) {
      setRenaming(null);
      return;
    }
    try {
      await apiPatch(`/api/v1/ai/conversations/${renaming.id}`, { title: next });
      toast.success(t("common.saved", "Saved"));
      if (activeConv?.id === renaming.id) setActiveConv({ ...renaming, title: next });
      setRenaming(null);
      await loadConversations();
    } catch (ex: any) {
      toast.error(ex?.message || String(ex));
    }
  }

  async function toggleArchive(c: Conversation) {
    const next = c.status === "archived" ? "active" : "archived";
    try {
      await apiPatch(`/api/v1/ai/conversations/${c.id}`, { status: next });
      toast.success(t("common.saved", "Saved"));
      if (activeConv?.id === c.id) setActiveConv({ ...c, status: next });
      await loadConversations();
    } catch (ex: any) {
      toast.error(ex?.message || String(ex));
    }
  }

  async function deleteConv(c: Conversation) {
    try {
      await apiDelete(`/api/v1/ai/conversations/${c.id}`);
      toast.success(t("common.recycled", "Moved to recycle bin"));
      if (activeConv?.id === c.id) {
        setActiveConv(null);
        setMessages([]);
      }
      await loadConversations();
    } catch (ex: any) {
      toast.error(ex?.message || String(ex));
    }
  }

  function formatTs(iso: string | null | undefined): string {
    if (!iso) return "—";
    return iso.slice(0, 16).replace("T", " ");
  }

  const convMenuItems = (c: Conversation): ContextMenuItem[] => [
    { key: "open", label: t("ctx.open", "Open"), onClick: () => setActiveConv(c) },
    { key: "rename", label: t("ai.rename", "Rename"), onClick: () => openRename(c) },
    {
      key: "archive",
      label: c.status === "archived" ? t("ai.unarchive", "Unarchive") : t("ai.archive", "Archive"),
      onClick: () => toggleArchive(c).catch(() => undefined),
    },
    { key: "delete", label: t("common.delete", "Delete"), onClick: () => deleteConv(c).catch(() => undefined) },
    { key: "copy", label: t("ctx.copy_id", "Copy id"), onClick: () => copyConvId(c) },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.ai_chat", "MariAI") }]}
        title={t("page.ai.chat.title", "MariAI Chat")}
        subtitle={t("page.ai.chat.sub", "Ask the fleet copilot — estimates, voyages, laytime and market context.")}
      />
      <div className="ai-chat">
        {/* 大模型未配置 → 友好常驻提示；已配置但回落 → 回复后提示 */}
        {aiStatus !== null && !aiStatus.available ? (
          <div className="ai-notice ai-notice-warn" role="status">
            <strong>{t("ai.chat.no_model_title", "No AI model configured yet")}</strong>
            <span>
              {t(
                "ai.chat.no_model",
                "Replies come from the built-in rules engine. Configure a provider in Settings → AI to enable full AI chat.",
              )}
            </span>
          </div>
        ) : null}
        {aiStatus?.available && fallbackNotice ? (
          <div className="ai-notice" role="status">
            {t(
              "ai.chat.fallback_reply",
              "The model didn't respond just now — the reply above was generated by the built-in rules engine. You can check the provider connection in Settings → AI.",
            )}
          </div>
        ) : null}

        <div className="desk-split">
          {/* Sidebar */}
          <div className="ai-chat-side">
            <div className="panel">
              <div className="panel-header">{t("ai.agents", "Agents")}</div>
              <div className="panel-body ai-chat-list">
                {agents.length === 0 && (
                  <button type="button" className="btn btn-sm" onClick={() => seedAgents().catch(() => undefined)}>
                    {t("ai.seed", "Seed preset agents")}
                  </button>
                )}
                {agents.map((a) => (
                  <button
                    key={a.agent_name}
                    type="button"
                    className={`ai-chat-pick${selectedAgent === a.agent_name ? " active" : ""}`}
                    onClick={() => setSelectedAgent(a.agent_name)}
                  >
                    {t(`ai.agent.${a.agent_name}`, a.display_name)}
                  </button>
                ))}
              </div>
            </div>

            <div className="panel">
              <div className="panel-header">{t("ai.history", "History")}</div>
              <div className="panel-body">
                <StatusLegend statuses={["active", "archived"]} />
                <div className="ai-chat-list ai-chat-hist">
                  {conversations.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      className={`ai-chat-pick${activeConv?.id === c.id ? " active" : ""}`}
                      onClick={() => setActiveConv(c)}
                      onContextMenu={convCtx.open(c)}
                    >
                      <span>{c.title || c.agent_name}</span>{" "}
                      <Num v={c.message_count} digits={0} />
                      <span className="ai-chat-hist-meta">
                        {" "}· {t("ai.updated_at", "Updated")} {formatTs(c.updated_at ?? c.created_at)}
                      </span>
                    </button>
                  ))}
                  {conversations.length === 0 && (
                    <p className="hint">{t("ai.no_history", "No conversations yet")}</p>
                  )}
                </div>
              </div>
              <ContextMenu controller={convCtx} items={convMenuItems} />
            </div>
          </div>

          {/* Chat area */}
          <div className="panel ai-chat-main">
            <div className="panel-header">
              <span className="ai-chat-agent-head">
                <strong>
                  {agent ? t(`ai.agent.${agent.agent_name}`, agent.display_name) : selectedAgent || t("page.ai.chat.title", "MariAI Chat")}
                </strong>
                {agent?.description ? (
                  <span className="ai-chat-agent-desc">{t(`ai.agent_desc.${agent.agent_name}`, agent.description)}</span>
                ) : null}
              </span>
              <button type="button" className="btn btn-primary btn-sm" onClick={() => startConversation().catch(() => undefined)}>
                {t("ai.new_chat", "New chat")}
              </button>
            </div>
            {agent && agent.tools.length > 0 ? (
              <div className="chips ai-chat-tools">
                {agent.tools.map((tool) => (
                  <span key={tool} className="badge">
                    {tool}
                  </span>
                ))}
              </div>
            ) : null}

            <div className="ai-chat-body">
              {messages.length === 0 && (
                <p className="hint ai-chat-empty">
                  {activeConv
                    ? t("ai.start_typing", "Start typing to chat with the agent")
                    : t("ai.select_or_create", "Select an agent and start a new conversation")}
                </p>
              )}
              {messages.map((m) => (
                <div key={m.id} className={`ai-chat-line ${m.role === "user" ? "right" : "left"}`}>
                  <div
                    className={`ai-chat-bubble ${
                      m.role === "user" ? "user" : m.role === "tool" ? "tool" : "assistant"
                    }`}
                  >
                    <pre className="ai-chat-text">{m.content}</pre>
                    {m.source ? (
                      <span className="ai-msg-src">
                        {m.source === "llm"
                          ? "AI"
                          : t("ai.assist.rules_badge", "rules")}
                      </span>
                    ) : null}
                    {m.tool_calls_json && (
                      <details className="ai-chat-tools-details">
                        <summary>{t("ai.tool_calls", "Tool calls")}</summary>
                        <pre>{JSON.stringify(m.tool_calls_json, null, 2)}</pre>
                      </details>
                    )}
                  </div>
                </div>
              ))}
              {loading && (
                <div className="ai-chat-line left">
                  <div className="ai-chat-bubble assistant">{t("ai.thinking", "Thinking...")}</div>
                </div>
              )}
            </div>

            <form className="ai-chat-form" onSubmit={(e) => sendMessage(e).catch(() => undefined)}>
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={t("ai.placeholder", "Ask about TCE, voyage P&L, port distances, compliance...")}
                aria-label={t("ai.placeholder", "Ask about TCE, voyage P&L, port distances, compliance...")}
                disabled={!activeConv || loading}
              />
              <button
                type="submit"
                disabled={!activeConv || loading || !input.trim()}
                className="btn btn-primary"
              >
                {t("ai.send", "Send")}
              </button>
            </form>
          </div>
        </div>
      </div>

      <RecordModal
        open={!!renaming}
        title={t("ai.rename", "Rename")}
        onClose={() => setRenaming(null)}
        onSave={saveRename}
        canDelete={false}
      >
        <label>
          {t("common.title", "Title")}
          <input
            value={renameTitle}
            onChange={(e) => setRenameTitle(e.target.value)}
            placeholder={t("ai.rename_placeholder", "Conversation title")}
          />
        </label>
      </RecordModal>
    </AppShell>
  );
}
