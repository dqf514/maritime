"use client";

import { msgOf } from "@/lib/errors";
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { AttachmentsPanel } from "@/components/AttachmentsPanel";
import { BunkerRequirementsPanel } from "@/components/BunkerRequirementsPanel";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { PartyPicker } from "@/components/DataPicker";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { LookupSelect } from "@/components/LookupSelect";
import { Num } from "@/components/Num";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { RowActions } from "@/components/RowActions";
import { StateView } from "@/components/StateView";
import { StatusLegend } from "@/components/StatusLegend";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";
import { formatDateTimeShort } from "@/lib/datetime";

type Ref = { id: string; name: string; voyage_no?: string };
type Order = {
  id: string;
  order_no: string;
  status: string;
  vessel_id: string | null;
  voyage_id: string | null;
  grade: string;
  qty_ordered: number;
  qty_delivered: number | null;
  unit_price: number;
  rob_before: number | null;
  rob_after: number | null;
  amount: number;
  currency: string;
  updated_at?: string | null;
};

type Inquiry = { id: string; supplier: string; quoted_price: number; status: string; updated_at?: string | null };

/** 交付告警 —— 后端返回 {code, message} 对象，不可直接 String()（会变成 [object Object]）。 */
type BunkerWarning = { code: string; message: string; orderNo?: string };

const EMPTY_FORM = {
  vessel_id: "",
  voyage_id: "",
  grade: "VLSFO",
  qty_ordered: "100",
  unit_price: "550",
  rob_before: "200",
  index_symbol: "",
  price_differential: "",
};

/** 把后端告警对象结构化：优先 code/message/severity，未知结构退回 JSON。 */
function readWarning(w: unknown, orderNo?: string): BunkerWarning {
  if (typeof w === "string") return { code: "", message: w, orderNo };
  if (w && typeof w === "object") {
    const o = w as Record<string, unknown>;
    const code = typeof o.code === "string" ? o.code : "";
    const severity = typeof o.severity === "string" ? o.severity : "";
    const message = typeof o.message === "string" ? o.message : "";
    if (!code && !severity && !message) {
      try {
        return { code: "", message: JSON.stringify(o), orderNo };
      } catch {
        return { code: "", message: String(w), orderNo };
      }
    }
    return { code: [code, severity].filter(Boolean).join(" · "), message, orderNo };
  }
  return { code: "", message: String(w), orderNo };
}

/** 数字字段解析结果：ok(合法数值) | empty(空串) | bad(非法输入，不可静默转 0)。 */
type NumParse = { kind: "ok"; value: number } | { kind: "empty" } | { kind: "bad" };

function parseNum(raw: string): NumParse {
  const s = (raw ?? "").trim();
  if (s === "") return { kind: "empty" };
  const n = Number(s);
  return Number.isFinite(n) ? { kind: "ok", value: n } : { kind: "bad" };
}

