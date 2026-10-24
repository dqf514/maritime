"use client";

// Interface Messages console — IMOS Data Center 标配。
// Integration exchange log: inbound/outbound tabs + stats, retry with stub processor.

import { RefreshButton } from "@/components/RefreshButton";
import { msgOf, handled } from "@/lib/errors";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { Tabs } from "@/components/Tabs";
import { Toolbar } from "@/components/Toolbar";
import { StatusBadge } from "@/components/StatusBadge";
import { RecordModal } from "@/components/RecordModal";
import { StateView } from "@/components/StateView";
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

/** 端点单次上限 200 条；按 100 一页递增加载，末尾显示「已加载 N 条」并提供「加载更多」 */
const PAGE_SIZE = 100;

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
  const [err, setErr] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const offsetRef = useRef(0);

  const load = useCallback(
    async (append = false) => {
      setLoading(true);
      setErr(null);
      try {
        if (tab === "stats") {
          setStats((await apiGet("/api/v1/interface/messages/stats")) as Stats);
          return;
        }
        const direction = tab === "in" ? "inbound" : "outbound";
        const qs = new URLSearchParams({ direction });
        if (statusFilter) qs.set("status", statusFilter);
        const off = append ? offsetRef.current : 0;
        qs.set("limit", String(PAGE_SIZE));
        qs.set("offset", String(off));
        const got = (await apiGet(`/api/v1/interface/messages?${qs.toString()}`)) as Msg[];
        setRows((prev) => (append ? [...prev, ...got] : got));
        offsetRef.current = off + got.length;
        setHasMore(got.length >= PAGE_SIZE);
      } catch (ex) {
        setErr(msgOf(ex));
      } finally {
        setLoading(false);
      }
    },
    [tab, statusFilter],
  );

  useEffect(() => {
    offsetRef.current = 0;
    setHasMore(false);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load(false).catch(handled);
  }, [load]);

  const openDetail = useCallback(
    async (row: Msg) => {
      try {
        setDetail((await apiGet(`/api/v1/interface/messages/${row.id}`)) as Msg);
      } catch (err) {
        toast.error(t("iface.detail_fail", "Failed to load message detail: {err}", { err: msgOf(err) }));
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
        toast.error(t("iface.retry_fail", "Retry failed: {err}", { err: msgOf(err) }));
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

  const columns = useMemo<ColumnDef<Msg>[]>(() => [
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
  ], [busy, openDetail, retry, t]);

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
        <StateView
          loading={loading}
          error={err ?? undefined}
          empty={!stats}
          onRetry={() => load(false)}
          emptyText={t("iface.empty_stats", "No statistics yet")}
        >
          {stats ? (
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
          ) : null}
        </StateView>
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
            <RefreshButton label={t("iface.refresh", "Refresh")} className="btn btn-sm" onClick={() => load(false)} />
            <span className="muted" style={{ fontSize: "var(--font-label)" }}>
              {t("common.count_total", "共 {n} 条", { n: rows.length })}
            </span>
          </Toolbar>

          <StateView
            loading={loading}
            error={err ?? undefined}
            empty={!rows.length}
            onRetry={() => load(false)}
            emptyText={t("iface.empty", "No interface messages")}
          >
            <DataGrid<Msg>
              columns={columns}
              data={rows}
              rowKey={(r) => r.id}
              storageKey="platform_interfaces"
              loading={loading}
              onRowDoubleClick={(r) => openDetail(r)}
              emptyText={t("iface.empty", "No interface messages")}
            />
          </StateView>
          <div className="dt-pager">
            <span className="muted">
              {t("iface.loaded_hint", "已加载 {n} 条（每次 {size} 条）", { n: rows.length, size: PAGE_SIZE })}
            </span>
            {hasMore ? (
              <button type="button" className="btn btn-sm" disabled={loading} onClick={() => load(true)}>
                {t("common.load_more", "加载更多")}
              </button>
            ) : null}
          </div>
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
