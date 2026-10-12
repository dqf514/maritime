"use client";

// Interface Messages console — IMOS Data Center 标配。
// Integration exchange log: inbound/outbound tabs + stats, retry with stub processor.

import { useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { Tabs } from "@/components/Tabs";
import { Toolbar } from "@/components/Toolbar";
import { StatusBadge } from "@/components/StatusBadge";
import { RecordModal } from "@/components/RecordModal";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type Msg = {
  id: string;
  direction: string;
  channel: string;
  interface_code: string;
  external_ref: string | null;
  status: string;
  error_message: string | null;
  retry_count: number;
  last_retry_at: string | null;
  created_at: string;
  updated_at: string;
  payload?: unknown;
};

type Stats = {
  total: number;
  by_status: { pending: number; success: number; failed: number };
  last_24h: { total: number; pending: number; success: number; failed: number };
};

type Tab = "in" | "out" | "stats";

function fmtTime(v: string | null | undefined) {
  return v ? String(v).replace("T", " ").slice(0, 19) : "—";
}

function prettyPayload(p: unknown) {
  if (p === null || p === undefined) return "—";
  if (typeof p === "string") return p;
  try {
    return JSON.stringify(p, null, 2);
  } catch {
    return String(p);
  }
}

export default function InterfaceMessagesPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [tab, setTab] = useState<Tab>("in");
  const [rows, setRows] = useState<Msg[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<Msg | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      if (tab === "stats") {
        setStats((await apiGet("/api/v1/interface/messages/stats")) as Stats);
        return;
      }
      const direction = tab === "in" ? "inbound" : "outbound";
      const qs = new URLSearchParams({ direction });
      if (statusFilter) qs.set("status", statusFilter);
      qs.set("limit", "100");
      setRows((await apiGet(`/api/v1/interface/messages?${qs.toString()}`)) as Msg[]);
    } catch (err) {
      toast.error(t("iface.load_fail", "Failed to load interface messages: {err}", { err: String(err) }));
    } finally {
      setLoading(false);
    }
  }, [tab, statusFilter, t, toast]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load().catch(() => undefined);
  }, [load]);

  const openDetail = useCallback(
    async (row: Msg) => {
      try {
        setDetail((await apiGet(`/api/v1/interface/messages/${row.id}`)) as Msg);
      } catch (err) {
        toast.error(t("iface.detail_fail", "Failed to load message detail: {err}", { err: String(err) }));
      }
    },
    [t, toast],
  );

  const retry = useCallback(
    async (row: Msg) => {
      setBusy(true);
      try {
        const updated = (await apiPost(`/api/v1/interface/messages/${row.id}/retry`)) as Msg;
        toast.success(t("iface.retry_ok", "Retry completed: {status}", { status: updated.status }));
        if (detail && detail.id === updated.id) setDetail(updated);
        await load();
      } catch (err) {
        toast.error(t("iface.retry_fail", "Retry failed: {err}", { err: String(err) }));
      } finally {
        setBusy(false);
      }
    },
    [detail, load, t, toast],
  );

  const tabs = useMemo(
    () => [
      { key: "in" as Tab, label: t("iface.tab_in", "Inbound") },
      { key: "out" as Tab, label: t("iface.tab_out", "Outbound") },
      { key: "stats" as Tab, label: t("iface.tab_stats", "Stats") },
    ],
    [t],
  );

  const columns: ColumnDef<Msg>[] = [
    {
      key: "created_at",
      title: t("iface.col_time", "Time"),
      width: 150,
      value: (r) => r.created_at,
      render: (v) => fmtTime(v as string),
    },
    {
      key: "direction",
      title: t("iface.col_direction", "Direction"),
      width: 90,
      value: (r) => r.direction,
      render: (v) => (
        <StatusBadge
          status={String(v)}
          tone={v === "inbound" ? "info" : "ok"}
          label={
            v === "inbound"
              ? t("iface.dir_in", "Inbound")
              : v === "outbound"
                ? t("iface.dir_out", "Outbound")
                : String(v)
          }
        />
      ),
    },
    {
      key: "interface_code",
      title: t("iface.col_code", "Code"),
      width: 140,
      value: (r) => r.interface_code,
    },
    {
      key: "external_ref",
      title: t("iface.col_ref", "External ref"),
      width: 150,
      value: (r) => r.external_ref || "",
      render: (v) => (v ? <span>{String(v)}</span> : <span className="muted">—</span>),
    },
    {
      key: "status",
      title: t("iface.col_status", "Status"),
      width: 100,
      value: (r) => r.status,
      render: (v) => <StatusBadge status={String(v)} />,
    },
    {
      key: "retry_count",
      title: t("iface.col_retry", "Retries"),
      width: 70,
      align: "right",
      value: (r) => r.retry_count,
    },
    {
      key: "_actions",
      title: "",
      width: 140,
      align: "right",
      render: (_v, r) => (
        <span style={{ display: "inline-flex", gap: 6 }}>
          <button type="button" className="btn btn-sm" onClick={() => openDetail(r)}>
            {t("iface.view", "View")}
          </button>
          <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={() => retry(r)}>
            {t("iface.retry", "Retry")}
          </button>
        </span>
      ),
    },
  ];

  const filterCount = statusFilter ? 1 : 0;

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[
          { label: t("iface.crumb_platform", "Platform"), href: "/platform" },
          { label: t("iface.title", "Interface messages") },
        ]}
        title={t("iface.title", "Interface messages")}
        subtitle={t("iface.sub", "Integration exchange log — inbound / outbound, retry & audit")}
      />

      <Tabs items={tabs} value={tab} onChange={(k) => setTab(k as Tab)} variant="pill" />

      {tab === "stats" ? (
        stats ? (
          <div className="form-grid" style={{ marginTop: "1rem" }}>
            <div className="card">
              <h3 className="muted">{t("iface.stats_total", "Total")}</h3>
              <p style={{ fontSize: "1.5rem", margin: 0 }}>{stats.total}</p>
              <p className="muted">
                {t("iface.stats_pending", "Pending")}: {stats.by_status.pending} ·{" "}
                {t("iface.stats_success", "Success")}: {stats.by_status.success} ·{" "}
                {t("iface.stats_failed", "Failed")}: {stats.by_status.failed}
              </p>
            </div>
            <div className="card">
              <h3 className="muted">{t("iface.stats_24h", "Last 24 hours")}</h3>
              <p style={{ fontSize: "1.5rem", margin: 0 }}>{stats.last_24h.total}</p>
              <p className="muted">
                {t("iface.stats_pending", "Pending")}: {stats.last_24h.pending} ·{" "}
                {t("iface.stats_success", "Success")}: {stats.last_24h.success} ·{" "}
                {t("iface.stats_failed", "Failed")}: {stats.last_24h.failed}
              </p>
            </div>
          </div>
        ) : (
          <p className="muted" style={{ marginTop: "1rem" }}>
            {t("iface.empty_stats", "No statistics yet")}
          </p>
        )
      ) : (
        <>
          <Toolbar
            filterCount={filterCount}
            onClearFilters={() => setStatusFilter("")}
            right={
              <select
                className="input input-sm"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                aria-label={t("iface.filter_status", "Status")}
              >
                <option value="">{t("iface.all_status", "All statuses")}</option>
                <option value="pending">{t("iface.status_pending", "Pending")}</option>
                <option value="success">{t("iface.status_success", "Success")}</option>
                <option value="failed">{t("iface.status_failed", "Failed")}</option>
              </select>
            }
          >
            <button type="button" className="btn btn-sm" onClick={() => load()} title={t("iface.refresh", "Refresh")}>
              ↻
            </button>
            <span className="muted" style={{ fontSize: "var(--font-label)" }}>
              {rows.length}
            </span>
          </Toolbar>

          <DataGrid<Msg>
            columns={columns}
            data={rows}
            rowKey={(r) => r.id}
            storageKey="platform_interfaces"
            loading={loading}
            onRowDoubleClick={(r) => openDetail(r)}
            emptyText={t("iface.empty", "No interface messages")}
          />
        </>
      )}

      <RecordModal
        open={!!detail}
        title={detail ? `${detail.interface_code} · ${detail.status}` : t("iface.title", "Interface messages")}
        onClose={() => setDetail(null)}
        canEdit={false}
        canDelete={false}
        size="lg"
      >
        {detail ? (
          <>
            <div className="form-grid">
              <span>
                {t("iface.col_time", "Time")}: {fmtTime(detail.created_at)}
              </span>
              <span>
                {t("iface.col_direction", "Direction")}: {detail.direction}
              </span>
              <span>
                {t("iface.col_channel", "Channel")}: {detail.channel}
              </span>
              <span>
                {t("iface.col_code", "Code")}: {detail.interface_code}
              </span>
              <span>
                {t("iface.col_ref", "External ref")}: {detail.external_ref || "—"}
              </span>
              <span>
                <StatusBadge status={detail.status} />
              </span>
              <span>
                {t("iface.col_retry", "Retries")}: {detail.retry_count}
                {detail.last_retry_at ? ` (${t("iface.last_retry", "last")}: ${fmtTime(detail.last_retry_at)})` : ""}
              </span>
            </div>

            {detail.error_message ? (
              <div style={{ marginTop: "0.75rem" }}>
                <strong className="muted">{t("iface.error", "Error")}</strong>
                <p style={{ color: "var(--danger, #c0392b)", whiteSpace: "pre-wrap", margin: "0.25rem 0 0" }}>
                  {detail.error_message}
                </p>
              </div>
            ) : null}

            <div style={{ marginTop: "0.75rem" }}>
              <strong className="muted">{t("iface.payload", "Payload")}</strong>
              <pre
                style={{
                  margin: "0.25rem 0 0",
                  padding: "0.5rem",
                  background: "var(--surface-2, #f5f5f5)",
                  borderRadius: 6,
                  maxHeight: 320,
                  overflow: "auto",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  fontSize: "var(--font-label, 12px)",
                }}
              >
                {prettyPayload(detail.payload)}
              </pre>
            </div>

            <div style={{ marginTop: "0.75rem", display: "flex", gap: 8 }}>
              <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => retry(detail)}>
                {t("iface.retry", "Retry")}
              </button>
            </div>
          </>
        ) : null}
      </RecordModal>
    </AppShell>
  );
}
