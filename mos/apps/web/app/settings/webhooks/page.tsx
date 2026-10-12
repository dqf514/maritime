"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { SavedViews } from "@/components/SavedViews";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";
import { useToast } from "@/components/ToastProvider";

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

function WebhooksPage() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const { query, setQuery } = useListQuery();
  const filterStatus = query.status ?? "";
  const [subs, setSubs] = useState<Subscription[]>([]);
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);

  // Create form (RecordModal)
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
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

  function openCreate() {
    setName("");
    setUrl("");
    setSelectedEvents([]);
    setCreating(true);
  }

  useListHotkeys(openCreate);

  function closeCreate() {
    setCreating(false);
  }

  function toggleEvent(ev: string) {
    setSelectedEvents((prev) =>
      prev.includes(ev) ? prev.filter((e) => e !== ev) : [...prev, ev]
    );
  }

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    if (!name || !url || selectedEvents.length === 0) return;
    setSaving(true);
    try {
      await apiPost("/api/v1/webhooks/subscriptions", { name, url, events: selectedEvents });
      toast.success(t("webhooks.created", "Subscription created"));
      setCreating(false);
      await load();
    } catch (err) {
      toast.error(t("webhooks.create_fail", "Failed to create subscription: {err}", { err: String(err) }));
    } finally {
      setSaving(false);
    }
  }

  async function toggleActive(sub: Subscription) {
    const newActive = sub.status !== "active";
    try {
      await apiPatch(`/api/v1/webhooks/subscriptions/${sub.id}`, { is_active: newActive });
      await load();
    } catch (err) {
      toast.error(t("webhooks.toggle_fail", "Failed to update subscription: {err}", { err: String(err) }));
    }
  }

  async function removeSub(id: string) {
    try {
      await apiDelete(`/api/v1/webhooks/subscriptions/${id}`);
      await load();
    } catch (err) {
      toast.error(t("webhooks.delete_fail", "Failed to delete subscription: {err}", { err: String(err) }));
    }
  }

  async function rotateSecret(id: string) {
    try {
      const result = await apiPost(`/api/v1/webhooks/subscriptions/${id}/rotate-secret`, {});
      toast.success(t("webhooks.new_secret", "New secret: {secret}", { secret: result.secret }));
    } catch (err) {
      toast.error(t("webhooks.rotate_fail", "Failed to rotate secret: {err}", { err: String(err) }));
    }
  }

  const filteredSubs = filterStatus ? subs.filter((s) => s.status === filterStatus) : subs;

  const subColumns: ColumnDef<Subscription>[] = [
    { key: "name", title: t("webhooks.name", "Name"), minWidth: 140, value: (r) => r.name },
    {
      key: "url",
      title: t("webhooks.url", "URL"),
      minWidth: 180,
      value: (r) => r.url,
      render: (v) => <span title={String(v)}>{String(v)}</span>,
    },
    {
      key: "events",
      title: t("webhooks.events", "Events"),
      minWidth: 180,
      value: (r) => (r.events || []).join(", "),
      render: (_v, s) => (
        <span>
          {(s.events || []).slice(0, 3).map((ev) => (
            <span key={ev} className="badge badge-info">{ev}</span>
          ))}
          {(s.events || []).length > 3 && <span className="muted">+{s.events.length - 3}</span>}
        </span>
      ),
    },
    {
      key: "status",
      title: t("common.status", "Status"),
      width: 100,
      value: (r) => r.status,
    },
    {
      key: "_actions",
      title: t("common.actions", "Actions"),
      width: 220,
      align: "right",
      render: (_v, s) => (
        <span>
          <button type="button" className="btn btn-sm" onClick={() => toggleActive(s)}>
            {s.status === "active" ? t("common.disable", "Disable") : t("common.enable", "Enable")}
          </button>{" "}
          <button type="button" className="btn btn-sm" onClick={() => rotateSecret(s.id)}>
            {t("webhooks.rotate", "Rotate secret")}
          </button>{" "}
          <button type="button" className="btn btn-sm btn-danger" onClick={() => removeSub(s.id)}>
            {t("common.delete", "Delete")}
          </button>
        </span>
      ),
    },
  ];

  const deliveryColumns: ColumnDef<Delivery>[] = [
    {
      key: "event",
      title: t("webhooks.event", "Event"),
      minWidth: 160,
      value: (r) => r.event,
      render: (v) => <code>{String(v)}</code>,
    },
    { key: "status", title: t("common.status", "Status"), width: 110, value: (r) => r.status },
    {
      key: "attempts",
      title: t("webhooks.attempts", "Attempts"),
      width: 90,
      align: "right",
      value: (r) => r.attempts,
    },
    {
      key: "response_code",
      title: t("webhooks.response", "Response"),
      width: 100,
      value: (r) => r.response_code ?? "",
      render: (v) => (v ? String(v) : "—"),
    },
    {
      key: "created_at",
      title: t("common.time", "Time"),
      width: 170,
      value: (r) => r.created_at,
      render: (v) => new Date(String(v)).toLocaleString(),
    },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[
          { label: t("nav.settings_hub", "System settings"), href: "/settings" },
          { label: t("page.webhooks.title", "Webhooks") },
        ]}
        title={t("page.webhooks.title", "Webhooks")}
        actions={
          <SavedViews
            storageKey="settings_webhooks"
            onApply={(qs) => router.replace(`/settings/webhooks${qs}`)}
          />
        }
      />
      <Toolbar
        filterCount={filterStatus ? 1 : 0}
        onClearFilters={() => setQuery({ status: null }, { resetPage: true })}
        right={
          <select
            className="input input-sm"
            value={filterStatus}
            onChange={(e) => setQuery({ status: e.target.value || null }, { resetPage: true })}
            aria-label={t("common.status", "Status")}
          >
            <option value="">{t("common.all", "All")}</option>
            <option value="active">{t("common.active", "Active")}</option>
            <option value="disabled">{t("common.disabled", "Disabled")}</option>
          </select>
        }
      >
        <button type="button" className="btn btn-primary" onClick={openCreate}>
          {t("webhooks.new_btn", "+ New webhook")}
        </button>
        <button type="button" className="btn btn-sm" onClick={() => load().catch(() => undefined)} title={t("common.refresh", "Refresh")}>
          ↻
        </button>
      </Toolbar>
      <div className="space-y-6">

        {/* Subscriptions list */}
        <div className="panel">
          <h3>{t("webhooks.subscriptions", "Subscriptions")}</h3>
          <DataGrid<Subscription>
            columns={subColumns}
            data={filteredSubs}
            rowKey={(r) => r.id}
            storageKey="settings_webhooks_subs_grid"
            emptyText={t("webhooks.none", "No subscriptions")}
          />
        </div>

        {/* Recent deliveries */}
        <div className="panel">
          <h3>{t("webhooks.deliveries", "Recent deliveries")}</h3>
          <DataGrid<Delivery>
            columns={deliveryColumns}
            data={deliveries}
            rowKey={(r) => r.id}
            storageKey="settings_webhooks_deliveries_grid"
            emptyText={t("webhooks.no_deliveries", "No deliveries yet")}
          />
        </div>
      </div>

      <RecordModal
        open={creating}
        title={t("webhooks.new", "New subscription")}
        onClose={closeCreate}
        onSave={onCreate}
        saving={saving}
        canDelete={false}
      >
        <div className="form-grid">
          <label>
            {t("webhooks.name", "Name")}
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="My integration" required />
          </label>
          <label>
            {t("webhooks.url", "URL")}
            <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/webhook" required />
          </label>
        </div>
        <label>
          {t("webhooks.events", "Events")}
          <span>
            {EVENT_OPTIONS.map((ev) => (
              <button
                key={ev}
                type="button"
                onClick={() => toggleEvent(ev)}
                className={selectedEvents.includes(ev) ? "btn btn-primary btn-sm" : "btn btn-ghost btn-sm"}
              >
                {ev}
              </button>
            ))}
          </span>
        </label>
      </RecordModal>
    </AppShell>
  );
}

// Next 16: useSearchParams（useListQuery）须位于 Suspense 边界内
export default function Page() {
  return (
    <Suspense fallback={null}>
      <WebhooksPage />
    </Suspense>
  );
}