export default function BunkerDeskPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [rows, setRows] = useState<Order[]>([]);
  const [vessels, setVessels] = useState<Ref[]>([]);
  const [voyages, setVoyages] = useState<Ref[]>([]);
  const [err, setErr] = useState("");
  const [listErr, setListErr] = useState("");
  const [loading, setLoading] = useState(true);
  const [refLoadFailed, setRefLoadFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<Order | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [deliverQty, setDeliverQty] = useState("");
  const [bdnQty, setBdnQty] = useState("");
  const [consumption, setConsumption] = useState("");
  const [warnings, setWarnings] = useState<BunkerWarning[]>([]);
  const [inquiries, setInquiries] = useState<Inquiry[]>([]);
  const [inqErr, setInqErr] = useState("");
  const [inqSupplier, setInqSupplier] = useState("");
  const [inqPrice, setInqPrice] = useState("");
  const [alloc, setAlloc] = useState<Record<string, unknown> | null>(null);
  // 破坏性操作（确认交付）二次确认：pending 存待执行动作 + 被指名的订单
  const [pendingDelivery, setPendingDelivery] = useState<{ run: () => void; orderNo: string } | null>(null);
  // 删除订单同样不可逆 —— 走指名对象的二次确认。
  const [pendingDelete, setPendingDelete] = useState<{ run: () => void; orderNo: string } | null>(null);

  useListHotkeys(openCreate);

  const orderCtx = useContextMenu<Order>();
  const inqCtx = useContextMenu<Inquiry>();

  function exportOrders(selected: Order[]) {
    downloadCsv(
      "bunker-orders",
      ["id", "order_no", "status", "grade", "qty_ordered", "qty_delivered", "unit_price", "amount", "currency", "rob_before", "rob_after"],
      selected.map((r) => [
        r.id,
        r.order_no,
        r.status,
        r.grade,
        r.qty_ordered,
        r.qty_delivered ?? "",
        r.unit_price,
        r.amount,
        r.currency,
        r.rob_before ?? "",
        r.rob_after ?? "",
      ]),
    );
  }

  function orderMenuItems(target: Order): ContextMenuItem[] {
    return [
      { key: "open", label: t("common.open", "Open"), onClick: () => openRow(target) },
      { key: "copy", label: t("common.copy_id", "Copy id"), onClick: () => void navigator.clipboard?.writeText(target.id) },
      { key: "export", label: t("page.finance.export_selected", "Export selected"), onClick: () => exportOrders([target]) },
      { key: "div", divider: true, label: "" },
      ...(target.status === "planned"
        ? [{ key: "inq", label: t("page.bunker.inquiry", "Inquiry"), onClick: () => move(target.id, "inquiry") } as ContextMenuItem]
        : []),
      ...(target.status === "inquiry"
        ? [{ key: "ord", label: t("page.bunker.order", "Place order"), onClick: () => move(target.id, "ordered") } as ContextMenuItem]
        : []),
      ...(target.status === "ordered"
        ? [{ key: "del", label: t("page.bunker.confirm_delivery", "Confirm delivery"), onClick: () => requestDelivery(target) } as ContextMenuItem]
        : []),
      ...(target.status === "delivered"
        ? [{ key: "close", label: t("common.close", "Close"), onClick: () => move(target.id, "closed") } as ContextMenuItem]
        : []),
    ];
  }

  function inqMenuItems(target: Inquiry): ContextMenuItem[] {
    return [
      { key: "copy", label: t("common.copy_id", "Copy id"), onClick: () => void navigator.clipboard?.writeText(target.id) },
      ...(target.status === "quoted"
        ? [{ key: "accept", label: t("page.bunker.accept", "Accept"), onClick: () => acceptInquiry(target.id) } as ContextMenuItem]
        : []),
    ];
  }

  const load = useCallback(async () => {
    setLoading(true);
    // 主列表：失败必须显性报错（StateView 错误态），不得静默变空列表
    try {
      const b = await apiGet("/api/v1/bunker-orders");
      setRows(Array.isArray(b) ? b : []);
      setListErr("");
    } catch (ex) {
      setRows([]);
      setListErr(msgOf(ex));
    }
    // 参考数据（船舶 / 航次下拉）：失败不让整页报错，但也不能完全静默
    const [v, voy] = await Promise.allSettled([
      apiGet("/api/v1/masterdata/vessels"),
      apiGet("/api/v1/voyages/options"),
    ]);
    setVessels(v.status === "fulfilled" ? (v.value as Ref[]) : []);
    setVoyages(voy.status === "fulfilled" ? (voy.value as Ref[]) : []);
    setRefLoadFailed(v.status === "rejected" || voy.status === "rejected");
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function openCreate() {
    setCreating(true);
    setOpen(null);
    setForm({ ...EMPTY_FORM });
    setDeliverQty("");
    setBdnQty("");
    setConsumption("");
    setWarnings([]);
    setInquiries([]);
    setInqErr("");
    setInqSupplier("");
    setInqPrice("");
    setAlloc(null);
    setErr("");
  }

  const closeModal = useCallback(() => {
    setOpen(null);
    setCreating(false);
  }, []);

  const loadInquiries = useCallback(async (orderId: string) => {
    // 询价列表失败：不让整页报错，但必须可见（不能静默变成「暂无报价」）
    try {
      const rows: Inquiry[] = await apiGet(`/api/v1/bunker-orders/${orderId}/inquiries`);
      setInquiries(Array.isArray(rows) ? rows : []);
      setInqErr("");
    } catch (ex) {
      setInquiries([]);
      setInqErr(msgOf(ex));
    }
  }, []);

  async function addInquiry() {
    if (!open) return;
    if (!inqSupplier.trim() || inqPrice === "") {
      setErr(t("page.bunker.inq_need", "Enter supplier and quote"));
      return;
    }
    const price = parseNum(inqPrice);
    if (price.kind !== "ok") {
      setErr(t("page.bunker.err_quoted_price", "Quoted price must be a valid number"));
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await apiPost(`/api/v1/bunker-orders/${open.id}/inquiries`, {
        supplier: inqSupplier.trim(),
        quoted_price: price.value,
      });
      await loadInquiries(open.id);
      setInqSupplier("");
      setInqPrice("");
      toast.success(t("page.bunker.inq_ok", "Quote logged"));
    } catch (ex) {
      setErr(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  const acceptInquiry = useCallback(
    async (id: string) => {
      if (!open) return;
      setBusy(true);
      setErr("");
      try {
        const res = await apiPost(`/api/v1/bunker-inquiries/${id}/accept`);
        await loadInquiries(open.id);
        setOpen({ ...open, unit_price: res.unit_price });
        setForm((f) => ({ ...f, unit_price: String(res.unit_price) }));
        toast.success(t("page.bunker.inq_accepted", "Quote accepted and order price updated"));
        await load();
      } catch (ex) {
        setErr(msgOf(ex));
      } finally {
        setBusy(false);
      }
    },
    [open, loadInquiries, toast, t, load],
  );

  async function loadAllocation() {
    if (!open?.voyage_id) return;
    setBusy(true);
    setErr("");
    try {
      setAlloc(await apiGet(`/api/v1/voyages/${open.voyage_id}/bunker-allocation`));
    } catch (ex) {
      setErr(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  async function move(id: string, target: string, qty?: { deliver?: string; bdn?: string; cons?: string }) {
    const dq = qty?.deliver ?? deliverQty;
    const bq = qty?.bdn ?? bdnQty;
    const cq = qty?.cons ?? consumption;
    // 交付量 / 消耗量：非法输入必须拦下（不能把 "abc" 送给后端，也不能静默变 0）
    const numericInputs: { key: string; raw: string; label: string }[] = [
      { key: "qty_delivered", raw: dq, label: t("page.bunker.deliver_qty", "Delivered qty") },
      { key: "bdn_qty", raw: bq, label: t("page.bunker.bdn_qty", "BDN qty") },
      { key: "consumption", raw: cq, label: t("page.bunker.consumption", "Consumption") },
    ];
    for (const inp of numericInputs) {
      if (inp.key === "bdn_qty" && target !== "delivered") continue;
      const parsed = parseNum(inp.raw);
      if (parsed.kind === "bad") {
        toast.error(t("page.bunker.err_numeric", "{field} must be a valid number", { field: inp.label }));
        return;
      }
    }
    setBusy(true);
    setWarnings([]);
    try {
      const q = new URLSearchParams({ target });
      if (dq) q.set("qty_delivered", dq);
      if (target === "delivered" && bq) q.set("bdn_qty", bq);
      if (cq) q.set("consumption", cq);
      const res = await apiPost(`/api/v1/bunker-orders/${id}/transition?${q.toString()}`);
      if (Array.isArray(res?.warnings) && res.warnings.length) {
        const orderNo = rows.find((r) => r.id === id)?.order_no;
        setWarnings((res.warnings as unknown[]).map((w) => readWarning(w, orderNo)));
      }
      toast.success(t("page.bunker.moved", "Status → {target}", { target }));
      closeModal();
      await load();
    } catch (ex) {
      setErr(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    // 数值校验：非法输入必须中止提交，不得用 || 0 把垃圾输入静默变成 0
    const qty = parseNum(form.qty_ordered);
    if (qty.kind !== "ok") {
      toast.error(t("page.bunker.err_qty", "Ordered quantity must be a valid number"));
      return;
    }
    if (qty.value < 0) {
      toast.error(t("page.bunker.err_qty_negative", "Ordered quantity must not be negative"));
      return;
    }
    const useIndex = form.index_symbol.trim() !== "";
    let unitPrice = 0;
    let priceDiff = 0;
    if (useIndex) {
      const pd = parseNum(form.price_differential);
      if (pd.kind === "bad") {
        toast.error(t("page.bunker.err_price_diff", "Price differential must be a valid number"));
        return;
      }
      priceDiff = pd.kind === "ok" ? pd.value : 0;
    } else {
      const up = parseNum(form.unit_price);
      if (up.kind !== "ok") {
        toast.error(t("page.bunker.err_unit_price", "Unit price must be a valid number"));
        return;
      }
      if (up.value < 0) {
        toast.error(t("page.bunker.err_unit_price_negative", "Unit price must not be negative"));
        return;
      }
      unitPrice = up.value;
    }
    const rob = parseNum(form.rob_before);
    if (rob.kind === "bad") {
      toast.error(t("page.bunker.err_rob", "ROB before must be a valid number"));
      return;
    }
    setBusy(true);
    setErr("");
    try {
      if (creating || !open) {
        await apiPost("/api/v1/bunker-orders", {
          vessel_id: form.vessel_id || null,
          voyage_id: form.voyage_id || null,
          grade: form.grade,
          qty_ordered: qty.value,
          ...(useIndex
            ? { index_symbol: form.index_symbol.trim(), price_differential: priceDiff }
            : { unit_price: unitPrice }),
          rob_before: rob.kind === "ok" ? rob.value : null,
        });
        toast.success(t("page.bunker.created", "Bunker order created"));
        closeModal();
      } else {
        if (orderLocked(open)) {
          toast.error(t("page.bunker.order_locked", "Delivered/closed orders cannot be edited or deleted"));
          return;
        }
        await apiPatch(`/api/v1/bunker-orders/${open.id}`, {
          grade: form.grade,
          qty_ordered: qty.value,
          unit_price: unitPrice,
          rob_before: rob.kind === "ok" ? rob.value : null,
          vessel_id: form.vessel_id || null,
          voyage_id: form.voyage_id || null,
        });
        toast.success(t("common.saved", "Saved"));
        closeModal();
      }
      await load();
    } catch (ex) {
      const anyEx = ex as { status?: number; detail?: { code?: string } };
      if (anyEx?.status === 422 && anyEx?.detail?.code === "NO_INDEX_QUOTE") {
        setErr(t("page.bunker.no_index_quote", "No market quote for this index (NO_INDEX_QUOTE). Configure pricing in Integration Hub or use a fixed unit price."));
      } else {
        setErr(msgOf(ex));
      }
    } finally {
      setBusy(false);
    }
  }

  const openRow = useCallback(
    (r: Order) => {
      setCreating(false);
      setOpen(r);
      setForm({
        vessel_id: r.vessel_id || "",
        voyage_id: r.voyage_id || "",
        grade: r.grade,
        qty_ordered: String(r.qty_ordered),
        unit_price: String(r.unit_price),
        rob_before: r.rob_before != null ? String(r.rob_before) : "",
        index_symbol: "",
        price_differential: "",
      });
      setDeliverQty(r.qty_delivered != null ? String(r.qty_delivered) : String(r.qty_ordered));
      setBdnQty("");
      setConsumption("");
      // 交付告警不清空：ROB 守恒告警必须在页面级持续可见
      setInquiries([]);
      setInqErr("");
      setInqSupplier("");
      setInqPrice("");
      setAlloc(null);
      void loadInquiries(r.id);
    },
    [loadInquiries],
  );

  const orderLocked = useCallback((r: Order) => r.status === "delivered" || r.status === "closed", []);

  /** 确认交付是不可逆动作 —— 走 ConfirmDialog 二次确认，且确认文案指名订单。 */
  function requestDelivery(order: Order, over?: { deliver?: string; bdn?: string; cons?: string }) {
    const deliver = over?.deliver ?? (order.qty_delivered != null ? String(order.qty_delivered) : String(order.qty_ordered));
    const run = () => move(order.id, "delivered", { deliver, bdn: over?.bdn ?? "", cons: over?.cons ?? "" });
    setPendingDelivery({ run, orderNo: order.order_no });
  }

  const deleteOrder = useCallback(
    async (id: string) => {
      try {
        await apiDelete(`/api/v1/bunker-orders/${id}`);
        toast.success(t("common.recycled", "Moved to recycle bin"));
        closeModal();
        await load();
      } catch (ex) {
        toast.error(msgOf(ex));
      }
    },
    [t, toast, closeModal, load],
  );

  /** 删除订单不可逆 —— 确认文案指名订单号。 */
  function requestDeleteOrder(order: Order) {
    setPendingDelete({ run: () => void deleteOrder(order.id), orderNo: order.order_no });
  }

  // ── 行内编辑（失焦/回车保存；值未变化不发请求，避免 blur→reload 打断输入） ──
  async function onOrderCellSave(rowId: string, colKey: string, value: unknown, row: Order) {
    if (orderLocked(row)) {
      toast.error(t("page.bunker.order_locked", "Delivered/closed orders cannot be edited or deleted"));
      return;
    }
    const numFields = ["qty_ordered", "unit_price", "rob_before"];
    let payload: Record<string, unknown>;
    if (numFields.includes(colKey)) {
      const n = Number(value);
      if (value === null || value === "" || !Number.isFinite(n)) {
        // 非法数字不能静默丢弃 —— 明确告诉用户这一格没写进去
        if (value !== null && value !== "" && !Number.isFinite(n)) {
          toast.error(t("page.bunker.err_numeric", "{field} must be a valid number", { field: colKey }));
        }
        return;
      }
      const prev = Number((row as unknown as Record<string, unknown>)[colKey]);
      if (n === prev) return;
      payload = { [colKey]: n };
    } else {
      if (((row as unknown as Record<string, unknown>)[colKey] ?? "") === (value ?? "")) return;
      payload = { [colKey]: value === "" ? null : value };
    }
    try {
      await apiPatch(`/api/v1/bunker-orders/${rowId}`, payload);
      toast.success(t("common.saved", "Saved"));
      await load();
    } catch (ex) {
      toast.error(msgOf(ex));
    }
  }

  const columns = useMemo<ColumnDef<Order>[]>(
    () => [
      { key: "order_no", title: t("page.finance.number", "No."), width: 130, value: (r) => r.order_no },
      { key: "grade", title: t("page.bunker.grade", "Grade"), width: 110, value: (r) => r.grade, editor: { type: "text" } },
      {
        key: "status",
        title: t("common.status", "Status"),
        width: 110,
        value: (r) => r.status,
        render: (v) => <span className={`badge badge-${v === "delivered" || v === "closed" ? "ok" : "info"}`}>{t(`status.${v}`, String(v))}</span>,
      },
      {
        key: "qty_ordered",
        title: t("page.bunker.qty", "Ordered qty (mt)"),
        width: 130,
        align: "right",
        value: (r) => r.qty_ordered,
        render: (v) => <Num v={v as number} digits={2} />,
        editor: { type: "number", min: 0 },
      },
      {
        key: "unit_price",
        title: t("page.bunker.price", "Unit price"),
        width: 110,
        align: "right",
        value: (r) => r.unit_price,
        render: (v) => <Num v={v as number} digits={2} />,
        editor: { type: "number", min: 0 },
      },
      {
        key: "amount",
        title: t("common.amount", "Amount"),
        width: 120,
        align: "right",
        value: (r) => r.amount,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      {
        key: "rob_before",
        title: t("page.bunker.rob_before", "ROB before"),
        width: 110,
        align: "right",
        value: (r) => r.rob_before,
        render: (v) => <Num v={v as number | null} digits={2} />,
        editor: { type: "number", min: 0 },
      },
      {
        key: "rob_after",
        title: t("page.bunker.rob_after", "ROB after"),
        width: 110,
        align: "right",
        value: (r) => r.rob_after,
        render: (v) => <Num v={v as number | null} digits={2} />,
      },
      {
        key: "updated_at",
        title: t("list.last_modified", "Last modified"),
        width: 135,
        value: (r) => r.updated_at ?? null,
        render: (v) => formatDateTimeShort(v as string | null),
      },
      {
        key: "_actions",
        title: "",
        width: 64,
        align: "center",
        render: (_v, r) => (
          <span title={orderLocked(r) ? t("page.bunker.order_locked", "Delivered/closed orders cannot be edited or deleted") : undefined}>
            <RowActions
              onEdit={() => openRow(r)}
              onDelete={() => deleteOrder(r.id)}
              canEdit={!orderLocked(r)}
              canDelete={!orderLocked(r)}
              label={r.order_no}
            />
          </span>
        ),
      },
    ],
    [t, orderLocked, openRow, deleteOrder],
  );

  const inquiryColumns = useMemo<ColumnDef<Inquiry>[]>(
    () => [
      { key: "supplier", title: t("page.bunker.supplier", "Supplier"), minWidth: 120, value: (r) => r.supplier },
      {
        key: "quoted_price",
        title: t("page.bunker.quoted_price", "Quoted price"),
        width: 110,
        align: "right",
        value: (r) => r.quoted_price,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      {
        key: "status",
        title: t("common.status", "Status"),
        width: 100,
        value: (r) => r.status,
        render: (_v, r) => (
          <span className={`badge ${r.status === "accepted" ? "badge-pass" : r.status === "rejected" ? "badge-fail" : "badge-warn"}`}>
            {t(`status.${r.status}`, r.status)}
          </span>
        ),
      },
      {
        key: "updated_at",
        title: t("list.last_modified", "Last modified"),
        width: 135,
        value: (r) => r.updated_at ?? null,
        render: (v) => formatDateTimeShort(v as string | null),
      },
      {
        key: "actions",
        title: "",
        width: 90,
        render: (_v, r) =>
          r.status === "quoted" ? (
            <button
              className="btn btn-primary btn-sm"
              type="button"
              disabled={busy}
              onClick={(e) => {
                e.stopPropagation();
                acceptInquiry(r.id);
              }}
            >
              {t("page.bunker.accept", "Accept")}
            </button>
          ) : null,
      },
    ],
    [t, busy, acceptInquiry],
  );

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.bunker", "Bunker desk") }]}
        title={t("page.bunker.title", "Bunker desk")}
        subtitle={t("page.bunker.sub", "Stem, delivery and ROB. Price feeds live in Integration Hub.")}
      />
      <Toolbar>
        <button type="button" className="btn btn-primary btn-sm" onClick={openCreate}>
          {t("page.bunker.create", "Create bunker order")}
        </button>
        <Link href="/settings/connectors" className="btn btn-ghost btn-sm">
          {t("page.connectors.title", "Integration Hub")}
        </Link>
      </Toolbar>
      {err ? <p className="flash-err">{err}</p> : null}
      {refLoadFailed ? (
        <p className="flash-warn">
          {t("page.bunker.ref_load_failed", "Vessel / voyage reference data could not be loaded — the pickers may be incomplete.")}
        </p>
      ) : null}
      {/* P1-28：列表总数必须可见（该接口无服务端分页，条数一次性返回） */}
      {!listErr && rows.length ? (
        <p className="muted">
          {t("list.count_total", "{n} records", { n: rows.length })}
        </p>
      ) : null}
      {warnings.length ? (
        <div className="panel panel-warn">
          {warnings.map((w, i) => (
            <p key={i} className="flash-warn">
              {w.code ? `[${w.code}] ` : ""}
              {w.message}
              {w.orderNo ? ` — ${w.orderNo}` : ""}
            </p>
          ))}
        </div>
      ) : null}

      <div className="panel panel-gap-top">
        <StatusLegend statuses={["planned", "inquiry", "ordered", "delivered", "closed"]} />
        <StateView
          loading={loading}
          error={listErr || undefined}
          empty={!rows.length}
          emptyText={t("common.empty", "No records")}
          onRetry={() => void load()}
        >
          <DataGrid<Order>
            columns={columns}
            data={rows}
            rowKey={(r) => r.id}
            editable
            onCellSave={onOrderCellSave}
            onRowClick={(r) => openRow(r)}
            onRowContextMenu={(row, _i, e) => orderCtx.open(row)(e)}
            storageKey="bunker_orders_grid"
            emptyText={t("common.empty", "No records")}
          />
        </StateView>
      </div>

      <BunkerRequirementsPanel />

      <RecordModal
        open={creating || Boolean(open)}
        title={
          creating
            ? t("page.bunker.create", "Create bunker order")
            : open
              ? `${t("page.bunker.edit", "Edit bunker order")} · ${open.order_no}`
              : ""
        }
        onClose={closeModal}
        onSave={save}
        canEdit={!open || !orderLocked(open)}
        saving={busy}
      >
        {!creating && open ? (
          <p className="muted">
            {t("common.status", "Status")}: {open.status}
          </p>
        ) : null}
        <label>
          {t("page.estimates.vessel", "Vessel")}
          <select value={form.vessel_id} onChange={(e) => setForm({ ...form, vessel_id: e.target.value })}>
            <option value="">—</option>
            {vessels.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("page.voyages.list", "Voyages")}
          <select value={form.voyage_id} onChange={(e) => setForm({ ...form, voyage_id: e.target.value })}>
            <option value="">—</option>
            {voyages.map((v) => (
              <option key={v.id} value={v.id}>
                {v.voyage_no || v.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("page.bunker.grade", "Grade")}
          <LookupSelect
            dataset="fuel_grades"
            value={form.grade}
            onChange={(v) => setForm({ ...form, grade: v })}
            allowEmpty={false}
          />
        </label>
        <label>
          {t("page.bunker.qty", "Ordered qty (mt)")}
          <input value={form.qty_ordered} onChange={(e) => setForm({ ...form, qty_ordered: e.target.value })} />
        </label>
        {creating ? (
          <label>
            {t("page.bunker.index_symbol", "Index symbol")}
            <input
              value={form.index_symbol}
              onChange={(e) => setForm({ ...form, index_symbol: e.target.value })}
              placeholder={t("page.bunker.index_symbol_ph", "SIN380 (optional)")}
            />
          </label>
        ) : null}
        {creating && form.index_symbol.trim() !== "" ? (
          <label>
            {t("page.bunker.price_diff", "Price differential")}
            <input
              value={form.price_differential}
              onChange={(e) => setForm({ ...form, price_differential: e.target.value })}
              placeholder="+12"
            />
          </label>
        ) : (
          <label>
            {t("page.bunker.price", "Unit price")}
            <input value={form.unit_price} onChange={(e) => setForm({ ...form, unit_price: e.target.value })} />
          </label>
        )}
        <label>
          {t("page.bunker.rob_before", "ROB before")}
          <input value={form.rob_before} onChange={(e) => setForm({ ...form, rob_before: e.target.value })} />
        </label>
        {!creating && open ? (
          <>
            <label>
              {t("page.bunker.deliver_qty", "Delivered qty")}
              <input value={deliverQty} onChange={(e) => setDeliverQty(e.target.value)} />
            </label>
            <label>
              {t("page.bunker.bdn_qty", "BDN qty")}
              <input value={bdnQty} onChange={(e) => setBdnQty(e.target.value)} placeholder={t("common.optional", "Optional")} />
            </label>
            <label>
              {t("page.bunker.consumption", "Consumption")}
              <input value={consumption} onChange={(e) => setConsumption(e.target.value)} />
            </label>
            <div className="desk-section desk-section-tight">
              <h3>{t("page.bunker.inquiries", "Inquiries")}</h3>
              {inqErr ? (
                <p className="flash-err">
                  {t("page.bunker.inquiries_load_failed", "Quotes could not be loaded.")} {inqErr}
                </p>
              ) : null}
              {inquiries.length ? (
                <DataGrid<Inquiry>
                  columns={inquiryColumns}
                  data={inquiries}
                  rowKey={(r) => r.id}
                  onRowContextMenu={(row, _i, e) => inqCtx.open(row)(e)}
                  storageKey="bunker_inquiries_grid"
                  showFooter={false}
                  showColumnMenu={false}
                  emptyText={t("page.bunker.no_inquiries", "No quotes yet")}
                />
              ) : (
                <p className="muted m-0">{t("page.bunker.no_inquiries", "No quotes yet")}</p>
              )}
              <div className="form-grid mt-sm">
                <label>
                  {t("page.bunker.supplier", "Supplier")}
                  <PartyPicker value="" onChange={(_id, item) => item && setInqSupplier(item.label)} placeholder={inqSupplier || t("picker.search", "Search counterparty…")} />
                </label>
                <label>
                  {t("page.bunker.quoted_price", "Quoted price")}
                  <input type="number" step="any" value={inqPrice} onChange={(e) => setInqPrice(e.target.value)} />
                </label>
                <div className="editor-actions">
                  <button className="btn btn-sm" type="button" disabled={busy} onClick={addInquiry}>
                    {t("page.bunker.add_inquiry", "Add quote")}
                  </button>
                </div>
              </div>
            </div>
            {open.voyage_id ? (
              <div className="desk-section desk-section-tight">
                <div className="desk-toolbar desk-toolbar-flush">
                  <h3 className="h3-compact">{t("page.bunker.allocation", "Voyage allocation estimate")}</h3>
                  <button className="btn btn-sm" type="button" disabled={busy} onClick={loadAllocation}>
                    {t("page.bunker.alloc_run", "Run allocation")}
                  </button>
                </div>
                {alloc ? (
                  <div className="desk-results mt-sm">
                    <div className="kv-box">
                      <span>{t("page.bunker.alloc_consumption", "Consumption mt")}</span>
                      <strong>{String(alloc.consumption_mt ?? "—")}</strong>
                    </div>
                    <div className="kv-box">
                      <span>{t("page.bunker.alloc_wavg", "Weighted avg price")}</span>
                      <strong>{alloc.weighted_avg_price != null ? String(alloc.weighted_avg_price) : "—"}</strong>
                    </div>
                    <div className="kv-box">
                      <span>{t("page.bunker.alloc_amount", "Allocated amount")}</span>
                      <strong>
                        {alloc.allocated_amount != null ? `${String(alloc.allocated_amount)} ${String(alloc.currency || "")}` : "—"}
                      </strong>
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}
            {/* 附件面板自带保存语义（上传即落库）—— 拦掉 onChange 冒泡，
                避免 RecordModal 的未保存守卫误报 */}
            <div onChange={(e) => e.stopPropagation()}>
              <AttachmentsPanel entityType="bunker_order" entityId={open.id} />
            </div>
            <div className="desk-toolbar">
              {open && !orderLocked(open) ? (
                <button
                  type="button"
                  className="btn btn-danger btn-sm"
                  disabled={busy}
                  onClick={() => requestDeleteOrder(open)}
                >
                  {t("common.delete", "Delete")}
                </button>
              ) : null}
              {open.status === "planned" ? (
                <button type="button" className="btn btn-sm" onClick={() => move(open.id, "inquiry")}>
                  {t("page.bunker.inquiry", "Inquiry")}
                </button>
              ) : null}
              {open.status === "inquiry" ? (
                <button type="button" className="btn btn-sm" onClick={() => move(open.id, "ordered")}>
                  {t("page.bunker.order", "Place order")}
                </button>
              ) : null}
              {open.status === "ordered" ? (
                <button type="button" className="btn btn-primary btn-sm" onClick={() => requestDelivery(open, { deliver: deliverQty, bdn: bdnQty, cons: consumption })}>
                  {t("page.bunker.confirm_delivery", "Confirm delivery")}
                </button>
              ) : null}
              {open.status === "delivered" ? (
                <button type="button" className="btn btn-sm" onClick={() => move(open.id, "closed")}>
                  {t("common.close", "Close")}
                </button>
              ) : null}
            </div>
          </>
        ) : null}
      </RecordModal>

      <ContextMenu controller={orderCtx} items={orderMenuItems} />
      <ContextMenu controller={inqCtx} items={inqMenuItems} />

      <ConfirmDialog
        open={Boolean(pendingDelivery)}
        title={t("page.bunker.confirm_delivery", "Confirm delivery")}
        message={t(
          "page.bunker.confirm_delivery_msg",
          'Confirm delivery for "{name}"? The ROB balance will be recalculated and this cannot be undone.',
          { name: pendingDelivery?.orderNo ?? "" },
        )}
        danger
        confirmLabel={t("page.bunker.confirm_delivery", "Confirm delivery")}
        onConfirm={() => {
          const fn = pendingDelivery;
          setPendingDelivery(null);
          fn?.run();
        }}
        onCancel={() => setPendingDelivery(null)}
      />

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title={t("common.confirm", "Confirm")}
        message={t("common.confirm_delete_named", 'Delete "{name}"?', { name: pendingDelete?.orderNo ?? "" })}
        danger
        confirmLabel={t("common.delete", "Delete")}
        onConfirm={() => {
          const fn = pendingDelete;
          setPendingDelete(null);
          fn?.run();
        }}
        onCancel={() => setPendingDelete(null)}
      />
    </AppShell>
  );
}
