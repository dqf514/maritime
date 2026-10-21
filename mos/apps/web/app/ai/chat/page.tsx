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
};

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
  }, []);

  useEffect(() => {
    if (activeConv) loadMessages(activeConv.id);
  }, [activeConv?.id]);

  async function seedAgents() {
    await apiPost("/api/v1/ai/agents/seed", {});
    toast.success(t("ai.seeded", "Agents seeded"));
    await loadAgents();
  }

  async function startConversation(e: FormEvent) {
    e.preventDefault();
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
      const result = await apiPost(`/api/v1/ai/conversations/${activeConv.id}/chat`, {
        message: input,
      });
      setMessages((prev) => [
        ...prev,
        { id: "user-" + Date.now(), role: "user", content: input, tool_calls_json: null, created_at: new Date().toISOString() },
        { id: result.message_id || "ai-" + Date.now(), role: "assistant", content: result.response, tool_calls_json: result.tool_calls, created_at: new Date().toISOString() },
      ]);
      setInput("");
      setActiveConv({ ...activeConv, message_count: (activeConv.message_count || 0) + 2 });
    } catch {
      toast.error(t("ai.error", "Chat error"));
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
        title={t("page.ai.title", "MariAI Chat")}
        subtitle={t("page.ai.sub", "Ask the fleet copilot — estimates, voyages, laytime and market context.")}
      />
      <div className="space-y-4">

        <div className="flex gap-4">
          {/* Sidebar */}
          <div className="w-64 shrink-0 space-y-3">
            <div className="rounded-lg border bg-white p-3">
              <h3 className="mb-2 text-sm font-semibold">{t("ai.agents", "Agents")}</h3>
              {agents.length === 0 && (
                <button onClick={seedAgents} className="text-sm text-blue-600 hover:underline">
                  {t("ai.seed", "Seed preset agents")}
                </button>
              )}
              {agents.map((a) => (
                <button
                  key={a.agent_name}
                  onClick={() => setSelectedAgent(a.agent_name)}
                  className={`block w-full rounded px-2 py-1.5 text-left text-sm ${
                    selectedAgent === a.agent_name ? "bg-blue-50 text-blue-700" : "hover:bg-gray-50"
                  }`}
                >
                  {a.display_name}
                </button>
              ))}
            </div>

            <div className="rounded-lg border bg-white p-3">
              <h3 className="mb-2 text-sm font-semibold">{t("ai.history", "History")}</h3>
              <StatusLegend statuses={["active", "archived"]} />
              <div className="max-h-64 space-y-1 overflow-y-auto">
                {conversations.map((c) => (
                  <button
                    key={c.id}
                    onClick={() => setActiveConv(c)}
                    onContextMenu={convCtx.open(c)}
                    className={`block w-full truncate rounded px-2 py-1 text-left text-xs ${
                      activeConv?.id === c.id ? "bg-blue-50 text-blue-700" : "hover:bg-gray-50"
                    }`}
                  >
                    <span>{c.title || c.agent_name}</span>{" "}
                    <Num v={c.message_count} digits={0} />
                    <span className="text-[10px] text-gray-400"> · {t("ai.updated_at", "Updated")} {formatTs(c.updated_at ?? c.created_at)}</span>
                  </button>
                ))}
                {conversations.length === 0 && (
                  <p className="text-xs text-gray-400">{t("ai.no_history", "No conversations yet")}</p>
                )}
              </div>
              <ContextMenu controller={convCtx} items={convMenuItems} />
            </div>
          </div>

          {/* Chat area */}
          <div className="flex-1 rounded-lg border bg-white">
            <div className="border-b p-3">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="font-semibold">{agent?.display_name || selectedAgent}</h2>
                  {agent?.description && <p className="text-xs text-gray-500">{agent.description}</p>}
                </div>
                <form onSubmit={startConversation}>
                  <button
                    type="submit"
                    className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700"
                  >
                    {t("ai.new_chat", "New chat")}
                  </button>
                </form>
              </div>
              {agent && (
                <div className="mt-1 flex gap-1">
                  {agent.tools.map((tool) => (
                    <span key={tool} className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600">
                      {tool}
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className="h-96 overflow-y-auto p-4 space-y-3">
              {messages.length === 0 && (
                <p className="text-center text-sm text-gray-400">
                  {activeConv
                    ? t("ai.start_typing", "Start typing to chat with the agent")
                    : t("ai.select_or_create", "Select an agent and start a new conversation")}
                </p>
              )}
              {messages.map((m) => (
                <div key={m.id} className={m.role === "user" ? "text-right" : "text-left"}>
                  <div
                    className={`inline-block max-w-[80%] rounded-lg px-3 py-2 text-sm ${
                      m.role === "user"
                        ? "bg-blue-600 text-white"
                        : m.role === "tool"
                        ? "bg-yellow-50 text-yellow-900"
                        : "bg-gray-100 text-gray-800"
                    }`}
                  >
                    <pre className="whitespace-pre-wrap font-sans">{m.content}</pre>
                    {m.tool_calls_json && (
                      <details className="mt-1 text-[10px] opacity-70">
                        <summary>{t("ai.tool_calls", "Tool calls")}</summary>
                        <pre className="mt-1 overflow-x-auto text-[10px]">
                          {JSON.stringify(m.tool_calls_json, null, 2)}
                        </pre>
                      </details>
                    )}
                  </div>
                </div>
              ))}
              {loading && (
                <div className="text-left">
                  <div className="inline-block rounded-lg bg-gray-100 px-3 py-2 text-sm text-gray-500">
                    {t("ai.thinking", "Thinking...")}
                  </div>
                </div>
              )}
            </div>

            <form onSubmit={sendMessage} className="border-t p-3">
              <div className="flex gap-2">
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={t("ai.placeholder", "Ask about TCE, voyage P&L, port distances, compliance...")}
                  className="flex-1 rounded border px-3 py-2 text-sm"
                  disabled={!activeConv || loading}
                />
                <button
                  type="submit"
                  disabled={!activeConv || loading || !input.trim()}
                  className="rounded bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  {t("ai.send", "Send")}
                </button>
              </div>
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
