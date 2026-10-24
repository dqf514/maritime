"use client";

import { RefreshButton } from "@/components/RefreshButton";
import { FormEvent, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { SavedViews } from "@/components/SavedViews";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StateView } from "@/components/StateView";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { msgOf, handled } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { formatInTz } from "@/lib/datetime";
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
  const { t, locale } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const { query, setQuery } = useListQuery();
  const filterStatus = query.status ?? "";
  const [subs, setSubs] = useState<Subscription[]>([]);
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [pending, setPending] = useState<{ message: string; danger?: boolean; action: () => void } | null>(null);
  // 轮换出的签名密钥：默认不显示明文，仅脱敏 + 剪贴板复制
  const [rotated, setRotated] = useState<{ id: string; secret: string; name: string } | null>(null);
  const [revealSecret, setRevealSecret] = useState(false);

  // Create form (RecordModal)
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [selectedEvents, setSelectedEvents] = useState<string[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      setSubs(await apiGet("/api/v1/webhooks/subscriptions"));
    } catch (ex) {
      setErr(msgOf(ex));
      setSubs([]);
    }
    try {
      setDeliveries(await apiGet("/api/v1/webhooks/deliveries"));
    } catch (ex) {
      setErr(msgOf(ex));
      setDeliveries([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

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
      toast.error(t("webhooks.create_fail", "Failed to create subscription: {err}", { err: msgOf(err) }));
    } finally {
      setSaving(false);
    }
  }

  const toggleActive = useCallback(async (sub: Subscription) => {
    const newActive = sub.status !== "active";
    try {
      await apiPatch(`/api/v1/webhooks/subscriptions/${sub.id}`, { is_active: newActive });
      await load();
    } catch (err) {
      toast.error(t("webhooks.toggle_fail", "Failed to update subscription: {err}", { err: msgOf(err) }));
    }
  }, [load, t, toast]);

  const removeSub = useCallback(async (id: string) => {
    try {
      await apiDelete(`/api/v1/webhooks/subscriptions/${id}`);
      await load();
    } catch (err) {
      toast.error(t("webhooks.delete_fail", "Failed to delete subscription: {err}", { err: msgOf(err) }));
    }
  }, [load, t, toast]);

  /** 删除订阅不可逆 → ConfirmDialog 二次确认（指名订阅） */
  const askRemoveSub = useCallback((s: Subscription) => {
    setPending({
      message: t(
        "webhooks.confirm_delete",
        "删除 webhook 订阅 {name}（{url}）？该订阅将立即停止投递且不可恢复。",
        { name: s.name, url: s.url },
      ),
      danger: true,
      action: () => {
        removeSub(s.id).catch((ex) => toast.error(t("webhooks.delete_fail", "Failed to delete subscription: {err}", { err: msgOf(ex) })));
      },
    });
  }, [removeSub, t, toast]);

  const rotateSecret = useCallback(async (s: Subscription) => {
    try {
      const result = await apiPost(`/api/v1/webhooks/subscriptions/${s.id}/rotate-secret`, {});
      setRevealSecret(false);
      setRotated({ id: s.id, secret: String(result.secret || ""), name: s.name });
      toast.success(t("webhooks.secret_rotated", "Secret rotated — copy it to a safe place now."));
    } catch (err) {
      toast.error(t("webhooks.rotate_fail", "Failed to rotate secret: {err}", { err: msgOf(err) }));
    }
  }, [t, toast]);

  /** 脱敏显示：仅首尾片段可见 */
  function maskSecret(secret: string): string {
    if (!secret) return "";
    if (secret.length <= 8) return secret.slice(0, 2) + "…";
    return `${secret.slice(0, 4)}…${secret.slice(-4)}`;
  }

  async function copyRotatedSecret() {
    if (!rotated) return;
    try {
      await navigator.clipboard.writeText(rotated.secret);
      toast.success(t("webhooks.secret_copied", "Secret copied to clipboard."));
    } catch {
      toast.error(t("webhooks.copy_fail", "Failed to copy the secret — reveal and copy it manually."));
    }
  }

  const filteredSubs = filterStatus ? subs.filter((s) => s.status === filterStatus) : subs;

  const subColumns = useMemo<ColumnDef<Subscription>[]>(() => [
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
      render: (v) => <span className={`badge badge-${v === "active" ? "ok" : "warn"}`}>{t(`status.${v}`, String(v))}</span>,
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
          <button type="button" className="btn btn-sm" onClick={() => rotateSecret(s)}>
            {t("webhooks.rotate", "Rotate secret")}
          </button>{" "}
          <button type="button" className="btn btn-sm btn-danger" onClick={() => askRemoveSub(s)}>
            {t("common.delete", "Delete")}
          </button>
        </span>
      ),
    },
  ], [t, toggleActive, rotateSecret, askRemoveSub]);

  const deliveryColumns = useMemo<ColumnDef<Delivery>[]>(() => [
    {
      key: "event",
      title: t("webhooks.event", "Event"),
      minWidth: 160,
      value: (r) => r.event,
      render: (v) => <code>{String(v)}</code>,
    },
    {
      key: "status",
      title: t("common.status", "Status"),
      width: 110,
      value: (r) => r.status,
      render: (v) => <span className={`badge badge-${v === "delivered" ? "ok" : v === "failed" ? "err" : "warn"}`}>{t(`status.${v}`, String(v))}</span>,
    },
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
      render: (v) => formatInTz(v as string | null, null, undefined, locale),
    },
  ], [locale, t]);

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
        <RefreshButton label={t("common.refresh", "Refresh")} className="btn btn-sm" onClick={() => load()} />
      </Toolbar>
      {rotated ? (
        <div className="flash">
          <span>
            {t("webhooks.secret_rotated", "Secret rotated — copy it to a safe place now.")}{" "}
            <code>{revealSecret ? rotated.secret : maskSecret(rotated.secret)}</code>
          </span>{" "}
          <button type="button" className="btn btn-ghost" onClick={() => copyRotatedSecret().catch(handled)}>
            {t("webhooks.copy_secret", "Copy secret")}
          </button>{" "}
          <button
            type="button"
            className="btn btn-ghost"
            aria-expanded={revealSecret}
            aria-label={t("webhooks.reveal_secret", "显示密钥")}
            onClick={() => setRevealSecret((v) => !v)}
          >
            {revealSecret ? t("webhooks.hide_secret", "隐藏密钥") : t("webhooks.reveal_secret", "显示密钥")}
          </button>{" "}
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => {
              setRotated(null);
              setRevealSecret(false);
            }}
          >
            {t("common.close", "Close")}
          </button>
        </div>
      ) : null}
      <div className="stack-panels">

        {/* Subscriptions list */}
        <div className="panel">
          <h3>{t("webhooks.subscriptions", "Subscriptions")}</h3>
          <StateView
            loading={loading}
            error={err ?? undefined}
            empty={!filteredSubs.length}
            onRetry={() => load()}
            emptyText={t("webhooks.none", "No subscriptions")}
          >
            <DataGrid<Subscription>
              columns={subColumns}
              data={filteredSubs}
              rowKey={(r) => r.id}
              storageKey="settings_webhooks_subs_grid"
              emptyText={t("webhooks.none", "No subscriptions")}
            />
          </StateView>
        </div>

        {/* Recent deliveries */}
        <div className="panel">
          <h3>{t("webhooks.deliveries", "Recent deliveries")}</h3>
          <StateView
            loading={loading}
            error={err ?? undefined}
            empty={!deliveries.length}
            onRetry={() => load()}
            emptyText={t("webhooks.no_deliveries", "No deliveries yet")}
          >
            <DataGrid<Delivery>
              columns={deliveryColumns}
              data={deliveries}
              rowKey={(r) => r.id}
              storageKey="settings_webhooks_deliveries_grid"
              emptyText={t("webhooks.no_deliveries", "No deliveries yet")}
            />
          </StateView>
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

      <ConfirmDialog
        open={Boolean(pending)}
        title={t("common.confirm", "Confirm")}
        message={pending?.message || ""}
        danger={pending?.danger}
        onConfirm={() => {
          const fn = pending?.action;
          setPending(null);
          fn?.();
        }}
        onCancel={() => setPending(null)}
      />
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
