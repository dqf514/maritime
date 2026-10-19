"use client";

import { FormEvent, Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { DateTimeInput } from "@/components/DateInput";
import { ExportButton } from "@/components/ExportButton";
import { PageGuide } from "@/components/PageGuide";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { Toolbar } from "@/components/Toolbar";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { useListHotkeys } from "@/components/useListHotkeys";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";
import { useToast } from "@/components/ToastProvider";

type RefItem = { id: string; name: string; unlocode?: string };
type Voyage = { id: string; voyage_no: string; status: string; cargo: string | null; vessel_id: string | null; updated_at?: string | null };
type PortCall = {
  id: string;
  voyage_id: string;
  port_id: string | null;
  seq: number;
  purpose: string;
  eta: string | null;
  etd: string | null;
  agent: string | null;
  nor_at: string | null;
  eosp_at: string | null;
  bl_date: string | null;
};
type OffHire = {
  id: string;
  start_at: string | null;
  end_at: string | null;
  reason: string | null;
  deduct_hire?: boolean;
  deducted_days?: number | null;
};
type SofSummary = {
  events: Array<{ id: string; event_code: string; event_at: string | null }>;
  working_hours: number | null;
  waiting_hours: number | null;
};

const SOF_CODES = [
  "NOR",
  "EOSP",
  "ANCHOR",
  "AWSP",
  "POB",
  "DOCKED",
  "SHIFTED_BERTH",
  "COMMENCED",
  "COMPLETED",
  "HOSES_OFF",
  "BL_DATE",
  "SAILED",
];
type Schedule = {
  id: string;
  title: string;
  block_type: string;
  start_at: string;
  end_at: string;
  hard_conflict: boolean;
  vessel_id: string;
};
type Twin = {
  level: string;
  noon_track: Array<{ at: string; lat: number | null; lon: number | null }>;
  port_calls: PortCall[];
};

function toLocalInput(iso: string | null | undefined) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromLocalInput(v: string) {
  if (!v) return null;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

function VoyagesPageInner() {
  const { t } = useI18n();
  const toast = useToast();
  const { query, setQuery } = useListQuery();
  const [rows, setRows] = useState<Voyage[]>([]);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [ports, setPorts] = useState<RefItem[]>([]);
  const [agents, setAgents] = useState<RefItem[]>([]);
  const selectedId = typeof query.v === "string" && query.v ? query.v : null;
  const setSelectedId = (id: string | null) => setQuery({ v: id });
  const [portCalls, setPortCalls] = useState<PortCall[]>([]);
  const [selectedPc, setSelectedPc] = useState<string>("");
  const [sofEvents, setSofEvents] = useState<Array<{ id: string; event_code: string; event_at: string | null; port_call_id: string }>>([]);
  const [twin, setTwin] = useState<Twin | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [reassignOpen, setReassignOpen] = useState(false);
  const [reassignOperator, setReassignOperator] = useState("");

  const [newVoyageNo, setNewVoyageNo] = useState("");
  const [newCargo, setNewCargo] = useState("");
  const [creating, setCreating] = useState(false);

  useListHotkeys(() => setCreating(true));

  const [pcPurpose, setPcPurpose] = useState("load");
  const [pcSeq, setPcSeq] = useState("1");
  const [pcPort, setPcPort] = useState("");
  const [pcEta, setPcEta] = useState("");
  const [pcEtd, setPcEtd] = useState("");
  const [pcAgent, setPcAgent] = useState("");

  const [sofCode, setSofCode] = useState("NOR");
  const [sofAt, setSofAt] = useState("");
  const [sofSummary, setSofSummary] = useState<{ pc: string; data: SofSummary | null } | null>(null);

  const [offHires, setOffHires] = useState<OffHire[]>([]);
  const [ohStart, setOhStart] = useState("");
  const [ohReason, setOhReason] = useState("");
  const [ohDeduct, setOhDeduct] = useState(true);
  const [ohCloseAt, setOhCloseAt] = useState("");

  const [noonLat, setNoonLat] = useState("");
  const [noonLon, setNoonLon] = useState("");
  const [noonSpeed, setNoonSpeed] = useState("");
  const [noonFo, setNoonFo] = useState("");
  const [noonDo, setNoonDo] = useState("");
  const [noonWind, setNoonWind] = useState("");
  const [noonSea, setNoonSea] = useState("");
  const [noonCurrent, setNoonCurrent] = useState("");
  const [noonEta, setNoonEta] = useState("");
  const [noonRemarks, setNoonRemarks] = useState("");
  const [lastNoon, setLastNoon] = useState<{
    eta_deviation_hours: number | null;
    wind_bf: number | null;
    sea_state: string | null;
    current_kn: number | null;
  } | null>(null);

  const load = useCallback(async () => {
    const [v, s, p, parties] = await Promise.all([
      apiGet("/api/v1/voyages"),
      apiGet("/api/v1/schedules"),
      apiGet("/api/v1/masterdata/ports"),
      apiGet("/api/v1/masterdata/counterparties").catch(() => []),
    ]);
    setRows(v);
    setSchedules(s);
    setPorts(p);
    setAgents(
      (parties as Array<{ id: string; name: string; type?: string }>).filter(
        (x) => !x.type || x.type === "agent" || x.type === "other",
      ),
    );
    if (!pcPort && p[0]?.id) setPcPort(p[0].id);
    return v as Voyage[];
  }, [pcPort]);

  const loadPortCalls = useCallback(async (voyageId: string, preferPc?: string) => {
    const pcs: PortCall[] = await apiGet(`/api/v1/port-calls?voyage_id=${voyageId}`);
    setPortCalls(pcs);
    const keep = preferPc && pcs.some((p) => p.id === preferPc) ? preferPc : pcs[0]?.id || "";
    setSelectedPc(keep);
    try {
      const sof = await apiGet(`/api/v1/sof-events?voyage_id=${voyageId}`);
      setSofEvents(sof);
    } catch {
      setSofEvents([]);
    }
    try {
      const tw = await apiGet(`/api/v1/twin/voyages/${voyageId}`);
      setTwin(tw);
    } catch {
      setTwin(null);
    }
    try {
      const oh = await apiGet(`/api/v1/voyages/${voyageId}/off-hire`);
      setOffHires(oh);
    } catch {
      setOffHires([]);
    }
  }, []);

  useEffect(() => {
    if (!selectedPc) return;
    let cancelled = false;
    apiGet(`/api/v1/port-calls/${selectedPc}/sof-summary`)
      .then((s: SofSummary) => {
        if (!cancelled) setSofSummary({ pc: selectedPc, data: s });
      })
      .catch(() => {
        if (!cancelled) setSofSummary({ pc: selectedPc, data: null });
      });
    return () => {
      cancelled = true;
    };
  }, [selectedPc]);

  useEffect(() => {
    load()
      .then((v) => {
        // 深链 ?v=<id> 优先，不被列表首条覆盖；无深链才默认选中首条
        const deep = selectedId && v.some((x: Voyage) => x.id === selectedId) ? selectedId : null;
        const pick = deep || v[0]?.id || null;
        if (pick) {
          if (pick !== selectedId) setSelectedId(pick);
          return loadPortCalls(pick);
        }
      })
      .catch(() => setErr(t("common.failed", "Failed")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function selectVoyage(id: string) {
    setSelectedId(id);
    setTwin(null);
    setLastNoon(null);
    setErr("");
    try {
      await loadPortCalls(id);
    } catch (ex) {
      setErr(String(ex));
    }
  }

  async function createVoyage(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const vno = newVoyageNo.trim() || `V-${new Date().toISOString().slice(0, 10).replace(/-/g, "")}-MAN`;
      const created = await apiPost("/api/v1/voyages", {
        voyage_no: vno,
        cargo: newCargo || null,
      });
      toast.success(t("page.voyages.created", "Voyage {no} created", { no: created.voyage_no }));
      setNewVoyageNo("");
      setNewCargo("");
      setCreating(false);
      const list = await load();
      if (created.id) {
        setSelectedId(created.id);
        await loadPortCalls(created.id);
      } else if (list[0]) {
        setSelectedId(list[0].id);
      }
    } catch (ex: any) {
      toast.error(ex?.message || String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function move(id: string, target: string) {
    setBusy(true);
    try {
      await apiPost(`/api/v1/voyages/${id}/transition`, { target });
      toast.success(t("page.voyages.moved", "Voyage → {target}", { target }));
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function saveSelectedVoyage() {
    if (!selected) return;
    setBusy(true);
    try {
      await apiPatch(`/api/v1/voyages/${selected.id}`, {
        voyage_no: selected.voyage_no,
        cargo: selected.cargo,
      });
      toast.success(t("common.saved", "Saved"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function removeVoyage() {
    if (!selected) return;
    if (!window.confirm(t("common.confirm_delete", "Delete this record? It will move to the recycle bin and can be restored."))) return;
    setBusy(true);
    try {
      await apiDelete(`/api/v1/voyages/${selected.id}`);
      setSelectedId(null);
      toast.success(t("common.recycled", "Moved to recycle bin"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function addPortCall(e: FormEvent) {
    e.preventDefault();
    if (!selectedId) return;
    if ((pcEta && !fromLocalInput(pcEta)) || (pcEtd && !fromLocalInput(pcEtd))) {
      setErr(t("page.voyages.bad_date", "Invalid date/time format. Please reselect."));
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await apiPost("/api/v1/port-calls", {
        voyage_id: selectedId,
        port_id: pcPort || null,
        seq: Number(pcSeq) || 1,
        purpose: pcPurpose,
        eta: fromLocalInput(pcEta),
        etd: fromLocalInput(pcEtd),
        agent: pcAgent || null,
      });
      toast.success(t("page.voyages.pc_ok", "Port call added"));
      setPcSeq(String((Number(pcSeq) || 1) + 1));
      await loadPortCalls(selectedId);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function addSof(e: FormEvent) {
    e.preventDefault();
    if (!selectedPc) {
      setErr(t("page.voyages.need_pc", "Select a port call first"));
      return;
    }
    if (sofAt && !fromLocalInput(sofAt)) {
      setErr(t("page.voyages.bad_date", "Invalid date/time format. Please reselect."));
      return;
    }
    setBusy(true);
    try {
      await apiPost("/api/v1/sof-events", {
        port_call_id: selectedPc,
        event_code: sofCode,
        event_at: fromLocalInput(sofAt) || new Date().toISOString(),
      });
      toast.success(t("page.voyages.sof_ok", "SOF {code} recorded", { code: sofCode }));
      if (selectedId) await loadPortCalls(selectedId);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function addOffHire(e: FormEvent) {
    e.preventDefault();
    if (!selectedId) return;
    if (!ohStart || !fromLocalInput(ohStart)) {
      setErr(t("page.voyages.bad_date", "Invalid date/time format. Please reselect."));
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await apiPost(`/api/v1/voyages/${selectedId}/off-hire`, {
        start_at: fromLocalInput(ohStart),
        reason: ohReason || null,
        deduct_hire: ohDeduct,
      });
      toast.success(t("page.voyages.oh_ok", "Off-hire opened"));
      setOhStart("");
      setOhReason("");
      await loadPortCalls(selectedId);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function closeOffHire(id: string) {
    if (!selectedId) return;
    if (!ohCloseAt || !fromLocalInput(ohCloseAt)) {
      setErr(t("page.voyages.bad_date", "Invalid date/time format. Please reselect."));
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await apiPost(`/api/v1/off-hire/${id}/close`, { end_at: fromLocalInput(ohCloseAt) });
      toast.success(t("page.voyages.oh_closed", "Off-hire closed"));
      setOhCloseAt("");
      await loadPortCalls(selectedId);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function addNoon(e: FormEvent) {
    e.preventDefault();
    if (!selectedId) return;
    if (noonEta && !fromLocalInput(noonEta)) {
      setErr(t("page.voyages.bad_date", "Invalid date/time format. Please reselect."));
      return;
    }
    setBusy(true);
    try {
      const res = await apiPost("/api/v1/noon-reports", {
        voyage_id: selectedId,
        report_at: new Date().toISOString(),
        lat: noonLat === "" ? null : Number(noonLat),
        lon: noonLon === "" ? null : Number(noonLon),
        speed: noonSpeed === "" ? null : Number(noonSpeed),
        rob_fo: noonFo === "" ? null : Number(noonFo),
        rob_do: noonDo === "" ? null : Number(noonDo),
        wind_bf: noonWind === "" ? null : Number(noonWind),
        sea_state: noonSea || null,
        current_kn: noonCurrent === "" ? null : Number(noonCurrent),
        eta_next: fromLocalInput(noonEta),
        remarks: noonRemarks || null,
      });
      setLastNoon({
        eta_deviation_hours: res?.eta_deviation_hours ?? null,
        wind_bf: res?.wind_bf ?? null,
        sea_state: res?.sea_state ?? null,
        current_kn: res?.current_kn ?? null,
      });
      toast.success(t("page.voyages.noon_ok", "Noon report filed"));
      await loadPortCalls(selectedId);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  function portLabel(id: string | null) {
    if (!id) return "—";
    const p = ports.find((x) => x.id === id);
    return p ? `${p.name}${p.unlocode ? ` (${p.unlocode})` : ""}` : id.slice(0, 8);
  }

  function togglePick(id: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function togglePickAll() {
    setPicked((prev) => (prev.size === rows.length ? new Set() : new Set(rows.map((r) => r.id))));
  }

  async function runBatch(action: "close" | "assign", operator?: string) {
    if (!picked.size) return;
    setBusy(true);
    try {
      const body: Record<string, unknown> = { action, voyage_ids: [...picked] };
      if (operator) body.operator = operator;
      const res = await apiPost("/api/v1/voyages/batch", body);
      const okN: number = res?.ok?.length ?? 0;
      const failN: number = res?.failed?.length ?? 0;
      if (failN > 0) {
        toast.error(
          t("page.voyages.batch_partial", "Batch {action}: {ok} ok, {failed} failed", {
            action,
            ok: okN,
            failed: failN,
          }),
        );
      } else {
        toast.success(
          t("page.voyages.batch_ok", "Batch {action}: {n} voyages updated", { action, n: okN }),
        );
      }
      setPicked(new Set());
      setReassignOpen(false);
      setReassignOperator("");
      await load();
    } catch (ex: any) {
      toast.error(ex?.message || String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function copyItinerary() {
    if (picked.size !== 1) return;
    const srcId = [...picked][0];
    setBusy(true);
    try {
      const created = await apiPost(`/api/v1/voyages/${srcId}/copy-itinerary`);
      toast.success(
        t("page.voyages.copy_ok", "Itinerary copied to {no}", { no: created?.voyage_no || "" }),
      );
      setPicked(new Set());
      await load();
      if (created?.id) {
        setSelectedId(created.id);
        await loadPortCalls(created.id);
      }
    } catch (ex: any) {
      toast.error(ex?.message || String(ex));
    } finally {
      setBusy(false);
    }
  }

  const selected = rows.find((r) => r.id === selectedId) || null;
  const conflicts = schedules.filter((s) => s.hard_conflict);

  const voyageColumns: ColumnDef<Voyage>[] = [
    {
      key: "_pick",
      title: "☑",
      width: 36,
      align: "center",
      value: (r) => picked.has(r.id),
      render: (_v, r) => (
        <input
          type="checkbox"
          checked={picked.has(r.id)}
          onChange={() => togglePick(r.id)}
          onClick={(e) => e.stopPropagation()}
          aria-label={t("page.voyages.batch_pick", "Select voyage")}
        />
      ),
    },
    {
      key: "voyage_no",
      title: t("page.voyages.no", "No"),
      minWidth: 120,
      value: (r) => r.voyage_no,
    },
    {
      key: "cargo",
      title: t("page.voyages.cargo", "Cargo"),
      minWidth: 110,
      value: (r) => r.cargo || "",
      render: (v) => (v ? String(v) : "—"),
    },
    { key: "status", title: t("common.status", "Status"), width: 110, value: (r) => r.status },
    {
      key: "updated_at",
      title: t("list.last_modified", "Last modified"),
      width: 135,
      value: (r) => r.updated_at ?? null,
      render: (v) => (v ? toLocalInput(v as string).replace("T", " ") : "—"),
    },
    {
      key: "_actions",
      title: "",
      width: 110,
      align: "right",
      render: (_v, r) => (
        <Link
          href={`/operations/voyages/${r.id}/workspace`}
          className="btn btn-ghost btn-sm"
          onClick={(e) => e.stopPropagation()}
        >
          {t("page.voyages.view360", "360° view")}
        </Link>
      ),
    },
  ];

  const portCallColumns: ColumnDef<PortCall>[] = [
    { key: "seq", title: "#", width: 48, align: "right", value: (r) => r.seq },
    {
      key: "port",
      title: t("page.voyages.port", "Port"),
      minWidth: 150,
      value: (r) => portLabel(r.port_id),
    },
    { key: "purpose", title: t("page.voyages.purpose", "Purpose"), width: 90, value: (r) => r.purpose },
    {
      key: "eta",
      title: "ETA",
      width: 130,
      value: (r) => r.eta || "",
      render: (v) => (v ? toLocalInput(v as string).replace("T", " ") : "—"),
    },
    {
      key: "etd",
      title: "ETD",
      width: 130,
      value: (r) => r.etd || "",
      render: (v) => (v ? toLocalInput(v as string).replace("T", " ") : "—"),
    },
    {
      key: "nor_at",
      title: "NOR",
      width: 130,
      value: (r) => r.nor_at || "",
      render: (v) => (v ? toLocalInput(v as string).replace("T", " ") : "—"),
    },
    {
      key: "eosp_at",
      title: "EOSP",
      width: 130,
      value: (r) => r.eosp_at || "",
      render: (v) => (v ? toLocalInput(v as string).replace("T", " ") : "—"),
    },
    {
      key: "bl_date",
      title: "B/L",
      width: 110,
      value: (r) => r.bl_date || "",
      render: (v) => (v ? String(v) : "—"),
    },
    {
      key: "agent",
      title: t("page.voyages.agent", "Agent"),
      minWidth: 110,
      value: (r) => r.agent || "",
      render: (v) => (v ? String(v) : "—"),
    },
  ];

  const sofColumns: ColumnDef<(typeof sofEvents)[number]>[] = [
    { key: "event_code", title: t("page.voyages.event", "Event"), width: 130, value: (r) => r.event_code },
    {
      key: "event_at",
      title: t("page.voyages.event_at", "Event at"),
      minWidth: 160,
      value: (r) => r.event_at || "",
      render: (v) => (v ? new Date(v as string).toLocaleString() : "—"),
    },
    {
      key: "port_call_id",
      title: t("page.voyages.port_call", "Port call"),
      width: 110,
      value: (r) => r.port_call_id.slice(0, 8),
    },
  ];

  const offHireColumns: ColumnDef<OffHire>[] = [
    {
      key: "start_at",
      title: t("page.voyages.oh_start", "Start at"),
      width: 130,
      value: (r) => r.start_at || "",
      render: (v) => (v ? toLocalInput(v as string).replace("T", " ") : "—"),
    },
    {
      key: "end_at",
      title: t("page.voyages.oh_end", "End at"),
      width: 130,
      value: (r) => r.end_at || "",
      render: (v) => (v ? toLocalInput(v as string).replace("T", " ") : "—"),
    },
    {
      key: "reason",
      title: t("page.voyages.oh_reason", "Reason"),
      minWidth: 120,
      value: (r) => r.reason || "",
      render: (v) => (v ? String(v) : "—"),
    },
    {
      key: "deducted_days",
      title: t("page.voyages.oh_deducted", "Deducted days"),
      width: 110,
      align: "right",
      value: (r) => r.deducted_days ?? "",
      render: (v) => (v === "" || v == null ? "—" : String(v)),
    },
    {
      key: "_actions",
      title: "",
      width: 220,
      align: "right",
      render: (_v, oh) =>
        !oh.end_at ? (
          <span
            className="desk-toolbar"
            style={{ margin: 0, justifyContent: "flex-end" }}
            onClick={(e) => e.stopPropagation()}
          >
            <DateTimeInput value={ohCloseAt} onChange={setOhCloseAt} />
            <button className="btn btn-sm" type="button" disabled={busy} onClick={() => closeOffHire(oh.id)}>
              {t("common.close", "Close")}
            </button>
          </span>
        ) : null,
    },
  ];

  type NoonPoint = { at: string; lat: number | null; lon: number | null; key: string };
  const noonTrackColumns: ColumnDef<NoonPoint>[] = [
    {
      key: "at",
      title: t("page.voyages.at", "At"),
      minWidth: 140,
      value: (r) => r.at || "",
      render: (v) => (v ? toLocalInput(v as string).replace("T", " ") : "—"),
    },
    {
      key: "lat",
      title: "Lat",
      width: 90,
      align: "right",
      value: (r) => r.lat,
      render: (v) => (v == null ? "—" : String(v)),
    },
    {
      key: "lon",
      title: "Lon",
      width: 90,
      align: "right",
      value: (r) => r.lon,
      render: (v) => (v == null ? "—" : String(v)),
    },
  ];

  const scheduleColumns: ColumnDef<Schedule>[] = [
    { key: "title", title: t("common.title", "Title"), minWidth: 150, value: (r) => r.title },
    { key: "block_type", title: t("page.voyages.block_type", "Type"), width: 100, value: (r) => r.block_type },
    {
      key: "start_at",
      title: t("page.voyages.start_at", "Start"),
      width: 130,
      value: (r) => r.start_at,
      render: (v) => toLocalInput(v as string).replace("T", " "),
    },
    {
      key: "end_at",
      title: t("page.voyages.end_at", "End"),
      width: 130,
      value: (r) => r.end_at,
      render: (v) => toLocalInput(v as string).replace("T", " "),
    },
    {
      key: "hard_conflict",
      title: t("page.voyages.conflict", "Conflict"),
      width: 90,
      value: (r) => r.hard_conflict,
      render: (v) =>
        v ? (
          <span className="badge badge-fail">{t("page.voyages.hard", "HARD")}</span>
        ) : (
          <span className="badge badge-pass">{t("page.voyages.ok", "ok")}</span>
        ),
    },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.ops", "Voyages") }]}
        title={t("page.voyages.title", "Operations & Schedule")}
        subtitle={t("page.voyages.sub", "Voyages, port calls and schedule blocks.")}
        actions={
          <>
            <ExportButton entity="voyages" />
            <PageGuide pageKey="voyages" />
            <Link href="/settings/recycle" className="btn btn-ghost">
              {t("nav.recycle", "Recycle bin")}
            </Link>
          </>
        }
      />

      <Toolbar
        right={
          <>
            {picked.size > 0 ? (
              <span className="badge badge-info">
                {t("page.voyages.batch_selected", "{n} selected", { n: picked.size })}
              </span>
            ) : null}
            <span className="hint">{t("page.voyages.count", "{n} voyages", { n: rows.length })}</span>
          </>
        }
      >
        <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => setCreating(true)}>
          + {t("page.voyages.create", "New voyage")}
        </button>
        <button
          className="btn btn-sm"
          type="button"
          disabled={busy || !rows.length}
          onClick={togglePickAll}
          title={t("page.voyages.batch_select_all", "Select all / clear")}
        >
          ☑
        </button>
        <button
          className="btn btn-sm"
          type="button"
          disabled={busy || !picked.size}
          onClick={() => runBatch("close")}
        >
          {t("page.voyages.batch_close", "Batch close")}
        </button>
        <button
          className="btn btn-sm"
          type="button"
          disabled={busy || !picked.size}
          onClick={() => {
            setReassignOperator("");
            setReassignOpen(true);
          }}
        >
          {t("page.voyages.batch_reassign", "Reassign")}
        </button>
        <button
          className="btn btn-sm"
          type="button"
          disabled={busy || picked.size !== 1}
          onClick={copyItinerary}
          title={t("page.voyages.copy_hint", "Copy port-call itinerary to a new voyage")}
        >
          {t("page.voyages.copy_itinerary", "Copy itinerary")}
        </button>
        <button className="btn btn-sm" type="button" disabled={busy} onClick={() => load().catch(() => undefined)} title={t("common.refresh", "Refresh")}>
          ↻
        </button>
      </Toolbar>

      {err ? <p className="flash-err">{err}</p> : null}

      {/* 宽屏下左栏 240px 过窄（航次列挤成一团）— 本页放宽到 340px */}
      <div className="desk-split" style={{ gridTemplateColumns: "minmax(300px, 340px) minmax(0, 1fr)" }}>
        <div className="panel desk-list">
          <h3 style={{ margin: "0.85rem 1rem 0.35rem", fontSize: "0.95rem" }}>{t("page.voyages.list", "Voyages")}</h3>
          <p className="muted" style={{ padding: "0 1rem", marginTop: 0, fontSize: "0.8rem" }}>
            {t("page.voyages.create_hint", "Or activate a charter to auto-create a voyage + schedule block.")}
          </p>
          <DataGrid<Voyage>
            columns={voyageColumns}
            data={rows}
            rowKey={(r) => r.id}
            storageKey="voyages_list_grid"
            showFooter={false}
            emptyText={t("common.empty", "No records")}
            onRowClick={(r) => selectVoyage(r.id)}
          />
        </div>

        <div>
          {selected ? (
            <div className="panel" style={{ marginTop: 0 }}>
              <div className="page-header" style={{ marginBottom: "0.5rem" }}>
                <div>
                  <h3 style={{ margin: 0 }}>
                    {selected.voyage_no} · {selected.status}
                  </h3>
                  <label style={{ display: "block", marginTop: "0.5rem" }}>
                    {t("page.voyages.cargo", "Cargo")}
                    <input
                      value={selected.cargo || ""}
                      onChange={(e) =>
                        setRows((prev) => prev.map((r) => (r.id === selected.id ? { ...r, cargo: e.target.value } : r)))
                      }
                    />
                  </label>
                </div>
                <div className="desk-toolbar" style={{ margin: 0 }}>
                  <button className="btn btn-sm" type="button" disabled={busy} onClick={saveSelectedVoyage}>
                    {t("common.save", "Save")}
                  </button>
                  {selected.status === "planned" ? (
                    <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => move(selected.id, "in_progress")}>
                      {t("page.voyages.start", "Start")}
                    </button>
                  ) : null}
                  {selected.status === "in_progress" ? (
                    <button className="btn btn-sm" type="button" disabled={busy} onClick={() => move(selected.id, "completed")}>
                      {t("page.voyages.complete", "Complete")}
                    </button>
                  ) : null}
                  <button className="btn btn-danger btn-sm" type="button" disabled={busy} onClick={removeVoyage}>
                    {t("common.delete", "Delete")}
                  </button>
                </div>
              </div>

              <div className="desk-section">
                <h3>{t("page.voyages.port_calls", "Port calls")}</h3>
                <DataGrid<PortCall>
                  columns={portCallColumns}
                  data={portCalls}
                  rowKey={(r) => r.id}
                  storageKey="voyages_portcalls_grid"
                  showFooter={false}
                  emptyText={t("common.empty", "No records")}
                  onRowClick={(pc) => setSelectedPc(pc.id)}
                />

                <form className="form-grid" onSubmit={addPortCall} style={{ marginTop: "0.75rem" }}>
                  <label>
                    {t("page.voyages.purpose", "Purpose")}
                    <select value={pcPurpose} onChange={(e) => setPcPurpose(e.target.value)}>
                      <option value="load">load</option>
                      <option value="discharge">discharge</option>
                      <option value="bunker">bunker</option>
                      <option value="transit">transit</option>
                    </select>
                  </label>
                  <label>
                    {t("page.voyages.seq", "Seq")}
                    <input type="number" value={pcSeq} onChange={(e) => setPcSeq(e.target.value)} />
                  </label>
                  <label>
                    {t("page.voyages.port", "Port")}
                    <select value={pcPort} onChange={(e) => setPcPort(e.target.value)}>
                      {ports.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    ETA
                    <DateTimeInput value={pcEta} onChange={setPcEta} />
                  </label>
                  <label>
                    ETD
                    <DateTimeInput value={pcEtd} onChange={setPcEtd} />
                  </label>
                  <label>
                    {t("page.voyages.agent", "Agent")}
                    <select value={pcAgent} onChange={(e) => setPcAgent(e.target.value)}>
                      <option value="">{t("common.select", "Select…")}</option>
                      {agents.map((a) => (
                        <option key={a.id} value={a.name}>
                          {a.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div style={{ display: "flex", alignItems: "end" }}>
                    <button className="btn btn-primary btn-sm" type="submit" disabled={busy}>
                      {t("page.voyages.add_pc", "Add port call")}
                    </button>
                  </div>
                </form>
              </div>

              <div className="desk-section">
                <h3>{t("page.voyages.sof", "SOF events")}</h3>
                <form className="form-grid" onSubmit={addSof}>
                  <label>
                    {t("page.voyages.port_call", "Port call")}
                    <select value={selectedPc} onChange={(e) => setSelectedPc(e.target.value)}>
                      <option value="">{t("common.select", "Select…")}</option>
                      {portCalls.map((pc) => (
                        <option key={pc.id} value={pc.id}>
                          #{pc.seq} {pc.purpose} · {portLabel(pc.port_id)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    {t("page.voyages.event", "Event")}
                    <select value={sofCode} onChange={(e) => setSofCode(e.target.value)}>
                      {SOF_CODES.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    {t("page.voyages.event_at", "Event at")}
                    <DateTimeInput value={sofAt} onChange={setSofAt} />
                  </label>
                  <div style={{ display: "flex", alignItems: "end" }}>
                    <button className="btn btn-sm" type="submit" disabled={busy}>
                      {t("page.voyages.post_sof", "Post SOF")}
                    </button>
                  </div>
                </form>
                <div style={{ marginTop: "0.75rem" }}>
                  <DataGrid
                    columns={sofColumns}
                    data={sofEvents}
                    rowKey={(r) => r.id}
                    storageKey="voyages_sof_grid"
                    showFooter={false}
                    emptyText={t("common.no_data", "No data")}
                  />
                </div>
                {selectedPc && sofSummary?.pc === selectedPc && sofSummary.data ? (
                  <div className="desk-results" style={{ marginTop: "0.75rem" }}>
                    <div className="kv-box">
                      <span>{t("page.voyages.working_hours", "Working hours")}</span>
                      <strong>{sofSummary.data.working_hours ?? "—"}</strong>
                    </div>
                    <div className="kv-box">
                      <span>{t("page.voyages.waiting_hours", "Waiting hours")}</span>
                      <strong>{sofSummary.data.waiting_hours ?? "—"}</strong>
                    </div>
                  </div>
                ) : null}
              </div>

              <div className="desk-section">
                <h3>{t("page.voyages.off_hire", "Off-hire")}</h3>
                <form className="form-grid" onSubmit={addOffHire}>
                  <label>
                    {t("page.voyages.oh_start", "Start at")}
                    <DateTimeInput value={ohStart} onChange={setOhStart} />
                  </label>
                  <label>
                    {t("page.voyages.oh_reason", "Reason")}
                    <input value={ohReason} onChange={(e) => setOhReason(e.target.value)} />
                  </label>
                  <label style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                    <input type="checkbox" checked={ohDeduct} onChange={(e) => setOhDeduct(e.target.checked)} />
                    {t("page.voyages.oh_deduct", "Deduct hire")}
                  </label>
                  <div style={{ display: "flex", alignItems: "end" }}>
                    <button className="btn btn-sm" type="submit" disabled={busy}>
                      {t("page.voyages.oh_open", "Open off-hire")}
                    </button>
                  </div>
                </form>
                <div style={{ marginTop: "0.75rem" }}>
                  <DataGrid<OffHire>
                    columns={offHireColumns}
                    data={offHires}
                    rowKey={(r) => r.id}
                    storageKey="voyages_offhire_grid"
                    showFooter={false}
                    emptyText={t("common.no_data", "No data")}
                  />
                </div>
              </div>

              <div className="desk-section">
                <h3>{t("page.voyages.noon", "Noon report")}</h3>
                <form className="form-grid" onSubmit={addNoon}>
                  <label>
                    Lat
                    <input type="number" step="any" value={noonLat} onChange={(e) => setNoonLat(e.target.value)} />
                  </label>
                  <label>
                    Lon
                    <input type="number" step="any" value={noonLon} onChange={(e) => setNoonLon(e.target.value)} />
                  </label>
                  <label>
                    {t("page.voyages.speed", "Speed")}
                    <input type="number" step="any" value={noonSpeed} onChange={(e) => setNoonSpeed(e.target.value)} />
                  </label>
                  <label>
                    ROB FO
                    <input type="number" step="any" value={noonFo} onChange={(e) => setNoonFo(e.target.value)} />
                  </label>
                  <label>
                    ROB DO
                    <input type="number" step="any" value={noonDo} onChange={(e) => setNoonDo(e.target.value)} />
                  </label>
                  <label>
                    {t("page.voyages.wind_bf", "Wind (BF)")}
                    <input type="number" step="any" min="0" max="12" value={noonWind} onChange={(e) => setNoonWind(e.target.value)} />
                  </label>
                  <label>
                    {t("page.voyages.sea_state", "Sea state")}
                    <select value={noonSea} onChange={(e) => setNoonSea(e.target.value)}>
                      <option value="">—</option>
                      {["calm", "slight", "moderate", "rough", "very_rough", "high", "phenomenal"].map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    {t("page.voyages.current_kn", "Current (kn)")}
                    <input type="number" step="any" value={noonCurrent} onChange={(e) => setNoonCurrent(e.target.value)} />
                  </label>
                  <label>
                    ETA next
                    <DateTimeInput value={noonEta} onChange={setNoonEta} />
                  </label>
                  <label style={{ gridColumn: "1 / -1" }}>
                    {t("page.voyages.remarks", "Remarks")}
                    <input value={noonRemarks} onChange={(e) => setNoonRemarks(e.target.value)} />
                  </label>
                  <div style={{ display: "flex", alignItems: "end" }}>
                    <button className="btn btn-sm" type="submit" disabled={busy}>
                      {t("page.voyages.post_noon", "Post noon")}
                    </button>
                  </div>
                </form>
                {lastNoon ? (
                  <div className="desk-results" style={{ marginTop: "0.75rem" }}>
                    <div className="kv-box">
                      <span>{t("page.voyages.wind_bf", "Wind (BF)")}</span>
                      <strong>{lastNoon.wind_bf ?? "—"}</strong>
                    </div>
                    <div className="kv-box">
                      <span>{t("page.voyages.sea_state", "Sea state")}</span>
                      <strong>{lastNoon.sea_state || "—"}</strong>
                    </div>
                    <div className="kv-box">
                      <span>{t("page.voyages.current_kn", "Current (kn)")}</span>
                      <strong>{lastNoon.current_kn ?? "—"}</strong>
                    </div>
                    <div className="kv-box">
                      <span>{t("page.voyages.eta_dev", "ETA dev (h)")}</span>
                      <strong>{lastNoon.eta_deviation_hours ?? "—"}</strong>
                    </div>
                  </div>
                ) : null}
              </div>

              <div className="desk-section">
                <h3>{t("page.voyages.twin", "Twin track")}</h3>
                {twin ? (
                  <>
                    <p className="muted">
                      L{twin.level} · {twin.noon_track?.length || 0} noon points · {twin.port_calls?.length || 0} port calls
                    </p>
                    <DataGrid<NoonPoint>
                      columns={noonTrackColumns}
                      data={(twin.noon_track || []).map((n, i) => ({ ...n, key: `noon-${i}` }))}
                      rowKey={(r) => r.key}
                      storageKey="voyages_noon_track_grid"
                      showFooter={false}
                      emptyText={t("page.voyages.no_track", "No noon track yet")}
                    />
                  </>
                ) : (
                  <p className="muted">{t("page.voyages.twin_na", "Twin data unavailable (module or empty).")}</p>
                )}
              </div>
            </div>
          ) : (
            <div className="panel" style={{ marginTop: 0 }}>
              <p className="muted">{t("page.voyages.select", "Select a voyage")}</p>
            </div>
          )}
        </div>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.voyages.schedule", "Schedule blocks")}</h3>
        {conflicts.length ? (
          <p className="flash-err">
            {t("page.voyages.conflicts_n", "{n} hard conflict(s)", { n: conflicts.length })}
          </p>
        ) : (
          <p className="muted">{t("page.voyages.no_conflicts", "No hard conflicts")}</p>
        )}
        <DataGrid<Schedule>
          columns={scheduleColumns}
          data={schedules}
          rowKey={(r) => r.id}
          storageKey="voyages_schedule_grid"
          showFooter={false}
          emptyText={t("common.empty", "No records")}
        />
      </div>

      <RecordModal
        open={creating}
        title={t("page.voyages.create_title", "New voyage")}
        onClose={() => setCreating(false)}
        onSave={createVoyage}
        canDelete={false}
        saving={busy}
        size="md"
      >
        <div className="form-grid">
          <label className="field">
            <span>{t("page.voyages.no", "No")}</span>
            <input
              className="input"
              value={newVoyageNo}
              onChange={(e) => setNewVoyageNo(e.target.value)}
              placeholder="V-…"
            />
          </label>
          <label className="field">
            <span>{t("page.voyages.cargo", "Cargo")}</span>
            <input className="input" value={newCargo} onChange={(e) => setNewCargo(e.target.value)} />
          </label>
        </div>
      </RecordModal>

      <RecordModal
        open={reassignOpen}
        title={t("page.voyages.batch_reassign_title", "Reassign operator")}
        onClose={() => setReassignOpen(false)}
        onSave={(e) => {
          e.preventDefault();
          return runBatch("assign", reassignOperator);
        }}
        canDelete={false}
        saving={busy}
        size="md"
      >
        <div className="form-grid">
          <label className="field">
            <span>{t("page.voyages.batch_operator", "Operator")}</span>
            <input
              className="input"
              value={reassignOperator}
              onChange={(e) => setReassignOperator(e.target.value)}
              placeholder={t("page.voyages.batch_operator_ph", "Operator name")}
            />
          </label>
        </div>
        <p className="muted">
          {t("page.voyages.batch_reassign_hint", "{n} voyages will be reassigned.", { n: picked.size })}
        </p>
      </RecordModal>
    </AppShell>
  );
}

export default function VoyagesPage() {
  return (
    <Suspense fallback={null}>
      <VoyagesPageInner />
    </Suspense>
  );
}
