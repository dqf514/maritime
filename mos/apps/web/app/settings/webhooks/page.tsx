"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Subscription = {
  id: string;
  name: string;
  url: string;
  events: string[];
  status: string;
  created_at: string;
};

type Delivery = {
  id: string;
  endpoint_id: string;
  event: string;
  status: string;
  attempts: number;
  response_code: number | null;
  created_at: string;
};

const EVENT_OPTIONS = [
  "voyage.*", "voyage.completed", "voyage.started",
  "charter.*", "charter.activated",
  "invoice.*", "invoice.approved", "invoice.issued",
  "payment.*",
  "bunker.*",
  "claim.*",
  "certificate.*",
];

export default function WebhooksPage() {
  const { t } = useI18n();
  const [subs, setSubs] = useState<Subscription[]>([]);
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [msg, setMsg] = useState("");

  // Create form
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [selectedEvents, setSelectedEvents] = useState<string[]>([]);

  async function load() {
    setSubs(await apiGet("/api/v1/webhooks/subscriptions"));
    setDeliveries(await apiGet("/api/v1/webhooks/deliveries"));
  }

  useEffect(() => {
    load().catch(() => {});
  }, []);

  function toggleEvent(ev: string) {
    setSelectedEvents((prev) =>
      prev.includes(ev) ? prev.filter((e) => e !== ev) : [...prev, ev]
    );
  }

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    if (!name || !url || selectedEvents.length === 0) return;
    await apiPost("/api/v1/webhooks/subscriptions", { name, url, events: selectedEvents });
    setName("");
    setUrl("");
    setSelectedEvents([]);
    setMsg(t("webhooks.created", "Subscription created"));
    await load();
  }

  async function toggleActive(sub: Subscription) {
    const newActive = sub.status !== "active";
    await apiPatch(`/api/v1/webhooks/subscriptions/${sub.id}`, { is_active: newActive });
    await load();
  }

  async function removeSub(id: string) {
    await apiDelete(`/api/v1/webhooks/subscriptions/${id}`);
    await load();
  }

  async function rotateSecret(id: string) {
    const result = await apiPost(`/api/v1/webhooks/subscriptions/${id}/rotate-secret`, {});
    setMsg(`New secret: ${result.secret}`);
  }

  return (
    <AppShell title="Webhooks">
      <div className="space-y-6">
        {msg && <div className="rounded bg-blue-50 p-3 text-sm text-blue-800">{msg}</div>}

        {/* Create subscription */}
        <div className="rounded-lg border bg-white p-4">
          <h3 className="mb-3 font-semibold">{t("webhooks.new", "New subscription")}</h3>
          <form onSubmit={onCreate} className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-sm text-gray-600">{t("webhooks.name", "Name")}</label>
                <input value={name} onChange={(e) => setName(e.target.value)} className="w-full rounded border px-3 py-2 text-sm" placeholder="My integration" />
              </div>
              <div>
                <label className="mb-1 block text-sm text-gray-600">{t("webhooks.url", "URL")}</label>
                <input value={url} onChange={(e) => setUrl(e.target.value)} className="w-full rounded border px-3 py-2 text-sm" placeholder="https://example.com/webhook" />
              </div>
            </div>
            <div>
              <label className="mb-1 block text-sm text-gray-600">{t("webhooks.events", "Events")}</label>
              <div className="flex flex-wrap gap-2">
                {EVENT_OPTIONS.map((ev) => (
                  <button
                    key={ev}
                    type="button"
                    onClick={() => toggleEvent(ev)}
                    className={`rounded px-2 py-1 text-xs ${
                      selectedEvents.includes(ev) ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                    }`}
                  >
                    {ev}
                  </button>
                ))}
              </div>
            </div>
            <button type="submit" className="rounded bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700">
              {t("webhooks.create", "Create subscription")}
            </button>
          </form>
        </div>

        {/* Subscriptions list */}
        <div className="rounded-lg border bg-white">
          <div className="border-b p-4">
            <h3 className="font-semibold">{t("webhooks.subscriptions", "Subscriptions")}</h3>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs text-gray-500">
              <tr>
                <th className="px-4 py-2">{t("webhooks.name", "Name")}</th>
                <th className="px-4 py-2">{t("webhooks.url", "URL")}</th>
                <th className="px-4 py-2">{t("webhooks.events", "Events")}</th>
                <th className="px-4 py-2">{t("common.status", "Status")}</th>
                <th className="px-4 py-2">{t("common.actions", "Actions")}</th>
              </tr>
            </thead>
            <tbody>
              {subs.map((s) => (
                <tr key={s.id} className="border-t">
                  <td className="px-4 py-2 font-medium">{s.name}</td>
                  <td className="px-4 py-2 max-w-xs truncate text-gray-600">{s.url}</td>
                  <td className="px-4 py-2">
                    <div className="flex flex-wrap gap-1">
                      {(s.events || []).slice(0, 3).map((ev) => (
                        <span key={ev} className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px]">{ev}</span>
                      ))}
                      {(s.events || []).length > 3 && (
                        <span className="text-[10px] text-gray-400">+{s.events.length - 3}</span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-2">
                    <span className={`rounded px-2 py-0.5 text-xs ${s.status === "active" ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"}`}>
                      {s.status}
                    </span>
                  </td>
                  <td className="px-4 py-2">
                    <div className="flex gap-2">
                      <button onClick={() => toggleActive(s)} className="text-xs text-blue-600 hover:underline">
                        {s.status === "active" ? t("common.disable", "Disable") : t("common.enable", "Enable")}
                      </button>
                      <button onClick={() => rotateSecret(s.id)} className="text-xs text-amber-600 hover:underline">
                        {t("webhooks.rotate", "Rotate secret")}
                      </button>
                      <button onClick={() => removeSub(s.id)} className="text-xs text-red-600 hover:underline">
                        {t("common.delete", "Delete")}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {subs.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400">{t("webhooks.none", "No subscriptions")}</td></tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Recent deliveries */}
        <div className="rounded-lg border bg-white">
          <div className="border-b p-4">
            <h3 className="font-semibold">{t("webhooks.deliveries", "Recent deliveries")}</h3>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs text-gray-500">
              <tr>
                <th className="px-4 py-2">{t("webhooks.event", "Event")}</th>
                <th className="px-4 py-2">{t("common.status", "Status")}</th>
                <th className="px-4 py-2">{t("webhooks.attempts", "Attempts")}</th>
                <th className="px-4 py-2">{t("webhooks.response", "Response")}</th>
                <th className="px-4 py-2">{t("common.time", "Time")}</th>
              </tr>
            </thead>
            <tbody>
              {deliveries.map((d) => (
                <tr key={d.id} className="border-t">
                  <td className="px-4 py-2 font-mono text-xs">{d.event}</td>
                  <td className="px-4 py-2">
                    <span className={`rounded px-2 py-0.5 text-xs ${
                      d.status === "delivered" ? "bg-green-100 text-green-700" :
                      d.status === "failed" ? "bg-red-100 text-red-700" :
                      "bg-yellow-100 text-yellow-700"
                    }`}>
                      {d.status}
                    </span>
                  </td>
                  <td className="px-4 py-2">{d.attempts}</td>
                  <td className="px-4 py-2">{d.response_code || "—"}</td>
                  <td className="px-4 py-2 text-gray-500">{new Date(d.created_at).toLocaleString()}</td>
                </tr>
              ))}
              {deliveries.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400">{t("webhooks.no_deliveries", "No deliveries yet")}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </AppShell>
  );
}
