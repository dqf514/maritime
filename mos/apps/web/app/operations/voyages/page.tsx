"use client";

import { FormEvent, MouseEvent as ReactMouseEvent, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { RefreshButton } from "@/components/RefreshButton";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DateTimeInput } from "@/components/DateInput";
import { DeskSection } from "@/components/DeskSection";
import { ExportButton } from "@/components/ExportButton";
import { PageGuide } from "@/components/PageGuide";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { RowActions } from "@/components/RowActions";
import { StatusBadge } from "@/components/StatusBadge";
import { StateView } from "@/components/StateView";
import { Toolbar } from "@/components/Toolbar";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { useListHotkeys } from "@/components/useListHotkeys";
import { useTodoAdd } from "@/components/TodoQuickAdd";
import { apiDelete, apiGet, apiList, apiPatch, apiPost } from "@/lib/api";
import { msgOf, handled } from "@/lib/errors";
import { formatInTz, fromUtcInput, parseUtc, toUtcInput } from "@/lib/datetime";
import { useI18n } from "@/lib/i18n";
import { toPositiveInt } from "@/lib/numbers";
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
  status?: string;
};
type NoonRow = {
  id: string;
  report_at: string | null;
  speed: number | null;
  rob_fo: number | null;
  rob_do: number | null;
  remarks: string | null;
  stage?: string | null;
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

// 航次页所有 datetime 一律用 UTC 墙钟：与 DataGrid 行内编辑器、其它列表页一致，
// 避免同一列在「行内编辑」与「表单录入」两条路径上按不同时区解释而整体偏移。
function toLocalInput(iso: string | null | undefined) {
  return toUtcInput(iso);
}

function fromLocalInput(v: string) {
  return fromUtcInput(v);
}

function VoyagesPageInner() {
  const { t, locale } = useI18n();
  const toast = useToast();
  const { query, setQuery, page, limit } = useListQuery();
  const [rows, setRows] = useState<Voyage[]>([]);
  // 服务端分页的总数（信封 total）
  const [total, setTotal] = useState(0);
  // 跨页/深链选中的航次（当前页里没有它时按 id 补拉）
  const [selectedRow, setSelectedRow] = useState<Voyage | null>(null);
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
  // 破坏性操作二次确认（P1-8）
  const [confirm, setConfirm] = useState<{ title: string; message: string; action: () => void } | null>(null);
  // 主列表取数状态（P1-4）
  const [listLoading, setListLoading] = useState(true);
  const [listErr, setListErr] = useState("");
  // 参考数据取数失败的可见提示（P1-4）
  const [refWarn, setRefWarn] = useState("");

  // 列表内检索（URL 参数 q，可分享/回退）—— 与其它列表页一致：窄列表也能立刻定位航次
  const voyageQuery = typeof query.q === "string" ? query.q : "";
  // 检索框本地草稿 + 防抖：服务端检索时，每敲一个字就发一次请求会把 API 打满；
  // 草稿保证输入框响应即时，URL 只在停顿 300ms 后才更新。
  const [qDraft, setQDraft] = useState(voyageQuery);
  useEffect(() => {
    setQDraft(voyageQuery);
  }, [voyageQuery]);
  useEffect(() => {
    if (qDraft === voyageQuery) return;
    const timer = setTimeout(() => {
      setQuery({ q: qDraft || null }, { resetPage: true });
    }, 300);
    return () => clearTimeout(timer);
  }, [qDraft, voyageQuery, setQuery]);

  // 分页（P1-28）：**服务端分页** —— 后端返回 {items,total,limit,offset} 信封。
  // 以前这里是"一次拉全表 + 前端切片"，租户航次一多就把整张表序列化一遍。
  // 现在只取当前页，total 来自服务端，截断对用户可见（显示「共 N 条」）。
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const safePage = Math.min(page, totalPages);
  const pagedRows = rows;
  const setPage = (p: number) => setQuery({ page: p > 1 ? p : null });

  // 三栏宽度（列表 | 详情 | 船期块），可拖拽并记忆
  const [leftW, setLeftW] = useState(280);
  const [rightW, setRightW] = useState(340);
  useEffect(() => {
    const l = Number(localStorage.getItem("voyages_split_left"));
    const r = Number(localStorage.getItem("voyages_split_right"));
    if (l >= 220 && l <= 480) setLeftW(l);
    if (r >= 260 && r <= 560) setRightW(r);
  }, []);
  useEffect(() => {
    localStorage.setItem("voyages_split_left", String(leftW));
  }, [leftW]);
  useEffect(() => {
    localStorage.setItem("voyages_split_right", String(rightW));
  }, [rightW]);
  function startSplitDrag(side: "left" | "right", e: ReactMouseEvent) {
    e.preventDefault();
    const startX = e.clientX;
    const startL = leftW;
    const startR = rightW;
    const onMove = (ev: MouseEvent) => {
      const dx = ev.clientX - startX;
      if (side === "left") setLeftW(Math.min(480, Math.max(220, startL + dx)));
      else setRightW(Math.min(560, Math.max(260, startR - dx)));
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }

  const [newVoyageNo, setNewVoyageNo] = useState("");
  const [newCargo, setNewCargo] = useState("");
  const [creating, setCreating] = useState(false);

  useListHotkeys(() => setCreating(true));

  // 行右键菜单：打开 / 工作台 / 添加到个人待办 / 复制 id
  const router = useRouter();
  const rowCtx = useContextMenu<Voyage>();
  const todo = useTodoAdd();
  function voyageMenuItems(row: Voyage): ContextMenuItem[] {
    return [
      { key: "open", label: t("common.open", "Open"), onClick: () => selectVoyage(row.id) },
      {
        key: "workspace",
        label: t("page.voyages.open_ws", "Open workspace"),
        onClick: () => router.push(`/operations/voyages/${row.id}/workspace`),
      },
      { key: "divider", divider: true },
      todo.menuItem({ entityType: "voyage", entityId: row.id, title: row.voyage_no }),
      { key: "copy", label: t("common.copy_id", "Copy id"), onClick: () => void navigator.clipboard?.writeText(row.id) },
    ];
  }

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
  const [noons, setNoons] = useState<NoonRow[]>([]);
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
    setListLoading(true);
    setListErr("");
    try {
      const [v, s, p, parties] = await Promise.all([
        // 服务端分页 + 服务端检索（U1 列表信封：{items,total,limit,offset}）
        apiList<Voyage>("/api/v1/voyages", {
          limit,
          offset: (page - 1) * limit,
          q: voyageQuery,
        }),
        apiGet("/api/v1/schedules"),
        apiGet("/api/v1/masterdata/ports/options"),
        // 参考数据（对手方）失败不让整页报错，但要可见（P1-4）。
        apiGet("/api/v1/masterdata/counterparties").catch(() => {
          setRefWarn(t("page.voyages.cparties_fail", "Could not load counterparties — the agent list may be empty."));
          return [];
        }),
      ]);
      setRows(v.items);
      setTotal(v.total);
      setSchedules(s);
      setPorts(p);
      setAgents(
        (parties as Array<{ id: string; name: string; type?: string }>).filter(
          (x) => !x.type || x.type === "agent" || x.type === "other",
        ),
      );
      // 用函数式更新：只在还没选港口时兜底成第一个港口。
      // 这样回调不必读 pcPort —— React Compiler 才能保住这段 useCallback 的记忆化
      // （直接读 pcPort 会让编译器跳过优化并报 preserve-manual-memoization）。
      setPcPort((cur) => cur || (p[0]?.id ?? ""));
      return v.items as Voyage[];
    } catch (e) {
      // 主列表失败必须走 StateView 错误态，不能静默变成空列表（P1-4）。
      setListErr(msgOf(e, t("common.failed", "Failed")));
      throw e;
    } finally {
      setListLoading(false);
    }
  }, [setPcPort, limit, page, voyageQuery]);

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
    try {
      const nn = await apiGet(`/api/v1/noon-reports?voyage_id=${voyageId}`);
      setNoons(nn);
    } catch {
      setNoons([]);
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

  // 服务端分页：翻页 / 改每页条数 / 改检索词都要重新取当前页
  useEffect(() => {
    load().catch(handled);
  }, [load]);

  // 当前页越界（例如刚删完本页最后一条）→ 回到最后一页，别停在空白页
  useEffect(() => {
    if (!total) return;
    const maxPage = Math.max(1, Math.ceil(total / limit));
    if (page > maxPage) setQuery({ page: maxPage > 1 ? maxPage : null });
  }, [total, page, limit, setQuery]);

  // 首次进入：深链 ?v=<id> 优先，不被列表首条覆盖；无深链才默认选中首条
  const bootstrapped = useRef(false);
  useEffect(() => {
    if (bootstrapped.current) return;
    if (!rows.length) return;
    bootstrapped.current = true;
    if (selectedId) {
      // 深链：右栏由下面「按 id 补拉」effect 解析，这里只把靠泊记录拉出来
      void loadPortCalls(selectedId).catch(handled);
      return;
    }
    const pick = rows[0].id;
    setSelectedId(pick);
    setSelectedRow(rows[0]);
    void loadPortCalls(pick).catch(handled);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, selectedId]);

  // 深链 / 跨页选中：当前页里没有这条航次时按 id 补拉一次，
  // 否则翻页后右栏会莫名其妙变成空白。
  useEffect(() => {
    if (!selectedId) {
      setSelectedRow(null);
      return;
    }
    const inPage = rows.find((r) => r.id === selectedId);
    if (inPage) {
      setSelectedRow(inPage);
      return;
    }
    let cancelled = false;
    apiGet(`/api/v1/voyages/${selectedId}`)
      .then((v: Voyage) => {
        if (!cancelled) setSelectedRow(v);
      })
      .catch((ex) => {
        if (cancelled) return;
        // P1-4：单条航次补拉失败不能静默把右栏清空 —— 用户会以为这条航次
        // 没有明细。明确提示，并保留列表里的那一条。
        setSelectedRow(null);
        toast.warning(
          msgOf(ex, t("page.voyages.detail_fail", "Could not load this voyage's details.")),
        );
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId, rows, t, toast]);

  async function selectVoyage(id: string) {
    setSelectedId(id);
    setSelectedRow(rows.find((r) => r.id === id) ?? null);
    setTwin(null);
    setLastNoon(null);
    setErr("");
    try {
      await loadPortCalls(id);
    } catch (ex) {
      setErr(msgOf(ex));
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
      toast.error(msgOf(ex));
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
      setErr(msgOf(ex));
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
      setErr(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  async function removeVoyage() {
    if (!selected) return;
    setBusy(true);
    try {
      await apiDelete(`/api/v1/voyages/${selected.id}`);
      setSelectedId(null);
      toast.success(t("common.recycled", "Moved to recycle bin"));
      await load();
    } catch (ex) {
      setErr(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  /** 删除航次不可撤销 —— 走 ConfirmDialog 并指名航次（P1-8）。 */
  function askRemoveVoyage() {
    if (!selected) return;
    setConfirm({
      title: t("common.delete", "Delete"),
      message: t(
        "page.voyages.delete_confirm",
        'Delete voyage "{no}"? It will move to the recycle bin and can be restored.',
        { no: selected.voyage_no },
      ),
      action: () => void removeVoyage(),
    });
  }

  async function addPortCall(e: FormEvent) {
    e.preventDefault();
    if (!selectedId) return;
    if ((pcEta && !fromLocalInput(pcEta)) || (pcEtd && !fromLocalInput(pcEtd))) {
      setErr(t("page.voyages.bad_date", "Invalid date/time format. Please reselect."));
      return;
    }
    // P1-24：挂靠序号是 1 起始的整数 —— 填 0 / 填字母都是非法值，必须报错，
    // 不能静默替换成 1（那会让用户以为存进去的是自己填的值）。
    const seqNum = toPositiveInt(pcSeq);
    if (seqNum === null) {
      setErr(t("page.voyages.bad_seq", {
        en: "Sequence must be a whole number of 1 or more.",
        zh: "序号必须是大于等于 1 的整数。",
      }));
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await apiPost("/api/v1/port-calls", {
        voyage_id: selectedId,
        port_id: pcPort || null,
        seq: seqNum,
        purpose: pcPurpose,
        eta: fromLocalInput(pcEta),
        etd: fromLocalInput(pcEtd),
        agent: pcAgent || null,
      });
      toast.success(t("page.voyages.pc_ok", "Port call added"));
      setPcSeq(String(seqNum + 1));
      await loadPortCalls(selectedId);
    } catch (ex) {
      setErr(msgOf(ex));
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
      setErr(msgOf(ex));
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
      setErr(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  const closeOffHire = useCallback(async (id: string) => {
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
      setErr(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }, [loadPortCalls, ohCloseAt, selectedId, setOhCloseAt, t, toast]);

  /** 关闭 off-hire 期 —— 关闭后不可再改期，二次确认（P1-8）。 */
  const askCloseOffHire = useCallback((id: string) => {
    setConfirm({
      title: t("common.close", "Close"),
      message: t(
        "page.voyages.oh_close_confirm",
        "Close this off-hire period? Once closed the period can no longer be amended.",
      ),
      action: () => void closeOffHire(id),
    });
  }, [closeOffHire, t]);

  // ── 行内编辑（失焦/回车保存；值未变化不发请求，避免 blur→reload 打断输入） ──

  async function onPcCellSave(rowId: string, colKey: string, value: unknown, row: PortCall) {
    const dtFields = ["eta", "etd", "nor_at", "eosp_at"];
    let payload: Record<string, unknown>;
    if (colKey === "seq") {
      // P1-24：非法输入不能静默丢弃 —— 明确告诉用户这一格没写进去
      const n = value === null || value === "" ? null : Number(value);
      if (n !== null && !Number.isFinite(n)) {
        toast.error(t("page.voyages.err_numeric", {
          en: "{field} must be a valid number",
          zh: "{field} 必须是有效数字",
        }, { field: colKey }));
        return;
      }
      if (n === null || n === row.seq) return;
      payload = { seq: n };
    } else if (dtFields.includes(colKey)) {
      const prev = (row as Record<string, unknown>)[colKey];
      const nextIso = value ? parseUtc(String(value))?.toISOString() ?? null : null;
      const prevT = prev ? parseUtc(String(prev))?.getTime() ?? null : null;
      const nextT = nextIso ? new Date(nextIso).getTime() : null;
      if (prevT === nextT) return;
      payload = { [colKey]: nextIso };
    } else {
      if (((row as Record<string, unknown>)[colKey] ?? "") === (value ?? "")) return;
      payload = { [colKey]: value === "" ? null : value };
    }
    try {
      await apiPatch(`/api/v1/port-calls/${rowId}`, payload);
      toast.success(t("common.saved", "Saved"));
      if (selectedId) await loadPortCalls(selectedId, selectedPc);
    } catch (ex: any) {
      toast.error(msgOf(ex));
    }
  }

  const deletePortCall = useCallback(async (pcId: string) => {
    if (!selectedId) return;
    try {
      await apiDelete(`/api/v1/port-calls/${pcId}`);
      toast.success(t("common.recycled", "Moved to recycle bin"));
      await loadPortCalls(selectedId);
    } catch (ex: any) {
      toast.error(msgOf(ex));
    }
  }, [loadPortCalls, selectedId, t, toast]);

  async function onSofCellSave(
    rowId: string,
    colKey: string,
    value: unknown,
    row: (typeof sofEvents)[number],
  ) {
    let payload: Record<string, unknown>;
    if (colKey === "event_at") {
      const prev = row.event_at;
      const nextIso = value ? parseUtc(String(value))?.toISOString() ?? null : null;
      const prevT = prev ? parseUtc(prev)?.getTime() ?? null : null;
      const nextT = nextIso ? new Date(nextIso).getTime() : null;
      if (prevT === nextT) return;
      payload = { event_at: nextIso };
    } else {
      if ((row as Record<string, unknown>)[colKey] === (value ?? null)) return;
      payload = { [colKey]: value ?? null };
    }
    try {
      await apiPatch(`/api/v1/sof-events/${rowId}`, payload);
      toast.success(t("common.saved", "Saved"));
      if (selectedId) await loadPortCalls(selectedId, selectedPc);
    } catch (ex: any) {
      toast.error(msgOf(ex));
    }
  }

  const deleteSof = useCallback(async (eventId: string) => {
    try {
      await apiDelete(`/api/v1/sof-events/${eventId}`);
      toast.success(t("common.deleted", "Deleted"));
      if (selectedId) await loadPortCalls(selectedId, selectedPc);
    } catch (ex: any) {
      toast.error(msgOf(ex));
    }
  }, [loadPortCalls, selectedId, selectedPc, t, toast]);

  async function onOffHireCellSave(rowId: string, colKey: string, value: unknown, row: OffHire) {
    const src = row as Record<string, unknown>;
    let payload: Record<string, unknown>;
    if (colKey === "start_at" || colKey === "end_at") {
      const prev = src[colKey];
      const nextIso = value ? parseUtc(String(value))?.toISOString() ?? null : null;
      const prevT = prev ? parseUtc(String(prev))?.getTime() ?? null : null;
      const nextT = nextIso ? new Date(nextIso).getTime() : null;
      if (prevT === nextT) return;
      payload = { [colKey]: nextIso };
    } else {
      if ((src[colKey] ?? "") === (value ?? "")) return;
      payload = { [colKey]: value === "" ? null : value };
    }
    try {
      await apiPatch(`/api/v1/off-hire/${rowId}`, payload);
      toast.success(t("common.saved", "Saved"));
      if (selectedId) await loadPortCalls(selectedId, selectedPc);
    } catch (ex: any) {
      toast.error(msgOf(ex));
    }
  }

  const deleteOffHire = useCallback(async (eventId: string) => {
    try {
      await apiDelete(`/api/v1/off-hire/${eventId}`);
      toast.success(t("common.deleted", "Deleted"));
      if (selectedId) await loadPortCalls(selectedId, selectedPc);
    } catch (ex: any) {
      toast.error(msgOf(ex));
    }
  }, [loadPortCalls, selectedId, selectedPc, t, toast]);

  async function onNoonCellSave(rowId: string, colKey: string, value: unknown, row: NoonRow) {
    const src = row as Record<string, unknown>;
    let payload: Record<string, unknown>;
    if (colKey === "report_at") {
      const prev = row.report_at;
      const nextIso = value ? parseUtc(String(value))?.toISOString() ?? null : null;
      const prevT = prev ? parseUtc(String(prev))?.getTime() ?? null : null;
      const nextT = nextIso ? new Date(nextIso).getTime() : null;
      if (prevT === nextT) return;
      payload = { report_at: nextIso };
    } else if (colKey === "speed" || colKey === "rob_fo" || colKey === "rob_do") {
      const next = value === null || value === "" ? null : Number(value);
      // P1-24：非法输入不能静默丢弃 —— 明确告诉用户这一格没写进去
      if (next !== null && !Number.isFinite(next)) {
        toast.error(t("page.voyages.err_numeric", {
          en: "{field} must be a valid number",
          zh: "{field} 必须是有效数字",
        }, { field: colKey }));
        return;
      }
      if ((src[colKey] ?? null) === next) return;
      payload = { [colKey]: next };
    } else {
      if ((src[colKey] ?? "") === (value ?? "")) return;
      payload = { [colKey]: value === "" ? null : value };
    }
    try {
      await apiPatch(`/api/v1/noon-reports/${rowId}`, payload);
      toast.success(t("common.saved", "Saved"));
      if (selectedId) await loadPortCalls(selectedId, selectedPc);
    } catch (ex: any) {
      toast.error(msgOf(ex));
    }
  }

  const deleteNoon = useCallback(async (noonId: string) => {
    try {
      await apiDelete(`/api/v1/noon-reports/${noonId}`);
      toast.success(t("common.deleted", "Deleted"));
      if (selectedId) await loadPortCalls(selectedId, selectedPc);
    } catch (ex: any) {
      toast.error(msgOf(ex));
    }
  }, [loadPortCalls, selectedId, selectedPc, t, toast]);

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
      setErr(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  const portLabel = useCallback((id: string | null) => {
    if (!id) return "—";
    const p = ports.find((x) => x.id === id);
    return p ? `${p.name}${p.unlocode ? ` (${p.unlocode})` : ""}` : id.slice(0, 8);
  }, [ports]);

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
      toast.error(msgOf(ex));
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
      toast.error(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  // 当前选中的航次：优先取当前页的行；跨页/深链时用补拉到的 selectedRow
  const selected = (selectedId ? rows.find((r) => r.id === selectedId) ?? selectedRow : null) ?? null;
  const conflicts = schedules.filter((s) => s.hard_conflict);

  const voyageColumns = useMemo<ColumnDef<Voyage>[]>(() => [
    {
      key: "_pick",
      title: "☑",
      width: 28,
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
    // 窄列表：仅勾选/操作列定宽，其余列均分剩余宽度 → 任何栏宽下都不出现横向滚动条
    {
      key: "voyage_no",
      title: t("page.voyages.no", "No"),
      value: (r) => r.voyage_no,
    },
    {
      key: "cargo",
      title: t("page.voyages.cargo", "Cargo"),
      value: (r) => r.cargo || "",
      render: (v) => (v ? String(v) : "—"),
    },
    { key: "status", title: t("common.status", "Status"), value: (r) => r.status },
    {
      key: "updated_at",
      title: t("list.last_modified", "Modified"),
      value: (r) => r.updated_at ?? null,
      // 窄列表：只显示 MM-DD HH:mm（省略年份与秒）
      render: (v) => (v ? toLocalInput(v as string).replace("T", " ").slice(5, 16) : "—"),
    },
    {
      key: "_actions",
      title: "",
      width: 26,
      align: "center",
      render: (_v, r) => (
        <Link
          href={`/operations/voyages/${r.id}/workspace`}
          className="icon-btn icon-btn-xs"
          title={t("page.voyages.view360", "360° view")}
          aria-label={t("page.voyages.view360", "360° view")}
          onClick={(e) => e.stopPropagation()}
        >
          ⤢
        </Link>
      ),
    },
  ], [picked, t]);

  const portCallColumns = useMemo<ColumnDef<PortCall>[]>(() => [
    { key: "seq", title: "#", width: 48, align: "right", value: (r) => r.seq, editor: { type: "number" } },
    {
      key: "port_id",
      title: t("page.voyages.port", "Port"),
      minWidth: 150,
      value: (r) => r.port_id || "",
      render: (_v, r) => portLabel(r.port_id),
      editor: {
        type: "select",
        options: ports.map((p) => ({ value: p.id, label: p.name })),
      },
    },
    {
      key: "purpose",
      title: t("page.voyages.purpose", "Purpose"),
      width: 90,
      value: (r) => r.purpose,
      render: (v) => t(`page.voyages.purpose_${v}`, String(v ?? "")),
      editor: {
        type: "select",
        options: ["load", "discharge", "bunker", "transit"].map((p) => ({
          value: p,
          label: t(`page.voyages.purpose_${p}`, p),
        })),
      },
    },
    {
      key: "eta",
      title: "ETA",
      width: 130,
      value: (r) => r.eta || "",
      render: (v) => (v ? toLocalInput(v as string).replace("T", " ") : "—"),
      editor: { type: "datetime" },
    },
    {
      key: "etd",
      title: "ETD",
      width: 130,
      value: (r) => r.etd || "",
      render: (v) => (v ? toLocalInput(v as string).replace("T", " ") : "—"),
      editor: { type: "datetime" },
    },
    {
      key: "nor_at",
      title: "NOR",
      width: 130,
      value: (r) => r.nor_at || "",
      render: (v) => (v ? toLocalInput(v as string).replace("T", " ") : "—"),
      editor: { type: "datetime" },
    },
    {
      key: "eosp_at",
      title: "EOSP",
      width: 130,
      value: (r) => r.eosp_at || "",
      render: (v) => (v ? toLocalInput(v as string).replace("T", " ") : "—"),
      editor: { type: "datetime" },
    },
    {
      key: "bl_date",
      title: "B/L",
      width: 110,
      value: (r) => r.bl_date || "",
      render: (v) => (v ? String(v) : "—"),
      editor: { type: "text" },
    },
    {
      key: "agent",
      title: t("page.voyages.agent", "Agent"),
      minWidth: 110,
      value: (r) => r.agent || "",
      render: (v) => (v ? String(v) : "—"),
      editor: { type: "text" },
    },
    {
      key: "_actions",
      title: "",
      width: 30,
      align: "center",
      render: (_v, r) => (
        <RowActions
          onDelete={() => deletePortCall(r.id)}
          label={`#${r.seq} ${portLabel(r.port_id)}`}
        />
      ),
    },
  ], [deletePortCall, portLabel, ports, t]);

  const sofColumns = useMemo<ColumnDef<(typeof sofEvents)[number]>[]>(() => [
    {
      key: "event_code",
      title: t("page.voyages.event", "Event"),
      width: 130,
      value: (r) => r.event_code,
      editor: { type: "select", options: SOF_CODES.map((c) => ({ value: c, label: c })) },
    },
    {
      key: "event_at",
      title: t("page.voyages.event_at", "Event at"),
      minWidth: 160,
      value: (r) => r.event_at || "",
      render: (v) => formatInTz(v as string | null, null, undefined, locale),
      editor: { type: "datetime" },
    },
    {
      key: "port_call_id",
      title: t("page.voyages.port_call", "Port call"),
      width: 110,
      value: (r) => r.port_call_id.slice(0, 8),
    },
    {
      key: "_actions",
      title: "",
      width: 30,
      align: "center",
      render: (_v, r) => (
        <RowActions
          onDelete={() => deleteSof(r.id)}
          label={r.event_code}
        />
      ),
    },
  ], [deleteSof, locale, t]);

  const offHireColumns = useMemo<ColumnDef<OffHire>[]>(() => [
    {
      key: "start_at",
      title: t("page.voyages.oh_start", "Start at"),
      width: 130,
      value: (r) => r.start_at || "",
      render: (v) => (v ? toLocalInput(v as string).replace("T", " ") : "—"),
      editor: { type: "datetime" },
    },
    {
      key: "end_at",
      title: t("page.voyages.oh_end", "End at"),
      width: 130,
      value: (r) => r.end_at || "",
      render: (v) => (v ? toLocalInput(v as string).replace("T", " ") : "—"),
      editor: { type: "datetime" },
    },
    {
      key: "reason",
      title: t("page.voyages.oh_reason", "Reason"),
      minWidth: 120,
      value: (r) => r.reason || "",
      render: (v) => (v ? String(v) : "—"),
      editor: { type: "text" },
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
      width: 250,
      align: "right",
      render: (_v, oh) => (
        <span
          className="desk-toolbar"
          style={{ margin: 0, justifyContent: "flex-end" }}
          onClick={(e) => e.stopPropagation()}
        >
          {!oh.end_at ? (
            <>
              <DateTimeInput value={ohCloseAt} onChange={setOhCloseAt} />
              <button className="btn btn-sm" type="button" disabled={busy} onClick={() => askCloseOffHire(oh.id)}>
                {t("common.close", "Close")}
              </button>
            </>
          ) : null}
          <RowActions
            onDelete={oh.status !== "closed" ? () => deleteOffHire(oh.id) : undefined}
            label={oh.reason || toLocalInput(oh.start_at)}
          />
        </span>
      ),
    },
  ], [askCloseOffHire, busy, deleteOffHire, ohCloseAt, setOhCloseAt, t]);

  const noonColumns = useMemo<ColumnDef<NoonRow>[]>(() => [
    {
      key: "report_at",
      title: t("page.voyages.at", "At"),
      width: 130,
      value: (r) => r.report_at || "",
      render: (v) => (v ? toLocalInput(v as string).replace("T", " ") : "—"),
      editor: { type: "datetime" },
    },
    {
      key: "speed",
      title: t("page.voyages.speed", "Speed"),
      width: 80,
      align: "right",
      value: (r) => r.speed ?? "",
      render: (v) => (v === "" || v == null ? "—" : String(v)),
      editor: { type: "number", step: 0.1 },
    },
    {
      key: "rob_fo",
      title: "ROB FO",
      width: 85,
      align: "right",
      value: (r) => r.rob_fo ?? "",
      render: (v) => (v === "" || v == null ? "—" : String(v)),
      editor: { type: "number", step: 0.1 },
    },
    {
      key: "rob_do",
      title: "ROB DO",
      width: 85,
      align: "right",
      value: (r) => r.rob_do ?? "",
      render: (v) => (v === "" || v == null ? "—" : String(v)),
      editor: { type: "number", step: 0.1 },
    },
    {
      key: "remarks",
      title: t("page.voyages.remarks", "Remarks"),
      minWidth: 120,
      value: (r) => r.remarks || "",
      render: (v) => (v ? String(v) : "—"),
      editor: { type: "text" },
    },
    {
      key: "_actions",
      title: "",
      width: 30,
      align: "center",
      render: (_v, r) => (
        <RowActions
          onDelete={() => deleteNoon(r.id)}
          label={toLocalInput(r.report_at).replace("T", " ")}
        />
      ),
    },
  ], [deleteNoon, t]);

  type NoonPoint = { at: string; lat: number | null; lon: number | null; key: string };
  const noonTrackColumns = useMemo<ColumnDef<NoonPoint>[]>(() => [
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
  ], [t]);

  const scheduleColumns = useMemo<ColumnDef<Schedule>[]>(() => [
    { key: "title", title: t("common.title", "Title"), minWidth: 150, value: (r) => r.title },
    {
      key: "block_type",
      title: t("page.voyages.block_type", "Type"),
      width: 100,
      value: (r) => r.block_type,
      render: (v) => t(`page.voyages.block_${v}`, String(v ?? "")),
    },
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
  ], [t]);

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
        filterCount={voyageQuery ? 1 : 0}
        onClearFilters={() => setQuery({ q: null })}
        right={
          <>
            {picked.size > 0 ? (
              <span className="badge badge-info">
                {t("page.voyages.batch_selected", "{n} selected", { n: picked.size })}
              </span>
            ) : null}
            <input
              className="input input-sm"
              type="search"
              value={qDraft}
              onChange={(e) => setQDraft(e.target.value)}
              placeholder={t("page.voyages.search", "Search no / cargo…")}
              aria-label={t("common.search", "Search")}
            />
            <span className="hint">
              {t("page.voyages.count", "{n} voyages", { n: total })}
            </span>
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
          aria-label={t("page.voyages.batch_select_all", "Select all / clear")}
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
        <RefreshButton label={t("common.refresh", "Refresh")} className="btn btn-sm" disabled={busy} onClick={() => load().catch(handled)} />
      </Toolbar>

      {err ? <p className="flash-err">{err}</p> : null}
      {refWarn ? <p className="flash-err">{refWarn}</p> : null}

      {/* 三栏工作台：列表 | 详情 | 船期块（底部上移）；分隔条可拖拽改宽 */}
      <div
        className="desk-split voy3"
        style={{ gridTemplateColumns: `${leftW}px 6px minmax(0, 1fr) 6px ${rightW}px` }}
      >
        <div className="panel desk-list">
          <h3 style={{ margin: "0.85rem 1rem 0.35rem", fontSize: "0.95rem" }}>{t("page.voyages.list", "Voyages")}</h3>
          <p className="muted" style={{ padding: "0 1rem", marginTop: 0, fontSize: "0.8rem" }}>
            {t("page.voyages.create_hint", "Or activate a charter to auto-create a voyage + schedule block.")}
          </p>
          <StateView
            loading={listLoading && !rows.length}
            error={listErr || undefined}
            empty={!listErr && !pagedRows.length}
            emptyText={t("common.empty", "No records")}
            onRetry={() => load().catch(handled)}
          >
            <DataGrid<Voyage>
              columns={voyageColumns}
              data={pagedRows}
              rowKey={(r) => r.id}
              storageKey="voyages_list_grid"
              showFooter={false}
              emptyText={t("common.empty", "No records")}
              onRowClick={(r) => selectVoyage(r.id)}
              onRowContextMenu={(row, _i, e) => rowCtx.open(row)(e)}
            />
          </StateView>
          {/* 分页：截断对用户可见（P1-28） */}
          {!listErr ? (
            <div className="dt-pagination">
              <span className="dt-page-info">
                {t("page.voyages.page_of", "{from}-{to} of {n}", {
                  from: total ? (safePage - 1) * limit + 1 : 0,
                  to: Math.min(safePage * limit, total),
                  n: total,
                })}
              </span>
              <span className="dt-page-btns">
                <button type="button" onClick={() => setPage(safePage - 1)} disabled={safePage <= 1} aria-label="prev">
                  ‹
                </button>
                <button type="button" onClick={() => setPage(safePage + 1)} disabled={safePage >= totalPages} aria-label="next">
                  ›
                </button>
              </span>
            </div>
          ) : null}
        </div>

        <div
          className="splitter"
          role="separator"
          aria-orientation="vertical"
          aria-label={t("page.voyages.split_hint", "Drag to resize")}
          onMouseDown={(e) => startSplitDrag("left", e)}
        />

        <div>
          {selected ? (
            <div className="panel" style={{ marginTop: 0 }}>
              <div className="page-header" style={{ marginBottom: "0.5rem" }}>
                <div>
                  <h3 style={{ margin: 0 }}>
                    {selected.voyage_no} <StatusBadge status={selected.status} />
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
                  <button className="btn btn-danger btn-sm" type="button" disabled={busy} onClick={askRemoveVoyage}>
                    {t("common.delete", "Delete")}
                  </button>
                </div>
              </div>

              <DeskSection title={t("page.voyages.port_calls", "Port calls")}>
                <DataGrid<PortCall>
                  columns={portCallColumns}
                  data={portCalls}
                  rowKey={(r) => r.id}
                  storageKey="voyages_portcalls_grid"
                  showFooter={false}
                  editable
                  onCellSave={onPcCellSave}
                  emptyText={t("common.empty", "No records")}
                  onRowClick={(pc) => setSelectedPc(pc.id)}
                />

                <form className="form-grid" onSubmit={addPortCall} style={{ marginTop: "0.75rem" }}>
                  <label>
                    {t("page.voyages.purpose", "Purpose")}
                    <select value={pcPurpose} onChange={(e) => setPcPurpose(e.target.value)}>
                      <option value="load">{t("page.voyages.purpose_load", "Load")}</option>
                      <option value="discharge">{t("page.voyages.purpose_discharge", "Discharge")}</option>
                      <option value="bunker">{t("page.voyages.purpose_bunker", "Bunker")}</option>
                      <option value="transit">{t("page.voyages.purpose_transit", "Transit")}</option>
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
                  <div className="form-actions">
                    <button className="btn btn-primary btn-sm" type="submit" disabled={busy}>
                      {t("page.voyages.add_pc", "Add port call")}
                    </button>
                  </div>
                </form>
              </DeskSection>

              <DeskSection title={t("page.voyages.sof", "SOF events")}>
                <form className="form-grid" onSubmit={addSof}>
                  <label>
                    {t("page.voyages.port_call", "Port call")}
                    <select value={selectedPc} onChange={(e) => setSelectedPc(e.target.value)}>
                      <option value="">{t("common.select", "Select…")}</option>
                      {portCalls.map((pc) => (
                        <option key={pc.id} value={pc.id}>
                          #{pc.seq} {t(`page.voyages.purpose_${pc.purpose}`, pc.purpose)} · {portLabel(pc.port_id)}
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
                  <div className="form-actions">
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
                    editable
                    onCellSave={onSofCellSave}
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
              </DeskSection>

              <DeskSection title={t("page.voyages.noon", "Noon report")}>
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
                  <div className="form-actions">
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
                <div style={{ marginTop: "0.75rem" }}>
                  <DataGrid<NoonRow>
                    columns={noonColumns}
                    data={noons}
                    rowKey={(r) => r.id}
                    storageKey="voyages_noons_grid"
                    showFooter={false}
                    editable
                    onCellSave={onNoonCellSave}
                    emptyText={t("page.voyages.no_noons", "No noon reports yet")}
                  />
                </div>
              </DeskSection>
            </div>
          ) : (
            <div className="panel" style={{ marginTop: 0 }}>
              <p className="muted">{t("page.voyages.select", "Select a voyage")}</p>
            </div>
          )}
        </div>

        <div
          className="splitter"
          role="separator"
          aria-orientation="vertical"
          aria-label={t("page.voyages.split_hint", "Drag to resize")}
          onMouseDown={(e) => startSplitDrag("right", e)}
        />

        {/* 右栏 = 监控/上下文区（顺手习惯：对照船期看轨迹，异常时开停租）；吸顶独立滚动，⤢ 可局部放大 */}
        <div className="panel desk-side">
          <DeskSection title={t("page.voyages.schedule", "Schedule blocks")}>
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
          </DeskSection>

          <DeskSection title={t("page.voyages.twin", "Twin track")}>
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
          </DeskSection>

          <DeskSection title={t("page.voyages.off_hire", "Off-hire")}>
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
              <div className="form-actions">
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
                editable
                onCellSave={onOffHireCellSave}
                emptyText={t("common.no_data", "No data")}
              />
            </div>
          </DeskSection>
        </div>
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

      <ContextMenu controller={rowCtx} items={voyageMenuItems} />
      {todo.element}

      <ConfirmDialog
        open={Boolean(confirm)}
        title={confirm?.title || ""}
        message={confirm?.message || ""}
        danger
        confirmLabel={t("common.delete", "Delete")}
        onConfirm={() => {
          const fn = confirm?.action;
          setConfirm(null);
          fn?.();
        }}
        onCancel={() => setConfirm(null)}
      />
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
