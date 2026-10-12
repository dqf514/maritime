"use client";

// 航次工作台（Phase 2）：标签式布局替代单页长滚动 —
// Summary / P&L / Port Calls / Finance / Map / Notes / Instructions / Activity。

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { DateInput } from "@/components/DateInput";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { RevisionsPanel } from "@/components/RevisionsPanel";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { useStateActions } from "@/components/useTransitions";
import { StateView } from "@/components/StateView";
import { useToast } from "@/components/ToastProvider";
import { ValidateButton, type ValidateIssue } from "@/components/ValidateButton";
import { DataGrid } from "@/components/grid/DataGrid";
import type { ColumnDef as GridColumnDef } from "@/components/grid/types";
import { Panel } from "@/components/workspace/Panel";
import { PanelTabs } from "@/components/workspace/PanelTabs";
import { PortTime } from "@/components/PortTime";
import { VoyageTimeline, type TimelineEvent, type TimelinePortCall } from "@/components/workspace/VoyageTimeline";
import { WorkspaceShell } from "@/components/workspace/WorkspaceShell";
import { apiDelete, apiGet, apiPatch, apiPost, type VoyageOverview, type VoyagePnlLine } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

// —— helpers ——

function fmtDate(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fmtDay(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function fmtMoney(n: number | null | undefined, currency: string, locale: string) {
  if (n === null || n === undefined) return "—";
  const text = n.toLocaleString(locale.startsWith("zh") ? "zh-CN" : "en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
  return currency ? `${currency} ${text}` : text;
}

function varianceClass(n: number | null | undefined) {
  if (n === null || n === undefined || n === 0) return "";
  return n < 0 ? "neg" : "pos";
}

type PortRef = { id: string; name: string; latitude: number | null; longitude: number | null; timezone?: string | null };

type PortFunctionMeta = { code: string; label_en: string; label_zh: string; tone: string };

type PcRow = TimelinePortCall & {
  function_code?: string | null;
  id?: string | null;
  port_id?: string | null;
  timezone?: string | null;
};

function fnTone(tone: string): StatusTone | null {
  return tone === "ok" || tone === "warn" || tone === "danger" || tone === "info" || tone === "muted" ? tone : null;
}

type VoyageNote = {
  id: string;
  content?: string | null;
  body?: string | null;
  note?: string | null;
  author_name?: string | null;
  created_by_name?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

type ActivityItem = {
  id?: string;
  at?: string | null;
  created_at?: string | null;
  kind?: string | null;
  type?: string | null;
  action?: string | null;
  title?: string | null;
  label?: string | null;
  detail?: string | null;
  message?: string | null;
};

/** 列表容错：数组 / {items} 包裹 / 端点未挂载(404|405) → 空 */
async function fetchList<T>(path: string): Promise<T[]> {
  try {
    const data = await apiGet(path);
    if (Array.isArray(data)) return data as T[];
    if (data && Array.isArray((data as { items?: unknown }).items)) return (data as { items: T[] }).items;
    return [];
  } catch (e: any) {
    if (e?.status === 404 || e?.status === 405) return [];
    throw e;
  }
}

function noteText(n: VoyageNote): string {
  return (n.content ?? n.body ?? n.note ?? "").trim();
}

// —— map projection (equirectangular + great-circle waypoints) ——

const MAP_W = 960;
const MAP_H = 420;

function proj(lat: number, lon: number): [number, number] {
  const x = ((lon + 180) / 360) * MAP_W;
  const y = ((90 - lat) / 180) * MAP_H;
  return [x, y];
}

function greatCircle(a: [number, number], b: [number, number], steps = 24): [number, number][] {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const lat1 = toRad(a[0]);
  const lon1 = toRad(a[1]);
  const lat2 = toRad(b[0]);
  const lon2 = toRad(b[1]);
  const d =
    2 *
    Math.asin(
      Math.sqrt(
        Math.sin((lat2 - lat1) / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin((lon2 - lon1) / 2) ** 2,
      ),
    );
  if (!d || Number.isNaN(d)) return [a, b];
  const out: [number, number][] = [];
  for (let i = 0; i <= steps; i++) {
    const f = i / steps;
    const A = Math.sin((1 - f) * d) / Math.sin(d);
    const B = Math.sin(f * d) / Math.sin(d);
    const x = A * Math.cos(lat1) * Math.cos(lon1) + B * Math.cos(lat2) * Math.cos(lon2);
    const y = A * Math.cos(lat1) * Math.sin(lon1) + B * Math.cos(lat2) * Math.sin(lon2);
    const z = A * Math.sin(lat1) + B * Math.sin(lat2);
    const lat = Math.atan2(z, Math.sqrt(x * x + y * y));
    const lon = Math.atan2(y, x);
    out.push([lat, lon]);
  }
  return out;
}

function greatCirclePath(points: [number, number][], toXy: (lat: number, lon: number) => [number, number]): string {
  if (points.length < 2) return "";
  let d = "";
  for (let i = 0; i < points.length - 1; i++) {
    const seg = greatCircle(points[i], points[i + 1]);
    for (const [lat, lon] of seg) {
      const [x, y] = toXy(lat, lon);
      d += `${d ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
    }
  }
  return d;
}

// —— page ——

export default function VoyageWorkspacePage() {
  const { t, locale } = useI18n();
  const toast = useToast();
  const params = useParams();
  const id = String(params.id || "");

  const [data, setData] = useState<VoyageOverview | null>(null);
  const [ports, setPorts] = useState<PortRef[]>([]);
  const [portFns, setPortFns] = useState<PortFunctionMeta[]>([]);
  const [sofEvents, setSofEvents] = useState<{ id: string; event_code: string; event_at: string | null }[]>([]);
  const [noonTrack, setNoonTrack] = useState<{ at: string; lat: number | null; lon: number | null }[]>([]);
  const [laycan, setLaycan] = useState<{ from: string | null; to: string | null } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // notes / instructions
  const [notes, setNotes] = useState<VoyageNote[]>([]);
  const [instructions, setInstructions] = useState<VoyageNote[]>([]);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [noteModal, setNoteModal] = useState<{ open: boolean; kind: "note" | "instruction"; id: string | null }>({
    open: false,
    kind: "note",
    id: null,
  });
  const [noteTextDraft, setNoteTextDraft] = useState("");
  const [noteDate, setNoteDate] = useState("");
  const [savingNote, setSavingNote] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  // port-call create (C2: function_code select)
  const [pcModalOpen, setPcModalOpen] = useState(false);
  const [pcSaving, setPcSaving] = useState(false);
  const [pcForm, setPcForm] = useState({
    port_id: "",
    seq: "1",
    purpose: "load",
    function_code: "",
    eta: "",
    etd: "",
    agent: "",
  });

  const openPortCallModal = useCallback(() => {
    const lastSeq = (data?.port_calls || []).reduce((m, pc) => Math.max(m, pc.seq ?? 0), 0);
    setPcForm({
      port_id: "",
      seq: String(lastSeq + 1),
      purpose: "load",
      function_code: "",
      eta: "",
      etd: "",
      agent: "",
    });
    setPcModalOpen(true);
  }, [data?.port_calls]);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError("");
    try {
      const [overview, portRows, sof, twin, fnRows] = await Promise.all([
        apiGet(`/api/v1/voyages/${id}/overview`),
        fetchList<PortRef>("/api/v1/ports").catch(() => [] as PortRef[]),
        fetchList<{ id: string; event_code: string; event_at: string | null }>(`/api/v1/sof-events?voyage_id=${id}`).catch(
          () => [],
        ),
        apiGet(`/api/v1/twin/voyages/${id}`).catch(() => null),
        fetchList<PortFunctionMeta>("/api/v1/meta/port-functions").catch(() => [] as PortFunctionMeta[]),
      ]);
      setData(overview as VoyageOverview);
      setPorts(portRows);
      setPortFns(fnRows);
      setSofEvents(sof);
      setNoonTrack(Array.isArray(twin?.noon_track) ? twin.noon_track : []);
      const charterId = (overview as VoyageOverview)?.voyage?.charter_id;
      if (charterId) {
        try {
          const ch = await apiGet(`/api/v1/charters/${charterId}`);
          setLaycan({
            from: ch?.laycan_from ? String(ch.laycan_from) : null,
            to: ch?.laycan_to ? String(ch.laycan_to) : null,
          });
        } catch {
          setLaycan(null);
        }
      } else {
        setLaycan(null);
      }
    } catch (e: any) {
      setError(e?.message || t("common.failed", "Failed"));
    } finally {
      setLoading(false);
    }
  }, [id, t]);

  const savePortCall = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      if (!id) return;
      setPcSaving(true);
      try {
        await apiPost("/api/v1/port-calls", {
          voyage_id: id,
          port_id: pcForm.port_id || null,
          seq: Number(pcForm.seq) || 1,
          purpose: pcForm.purpose || "load",
          function_code: pcForm.function_code || null,
          eta: pcForm.eta ? new Date(pcForm.eta).toISOString() : null,
          etd: pcForm.etd ? new Date(pcForm.etd).toISOString() : null,
          agent: pcForm.agent || null,
        });
        toast.success(t("ws.pc_created", "Port call added"));
        setPcModalOpen(false);
        await load();
      } catch (ex: any) {
        toast.error(ex?.message || t("common.failed", "Failed"));
      } finally {
        setPcSaving(false);
      }
    },
    [id, pcForm, load, toast, t],
  );

  const loadAux = useCallback(async () => {
    if (!id) return;
    const [n, ins, act] = await Promise.all([
      fetchList<VoyageNote>(`/api/v1/voyages/${id}/notes`).catch(() => [] as VoyageNote[]),
      fetchList<VoyageNote>(`/api/v1/voyages/${id}/instructions`).catch(() => [] as VoyageNote[]),
      fetchList<ActivityItem>(`/api/v1/voyages/${id}/activity`).catch(() => [] as ActivityItem[]),
    ]);
    setNotes(n);
    setInstructions(ins);
    setActivity(act);
  }, [id]);

  useEffect(() => {
    load();
    loadAux();
  }, [load, loadAux]);

  const voyage = data?.voyage;
  const pnl = data?.pnl;
  const currency = pnl?.currency || "USD";
  const title = voyage?.voyage_no || voyage?.vessel_name || id.slice(0, 8);

  // 状态机动作可见性：只渲染当前状态可执行的转移（非法动作不出现）
  const nextStatuses = useStateActions("voyage", voyage?.status);
  async function goStatus(target: string) {
    try {
      await apiPost(`/api/v1/voyages/${id}/transition`, { target });
      toast.success(t("ws.status_changed", "Status changed → {s}", { s: target }));
      await load();
    } catch (e: any) {
      toast.error(e?.message || t("common.failed", "Operation failed"));
    }
  }

  const portById = useMemo(() => {
    const m = new Map<string, PortRef>();
    for (const p of ports) m.set(p.id, p);
    return m;
  }, [ports]);

  const timelinePortCalls: PcRow[] = useMemo(
    () =>
      (data?.port_calls || []).map((pc, i) => {
        const port = portById.get(pc.port_id || "");
        const tz =
          (pc as { timezone?: string | null }).timezone ??
          (port as { timezone?: string | null } | undefined)?.timezone ??
          null;
        return {
          id: pc.id,
          seq: pc.seq ?? i + 1,
          port_name: pc.port_name || port?.name || pc.port_id?.slice(0, 8) || "?",
          port_id: pc.port_id ?? null,
          eta: pc.eta,
          etd: pc.etd,
          ata: pc.ata,
          atd: pc.atd,
          purpose: pc.purpose,
          function_code: (pc as { function_code?: string | null }).function_code ?? null,
          timezone: tz,
        };
      }),
    [data?.port_calls, portById],
  );

  const fnByCode = useMemo(() => {
    const m = new Map<string, PortFunctionMeta>();
    for (const fn of portFns) m.set(fn.code, fn);
    return m;
  }, [portFns]);

  function fnLabel(fn: PortFunctionMeta) {
    return locale.startsWith("zh") ? fn.label_zh || fn.label_en : fn.label_en;
  }

  function PortFnChip({ code }: { code?: string | null }) {
    if (!code) return null;
    const fn = fnByCode.get(code);
    const label = fn ? fnLabel(fn) : code;
    const tone = fn ? fnTone(fn.tone) : null;
    if (!tone) {
      return (
        <span className="muted" title={label}>
          {code}
        </span>
      );
    }
    return <StatusBadge status={code} tone={tone} label={code} title={`${code} · ${label}`} />;
  }

  function runValidate(): ValidateIssue[] {
    const issues: ValidateIssue[] = [];
    const pcs = data?.port_calls || [];
    if (!pcs.length) {
      issues.push({ level: "error", message: t("ws.val.no_ports", "Voyage has no port calls") });
      return issues;
    }
    for (const pc of pcs) {
      if (pc.atd && !pc.etd) {
        issues.push({
          level: "warn",
          message: t("ws.val.missing_etd", "Departed port call missing ETD: {port}", {
            port: pc.port_name || pc.port_id?.slice(0, 8) || "?",
          }),
        });
      }
    }
    const fromTs = laycan?.from ? new Date(laycan.from).getTime() : null;
    if (fromTs !== null) {
      for (const pc of pcs) {
        const eta = pc.eta ? new Date(pc.eta).getTime() : null;
        if (eta === null) continue;
        if (fromTs !== null && eta < fromTs) {
          issues.push({
            level: "warn",
            message: t("ws.val.eta_before_laycan", "ETA before laycan: {port} {eta}", {
              port: pc.port_name || pc.port_id?.slice(0, 8) || "?",
              eta: fmtDay(pc.eta),
            }),
          });
        }
      }
    }
    return issues;
  }

  const timelineEvents: TimelineEvent[] = useMemo(
    () =>
      sofEvents
        .filter((e) => e.event_at)
        .map((e) => ({ type: e.event_code, at: e.event_at as string, label: e.event_code })),
    [sofEvents],
  );

  // Map tab geometry
  const mapModel = useMemo(() => {
    const calls = data?.port_calls || [];
    const coords: { name: string; lat: number; lon: number; seq: number }[] = [];
    for (const pc of calls) {
      const ref = pc.port_id ? portById.get(pc.port_id) : undefined;
      if (ref && ref.latitude != null && ref.longitude != null) {
        coords.push({
          name: ref.name,
          lat: Number(ref.latitude),
          lon: Number(ref.longitude),
          seq: pc.seq ?? coords.length + 1,
        });
      }
    }
    const track: [number, number][] = noonTrack
      .filter((n) => n.lat != null && n.lon != null)
      .map((n) => [Number(n.lat), Number(n.lon)]);
    return { coords, track };
  }, [data?.port_calls, portById, noonTrack]);

  // —— derived activity fallback (when /activity endpoint not mounted) ——
  const activityView: ActivityItem[] = useMemo(() => {
    if (activity.length) return activity;
    const derived: ActivityItem[] = [];
    for (const pc of data?.port_calls || []) {
      if (pc.ata) derived.push({ at: pc.ata, kind: "port", title: t("ws.act.arrive", "Arrived {port}", { port: pc.port_name || pc.port_id?.slice(0, 8) || "" }) });
      if (pc.atd) derived.push({ at: pc.atd, kind: "port", title: t("ws.act.depart", "Departed {port}", { port: pc.port_name || pc.port_id?.slice(0, 8) || "" }) });
    }
    for (const ev of sofEvents) {
      if (ev.event_at) derived.push({ at: ev.event_at, kind: "sof", title: `${ev.event_code}` });
    }
    for (const oh of data?.off_hire || []) {
      if (oh.start_at) derived.push({ at: oh.start_at, kind: "offhire", title: t("ws.act.offhire", "Off-hire started") });
    }
    for (const inv of data?.invoices || []) {
      derived.push({ at: null, kind: "invoice", title: `${inv.invoice_no || inv.id.slice(0, 8)} · ${inv.status || ""}` });
    }
    return derived.sort((a, b) => String(b.at || "").localeCompare(String(a.at || "")));
  }, [activity, data, sofEvents, t]);

  // —— notes CRUD (tolerant: endpoint may be /notes or not mounted yet) ——

  const openNoteModal = useCallback((kind: "note" | "instruction", edit?: VoyageNote) => {
    setNoteModal({ open: true, kind, id: edit?.id ?? null });
    setNoteTextDraft(edit ? noteText(edit) : "");
    setNoteDate(edit?.created_at ? String(edit.created_at).slice(0, 10) : new Date().toISOString().slice(0, 10));
  }, []);

  const saveNote = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      if (!id) return;
      setSavingNote(true);
      const base = `/api/v1/voyages/${id}/${noteModal.kind === "note" ? "notes" : "instructions"}`;
      try {
        const payload = { content: noteTextDraft, body: noteTextDraft, note_date: noteDate || undefined };
        if (noteModal.id) {
          await apiPatch(`${base}/${noteModal.id}`, payload);
        } else {
          await apiPost(base, payload);
        }
        toast.success(t("common.saved", "Saved"));
        setNoteModal({ open: false, kind: "note", id: null });
        setNoteTextDraft("");
        await loadAux();
      } catch (ex: any) {
        toast.error(ex?.message || t("common.failed", "Failed"));
      } finally {
        setSavingNote(false);
      }
    },
    [id, noteModal, noteTextDraft, noteDate, loadAux, toast, t],
  );

  const deleteNote = useCallback(
    async (kind: "note" | "instruction", noteId: string) => {
      const base = `/api/v1/voyages/${id}/${kind === "note" ? "notes" : "instructions"}`;
      try {
        await apiDelete(`${base}/${noteId}`);
        toast.success(t("common.deleted", "Deleted"));
        await loadAux();
      } catch (ex: any) {
        toast.error(ex?.message || t("common.failed", "Failed"));
      }
    },
    [id, loadAux, toast, t],
  );

  // —— tab contents ——

  const summaryTab = (
    <div className="ws-grid-2">
      <Panel title={t("ws.summary", "Voyage summary")}>
        <div className="ws-kv-grid">
          <div className="ws-kv">
            <span>{t("ws.vessel", "Vessel")}</span>
            <strong>{voyage?.vessel_name || "—"}</strong>
          </div>
          <div className="ws-kv">
            <span>{t("ws.charter_no", "Charter no.")}</span>
            <strong>{data?.charter?.charter_no || "—"}</strong>
          </div>
          <div className="ws-kv">
            <span>{t("ws.charter_type", "Charter type")}</span>
            <strong>{data?.charter?.charter_type || "—"}</strong>
          </div>
          <div className="ws-kv">
            <span>{t("ws.counterparty", "Counterparty")}</span>
            <strong>{data?.charter?.counterparty_name || "—"}</strong>
          </div>
          <div className="ws-kv">
            <span>CP</span>
            <strong>{fmtDay(voyage?.cp_date)}</strong>
          </div>
          <div className="ws-kv">
            <span>{t("ws.started", "Started")}</span>
            <strong>{fmtDate(voyage?.started_at)}</strong>
          </div>
          <div className="ws-kv">
            <span>{t("ws.completed", "Completed")}</span>
            <strong>{fmtDate(voyage?.completed_at)}</strong>
          </div>
          <div className="ws-kv">
            <span>{t("common.status", "Status")}</span>
            <strong>{voyage?.status || "—"}</strong>
          </div>
          <div className="ws-kv">
            <span>{t("ws.tce", "TCE")}</span>
            <strong>{fmtMoney(data?.estimate?.results_summary?.tce ?? null, currency, locale)}</strong>
          </div>
          <div className="ws-kv">
            <span>{t("ws.est_revenue", "Estimated revenue")}</span>
            <strong>{fmtMoney(data?.estimate?.results_summary?.total_revenue ?? null, currency, locale)}</strong>
          </div>
          <div className="ws-kv">
            <span>{t("ws.est_cost", "Estimated voyage cost")}</span>
            <strong>{fmtMoney(data?.estimate?.results_summary?.voyage_cost ?? null, currency, locale)}</strong>
          </div>
          <div className="ws-kv">
            <span>{t("ws.noon_reports", "Noon reports")}</span>
            <strong>{data?.noon_reports_count ?? 0}</strong>
          </div>
        </div>
      </Panel>

      <Panel title={t("ws.lifecycle", "Lifecycle")}>
        {data?.lifecycle?.length ? (
          <ol className="lc-stepper" style={{ flexWrap: "wrap" }}>
            {data.lifecycle.map((step, i) => {
              const label = locale.startsWith("zh") ? step.label.zh || step.label.en : step.label.en;
              const inner = (
                <span className="lc-step-link">
                  <span className="lc-dot" aria-hidden>
                    {step.state === "done" ? (
                      <svg viewBox="0 0 12 12" width="11" height="11">
                        <path fill="currentColor" d="M4.4 9 1.6 6.2l1-1 1.8 1.8L9.3 2.1l1 1z" />
                      </svg>
                    ) : (
                      i + 1
                    )}
                  </span>
                  <span className="lc-text">
                    <strong>{label}</strong>
                    {step.detail ? <small>{step.detail}</small> : null}
                  </span>
                </span>
              );
              return (
                <li key={step.key} className={`lc-step ${step.state}`}>
                  {step.href ? (
                    <Link href={step.href} className="lc-step-link">
                      {inner}
                    </Link>
                  ) : (
                    inner
                  )}
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="muted">{t("common.no_data", "No data")}</p>
        )}
      </Panel>
    </div>
  );

  const pnlColumns: GridColumnDef<VoyagePnlLine>[] = [
    {
      key: "category",
      title: t("ws.pnl_category", "Cost category"),
      minWidth: 140,
      value: (r) => t(`ws.pnl.${r.key}`, r.key),
    },
    {
      key: "estimated",
      title: t("ws.pnl_estimated_col", "Estimated"),
      width: 130,
      align: "right",
      value: (r) => r.estimated,
      render: (v) => fmtMoney(v as number | null, currency, locale),
    },
    {
      key: "actual",
      title: t("ws.pnl_actual_col", "Actual"),
      width: 130,
      align: "right",
      value: (r) => r.actual,
      render: (v) => fmtMoney(v as number | null, currency, locale),
    },
    {
      key: "variance",
      title: t("ws.pnl_variance_col", "Variance"),
      width: 130,
      align: "right",
      value: (r) => r.variance,
      render: (v) => <span className={varianceClass(v as number | null)}>{fmtMoney(v as number | null, currency, locale)}</span>,
    },
  ];

  const pnlTab = pnl ? (
    <Panel title={t("ws.pnl_title", "P&L attribution")}>
      <div className="desk-results pnl-summary">
        <div className="kv-box">
          <span>{t("ws.pnl_estimated", "Estimated P&L")}</span>
          <strong>{fmtMoney(pnl.estimated_pnl, currency, locale)}</strong>
        </div>
        <div className="kv-box">
          <span>{t("ws.pnl_actual", "Actual P&L")}</span>
          <strong>{fmtMoney(pnl.actual_pnl, currency, locale)}</strong>
        </div>
        <div className="kv-box">
          <span>{t("ws.pnl_variance", "Variance")}</span>
          <strong className={varianceClass(pnl.variance_pnl)}>{fmtMoney(pnl.variance_pnl, currency, locale)}</strong>
        </div>
      </div>
      <div style={{ marginTop: "0.65rem" }}>
        <DataGrid<VoyagePnlLine>
          columns={pnlColumns}
          data={pnl.lines || []}
          rowKey={(r) => r.key}
          storageKey="voyage_ws_pnl_grid"
          showFooter={false}
          emptyText={t("common.no_data", "No data")}
        />
      </div>
    </Panel>
  ) : (
    <Panel title={t("ws.pnl_title", "P&L attribution")}>
      <p className="muted">{t("common.no_data", "No data")}</p>
    </Panel>
  );

  const pcColumns: GridColumnDef<(typeof timelinePortCalls)[number]>[] = [
    { key: "seq", title: "#", width: 48, align: "right" },
    { key: "port_name", title: t("ws.port", "Port"), width: 160 },
    {
      key: "purpose",
      title: t("ws.purpose", "Purpose"),
      width: 140,
      render: (v, row) => (
        <>
          {v ? String(v) : "—"} <PortFnChip code={row.function_code} />
        </>
      ),
    },
    {
      key: "eta",
      title: "ETA",
      width: 150,
      render: (v, row) => <PortTime value={v as string | null} tz={row.timezone} showTz />,
    },
    {
      key: "ata",
      title: "ATA",
      width: 150,
      render: (v, row) => {
        const eta = row.eta ? new Date(row.eta).getTime() : null;
        const ata = row.ata ? new Date(row.ata).getTime() : null;
        const delayed = eta !== null && ata !== null && ata > eta;
        return (
          <span className={delayed ? "neg" : ""}>
            <PortTime value={v as string | null} tz={row.timezone} showTz />
            {delayed ? <span className="badge badge-fail" style={{ marginLeft: 6 }}>{t("ws.delayed", "Delayed")}</span> : null}
          </span>
        );
      },
    },
    { key: "etd", title: "ETD", width: 150, render: (v, row) => <PortTime value={v as string | null} tz={row.timezone} showTz /> },
    { key: "atd", title: "ATD", width: 150, render: (v, row) => <PortTime value={v as string | null} tz={row.timezone} showTz /> },
  ];

  const portCallsTab = (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap-md)" }}>
      <Panel title={t("ws.timeline", "Voyage timeline")} collapsible>
        <VoyageTimeline portCalls={timelinePortCalls} events={timelineEvents} />
      </Panel>
      <Panel
        title={t("ws.port_calls", "Port calls")}
        flush
        actions={
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => openPortCallModal()}>
            + {t("common.add", "Add")}
          </button>
        }
      >
        <DataGrid
          columns={pcColumns}
          data={timelinePortCalls}
          rowKey={(row) => row.id || `${row.seq}-${row.port_name}`}
          emptyText={t("common.empty", "No records")}
        />
      </Panel>
    </div>
  );

  type LaytimeRow = NonNullable<VoyageOverview["laytime"]>[number];
  type ClaimRow = NonNullable<VoyageOverview["claims"]>[number];
  type InvoiceRow = NonNullable<VoyageOverview["invoices"]>[number];
  type OffHireRow = NonNullable<VoyageOverview["off_hire"]>[number];

  const laytimeColumns: GridColumnDef<LaytimeRow>[] = [
    {
      key: "result_type",
      title: t("ws.result_type", "Result"),
      minWidth: 110,
      value: (r) => r.result_type || "",
      render: (v) => (v ? String(v) : "—"),
    },
    { key: "status", title: t("common.status", "Status"), width: 110, value: (r) => r.status },
    {
      key: "amount",
      title: t("common.amount", "Amount"),
      width: 130,
      align: "right",
      value: (r) => r.amount,
      render: (v, r) => fmtMoney(v as number | null, r.currency || currency, locale),
    },
  ];

  const claimColumns: GridColumnDef<ClaimRow>[] = [
    {
      key: "claim_no",
      title: t("ws.claim_no", "Claim no."),
      minWidth: 130,
      value: (r) => r.claim_no || r.id.slice(0, 8),
    },
    {
      key: "status",
      title: t("common.status", "Status"),
      width: 110,
      value: (r) => r.status || "",
      render: (v) => (v ? String(v) : "—"),
    },
    {
      key: "amount",
      title: t("common.amount", "Amount"),
      width: 130,
      align: "right",
      value: (r) => r.amount,
      render: (v, r) => fmtMoney(v as number | null, r.currency || currency, locale),
    },
  ];

  const invoiceColumns: GridColumnDef<InvoiceRow>[] = [
    {
      key: "invoice_no",
      title: t("ws.invoice_no", "Invoice no."),
      minWidth: 130,
      value: (r) => r.invoice_no || r.id.slice(0, 8),
    },
    {
      key: "status",
      title: t("common.status", "Status"),
      width: 110,
      value: (r) => r.status || "",
      render: (v) => (v ? String(v) : "—"),
    },
    {
      key: "amount",
      title: t("common.amount", "Amount"),
      width: 130,
      align: "right",
      value: (r) => r.amount,
      render: (v, r) => fmtMoney(v as number | null, r.currency || currency, locale),
    },
  ];

  const offHireWsColumns: GridColumnDef<OffHireRow>[] = [
    {
      key: "start_at",
      title: t("ws.start", "Start"),
      width: 140,
      value: (r) => r.start_at || "",
      render: (v) => fmtDate(v as string | null),
    },
    {
      key: "end_at",
      title: t("ws.end", "End"),
      width: 140,
      value: (r) => r.end_at || "",
      render: (v) => (v ? fmtDate(v as string) : t("ws.oh_open", "In progress")),
    },
    {
      key: "reason",
      title: t("ws.reason", "Reason"),
      minWidth: 130,
      value: (r) => r.reason || "",
      render: (v) => (v ? String(v) : "—"),
    },
  ];

  const financeTab = (
    <div className="ws-grid-2">
      <Panel title={t("ws.laytime", "Laytime/despatch")} flush>
        <DataGrid<LaytimeRow>
          columns={laytimeColumns}
          data={data?.laytime || []}
          rowKey={(r) => r.id}
          storageKey="voyage_ws_laytime_grid"
          showFooter={false}
          emptyText={t("common.no_data", "No data")}
        />
      </Panel>
      <Panel title={t("ws.claims", "Claims")} flush>
        <DataGrid<ClaimRow>
          columns={claimColumns}
          data={data?.claims || []}
          rowKey={(r) => r.id}
          storageKey="voyage_ws_claims_grid"
          showFooter={false}
          emptyText={t("common.no_data", "No data")}
        />
      </Panel>
      <Panel title={t("ws.invoices", "Invoices")} flush>
        <DataGrid<InvoiceRow>
          columns={invoiceColumns}
          data={data?.invoices || []}
          rowKey={(r) => r.id}
          storageKey="voyage_ws_invoices_grid"
          showFooter={false}
          emptyText={t("common.no_data", "No data")}
        />
      </Panel>
      <Panel title={t("ws.off_hire", "Off-hire")} flush>
        <DataGrid<OffHireRow>
          columns={offHireWsColumns}
          data={data?.off_hire || []}
          rowKey={(r) => r.id}
          storageKey="voyage_ws_offhire_grid"
          showFooter={false}
          emptyText={t("common.no_data", "No data")}
        />
      </Panel>
    </div>
  );

  const mapPath = greatCirclePath(
    mapModel.coords.map((c) => [c.lat, c.lon] as [number, number]),
    proj,
  );
  const trackPath = greatCirclePath(mapModel.track, proj);

  const mapTab = (
    <Panel title={t("ws.map", "Route map")} collapsible>
      {mapModel.coords.length + mapModel.track.length > 0 ? (
        <>
          <div className="ws-map">
            <svg viewBox={`0 0 ${MAP_W} ${MAP_H}`} role="img" aria-label={t("ws.map", "Route map")}>
              <rect x={0} y={0} width={MAP_W} height={MAP_H} fill="transparent" />
              {Array.from({ length: 12 }, (_, i) => (
                <line
                  key={`v${i}`}
                  x1={(i * MAP_W) / 12}
                  x2={(i * MAP_W) / 12}
                  y1={0}
                  y2={MAP_H}
                  stroke="rgba(15,28,40,0.06)"
                  strokeWidth={1}
                />
              ))}
              {Array.from({ length: 6 }, (_, i) => (
                <line
                  key={`h${i}`}
                  y1={(i * MAP_H) / 6}
                  y2={(i * MAP_H) / 6}
                  x1={0}
                  x2={MAP_W}
                  stroke="rgba(15,28,40,0.06)"
                  strokeWidth={1}
                />
              ))}
              <line x1={0} x2={MAP_W} y1={MAP_H / 2} y2={MAP_H / 2} stroke="rgba(15,28,40,0.14)" strokeDasharray="6 4" />
              {trackPath ? (
                <path d={trackPath} fill="none" stroke="#2f6fb0" strokeWidth={2} strokeDasharray="3 3" opacity={0.8} />
              ) : null}
              {mapPath ? <path d={mapPath} fill="none" stroke="#1A9B96" strokeWidth={2.5} strokeLinecap="round" /> : null}
              {mapModel.coords.map((c, i) => {
                const [x, y] = proj(c.lat, c.lon);
                return (
                  <g key={`${c.name}-${i}`}>
                    <circle cx={x} cy={y} r={5} fill="#fff" stroke="#1A9B96" strokeWidth={2.5} />
                    <text x={x + 8} y={y + 4} fontSize={11} fontWeight={600} fill="#0f1c28">
                      {c.seq}. {c.name}
                    </text>
                  </g>
                );
              })}
              {mapModel.track.map((p, i) => {
                const [x, y] = proj(p[0], p[1]);
                return <circle key={`t${i}`} cx={x} cy={y} r={2} fill="#2f6fb0" opacity={0.7} />;
              })}
            </svg>
          </div>
          <div className="ws-map-legend">
            <span>
              <i style={{ background: "#1A9B96" }} />
              {t("ws.map_route", "Planned route (great circle)")}
            </span>
            {trackPath ? (
              <span>
                <i style={{ background: "#2f6fb0" }} />
                {t("ws.map_track", "Noon position track")}
              </span>
            ) : null}
          </div>
        </>
      ) : (
        <p className="muted">{t("ws.map_empty", "No port coordinates or position data")}</p>
      )}
    </Panel>
  );

  const renderNoteList = (kind: "note" | "instruction", rows: VoyageNote[]) => (
    <Panel
      title={kind === "note" ? t("ws.notes", "Voyage notes") : t("ws.instructions", "Voyage instructions")}
      actions={
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => openNoteModal(kind)}>
          + {t("common.add", "Add")}
        </button>
      }
    >
      {rows.length ? (
        <div className="ws-note-list">
          {rows.map((n) => (
            <div className="ws-note" key={n.id}>
              <div className="ws-note-head">
                <small>
                  {n.author_name || n.created_by_name || "—"} · {fmtDate(n.updated_at || n.created_at)}
                </small>
                <span style={{ display: "flex", gap: 4 }}>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => openNoteModal(kind, n)}>
                    {t("common.edit", "Edit")}
                  </button>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => deleteNote(kind, n.id)}>
                    {t("common.delete", "Delete")}
                  </button>
                </span>
              </div>
              <p className="ws-note-body">{noteText(n)}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">{t("common.empty", "No records")}</p>
      )}
    </Panel>
  );

  const activityTab = (
    <Panel title={t("ws.activity", "Activity log")}>
      {activityView.length ? (
        <ul className="ws-activity">
          {activityView.map((a, i) => (
            <li key={a.id || `${a.at}-${i}`}>
              <time>{a.at || a.created_at ? fmtDate(a.at || a.created_at) : "—"}</time>
              <span className="ws-act-kind">{a.kind || a.type || a.action || "event"}</span>
              <span>{a.title || a.label || a.message || a.detail || "—"}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">{t("common.empty", "No records")}</p>
      )}
    </Panel>
  );

  return (
    <AppShell>
      <WorkspaceShell
        header={
          <PageHeader
            breadcrumb={[
              { label: t("nav.voyages", "Voyages"), href: "/operations/voyages" },
              { label: `${t("common.voyage", "Voyage")} ${title}` },
            ]}
            title={
              <>
                {t("ws.title", "Voyage workspace")}
                <span>{title}</span>
                {voyage ? <StatusBadge status={voyage.status} /> : null}
              </>
            }
            subtitle={
              <>
                {voyage?.vessel_name
                  ? t("ws.sub_vessel", "Vessel {vessel}", { vessel: voyage.vessel_name })
                  : t("ws.sub", "Full lifecycle voyage workspace")}
                {data?.charter?.charter_no ? ` · ${data.charter.charter_no}` : ""}
                {data?.charter?.counterparty_name ? ` · ${data.charter.counterparty_name}` : ""}
              </>
            }
            actions={
              <>
                <ValidateButton onValidate={runValidate} disabled={!data} />
                {nextStatuses.map((s) => (
                  <button key={s} type="button" className="btn btn-sm" onClick={() => goStatus(s)}>
                    {t(`ws.go_${s}`, s.replace(/_/g, " "))}
                  </button>
                ))}
                <Link href="/operations/schedule" className="btn btn-ghost btn-sm">
                  {t("ws.open_schedule", "Schedule")}
                </Link>
                <Link href="/finance" className="btn btn-ghost btn-sm">
                  {t("ws.goto_finance", "Finance")}
                </Link>
              </>
            }
          />
        }
        sidebar={id ? <RevisionsPanel entityType="voyage" entityId={id} /> : null}
        sidebarOpen={sidebarOpen}
        onToggleSidebar={() => setSidebarOpen((v) => !v)}
      >
        <StateView loading={loading && !data} error={error} empty={false} onRetry={load}>
          <PanelTabs
            tabs={[
              { id: "summary", label: t("ws.tab_summary", "Summary"), content: summaryTab },
              { id: "pnl", label: t("ws.tab_pnl", "P&L"), content: pnlTab },
              { id: "ports", label: t("ws.tab_ports", "Port activity"), content: portCallsTab },
              { id: "finance", label: t("ws.tab_finance", "Finance"), content: financeTab },
              { id: "map", label: t("ws.tab_map", "Map"), content: mapTab },
              { id: "notes", label: t("ws.tab_notes", "Notes"), content: renderNoteList("note", notes) },
              {
                id: "instructions",
                label: t("ws.tab_instructions", "Instructions"),
                content: renderNoteList("instruction", instructions),
              },
              { id: "activity", label: t("ws.tab_activity", "Activity"), content: activityTab },
            ]}
          />
        </StateView>
      </WorkspaceShell>

      <RecordModal
        open={pcModalOpen}
        title={t("ws.add_port_call", "Add port call")}
        onClose={() => setPcModalOpen(false)}
        onSave={savePortCall}
        canDelete={false}
        saving={pcSaving}
      >
        <label>
          {t("ws.port", "Port")}
          <select value={pcForm.port_id} onChange={(e) => setPcForm({ ...pcForm, port_id: e.target.value })}>
            <option value="">—</option>
            {ports.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("ws.purpose", "Purpose")}
          <select value={pcForm.purpose} onChange={(e) => setPcForm({ ...pcForm, purpose: e.target.value })}>
            <option value="load">load</option>
            <option value="discharge">discharge</option>
            <option value="bunker">bunker</option>
            <option value="transit">transit</option>
          </select>
        </label>
        <label>
          {t("ws.function_code", "Function")}
          <select
            value={pcForm.function_code}
            onChange={(e) => setPcForm({ ...pcForm, function_code: e.target.value })}
          >
            <option value="">{t("common.none", "None")}</option>
            {portFns.map((fn) => (
              <option key={fn.code} value={fn.code}>
                {fn.code} · {fnLabel(fn)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("ws.seq", "Seq")}
          <input type="number" value={pcForm.seq} onChange={(e) => setPcForm({ ...pcForm, seq: e.target.value })} />
        </label>
        <label>
          ETA
          <input
            type="datetime-local"
            value={pcForm.eta}
            onChange={(e) => setPcForm({ ...pcForm, eta: e.target.value })}
          />
        </label>
        <label>
          ETD
          <input
            type="datetime-local"
            value={pcForm.etd}
            onChange={(e) => setPcForm({ ...pcForm, etd: e.target.value })}
          />
        </label>
        <label>
          {t("ws.agent", "Agent")}
          <input value={pcForm.agent} onChange={(e) => setPcForm({ ...pcForm, agent: e.target.value })} />
        </label>
      </RecordModal>

      <RecordModal
        open={noteModal.open}
        title={
          noteModal.kind === "note"
            ? noteModal.id
              ? t("ws.edit_note", "Edit note")
              : t("ws.add_note", "Add note")
            : noteModal.id
              ? t("ws.edit_instruction", "Edit instruction")
              : t("ws.add_instruction", "Add instruction")
        }
        onClose={() => setNoteModal({ open: false, kind: "note", id: null })}
        onSave={saveNote}
        onDelete={
          noteModal.id
            ? async () => {
                await deleteNote(noteModal.kind, noteModal.id as string);
                setNoteModal({ open: false, kind: "note", id: null });
              }
            : undefined
        }
        canDelete={!!noteModal.id}
        saving={savingNote}
      >
        <label>
          {t("ws.note_date", "Date")}
          <DateInput value={noteDate} onChange={setNoteDate} />
        </label>
        <label>
          {t("ws.note_content", "Content")}
          <textarea
            rows={6}
            value={noteTextDraft}
            onChange={(e) => setNoteTextDraft(e.target.value)}
            placeholder={t("ws.note_placeholder", "Enter content…")}
          />
        </label>
      </RecordModal>
    </AppShell>
  );
}
