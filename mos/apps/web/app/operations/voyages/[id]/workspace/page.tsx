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
import { StateView } from "@/components/StateView";
import { useToast } from "@/components/ToastProvider";
import { DataGrid } from "@/components/grid/DataGrid";
import type { ColumnDef as GridColumnDef } from "@/components/grid/types";
import { Panel } from "@/components/workspace/Panel";
import { PanelTabs } from "@/components/workspace/PanelTabs";
import { VoyageTimeline, type TimelineEvent, type TimelinePortCall } from "@/components/workspace/VoyageTimeline";
import { WorkspaceShell } from "@/components/workspace/WorkspaceShell";
import { apiDelete, apiGet, apiPatch, apiPost, type VoyageOverview } from "@/lib/api";
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

type PortRef = { id: string; name: string; latitude: number | null; longitude: number | null };

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
  const [sofEvents, setSofEvents] = useState<{ id: string; event_code: string; event_at: string | null }[]>([]);
  const [noonTrack, setNoonTrack] = useState<{ at: string; lat: number | null; lon: number | null }[]>([]);
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

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError("");
    try {
      const [overview, portRows, sof, twin] = await Promise.all([
        apiGet(`/api/v1/voyages/${id}/overview`),
        fetchList<PortRef>("/api/v1/ports").catch(() => [] as PortRef[]),
        fetchList<{ id: string; event_code: string; event_at: string | null }>(`/api/v1/sof-events?voyage_id=${id}`).catch(
          () => [],
        ),
        apiGet(`/api/v1/twin/voyages/${id}`).catch(() => null),
      ]);
      setData(overview as VoyageOverview);
      setPorts(portRows);
      setSofEvents(sof);
      setNoonTrack(Array.isArray(twin?.noon_track) ? twin.noon_track : []);
    } catch (e: any) {
      setError(e?.message || t("common.failed", "加载失败"));
    } finally {
      setLoading(false);
    }
  }, [id, t]);

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

  const portById = useMemo(() => {
    const m = new Map<string, PortRef>();
    for (const p of ports) m.set(p.id, p);
    return m;
  }, [ports]);

  const timelinePortCalls: TimelinePortCall[] = useMemo(
    () =>
      (data?.port_calls || []).map((pc, i) => ({
        seq: pc.seq ?? i + 1,
        port_name: pc.port_name || portById.get(pc.port_id || "")?.name || pc.port_id?.slice(0, 8) || "?",
        eta: pc.eta,
        etd: pc.etd,
        ata: pc.ata,
        atd: pc.atd,
        purpose: pc.purpose,
      })),
    [data?.port_calls, portById],
  );

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
      if (pc.ata) derived.push({ at: pc.ata, kind: "port", title: t("ws.act.arrive", "抵港 {port}", { port: pc.port_name || pc.port_id?.slice(0, 8) || "" }) });
      if (pc.atd) derived.push({ at: pc.atd, kind: "port", title: t("ws.act.depart", "离港 {port}", { port: pc.port_name || pc.port_id?.slice(0, 8) || "" }) });
    }
    for (const ev of sofEvents) {
      if (ev.event_at) derived.push({ at: ev.event_at, kind: "sof", title: `${ev.event_code}` });
    }
    for (const oh of data?.off_hire || []) {
      if (oh.start_at) derived.push({ at: oh.start_at, kind: "offhire", title: t("ws.act.offhire", "停租开始") });
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
        toast.success(t("common.saved", "已保存"));
        setNoteModal({ open: false, kind: "note", id: null });
        setNoteTextDraft("");
        await loadAux();
      } catch (ex: any) {
        toast.error(ex?.message || t("common.failed", "保存失败"));
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
        toast.success(t("common.deleted", "已删除"));
        await loadAux();
      } catch (ex: any) {
        toast.error(ex?.message || t("common.failed", "删除失败"));
      }
    },
    [id, loadAux, toast, t],
  );

  // —— tab contents ——

  const summaryTab = (
    <div className="ws-grid-2">
      <Panel title={t("ws.summary", "航次概要")}>
        <div className="ws-kv-grid">
          <div className="ws-kv">
            <span>{t("ws.vessel", "船舶")}</span>
            <strong>{voyage?.vessel_name || "—"}</strong>
          </div>
          <div className="ws-kv">
            <span>{t("ws.charter_no", "租约号")}</span>
            <strong>{data?.charter?.charter_no || "—"}</strong>
          </div>
          <div className="ws-kv">
            <span>{t("ws.charter_type", "租约类型")}</span>
            <strong>{data?.charter?.charter_type || "—"}</strong>
          </div>
          <div className="ws-kv">
            <span>{t("ws.counterparty", "对手方")}</span>
            <strong>{data?.charter?.counterparty_name || "—"}</strong>
          </div>
          <div className="ws-kv">
            <span>CP</span>
            <strong>{fmtDay(voyage?.cp_date)}</strong>
          </div>
          <div className="ws-kv">
            <span>{t("ws.started", "开始")}</span>
            <strong>{fmtDate(voyage?.started_at)}</strong>
          </div>
          <div className="ws-kv">
            <span>{t("ws.completed", "完成")}</span>
            <strong>{fmtDate(voyage?.completed_at)}</strong>
          </div>
          <div className="ws-kv">
            <span>{t("common.status", "状态")}</span>
            <strong>{voyage?.status || "—"}</strong>
          </div>
          <div className="ws-kv">
            <span>{t("ws.tce", "TCE")}</span>
            <strong>{fmtMoney(data?.estimate?.results_summary?.tce ?? null, currency, locale)}</strong>
          </div>
          <div className="ws-kv">
            <span>{t("ws.est_revenue", "预估收入")}</span>
            <strong>{fmtMoney(data?.estimate?.results_summary?.total_revenue ?? null, currency, locale)}</strong>
          </div>
          <div className="ws-kv">
            <span>{t("ws.est_cost", "预估航次成本")}</span>
            <strong>{fmtMoney(data?.estimate?.results_summary?.voyage_cost ?? null, currency, locale)}</strong>
          </div>
          <div className="ws-kv">
            <span>{t("ws.noon_reports", "正午报")}</span>
            <strong>{data?.noon_reports_count ?? 0}</strong>
          </div>
        </div>
      </Panel>

      <Panel title={t("ws.lifecycle", "生命周期")}>
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

  const pnlTab = pnl ? (
    <Panel title={t("ws.pnl_title", "P&L 归因")}>
      <div className="desk-results pnl-summary">
        <div className="kv-box">
          <span>{t("ws.pnl_estimated", "预估盈亏")}</span>
          <strong>{fmtMoney(pnl.estimated_pnl, currency, locale)}</strong>
        </div>
        <div className="kv-box">
          <span>{t("ws.pnl_actual", "实际盈亏")}</span>
          <strong>{fmtMoney(pnl.actual_pnl, currency, locale)}</strong>
        </div>
        <div className="kv-box">
          <span>{t("ws.pnl_variance", "差异")}</span>
          <strong className={varianceClass(pnl.variance_pnl)}>{fmtMoney(pnl.variance_pnl, currency, locale)}</strong>
        </div>
      </div>
      <table className="table" style={{ marginTop: "0.65rem" }}>
        <thead>
          <tr>
            <th>{t("ws.pnl_category", "费用类别")}</th>
            <th className="num">{t("ws.pnl_estimated_col", "预估")}</th>
            <th className="num">{t("ws.pnl_actual_col", "实际")}</th>
            <th className="num">{t("ws.pnl_variance_col", "差异")}</th>
          </tr>
        </thead>
        <tbody>
          {(pnl.lines || []).map((line) => (
            <tr key={line.key}>
              <td>{t(`ws.pnl.${line.key}`, line.key)}</td>
              <td className="num">{fmtMoney(line.estimated, currency, locale)}</td>
              <td className="num">{fmtMoney(line.actual, currency, locale)}</td>
              <td className={`num ${varianceClass(line.variance)}`}>{fmtMoney(line.variance, currency, locale)}</td>
            </tr>
          ))}
          {!pnl.lines?.length ? (
            <tr>
              <td colSpan={4} className="muted">
                {t("common.no_data", "No data")}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </Panel>
  ) : (
    <Panel title={t("ws.pnl_title", "P&L 归因")}>
      <p className="muted">{t("common.no_data", "No data")}</p>
    </Panel>
  );

  const pcColumns: GridColumnDef<(typeof timelinePortCalls)[number]>[] = [
    { key: "seq", title: "#", width: 48, align: "right" },
    { key: "port_name", title: t("ws.port", "港口"), width: 160 },
    {
      key: "purpose",
      title: t("ws.purpose", "用途"),
      width: 90,
      render: (v) => (v ? String(v) : "—"),
    },
    {
      key: "eta",
      title: "ETA",
      width: 140,
      render: (v) => fmtDate(v as string),
    },
    {
      key: "ata",
      title: "ATA",
      width: 140,
      render: (v, row) => {
        const eta = row.eta ? new Date(row.eta).getTime() : null;
        const ata = row.ata ? new Date(row.ata).getTime() : null;
        const delayed = eta !== null && ata !== null && ata > eta;
        return (
          <span className={delayed ? "neg" : ""}>
            {fmtDate(v as string)}
            {delayed ? <span className="badge badge-fail" style={{ marginLeft: 6 }}>{t("ws.delayed", "延误")}</span> : null}
          </span>
        );
      },
    },
    { key: "etd", title: "ETD", width: 140, render: (v) => fmtDate(v as string) },
    { key: "atd", title: "ATD", width: 140, render: (v) => fmtDate(v as string) },
  ];

  const portCallsTab = (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap-md)" }}>
      <Panel title={t("ws.timeline", "航次时间轴")} collapsible>
        <VoyageTimeline portCalls={timelinePortCalls} events={timelineEvents} />
      </Panel>
      <Panel title={t("ws.port_calls", "港口挂靠")} flush>
        <DataGrid
          columns={pcColumns}
          data={timelinePortCalls}
          rowKey={(row) => `${row.seq}-${row.port_name}`}
          emptyText={t("common.empty", "No records")}
        />
      </Panel>
    </div>
  );

  const financeTab = (
    <div className="ws-grid-2">
      <Panel title={t("ws.laytime", "滞期/速遣")} flush>
        <table className="table">
          <thead>
            <tr>
              <th>{t("ws.result_type", "结果")}</th>
              <th>{t("common.status", "状态")}</th>
              <th className="num">{t("common.amount", "金额")}</th>
            </tr>
          </thead>
          <tbody>
            {(data?.laytime || []).map((lt) => (
              <tr key={lt.id}>
                <td>{lt.result_type || "—"}</td>
                <td>{lt.status}</td>
                <td className="num">{fmtMoney(lt.amount, lt.currency || currency, locale)}</td>
              </tr>
            ))}
            {!data?.laytime?.length ? (
              <tr>
                <td colSpan={3} className="muted">
                  {t("common.no_data", "No data")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </Panel>
      <Panel title={t("ws.claims", "索赔")} flush>
        <table className="table">
          <thead>
            <tr>
              <th>{t("ws.claim_no", "索赔号")}</th>
              <th>{t("common.status", "状态")}</th>
              <th className="num">{t("common.amount", "金额")}</th>
            </tr>
          </thead>
          <tbody>
            {(data?.claims || []).map((c) => (
              <tr key={c.id}>
                <td>{c.claim_no || c.id.slice(0, 8)}</td>
                <td>{c.status || "—"}</td>
                <td className="num">{fmtMoney(c.amount, c.currency || currency, locale)}</td>
              </tr>
            ))}
            {!data?.claims?.length ? (
              <tr>
                <td colSpan={3} className="muted">
                  {t("common.no_data", "No data")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </Panel>
      <Panel title={t("ws.invoices", "发票")} flush>
        <table className="table">
          <thead>
            <tr>
              <th>{t("ws.invoice_no", "发票号")}</th>
              <th>{t("common.status", "状态")}</th>
              <th className="num">{t("common.amount", "金额")}</th>
            </tr>
          </thead>
          <tbody>
            {(data?.invoices || []).map((inv) => (
              <tr key={inv.id}>
                <td>{inv.invoice_no || inv.id.slice(0, 8)}</td>
                <td>{inv.status || "—"}</td>
                <td className="num">{fmtMoney(inv.amount, inv.currency || currency, locale)}</td>
              </tr>
            ))}
            {!data?.invoices?.length ? (
              <tr>
                <td colSpan={3} className="muted">
                  {t("common.no_data", "No data")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </Panel>
      <Panel title={t("ws.off_hire", "停租")} flush>
        <table className="table">
          <thead>
            <tr>
              <th>{t("ws.start", "开始")}</th>
              <th>{t("ws.end", "结束")}</th>
              <th>{t("ws.reason", "原因")}</th>
            </tr>
          </thead>
          <tbody>
            {(data?.off_hire || []).map((oh) => (
              <tr key={oh.id}>
                <td>{fmtDate(oh.start_at)}</td>
                <td>{oh.end_at ? fmtDate(oh.end_at) : t("ws.oh_open", "进行中")}</td>
                <td>{oh.reason || "—"}</td>
              </tr>
            ))}
            {!data?.off_hire?.length ? (
              <tr>
                <td colSpan={3} className="muted">
                  {t("common.no_data", "No data")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </Panel>
    </div>
  );

  const mapPath = greatCirclePath(
    mapModel.coords.map((c) => [c.lat, c.lon] as [number, number]),
    proj,
  );
  const trackPath = greatCirclePath(mapModel.track, proj);

  const mapTab = (
    <Panel title={t("ws.map", "航线图")} collapsible>
      {mapModel.coords.length + mapModel.track.length > 0 ? (
        <>
          <div className="ws-map">
            <svg viewBox={`0 0 ${MAP_W} ${MAP_H}`} role="img" aria-label={t("ws.map", "航线图")}>
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
              {t("ws.map_route", "计划航线（大圆）")}
            </span>
            {trackPath ? (
              <span>
                <i style={{ background: "#2f6fb0" }} />
                {t("ws.map_track", "正午船位轨迹")}
              </span>
            ) : null}
          </div>
        </>
      ) : (
        <p className="muted">{t("ws.map_empty", "暂无港口坐标或船位数据")}</p>
      )}
    </Panel>
  );

  const renderNoteList = (kind: "note" | "instruction", rows: VoyageNote[]) => (
    <Panel
      title={kind === "note" ? t("ws.notes", "航次备注") : t("ws.instructions", "航次指令")}
      actions={
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => openNoteModal(kind)}>
          + {t("common.add", "新增")}
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
                    {t("common.edit", "编辑")}
                  </button>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => deleteNote(kind, n.id)}>
                    {t("common.delete", "删除")}
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
    <Panel title={t("ws.activity", "活动日志")}>
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
            left={
              <div className="ws-crumb">
                <Link href="/operations/voyages" className="muted">
                  ← {t("ws.back", "返回航次列表")}
                </Link>
              </div>
            }
            title={
              <>
                {t("ws.title", "航次工作台")}
                <span>{title}</span>
                {voyage ? (
                  <span className={`pill ${voyage.status === "in_progress" ? "normal" : "good"}`}>{voyage.status}</span>
                ) : null}
              </>
            }
            subtitle={
              <>
                {voyage?.vessel_name
                  ? t("ws.sub_vessel", "船舶 {vessel}", { vessel: voyage.vessel_name })
                  : t("ws.sub", "航次全生命周期工作台")}
                {data?.charter?.charter_no ? ` · ${data.charter.charter_no}` : ""}
                {data?.charter?.counterparty_name ? ` · ${data.charter.counterparty_name}` : ""}
              </>
            }
            actions={
              <>
                <Link href={`/operations/voyages/${id}`} className="btn btn-ghost btn-sm">
                  {t("ws.open_detail", "航次 360")}
                </Link>
                <Link href="/operations/schedule" className="btn btn-ghost btn-sm">
                  {t("ws.open_schedule", "排程")}
                </Link>
                <Link href="/finance" className="btn btn-ghost btn-sm">
                  {t("ws.goto_finance", "财务")}
                </Link>
              </>
            }
          />
        }
      >
        <StateView loading={loading && !data} error={error} empty={false} onRetry={load}>
          <PanelTabs
            tabs={[
              { id: "summary", label: t("ws.tab_summary", "概要"), content: summaryTab },
              { id: "pnl", label: t("ws.tab_pnl", "P&L"), content: pnlTab },
              { id: "ports", label: t("ws.tab_ports", "港口动态"), content: portCallsTab },
              { id: "finance", label: t("ws.tab_finance", "财务"), content: financeTab },
              { id: "map", label: t("ws.tab_map", "航线图"), content: mapTab },
              { id: "notes", label: t("ws.tab_notes", "备注"), content: renderNoteList("note", notes) },
              {
                id: "instructions",
                label: t("ws.tab_instructions", "指令"),
                content: renderNoteList("instruction", instructions),
              },
              { id: "activity", label: t("ws.tab_activity", "活动"), content: activityTab },
            ]}
          />
        </StateView>
      </WorkspaceShell>

      <RecordModal
        open={noteModal.open}
        title={
          noteModal.kind === "note"
            ? noteModal.id
              ? t("ws.edit_note", "编辑备注")
              : t("ws.add_note", "新增备注")
            : noteModal.id
              ? t("ws.edit_instruction", "编辑指令")
              : t("ws.add_instruction", "新增指令")
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
          {t("ws.note_date", "日期")}
          <DateInput value={noteDate} onChange={setNoteDate} />
        </label>
        <label>
          {t("ws.note_content", "内容")}
          <textarea
            rows={6}
            value={noteTextDraft}
            onChange={(e) => setNoteTextDraft(e.target.value)}
            placeholder={t("ws.note_placeholder", "输入内容…")}
          />
        </label>
      </RecordModal>
    </AppShell>
  );
}
